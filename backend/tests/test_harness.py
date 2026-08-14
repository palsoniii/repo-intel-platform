"""
Unit tests for the batch evaluation harness, run against a mocked ablation +
hallucination scorer so they're fast and need no live infra. Covers row assembly
(one row per model x representation), the self-judged flag, that failed generations
skip the judge, that a repo-level failure records a row and doesn't abort the batch,
and CSV output shape.
"""

import csv
import json
import sqlite3
from unittest.mock import MagicMock, patch

from app.evaluation.harness import EvaluationRow, run_evaluation, write_csv, write_sqlite
from app.evaluation.coverage import CoverageResult
from app.evaluation.hallucination import HallucinationResult
from app.pipeline import AnalysisError
from app.schemas.llm_result import (
    ContextVariant,
    LLMMetrics,
    LLMOutput,
    LLMResult,
    LLMTask,
    ProviderName,
    RunStatus,
)
from app.schemas.parser_schema import ModuleNode, ParsedRepository, RepoMetadata


def _parsed(name="repo-a") -> ParsedRepository:
    return ParsedRepository(
        metadata=RepoMetadata(
            name=name,
            source_url=f"https://github.com/test/{name}",
            detected_language="javascript",
            detected_framework="express",
        )
    )


def _result(model: str, variant: ContextVariant, status=RunStatus.SUCCESS) -> LLMResult:
    return LLMResult(
        provider=ProviderName.OLLAMA,
        model=model,
        task=LLMTask.SUMMARY,
        context_variant=variant,
        repo_name="repo-a",
        output=LLMOutput(raw_text="{}"),
        metrics=LLMMetrics(latency_ms=1000, input_tokens=300, output_tokens=60, estimated_cost_usd=0.0),
        status=status,
    )


def _scored(variant: ContextVariant) -> HallucinationResult:
    return HallucinationResult(
        repo_name="repo-a",
        context_variant=variant,
        judge_model="llama3.1:8b",
        total_claims=4,
        unsupported_claims=["uses MongoDB"],
        hallucination_score=0.25,
        judged=True,
        judge_raw_output="{}",
    )


def _scored_coverage(variant: ContextVariant) -> CoverageResult:
    return CoverageResult(
        repo_name="repo-a",
        context_variant=variant,
        judge_model="llama3.1:8b",
        total_facts=4,
        missing_facts=["Endpoint: GET /users"],
        coverage_score=0.75,
        judged=True,
        judge_raw_output="{}",
    )


def test_one_row_per_model_and_representation():
    ablation_results = [
        _result(m, v)
        for m in ("qwen2.5-coder:7b", "mistral:7b")
        for v in (ContextVariant.RAW, ContextVariant.DEPENDENCY_GRAPH, ContextVariant.KNOWLEDGE_GRAPH)
    ]
    with patch(
        "app.evaluation.harness.run_representation_ablation",
        return_value=(_parsed(), ablation_results),
    ), patch(
        "app.evaluation.harness.score_summary", side_effect=lambda p, pr, txt, v, judge_model: _scored(v)
    ), patch(
        "app.evaluation.harness.score_coverage",
        side_effect=lambda p, pr, txt, v, judge_model: _scored_coverage(v),
    ):
        rows = run_evaluation(
            ["https://github.com/test/repo-a"],
            judge_model="llama3.1:8b",
            driver=MagicMock(),
            provider=MagicMock(),
        )

    assert len(rows) == 6  # 2 models x 3 representations
    assert {r.context_variant for r in rows} == {"raw", "dependency_graph", "knowledge_graph"}
    assert all(r.hallucination_score == 0.25 for r in rows)
    assert all(r.unsupported_claims == 1 for r in rows)
    assert all(r.coverage_score == 0.75 for r in rows)
    assert all(r.missing_facts == 1 for r in rows)


def test_self_judged_flag_set_when_generator_equals_judge():
    results = [_result("llama3.1:8b", ContextVariant.RAW), _result("mistral:7b", ContextVariant.RAW)]
    with patch(
        "app.evaluation.harness.run_representation_ablation", return_value=(_parsed(), results)
    ), patch(
        "app.evaluation.harness.score_summary", side_effect=lambda p, pr, txt, v, judge_model: _scored(v)
    ), patch(
        "app.evaluation.harness.score_coverage",
        side_effect=lambda p, pr, txt, v, judge_model: _scored_coverage(v),
    ):
        rows = run_evaluation(["u"], judge_model="llama3.1:8b", driver=MagicMock(), provider=MagicMock())

    by_model = {r.model: r for r in rows}
    assert by_model["llama3.1:8b"].self_judged is True
    assert by_model["mistral:7b"].self_judged is False


def test_failed_generation_skips_the_judge():
    results = [_result("mistral:7b", ContextVariant.RAW, status=RunStatus.FAILED)]
    score = MagicMock()
    coverage = MagicMock()
    with patch(
        "app.evaluation.harness.run_representation_ablation", return_value=(_parsed(), results)
    ), patch("app.evaluation.harness.score_summary", score), patch(
        "app.evaluation.harness.score_coverage", coverage
    ):
        rows = run_evaluation(
            ["u"], judge_model="llama3.1:8b", driver=MagicMock(), provider=MagicMock()
        )

    score.assert_not_called()
    coverage.assert_not_called()  # neither judge is worth calling on a failed generation
    assert rows[0].run_status == "failed"
    assert rows[0].hallucination_judged is False
    assert rows[0].coverage_judged is False


