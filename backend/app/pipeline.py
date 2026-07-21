"""
Top-level orchestration: URL in, ParsedRepository out (analyze_repository), or URL in,
LLM-generated summary out (generate_repository_summary). This is what the FastAPI
endpoint (and later, the evaluation harness) calls -- it doesn't know about
GitPython, tree-sitter, Neo4j, or Ollama directly, just these two functions.
"""

from __future__ import annotations

import json

from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError

from app.acquisition.clone import AcquiredRepo, CloneFailedError, InvalidRepoUrlError, RepoTooLargeError, clone_repository
from app.context.builder import build_context
from app.db.neo4j_client import get_driver
from app.graph.builder import ensure_constraints, write_parsed_repository
from app.parsers.base import UnsupportedFrameworkError
from app.parsers.registry import parse_repository
from app.providers.base import BaseLLMProvider
from app.providers.ollama_provider import OllamaProvider
from app.providers.prompts import SUMMARY_PROMPT_TEMPLATE
from app.schemas.llm_result import ContextVariant, LLMResult, RunStatus
from app.schemas.parser_schema import ParsedRepository

REQUIRED_SUMMARY_KEYS = {"overview", "tech_stack", "services", "dependencies"}


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
