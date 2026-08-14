"""
Batch evaluation harness (Week 4 / Phase 7).

Runs the full battery -- every repo x every model x all 3 representations -- scoring
each generated summary with two LLM-as-judge metrics (hallucination: are the claims
it made true; coverage: how much of the parser's ground truth did it mention), and
writes one flat CSV row per (repo, model, representation). That CSV is the results
table the report is built from; each row carries the efficiency metrics (latency,
tokens) alongside both quality metrics, so the representation ablation can be read
straight off it -- and so a summary that's faithful only because it said almost
nothing (high hallucination score, but also low coverage) doesn't look identical to
one that's faithful AND complete.

Runs as a script: `python -m app.evaluation.harness <url> [<url> ...] --out results.csv`.
Meant to run on the single designated evaluation machine (roadmap Section 1) so the
latency numbers are comparable -- running arms on different laptops makes them
meaningless.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Optional

from neo4j import Driver
from pydantic import BaseModel

from app.db.neo4j_client import get_driver
from app.evaluation.coverage import score_coverage
from app.evaluation.hallucination import score_summary
from app.evaluation.diagram_score import (
    GraphDiffScore,
    extract_actual_structure,
    load_expected,
    score_diagram,
)
from app.pipeline import AnalysisError, PipelineInfrastructureError, run_representation_ablation
from app.providers.base import BaseLLMProvider
from app.providers.ollama_provider import OllamaProvider
from app.schemas.llm_result import LLMResult, RunStatus
from app.schemas.parser_schema import ParsedRepository


class EvaluationRow(BaseModel):
    repo_name: str
    source_url: str
    framework: Optional[str]
    model: str
    context_variant: str
    run_status: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    judge_model: str
    self_judged: bool  # generator == judge; filter these out when analysing, if desired
    hallucination_judged: bool  # did the judge's own output parse
    hallucination_score: float
    total_claims: int
    unsupported_claims: int
    # Coverage (recall) -- companion to hallucination (precision): how much of the
    # parser's ground truth the summary actually mentioned, vs. how much of what it
    # said was true. A summary can score 0.0 hallucination by saying almost nothing;
    # coverage is what would catch that.
    coverage_judged: bool
    coverage_score: float
    total_facts: int
    missing_facts: int
    # Diagram graph-diff (per repo, same across a repo's rows -- populated only when a
    # `<repo_name>.json` expected-structure annotation is found). None when unscored.
    diagram_scored: bool = False
    diagram_module_f1: Optional[float] = None
    diagram_import_f1: Optional[float] = None
    diagram_endpoint_f1: Optional[float] = None
    diagram_overall_f1: Optional[float] = None
    error: Optional[str] = None


def run_evaluation(
    repo_urls: list[str],
    models: Optional[list[str]] = None,
    judge_model: Optional[str] = None,
    max_size_mb: int = 200,
    annotations_dir: Optional[str | Path] = None,
    driver: Optional[Driver] = None,
    provider: Optional[BaseLLMProvider] = None,
) -> list[EvaluationRow]:
    """One shared Neo4j driver and provider across the whole batch (created here if
    not injected). A single repo failing -- bad URL, unsupported framework, Neo4j
    blip -- records a failure row and moves on rather than aborting the batch;
    'something always breaks on repos you didn't build against' (roadmap Week 4).

    If `annotations_dir` is given, each repo is also diagram-scored against
    `<annotations_dir>/<repo_name>.json` when that file exists (repos without an
    annotation just leave the diagram columns empty -- no error)."""
    owns_driver = driver is None
    driver = driver or get_driver()
    provider = provider or OllamaProvider()
    judge_model = judge_model or provider.default_model

    rows: list[EvaluationRow] = []
    try:
        for url in repo_urls:
            try:
                parsed, results = run_representation_ablation(
                    url,
                    models=models,
                    max_size_mb=max_size_mb,
                    driver=driver,
                    provider=provider,
                )
            except (AnalysisError, PipelineInfrastructureError) as e:
                rows.append(_failure_row(url, judge_model, str(e)))
                continue

            diagram = _diagram_score(parsed, annotations_dir)
            for result in results:
                rows.append(_row_for_result(provider, parsed, result, judge_model, diagram))
    finally:
        if owns_driver:
            driver.close()
    return rows


def _diagram_score(
    parsed: ParsedRepository, annotations_dir: Optional[str | Path]
) -> Optional[GraphDiffScore]:
    """Score the extracted structure against an annotation file if one exists for
    this repo. Per-repo (the diagram is deterministic from the graph), so it's
    computed once and repeated onto each of the repo's rows."""
    if annotations_dir is None:
        return None
    annotation_path = Path(annotations_dir) / f"{parsed.metadata.name}.json"
    if not annotation_path.exists():
        return None
    expected = load_expected(annotation_path)
    actual = extract_actual_structure(parsed)
    return score_diagram(actual, expected, parsed.metadata.name)


