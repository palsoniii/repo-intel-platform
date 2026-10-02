"""
Background analysis jobs.

An analysis runs in stages, and the dashboard becomes usable after the third:

  cloning -> parsing -> indexing   (seconds; status becomes "ready" here)
  -> graph                          (write to Neo4j; optional, failure is recorded)
  -> summarizing                    (local model; slow, runs on its own queue)

Structural work and model calls use separate executors. The model executor has a
single worker on purpose: two 7B generations at once on a 16GB machine is slower than
running them back to back (CLAUDE.md, "Run one generator at a time").
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.acquisition.clone import (
    CloneFailedError,
    InvalidRepoUrlError,
    RepoTooLargeError,
    clone_repository,
)
from app.context.builder import _format_knowledge_graph
from app.parsers.base import UnsupportedFrameworkError
from app.parsers.registry import parse_repository
from app.product import store
from app.product.insights import compute_insights
from app.schemas.parser_schema import ParsedRepository

log = logging.getLogger(__name__)

_structure_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analysis")
_model_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="model")

MAX_STORED_FILE_BYTES = 400_000
EXTRA_FILES = ("package.json", "README.md", "readme.md", "README", "tsconfig.json", ".env.example")
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "coverage"}


def summary_model() -> str:
    return os.environ.get("PRODUCT_SUMMARY_MODEL") or os.environ.get(
        "OLLAMA_MODEL_PRIMARY", "qwen2.5-coder:7b"
    ).split("#")[0].strip()


def submit_analysis(analysis_id: str, url: str) -> None:
    _structure_pool.submit(_run_analysis, analysis_id, url)


def submit_summary(analysis_id: str, model: str | None = None) -> None:
    store.update_analysis(analysis_id, summary_status="pending", summary_error=None)
    _model_pool.submit(_run_summary, analysis_id, model or summary_model())


def _stage(analysis_id: str, stage: str, **fields) -> None:
    store.update_analysis(analysis_id, stage=stage, **fields)


def _run_analysis(analysis_id: str, url: str) -> None:
    acquired = None
    try:
        store.update_analysis(analysis_id, status="running")
        t = time.monotonic()
        _stage(analysis_id, "cloning")
        max_mb = int(os.environ.get("MAX_REPO_SIZE_MB", "200").split("#")[0].strip())
        acquired = clone_repository(url, max_size_mb=max_mb)
        store.record_timing(analysis_id, "clone", time.monotonic() - t)

        t = time.monotonic()
        _stage(analysis_id, "parsing", commit_sha=acquired.commit_sha)
        parsed = parse_repository(acquired.local_path)
        parsed.metadata.source_url = url
        parsed.metadata.commit_sha = acquired.commit_sha
        store.record_timing(analysis_id, "parse", time.monotonic() - t)

        t = time.monotonic()
        _stage(analysis_id, "indexing", framework=parsed.metadata.detected_framework)
        files = _collect_files(acquired.local_path, parsed)
        insights = compute_insights(parsed, files)
        store.save_files(analysis_id, files)
        store.record_timing(analysis_id, "index", time.monotonic() - t)
        store.update_analysis(
            analysis_id,
            status="ready",
            stage="graph",
            repo_name=parsed.metadata.name,
            parsed_json=parsed.model_dump(mode="json"),
            insights_json=insights,
        )
    except (InvalidRepoUrlError, CloneFailedError, RepoTooLargeError, UnsupportedFrameworkError) as e:
        store.update_analysis(analysis_id, status="failed", stage="failed", error=_friendly_error(e))
        return
    except Exception as e:  # noqa: BLE001 -- a worker thread must record, not raise
        log.exception("analysis %s failed", analysis_id)
        store.update_analysis(analysis_id, status="failed", stage="failed", error=f"Unexpected error: {e}")
        return
    finally:
        if acquired is not None:
            acquired.cleanup()

    _write_graph(analysis_id, parsed)
    _stage(analysis_id, "summarizing")
    submit_summary(analysis_id)


def _friendly_error(e: Exception) -> str:
    if isinstance(e, UnsupportedFrameworkError):
        return (
            "This repository isn't an Express.js or NestJS project (checked package.json at "
            "the repository root). The platform currently supports those two frameworks."
        )
    if isinstance(e, CloneFailedError):
        return "Couldn't clone the repository. Check the URL, and that the repository is public."
    return str(e)


def _collect_files(repo_path: Path, parsed: ParsedRepository) -> dict[str, str]:
    wanted = {m.path for m in parsed.modules}
    for name in EXTRA_FILES:
        if (repo_path / name).is_file():
            wanted.add(name)
    for f in repo_path.rglob("*.prisma"):
        rel = f.relative_to(repo_path)
        if not any(part in SKIP_DIRS for part in rel.parts):
            wanted.add(rel.as_posix())

    files: dict[str, str] = {}
    for rel in sorted(wanted):
        path = repo_path / rel
        try:
            if path.stat().st_size > MAX_STORED_FILE_BYTES:
                continue
            files[rel] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return files


def _write_graph(analysis_id: str, parsed: ParsedRepository) -> None:
    """Stores the parse in Neo4j, the project's knowledge-graph store. Every view is
    served from SQLite, so a missing Neo4j only costs the Neo4j Browser demo, not the
    dashboard -- recorded as graph_status=unavailable rather than failing the analysis."""
    t = time.monotonic()
    try:
        from app.db.neo4j_client import get_driver
        from app.graph.builder import ensure_constraints, write_parsed_repository

        driver = get_driver()
        try:
            driver.verify_connectivity()
            ensure_constraints(driver)
            write_parsed_repository(driver, parsed)
        finally:
            driver.close()
        store.update_analysis(analysis_id, graph_status="stored")
    except Exception as e:  # noqa: BLE001
        log.warning("Neo4j write skipped for %s: %s", analysis_id, e)
        store.update_analysis(analysis_id, graph_status="unavailable")
    store.record_timing(analysis_id, "graph", time.monotonic() - t)


def knowledge_graph_context(parsed: ParsedRepository, insights: dict) -> str:
    """The study's knowledge_graph representation, built from the stored parse rather
    than queried back out of Neo4j -- same fields, same formatter
    (context/builder.py), plus the ORM models this layer extracts."""
    paths = {m.id: m.path for m in parsed.modules}
    classes_by_module: dict[str, list[str]] = {}
    for c in parsed.classes:
        classes_by_module.setdefault(c.module_id, []).append(c.name)
    functions = {f.id: f.name for f in parsed.functions}
    data = {
        "framework": parsed.metadata.detected_framework,
        "framework_version": parsed.metadata.framework_version,
        "module_rows": [
            {
                "path": m.path,
                "imports": [paths[i] for i in m.imports if i in paths],
                "classes": classes_by_module.get(m.id, []),
            }
            for m in parsed.modules
        ],
        "endpoints": [
            {
                "method": ep.method.value if hasattr(ep.method, "value") else ep.method,
                "path": ep.path,
                "handler": functions.get(ep.handler_function_id or ""),
            }
            for ep in parsed.api_endpoints
        ],
        "external_dependencies": [d.name for d in parsed.dependencies.external],
        "config_files": [c.path for c in parsed.config_files],
        "database_entities": [e["name"] for e in insights.get("entities", [])],
    }
    return _format_knowledge_graph(data)


def _run_summary(analysis_id: str, model: str) -> None:
    from app.pipeline import _try_parse_summary_json
    from app.providers.ollama_provider import OllamaProvider
    from app.providers.prompts import SUMMARY_PROMPT_TEMPLATE
    from app.schemas.llm_result import ContextVariant, RunStatus

    analysis = store.get_analysis(analysis_id)
    if analysis is None or analysis.get("parsed_json") is None:
        return
    store.update_analysis(analysis_id, summary_status="running", summary_model=model)
    t = time.monotonic()
    try:
        parsed = ParsedRepository.model_validate(analysis["parsed_json"])
        context = knowledge_graph_context(parsed, analysis.get("insights_json") or {})
        provider = OllamaProvider()
        result = provider.generate_summary(
            context=context,
            repo_name=parsed.metadata.name,
            context_variant=ContextVariant.KNOWLEDGE_GRAPH,
            prompt_template=SUMMARY_PROMPT_TEMPLATE,
            model=model,
        )
        if result.status != RunStatus.SUCCESS:
            raise RuntimeError(_friendly_model_error(result.error or "", model))
        summary, valid = _try_parse_summary_json(result.output.raw_text)
        store.update_analysis(
            analysis_id,
            summary_status="done" if summary else "failed",
            summary_error=None if summary else "The model's answer wasn't valid JSON. Try regenerating.",
            summary_json={
                "summary": summary,
                "valid": valid,
                "raw_text": result.output.raw_text,
                "model": model,
                "latency_ms": result.metrics.latency_ms,
                "input_tokens": result.metrics.input_tokens,
                "output_tokens": result.metrics.output_tokens,
            },
        )
    except Exception as e:  # noqa: BLE001
        log.warning("summary failed for %s: %s", analysis_id, e)
        store.update_analysis(analysis_id, summary_status="failed", summary_error=str(e))
    finally:
        store.record_timing(analysis_id, "summary", time.monotonic() - t)
        current = store.get_analysis(analysis_id, include_documents=False)
        if current and current["status"] == "ready":
            store.update_analysis(analysis_id, stage="done")


def _friendly_model_error(error: str, model: str) -> str:
    low = error.lower()
    if "not found" in low and "model" in low:
        return f"The model '{model}' isn't installed. Run: ollama pull {model}"
    if "connect" in low or "connection" in low:
        return "Couldn't reach Ollama. Is it running? (ollama serve)"
    return error
