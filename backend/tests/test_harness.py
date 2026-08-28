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
from app.schemas.parser_schema import (
    ApiEndpoint,
    Dependencies,
    ExternalDependency,
    HttpMethod,
    ModuleNode,
    ParsedRepository,
    RepoMetadata,
)


def _parsed(name="repo-a") -> ParsedRepository:
    return ParsedRepository(
        metadata=RepoMetadata(
            name=name,
            source_url=f"https://github.com/test/{name}",
            detected_language="javascript",
            detected_framework="express",
        )
    )


def _parsed_with_facts(name="repo-a") -> ParsedRepository:
    """Like _parsed(), but with real dependency/endpoint facts to check for a
    non-empty facts_by_category (bare _parsed() has none, so category-breakdown
    behavior can't be observed against it)."""
    parsed = _parsed(name)
    parsed.dependencies = Dependencies(
        external=[ExternalDependency(name="express"), ExternalDependency(name="cors")]
    )
    parsed.api_endpoints = [
        ApiEndpoint(id="ep_0", method=HttpMethod.GET, path="/users"),
    ]
    return parsed


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


def test_text_overlap_scored_when_reference_summary_present(tmp_path):
    (tmp_path / "repo-a.json").write_text(json.dumps({"overview": "A REST API for tutorials."}))
    result_with_overview = LLMResult(
        provider=ProviderName.OLLAMA, model="mistral:7b", task=LLMTask.SUMMARY,
        context_variant=ContextVariant.RAW, repo_name="repo-a",
        output=LLMOutput(raw_text=json.dumps({"overview": "A REST API for tutorials."})),
        metrics=LLMMetrics(latency_ms=1000, input_tokens=300, output_tokens=60, estimated_cost_usd=0.0),
        status=RunStatus.SUCCESS,
    )
    with patch(
        "app.evaluation.harness.run_representation_ablation",
        return_value=(_parsed(), [result_with_overview]),
    ), patch(
        "app.evaluation.harness.score_summary", side_effect=lambda p, pr, txt, v, judge_model: _scored(v)
    ), patch(
        "app.evaluation.harness.score_coverage",
        side_effect=lambda p, pr, txt, v, judge_model: _scored_coverage(v),
    ):
        rows = run_evaluation(
            ["https://github.com/test/repo-a"],
            judge_model="llama3.1:8b",
            reference_summaries_dir=tmp_path,
            bert_scorer=lambda refs, hyps: [0.9] * len(hyps),
            driver=MagicMock(),
            provider=MagicMock(),
        )

    assert rows[0].text_overlap_scored is True
    assert rows[0].bleu4 is not None and rows[0].bleu4 > 0.9  # identical text
    assert rows[0].bertscore_f1 == 0.9


def test_text_overlap_not_scored_without_reference_summaries_dir():
    with patch(
        "app.evaluation.harness.run_representation_ablation",
        return_value=(_parsed(), [_result("mistral:7b", ContextVariant.RAW)]),
    ), patch(
        "app.evaluation.harness.score_summary", side_effect=lambda p, pr, txt, v, judge_model: _scored(v)
    ), patch(
        "app.evaluation.harness.score_coverage",
        side_effect=lambda p, pr, txt, v, judge_model: _scored_coverage(v),
    ):
        rows = run_evaluation(
            ["https://github.com/test/repo-a"], judge_model="llama3.1:8b",
            driver=MagicMock(), provider=MagicMock(),
        )
    assert rows[0].text_overlap_scored is False
    assert rows[0].bleu4 is None


def test_quality_judge_off_by_default():
    with patch(
        "app.evaluation.harness.run_representation_ablation",
        return_value=(_parsed(), [_result("mistral:7b", ContextVariant.RAW)]),
    ), patch(
        "app.evaluation.harness.score_summary", side_effect=lambda p, pr, txt, v, judge_model: _scored(v)
    ), patch(
        "app.evaluation.harness.score_coverage",
        side_effect=lambda p, pr, txt, v, judge_model: _scored_coverage(v),
    ), patch("app.evaluation.harness.score_summary_quality") as quality_mock:
        rows = run_evaluation(
            ["https://github.com/test/repo-a"], judge_model="llama3.1:8b",
            driver=MagicMock(), provider=MagicMock(),
        )
    quality_mock.assert_not_called()
    assert rows[0].quality_judged is False


def test_quality_judge_runs_when_enabled():
    from app.evaluation.quality_judge import GEvalScore, QualityJudgeResult

    fake_result = QualityJudgeResult(
        repo_name="repo-a", context_variant=ContextVariant.RAW, judge_model="llama3.1:8b",
        target="summary",
        scores={
            "completeness": GEvalScore(criterion="completeness", score=4.0, method="logprob_weighted", raw_response=""),
            "conciseness": GEvalScore(criterion="conciseness", score=4.0, method="logprob_weighted", raw_response=""),
            "correctness": GEvalScore(criterion="correctness", score=4.0, method="logprob_weighted", raw_response=""),
            "cohesiveness": GEvalScore(criterion="cohesiveness", score=4.0, method="logprob_weighted", raw_response=""),
            "domain_specificity": GEvalScore(criterion="domain_specificity", score=4.0, method="logprob_weighted", raw_response=""),
        },
        mean_score=4.0,
    )
    with patch(
        "app.evaluation.harness.run_representation_ablation",
        return_value=(_parsed(), [_result("mistral:7b", ContextVariant.RAW)]),
    ), patch(
        "app.evaluation.harness.score_summary", side_effect=lambda p, pr, txt, v, judge_model: _scored(v)
    ), patch(
        "app.evaluation.harness.score_coverage",
        side_effect=lambda p, pr, txt, v, judge_model: _scored_coverage(v),
    ), patch("app.evaluation.harness.score_summary_quality", return_value=fake_result) as quality_mock:
        rows = run_evaluation(
            ["https://github.com/test/repo-a"], judge_model="llama3.1:8b",
            enable_quality_judge=True,
            driver=MagicMock(), provider=MagicMock(),
        )
    quality_mock.assert_called_once()
    assert rows[0].quality_judged is True
    assert rows[0].quality_mean_score == 4.0
    assert rows[0].quality_completeness == 4.0


