"""
Unit tests for run_representation_ablation's orchestration, run against mocked
clone/Neo4j/provider so they're fast and don't need a live model (a real 3-model x
3-representation run takes minutes -- exercised manually, not in the offline suite;
see README).
"""

from unittest.mock import MagicMock, patch

import pytest

from app.acquisition.clone import AcquiredRepo
from app.pipeline import run_representation_ablation, run_scored_ablation
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


def _fake_llm_result(
    model: str, variant: ContextVariant, status: RunStatus = RunStatus.SUCCESS
) -> LLMResult:
    return LLMResult(
        provider=ProviderName.OLLAMA,
        model=model,
        task=LLMTask.SUMMARY,
        context_variant=variant,
        repo_name="fake-repo",
        output=LLMOutput(
            raw_text='{"overview": "x", "tech_stack": [], "services": [], "dependencies": []}'
        ),
        metrics=LLMMetrics(latency_ms=100, input_tokens=10, output_tokens=5, estimated_cost_usd=0.0),
        status=status,
    )


@pytest.fixture
def fake_acquired_repo(tmp_path):
    (tmp_path / "app.js").write_text("console.log('hello');")
    return AcquiredRepo(
        local_path=tmp_path,
        owner="test",
        repo_name="fake-repo",
        source_url="https://github.com/test/fake-repo",
        commit_sha="abc123",
    )


@pytest.fixture
def fake_parsed_repository():
    return ParsedRepository(
        metadata=RepoMetadata(
            name="fake-repo",
            source_url="https://github.com/test/fake-repo",
            detected_language="javascript",
            detected_framework="express",
        ),
        modules=[ModuleNode(id="mod_0", path="app.js")],
    )


def test_runs_all_models_across_all_three_representations(fake_acquired_repo, fake_parsed_repository):
    provider = MagicMock()
    provider.generate_summary.side_effect = lambda **kwargs: _fake_llm_result(
        kwargs["model"], kwargs["context_variant"]
    )
    mock_driver = MagicMock()

    with patch("app.pipeline.clone_repository", return_value=fake_acquired_repo), patch(
        "app.pipeline.parse_repository", return_value=fake_parsed_repository
    ), patch("app.pipeline.ensure_constraints"), patch(
        "app.pipeline.write_parsed_repository"
    ), patch(
        "app.pipeline.build_context",
        side_effect=lambda driver, repo_name, variant: f"context-for-{variant.value}",
    ):
        parsed, results = run_representation_ablation(
            "https://github.com/test/fake-repo",
            models=["model-a", "model-b"],
            driver=mock_driver,
            provider=provider,
        )

    assert parsed.metadata.name == "fake-repo"
    assert len(results) == 2 * 3  # 2 models x 3 representations
    seen = {(r.model, r.context_variant) for r in results}
    assert seen == {
        ("model-a", ContextVariant.RAW),
        ("model-a", ContextVariant.DEPENDENCY_GRAPH),
        ("model-a", ContextVariant.KNOWLEDGE_GRAPH),
        ("model-b", ContextVariant.RAW),
        ("model-b", ContextVariant.DEPENDENCY_GRAPH),
        ("model-b", ContextVariant.KNOWLEDGE_GRAPH),
    }


def test_raw_context_actually_contains_source_text(fake_acquired_repo, fake_parsed_repository):
    provider = MagicMock()
    captured_contexts = {}

    def _capture(**kwargs):
        captured_contexts[kwargs["context_variant"]] = kwargs["context"]
        return _fake_llm_result(kwargs["model"], kwargs["context_variant"])

    provider.generate_summary.side_effect = _capture
    mock_driver = MagicMock()

    with patch("app.pipeline.clone_repository", return_value=fake_acquired_repo), patch(
        "app.pipeline.parse_repository", return_value=fake_parsed_repository
    ), patch("app.pipeline.ensure_constraints"), patch(
        "app.pipeline.write_parsed_repository"
    ), patch("app.pipeline.build_context", return_value="graph-based-context"):
        run_representation_ablation(
            "https://github.com/test/fake-repo",
            models=["model-a"],
            driver=mock_driver,
            provider=provider,
        )

    assert "console.log('hello')" in captured_contexts[ContextVariant.RAW]
    assert captured_contexts[ContextVariant.DEPENDENCY_GRAPH] == "graph-based-context"
    assert captured_contexts[ContextVariant.KNOWLEDGE_GRAPH] == "graph-based-context"