def _row_for_result(
    provider: BaseLLMProvider,
    parsed: ParsedRepository,
    result: LLMResult,
    judge_model: str,
    diagram: Optional[GraphDiffScore] = None,
) -> EvaluationRow:
    self_judged = result.model == judge_model

    if result.status == RunStatus.SUCCESS:
        scored = score_summary(
            provider,
            parsed,
            result.output.raw_text,
            result.context_variant,
            judge_model=judge_model,
        )
        hallucination_judged = scored.judged
        hallucination_score = scored.hallucination_score
        total_claims = scored.total_claims
        unsupported = len(scored.unsupported_claims)

        coverage = score_coverage(
            provider,
            parsed,
            result.output.raw_text,
            result.context_variant,
            judge_model=judge_model,
        )
        coverage_judged = coverage.judged
        coverage_score = coverage.coverage_score
        total_facts = coverage.total_facts
        missing = len(coverage.missing_facts)
    else:
        # A failed/empty generation has nothing to judge -- don't spend a judge call.
        hallucination_judged = False
        hallucination_score = 0.0
        total_claims = 0
        unsupported = 0
        coverage_judged = False
        coverage_score = 0.0
        total_facts = 0
        missing = 0

    return EvaluationRow(
        repo_name=parsed.metadata.name,
        source_url=parsed.metadata.source_url,
        framework=parsed.metadata.detected_framework,
        model=result.model,
        context_variant=result.context_variant.value,
        run_status=result.status.value,
        latency_ms=result.metrics.latency_ms,
        input_tokens=result.metrics.input_tokens,
        output_tokens=result.metrics.output_tokens,
        estimated_cost_usd=result.metrics.estimated_cost_usd,
        judge_model=judge_model,
        self_judged=self_judged,
        hallucination_judged=hallucination_judged,
        hallucination_score=hallucination_score,
        total_claims=total_claims,
        unsupported_claims=unsupported,
        coverage_judged=coverage_judged,
        coverage_score=coverage_score,
        total_facts=total_facts,
        missing_facts=missing,
        diagram_scored=diagram is not None,
        diagram_module_f1=diagram.modules.f1 if diagram else None,
        diagram_import_f1=diagram.imports.f1 if diagram else None,
        diagram_endpoint_f1=diagram.endpoints.f1 if diagram else None,
        diagram_overall_f1=diagram.overall_f1 if diagram else None,
    )


def _failure_row(url: str, judge_model: str, error: str) -> EvaluationRow:
    return EvaluationRow(
        repo_name=url,
        source_url=url,
        framework=None,
        model="",
        context_variant="",
        run_status="failed",
        latency_ms=0,
        input_tokens=0,
        output_tokens=0,
        estimated_cost_usd=0.0,
        judge_model=judge_model,
        self_judged=False,
        hallucination_judged=False,
        hallucination_score=0.0,
        total_claims=0,
        unsupported_claims=0,
        coverage_judged=False,
        coverage_score=0.0,
        total_facts=0,
        missing_facts=0,
        error=error,
    )


def write_csv(rows: list[EvaluationRow], path: str | Path) -> None:
    path = Path(path)
    fieldnames = list(EvaluationRow.model_fields.keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.model_dump())


def write_sqlite(rows: list[EvaluationRow], path: str | Path, table: str = "evaluation_runs") -> None:
    """Append rows into a SQLite table (created if absent). Unlike the CSV -- which is
    overwritten each run -- this accumulates across runs, so results from multiple
    batches (or the same battery re-run) build up in one queryable place. A run_at
    timestamp column distinguishes them."""
    fields = list(EvaluationRow.model_fields.keys())
    columns = ", ".join(f'"{f}"' for f in fields)
    placeholders = ", ".join("?" for _ in fields)
    conn = sqlite3.connect(str(path))
    try:
        # Columns declared with no type affinity so each value keeps its native
        # storage class (int/float/text) for analysis, instead of everything becoming
        # TEXT. run_at keeps a real type for its default.
        col_defs = ", ".join(f'"{f}"' for f in fields)
        conn.execute(
            f'CREATE TABLE IF NOT EXISTS "{table}" '
            f'(run_at TEXT DEFAULT CURRENT_TIMESTAMP, {col_defs})'
        )
        conn.executemany(
            f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})',
            [tuple(_sqlite_value(v) for v in row.model_dump().values()) for row in rows],
        )
        conn.commit()
    finally:
        conn.close()


def _sqlite_value(value: object) -> object:
    # sqlite3 handles str/int/float/None natively; coerce bools to 0/1 and anything
    # else (shouldn't occur) to str, so the insert never raises on an odd type.
    if isinstance(value, bool):
        return int(value)
    if value is None or isinstance(value, (str, int, float)):
        return value
    return str(value)


def main() -> None:
    import argparse

    from dotenv import load_dotenv

    load_dotenv()  # standalone script -- pick up .env (Neo4j creds, Ollama host, models)

    parser = argparse.ArgumentParser(description="Run the evaluation battery over repos.")
    parser.add_argument("urls", nargs="+", help="GitHub repo URLs to evaluate")
    parser.add_argument(
        "--models", nargs="*", default=None, help="Models to compare (default: the .env comparison models)"
    )
    parser.add_argument("--judge-model", default=None, help="Model used as the hallucination judge")
    parser.add_argument(
        "--annotations-dir",
        default=None,
        help="Directory of <repo_name>.json expected-structure annotations for diagram scoring",
    )
    parser.add_argument("--out", default="evaluation_results.csv", help="Output CSV path")
    parser.add_argument(
        "--sqlite", default=None, help="Optional SQLite DB path to also append results to"
    )
    args = parser.parse_args()

    rows = run_evaluation(
        args.urls,
        models=args.models,
        judge_model=args.judge_model,
        annotations_dir=args.annotations_dir,
    )
    write_csv(rows, args.out)
    if args.sqlite:
        write_sqlite(rows, args.sqlite)
    failures = sum(1 for r in rows if r.run_status == "failed")
    sqlite_note = f" and appended to {args.sqlite}" if args.sqlite else ""
    print(f"Wrote {len(rows)} rows to {args.out}{sqlite_note} ({failures} repo-level failures).")


if __name__ == "__main__":
    main()