def test_repo_level_failure_records_a_row_and_continues():
    good_results = [_result("mistral:7b", ContextVariant.RAW)]

    def _ablation(url, **kwargs):
        if "bad" in url:
            raise AnalysisError("unsupported framework")
        return _parsed(), good_results

    with patch("app.evaluation.harness.run_representation_ablation", side_effect=_ablation), patch(
        "app.evaluation.harness.score_summary", side_effect=lambda p, pr, txt, v, judge_model: _scored(v)
    ), patch(
        "app.evaluation.harness.score_coverage",
        side_effect=lambda p, pr, txt, v, judge_model: _scored_coverage(v),
    ):
        rows = run_evaluation(
            ["https://github.com/test/bad-repo", "https://github.com/test/good-repo"],
            judge_model="llama3.1:8b",
            driver=MagicMock(),
            provider=MagicMock(),
        )

    failed = [r for r in rows if r.run_status == "failed"]
    assert len(failed) == 1
    assert failed[0].error == "unsupported framework"
    # the second (good) repo still ran despite the first failing
    assert any(r.run_status == "success" for r in rows)


def test_write_csv_roundtrip(tmp_path):
    rows = [
        EvaluationRow(
            repo_name="repo-a", source_url="u", framework="express", model="mistral:7b",
            context_variant="raw", run_status="success", latency_ms=1000, input_tokens=300,
            output_tokens=60, estimated_cost_usd=0.0, judge_model="llama3.1:8b", self_judged=False,
            hallucination_judged=True, hallucination_score=0.25, total_claims=4, unsupported_claims=1,
            coverage_judged=True, coverage_score=0.75, total_facts=4, missing_facts=1,
        )
    ]
    out = tmp_path / "results.csv"
    write_csv(rows, out)

    with out.open(newline="") as f:
        parsed_rows = list(csv.DictReader(f))
    assert len(parsed_rows) == 1
    assert parsed_rows[0]["model"] == "mistral:7b"
    assert parsed_rows[0]["context_variant"] == "raw"
    assert parsed_rows[0]["hallucination_score"] == "0.25"


def _parsed_with_modules() -> ParsedRepository:
    return ParsedRepository(
        metadata=RepoMetadata(
            name="repo-a", source_url="https://github.com/test/repo-a",
            detected_language="javascript", detected_framework="express",
        ),
        modules=[ModuleNode(id="mod_0", path="app.js")],
    )


def test_diagram_scored_when_annotation_present(tmp_path):
    (tmp_path / "repo-a.json").write_text(
        json.dumps({"modules": ["app.js"], "imports": [], "endpoints": []})
    )
    with patch(
        "app.evaluation.harness.run_representation_ablation",
        return_value=(_parsed_with_modules(), [_result("mistral:7b", ContextVariant.RAW)]),
    ), patch(
        "app.evaluation.harness.score_summary", side_effect=lambda p, pr, txt, v, judge_model: _scored(v)
    ), patch(
        "app.evaluation.harness.score_coverage",
        side_effect=lambda p, pr, txt, v, judge_model: _scored_coverage(v),
    ):
        rows = run_evaluation(
            ["https://github.com/test/repo-a"],
            judge_model="llama3.1:8b",
            annotations_dir=tmp_path,
            driver=MagicMock(),
            provider=MagicMock(),
        )

    assert rows[0].diagram_scored is True
    assert rows[0].diagram_module_f1 == 1.0  # annotation's single module matches
    assert rows[0].diagram_overall_f1 == 1.0


def _sample_row() -> EvaluationRow:
    return EvaluationRow(
        repo_name="repo-a", source_url="u", framework="express", model="mistral:7b",
        context_variant="raw", run_status="success", latency_ms=1000, input_tokens=300,
        output_tokens=60, estimated_cost_usd=0.0, judge_model="llama3.1:8b", self_judged=False,
        hallucination_judged=True, hallucination_score=0.25, total_claims=4, unsupported_claims=1,
        coverage_judged=True, coverage_score=0.75, total_facts=4, missing_facts=1,
    )


def test_write_sqlite_accumulates_across_runs(tmp_path):
    db = tmp_path / "results.db"
    write_sqlite([_sample_row()], db)
    write_sqlite([_sample_row()], db)  # second run appends, not overwrites

    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT model, context_variant, hallucination_score, self_judged FROM evaluation_runs"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 2  # both runs present
    assert rows[0][0] == "mistral:7b"
    assert rows[0][3] == 0  # bool coerced to 0/1


def test_diagram_not_scored_when_no_annotation(tmp_path):
    with patch(
        "app.evaluation.harness.run_representation_ablation",
        return_value=(_parsed_with_modules(), [_result("mistral:7b", ContextVariant.RAW)]),
    ), patch(
        "app.evaluation.harness.score_summary", side_effect=lambda p, pr, txt, v, judge_model: _scored(v)
    ), patch(
        "app.evaluation.harness.score_coverage",
        side_effect=lambda p, pr, txt, v, judge_model: _scored_coverage(v),
    ):
        rows = run_evaluation(
            ["https://github.com/test/repo-a"],
            judge_model="llama3.1:8b",
            annotations_dir=tmp_path,  # dir exists but has no repo-a.json
            driver=MagicMock(),
            provider=MagicMock(),
        )

    assert rows[0].diagram_scored is False
    assert rows[0].diagram_overall_f1 is None
