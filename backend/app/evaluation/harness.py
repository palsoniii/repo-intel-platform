"""
Batch evaluation harness (Week 4 / Phase 7).

Runs the full battery -- every repo x every model x all 3 representations -- scoring
each generated summary with the LLM-as-judge hallucination metric, and writes one
flat CSV row per (repo, model, representation). That CSV is the results table the
report is built from; each row carries both the efficiency metrics (latency, tokens)
and the quality metric (hallucination score) side by side, so the representation
ablation can be read straight off it.

Runs as a script: `python -m app.evaluation.harness <url> [<url> ...] --out results.csv`.
Meant to run on the single designated evaluation machine (roadmap Section 1) so the
latency numbers are comparable -- running arms on different laptops makes them
meaningless.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from neo4j import Driver
from pydantic import BaseModel

from app.db.neo4j_client import get_driver
from app.evaluation.hallucination import score_summary
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
    error: Optional[str] = None


def run_evaluation(
    repo_urls: list[str],
    models: Optional[list[str]] = None,
    judge_model: Optional[str] = None,
    max_size_mb: int = 200,
    driver: Optional[Driver] = None,
    provider: Optional[BaseLLMProvider] = None,
) -> list[EvaluationRow]:
    """One shared Neo4j driver and provider across the whole batch (created here if
    not injected). A single repo failing -- bad URL, unsupported framework, Neo4j
    blip -- records a failure row and moves on rather than aborting the batch;
    'something always breaks on repos you didn't build against' (roadmap Week 4)."""
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

            for result in results:
                rows.append(_row_for_result(provider, parsed, result, judge_model))
    finally:
        if owns_driver:
            driver.close()
    return rows


def _row_for_result(
    provider: BaseLLMProvider,
    parsed: ParsedRepository,
    result: LLMResult,
    judge_model: str,
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
    else:
        # A failed/empty generation has nothing to judge -- don't spend a judge call.
        hallucination_judged = False
        hallucination_score = 0.0
        total_claims = 0
        unsupported = 0

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
    parser.add_argument("--out", default="evaluation_results.csv", help="Output CSV path")
    args = parser.parse_args()

    rows = run_evaluation(args.urls, models=args.models, judge_model=args.judge_model)
    write_csv(rows, args.out)
    failures = sum(1 for r in rows if r.run_status == "failed")
    print(f"Wrote {len(rows)} rows to {args.out} ({failures} repo-level failures).")


if __name__ == "__main__":
    main()