def test_raw_context_is_truncated_to_max_chars(fake_acquired_repo, fake_parsed_repository):
    (fake_acquired_repo.local_path / "app.js").write_text("x" * 5000)
    provider = MagicMock()
    captured = {}
    provider.generate_summary.side_effect = lambda **kwargs: (
        captured.__setitem__(kwargs["context_variant"], kwargs["context"])
        or _fake_llm_result(kwargs["model"], kwargs["context_variant"])
    )
    mock_driver = MagicMock()

    with patch("app.pipeline.clone_repository", return_value=fake_acquired_repo), patch(
        "app.pipeline.parse_repository", return_value=fake_parsed_repository
    ), patch("app.pipeline.ensure_constraints"), patch(
        "app.pipeline.write_parsed_repository"
    ), patch("app.pipeline.build_context", return_value="ctx"):
        run_representation_ablation(
            "https://github.com/test/fake-repo",
            models=["model-a"],
            max_raw_chars=100,
            driver=mock_driver,
            provider=provider,
        )

    assert len(captured[ContextVariant.RAW]) <= 100


def test_cleans_up_acquired_repo_even_if_neo4j_fails(fake_acquired_repo, fake_parsed_repository):
    fake_acquired_repo_mock = MagicMock(wraps=fake_acquired_repo)
    fake_acquired_repo_mock.local_path = fake_acquired_repo.local_path

    with patch("app.pipeline.clone_repository", return_value=fake_acquired_repo_mock), patch(
        "app.pipeline.parse_repository", return_value=fake_parsed_repository
    ), patch("app.pipeline.ensure_constraints", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            run_representation_ablation(
                "https://github.com/test/fake-repo", driver=MagicMock(), provider=MagicMock()
            )

    fake_acquired_repo_mock.cleanup.assert_called_once()


def test_run_scored_ablation_attaches_a_score_per_successful_result(fake_parsed_repository):
    from app.evaluation.coverage import CoverageResult
    from app.evaluation.hallucination import HallucinationResult

    results = [
        _fake_llm_result("model-a", ContextVariant.RAW),
        _fake_llm_result("model-a", ContextVariant.KNOWLEDGE_GRAPH, status=RunStatus.FAILED),
    ]

    def _fake_score(provider, parsed, text, variant, judge_model):
        return HallucinationResult(
            repo_name="fake-repo", context_variant=variant, judge_model=judge_model,
            total_claims=2, unsupported_claims=[], hallucination_score=0.0, judged=True,
            judge_raw_output="{}",
        )

    def _fake_coverage(provider, parsed, text, variant, judge_model):
        return CoverageResult(
            repo_name="fake-repo", context_variant=variant, judge_model=judge_model,
            total_facts=3, missing_facts=[], coverage_score=1.0, judged=True,
            judge_raw_output="{}",
        )

    with patch(
        "app.pipeline.run_representation_ablation",
        return_value=(fake_parsed_repository, results),
    ), patch("app.pipeline.score_summary", side_effect=_fake_score) as mock_score, patch(
        "app.pipeline.score_coverage", side_effect=_fake_coverage
    ) as mock_coverage:
        parsed, scored = run_scored_ablation(
            "https://github.com/test/fake-repo",
            judge_model="llama3.1:8b",
            driver=MagicMock(),
            provider=MagicMock(),
        )

    assert len(scored) == 2
    # successful result got both scores; failed one got neither (nothing to grade)
    assert scored[0].hallucination is not None
    assert scored[0].hallucination.hallucination_score == 0.0
    assert scored[0].coverage is not None
    assert scored[0].coverage.coverage_score == 1.0
    assert scored[1].hallucination is None
    assert scored[1].coverage is None
    assert mock_score.call_count == 1  # only the successful result was judged
    assert mock_coverage.call_count == 1