def test_failure_tags_populated_on_successful_row():
    with patch(
        "app.evaluation.harness.run_representation_ablation",
        return_value=(_parsed(), [_result("mistral:7b", ContextVariant.RAW)]),
    ), patch(
        "app.evaluation.harness.score_summary", side_effect=lambda p, pr, txt, v, judge_model: _scored(v)
    ), patch(
        "app.evaluation.harness.score_coverage",
        side_effect=lambda p, pr, txt, v, judge_model: _scored_coverage(v),
    ):
        rows = run_evaluation(
            ["https://github.com/test/repo-a"], judge_model="llama3.1:8b",
            driver=MagicMock(), provider=MagicMock(),
        )
    # _scored()/_scored_coverage() fixtures carry a MongoDB claim and a missed endpoint
    assert "missed_endpoint" in rows[0].failure_tags


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


def test_summary_text_persisted_on_success():
    result = _result("mistral:7b", ContextVariant.RAW)
    result.output.raw_text = '{"overview": "a test summary"}'
    with patch(
        "app.evaluation.harness.run_representation_ablation",
        return_value=(_parsed(), [result]),
    ), patch(
        "app.evaluation.harness.score_summary", side_effect=lambda p, pr, txt, v, judge_model: _scored(v)
    ), patch(
        "app.evaluation.harness.score_coverage",
        side_effect=lambda p, pr, txt, v, judge_model: _scored_coverage(v),
    ):
        rows = run_evaluation(
            ["https://github.com/test/repo-a"], judge_model="llama3.1:8b",
            driver=MagicMock(), provider=MagicMock(),
        )
    assert rows[0].summary_text == '{"overview": "a test summary"}'


def test_summary_text_empty_on_failed_generation():
    results = [_result("mistral:7b", ContextVariant.RAW, status=RunStatus.FAILED)]
    with patch(
        "app.evaluation.harness.run_representation_ablation", return_value=(_parsed(), results)
    ), patch("app.evaluation.harness.score_summary") as score_mock, patch(
        "app.evaluation.harness.score_coverage"
    ) as coverage_mock:
        rows = run_evaluation(["u"], judge_model="llama3.1:8b", driver=MagicMock(), provider=MagicMock())
    score_mock.assert_not_called()
    coverage_mock.assert_not_called()
    assert rows[0].summary_text == ""
    assert rows[0].missing_facts_list == "[]"
    assert rows[0].unsupported_claims_list == "[]"
    assert rows[0].facts_by_category == "{}"


def test_missing_and_unsupported_lists_are_json_encoded():
    with patch(
        "app.evaluation.harness.run_representation_ablation",
        return_value=(_parsed(), [_result("mistral:7b", ContextVariant.RAW)]),
    ), patch(
        "app.evaluation.harness.score_summary", side_effect=lambda p, pr, txt, v, judge_model: _scored(v)
    ), patch(
        "app.evaluation.harness.score_coverage",
        side_effect=lambda p, pr, txt, v, judge_model: _scored_coverage(v),
    ):
        rows = run_evaluation(
            ["https://github.com/test/repo-a"], judge_model="llama3.1:8b",
            driver=MagicMock(), provider=MagicMock(),
        )
    # _scored()/_scored_coverage() fixtures (see top of file) carry a MongoDB
    # claim and a missed GET /users endpoint respectively.
    assert json.loads(rows[0].unsupported_claims_list) == ["uses MongoDB"]
    assert json.loads(rows[0].missing_facts_list) == ["Endpoint: GET /users"]


def test_facts_by_category_reflects_parsed_repository():
    with patch(
        "app.evaluation.harness.run_representation_ablation",
        return_value=(_parsed_with_facts(), [_result("mistral:7b", ContextVariant.RAW)]),
    ), patch(
        "app.evaluation.harness.score_summary", side_effect=lambda p, pr, txt, v, judge_model: _scored(v)
    ), patch(
        "app.evaluation.harness.score_coverage",
        side_effect=lambda p, pr, txt, v, judge_model: _scored_coverage(v),
    ):
        rows = run_evaluation(
            ["https://github.com/test/repo-a"], judge_model="llama3.1:8b",
            driver=MagicMock(), provider=MagicMock(),
        )
    # _parsed_with_facts() has 2 external deps (express, cors), 1 endpoint, plus
    # the detected framework/language _parsed() already sets (express/javascript).
    by_category = json.loads(rows[0].facts_by_category)
    assert by_category == {"Framework": 1, "Language": 1, "Dependency": 2, "Endpoint": 1}
