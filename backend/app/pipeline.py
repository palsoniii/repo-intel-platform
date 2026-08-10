"""
Top-level orchestration: URL in, ParsedRepository out (analyze_repository), or URL in,
LLM-generated summary out (generate_repository_summary). This is what the FastAPI
endpoint (and later, the evaluation harness) calls -- it doesn't know about
GitPython, tree-sitter, Neo4j, or Ollama directly, just these two functions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError

from pydantic import BaseModel

from app.acquisition.clone import AcquiredRepo, CloneFailedError, InvalidRepoUrlError, RepoTooLargeError, clone_repository
from app.context.builder import build_context
from app.db.neo4j_client import get_driver
from app.evaluation.hallucination import HallucinationResult, score_summary
from app.graph.builder import ensure_constraints, write_parsed_repository
from app.graph.diagram import generate_architecture_diagram
from app.parsers.base import UnsupportedFrameworkError
from app.parsers.registry import parse_repository
from app.providers.base import BaseLLMProvider
from app.providers.ollama_provider import OllamaProvider
from app.providers.prompts import SUMMARY_PROMPT_TEMPLATE
from app.schemas.llm_result import ContextVariant, LLMResult, RunStatus
from app.schemas.parser_schema import ParsedRepository

REQUIRED_SUMMARY_KEYS = {"overview", "tech_stack", "services", "dependencies"}

# Conservative default: these 7-8B Ollama models commonly default to a 2-4K token
# context window (num_ctx isn't configured anywhere in this pipeline yet -- a known
# follow-up), so the raw-source arm of the ablation is capped well under that rather
# than assuming a larger window is available.
DEFAULT_MAX_RAW_CHARS = 8000


class AnalysisError(Exception):
    """Wraps all recoverable failure modes with a consistent message for the API layer."""


class PipelineInfrastructureError(Exception):
    """Neo4j (or another required service) is unreachable -- distinct from
    AnalysisError (bad input) because it's a 503-shaped problem (retry later, or
    start the service), not a 400-shaped one (fix your request)."""


def analyze_repository(url: str, max_size_mb: int = 200) -> ParsedRepository:
    acquired: AcquiredRepo | None = None
    try:
        acquired = clone_repository(url, max_size_mb=max_size_mb)
        parsed = parse_repository(acquired.local_path)
        parsed.metadata.source_url = url
        parsed.metadata.commit_sha = acquired.commit_sha
        return parsed
    except (InvalidRepoUrlError, CloneFailedError, RepoTooLargeError, UnsupportedFrameworkError) as e:
        raise AnalysisError(str(e)) from e
    finally:
        if acquired is not None:
            acquired.cleanup()


def generate_repository_summary(
    url: str,
    model: str | None = None,
    max_size_mb: int = 200,
    driver: Driver | None = None,
    provider: BaseLLMProvider | None = None,
) -> tuple[ParsedRepository, LLMResult]:
    """Week 2's real, no-mocks pipeline: GitHub URL -> parser -> Neo4j -> context ->
    Ollama -> summary. Uses the knowledge_graph representation (the richest) -- the
    3-way ablation across all representations is Week 3 work.

    `driver`/`provider` are injectable so tests don't need a live Neo4j/Ollama; when
    omitted, real connections are created and (for an owned driver) closed here.
    """
    parsed = analyze_repository(url, max_size_mb=max_size_mb)

    owns_driver = driver is None
    driver = driver or get_driver()
    provider = provider or OllamaProvider()
    try:
        try:
            ensure_constraints(driver)
            write_parsed_repository(driver, parsed)
            context = build_context(driver, parsed.metadata.name, ContextVariant.KNOWLEDGE_GRAPH)
        except (Neo4jError, DriverError, OSError) as e:
            raise PipelineInfrastructureError(
                f"Couldn't reach Neo4j -- is it running? ({e})"
            ) from e
    finally:
        if owns_driver:
            driver.close()

    result = provider.generate_summary(
        context=context,
        repo_name=parsed.metadata.name,
        context_variant=ContextVariant.KNOWLEDGE_GRAPH,
        prompt_template=SUMMARY_PROMPT_TEMPLATE,
        model=model or provider.default_model,
    )

    if result.status == RunStatus.SUCCESS:
        result.output.parsed, result.output.valid = _try_parse_summary_json(result.output.raw_text)

    return parsed, result


def generate_repository_diagram(
    url: str,
    max_size_mb: int = 200,
    driver: Driver | None = None,
) -> tuple[ParsedRepository, str]:
    """Week 3's diagram generation: GitHub URL -> parser -> Neo4j -> Mermaid
    flowchart. No LLM call anywhere in this path -- the diagram is generated
    directly from the graph (see graph/diagram.py's docstring), deterministic and
    free, unlike the summary pipeline."""
    parsed = analyze_repository(url, max_size_mb=max_size_mb)

    owns_driver = driver is None
    driver = driver or get_driver()
    try:
        try:
            ensure_constraints(driver)
            write_parsed_repository(driver, parsed)
            diagram = generate_architecture_diagram(driver, parsed.metadata.name)
        except (Neo4jError, DriverError, OSError) as e:
            raise PipelineInfrastructureError(
                f"Couldn't reach Neo4j -- is it running? ({e})"
            ) from e
    finally:
        if owns_driver:
            driver.close()

    return parsed, diagram


def _try_parse_summary_json(raw_text: str) -> tuple[dict | None, bool]:
    """Downstream parsing of the model's raw_text into the structured shape the
    prompt asked for (see providers/base.py: this is deliberately not the
    provider's job). Malformed or off-schema output is a real possibility with
    local models, not just a hypothetical -- treated as invalid, not raised."""
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return None, False
    if not isinstance(parsed, dict) or not REQUIRED_SUMMARY_KEYS.issubset(parsed.keys()):
        return None, False
    return parsed, True


def _default_comparison_models() -> list[str]:
    """Read lazily (not a module-level constant) so this reflects .env even if
    load_dotenv() runs after this module is first imported -- see main.py's
    load_dotenv() placement note for why that ordering isn't actually guaranteed
    to matter here, but this avoids depending on it regardless."""
    return [
        os.environ.get("OLLAMA_MODEL_PRIMARY", "qwen2.5-coder:7b"),
        os.environ.get("OLLAMA_MODEL_FALLBACK", "llama3.1:8b"),
        os.environ.get("OLLAMA_MODEL_DIVERSITY", "gpt-oss:20b"),
    ]


def _read_raw_source(
    repo_path: Path, parsed: ParsedRepository, max_chars: int = DEFAULT_MAX_RAW_CHARS
) -> str:
    """RAW ContextVariant: the repo's own source text, concatenated per-module and
    truncated to max_chars. Must run BEFORE the clone is cleaned up -- this is the
    only place raw source is available anywhere in the pipeline (see
    context/builder.py's docstring on why build_context() itself can't produce
    this variant)."""
    chunks: list[str] = []
    total = 0
    for module in parsed.modules:
        try:
            text = (repo_path / module.path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        chunk = f"// ---- {module.path} ----\n{text}"
        if total + len(chunk) > max_chars:
            remaining = max_chars - total
            if remaining > 0:
                chunks.append(chunk[:remaining])
            break
        chunks.append(chunk)
        total += len(chunk)
    return "\n\n".join(chunks)


def run_representation_ablation(
    url: str,
    models: list[str] | None = None,
    max_size_mb: int = 200,
    max_raw_chars: int = DEFAULT_MAX_RAW_CHARS,
    driver: Driver | None = None,
    provider: BaseLLMProvider | None = None,
) -> tuple[ParsedRepository, list[LLMResult]]:
    """Week 3's 3-way representation ablation: the same repo, the same models, three
    different context representations (raw / dependency_graph / knowledge_graph) --
    the core independent variable of the research question. Returns one LLMResult
    per (model, representation) pair -- len(models) * 3 total.

    Clones and parses once (not reusing analyze_repository(), which cleans up its
    checkout before returning -- raw source has to be read before that happens, see
    _read_raw_source), writes to the graph once, then reuses that single context
    build across every model for dependency_graph/knowledge_graph.
    """
    models = models or _default_comparison_models()

    acquired: AcquiredRepo | None = None
    try:
        acquired = clone_repository(url, max_size_mb=max_size_mb)
        parsed = parse_repository(acquired.local_path)
        parsed.metadata.source_url = url
        parsed.metadata.commit_sha = acquired.commit_sha
        raw_context = _read_raw_source(acquired.local_path, parsed, max_raw_chars)
    except (InvalidRepoUrlError, CloneFailedError, RepoTooLargeError, UnsupportedFrameworkError) as e:
        raise AnalysisError(str(e)) from e
    finally:
        if acquired is not None:
            acquired.cleanup()

    owns_driver = driver is None
    driver = driver or get_driver()
    provider = provider or OllamaProvider()
    try:
        try:
            ensure_constraints(driver)
            write_parsed_repository(driver, parsed)
            dependency_graph_context = build_context(
                driver, parsed.metadata.name, ContextVariant.DEPENDENCY_GRAPH
            )
            knowledge_graph_context = build_context(
                driver, parsed.metadata.name, ContextVariant.KNOWLEDGE_GRAPH
            )
        except (Neo4jError, DriverError, OSError) as e:
            raise PipelineInfrastructureError(
                f"Couldn't reach Neo4j -- is it running? ({e})"
            ) from e
    finally:
        if owns_driver:
            driver.close()

    contexts = {
        ContextVariant.RAW: raw_context,
        ContextVariant.DEPENDENCY_GRAPH: dependency_graph_context,
        ContextVariant.KNOWLEDGE_GRAPH: knowledge_graph_context,
    }

    results: list[LLMResult] = []
    for model in models:
        for variant, context in contexts.items():
            result = provider.generate_summary(
                context=context,
                repo_name=parsed.metadata.name,
                context_variant=variant,
                prompt_template=SUMMARY_PROMPT_TEMPLATE,
                model=model,
            )
            if result.status == RunStatus.SUCCESS:
                result.output.parsed, result.output.valid = _try_parse_summary_json(
                    result.output.raw_text
                )
            results.append(result)

    return parsed, results


class ScoredResult(BaseModel):
    """One ablation result paired with its hallucination score. `hallucination` is
    None for a run that failed (nothing to grade)."""

    result: LLMResult
    hallucination: HallucinationResult | None = None


def run_scored_ablation(
    url: str,
    models: list[str] | None = None,
    judge_model: str | None = None,
    max_size_mb: int = 200,
    driver: Driver | None = None,
    provider: BaseLLMProvider | None = None,
) -> tuple[ParsedRepository, list[ScoredResult]]:
    """The ablation plus a hallucination score per successful result -- what the
    /compare endpoint and dashboard use, so the comparison shows quality (not just
    latency/tokens). One shared provider does both generation and judging. The judge
    reads ground-truth facts from the ParsedRepository, so scoring needs no Neo4j and
    happens after the driver is released."""
    owns_driver = driver is None
    driver = driver or get_driver()
    provider = provider or OllamaProvider()
    judge_model = judge_model or provider.default_model

    try:
        parsed, results = run_representation_ablation(
            url, models=models, max_size_mb=max_size_mb, driver=driver, provider=provider
        )
    finally:
        if owns_driver:
            driver.close()

    scored: list[ScoredResult] = []
    for result in results:
        hallucination = None
        if result.status == RunStatus.SUCCESS:
            hallucination = score_summary(
                provider,
                parsed,
                result.output.raw_text,
                result.context_variant,
                judge_model=judge_model,
            )
        scored.append(ScoredResult(result=result, hallucination=hallucination))

    return parsed, scored
