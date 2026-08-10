"""
Unit tests for the LLM-as-judge hallucination scorer, run against a mocked provider
so they're fast and don't need a live Ollama. The judge's actual grading quality is
a separate, human-validated concern (roadmap Week 4) -- these tests cover the
scoring mechanics: fact formatting, verdict parsing, score arithmetic, and the
degenerate cases (unparseable verdict, zero claims).
"""

from unittest.mock import MagicMock

from app.evaluation.hallucination import HallucinationResult, build_ground_truth, score_summary
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
    DependencyType,
    ExternalDependency,
    HttpMethod,
    ModuleNode,
    ParsedRepository,
    RepoMetadata,
)


def _parsed_repo() -> ParsedRepository:
    return ParsedRepository(
        metadata=RepoMetadata(
            name="sample-repo",
            source_url="https://github.com/test/sample-repo",
            detected_language="javascript",
            detected_framework="express",
            framework_version="^4.18.0",
        ),
        modules=[ModuleNode(id="mod_0", path="app.js")],
        api_endpoints=[
            ApiEndpoint(id="mod_0_ep_0", method=HttpMethod.GET, path="/users"),
        ],
        dependencies=Dependencies(
            external=[ExternalDependency(name="express", dep_type=DependencyType.RUNTIME)]
        ),
    )


def _judge_result(raw_text: str, status: RunStatus = RunStatus.SUCCESS) -> LLMResult:
    return LLMResult(
        provider=ProviderName.OLLAMA,
        model="llama3.1:8b",
        task=LLMTask.HALLUCINATION_JUDGE,
        context_variant=ContextVariant.KNOWLEDGE_GRAPH,
        repo_name="sample-repo",
        output=LLMOutput(raw_text=raw_text),
        metrics=LLMMetrics(latency_ms=100, input_tokens=10, output_tokens=5, estimated_cost_usd=0.0),
        status=status,
    )


def _provider_returning(raw_text: str) -> MagicMock:
    provider = MagicMock()
    provider.default_model = "llama3.1:8b"
    provider.judge.return_value = _judge_result(raw_text)
    return provider


def test_ground_truth_includes_key_facts():
    facts = build_ground_truth(_parsed_repo())
    assert "express" in facts
    assert "GET /users" in facts
    assert "1 modules" in facts


def test_clean_summary_scores_zero():
    provider = _provider_returning('{"total_claims": 3, "unsupported_claims": []}')
    result = score_summary(
        provider, _parsed_repo(), "An Express app with a /users endpoint.",
        ContextVariant.KNOWLEDGE_GRAPH,
    )
    assert isinstance(result, HallucinationResult)
    assert result.judged is True
    assert result.total_claims == 3
    assert result.unsupported_claims == []
    assert result.hallucination_score == 0.0


def test_unsupported_claims_raise_the_score():
    provider = _provider_returning(
        '{"total_claims": 4, "unsupported_claims": ["uses MongoDB", "has a GraphQL API"]}'
    )
    result = score_summary(
        provider, _parsed_repo(), "An Express app using MongoDB with a GraphQL API.",
        ContextVariant.RAW,
    )
    assert result.total_claims == 4
    assert result.unsupported_claims == ["uses MongoDB", "has a GraphQL API"]
    assert result.hallucination_score == 0.5
    assert result.context_variant == ContextVariant.RAW  # attributable to the arm judged


def test_judge_model_defaults_but_is_overridable():
    provider = _provider_returning('{"total_claims": 1, "unsupported_claims": []}')
    score_summary(provider, _parsed_repo(), "summary", ContextVariant.RAW, judge_model="qwen2.5-coder:7b")
    assert provider.judge.call_args.kwargs["model"] == "qwen2.5-coder:7b"


def test_verdict_wrapped_in_prose_or_code_fence_still_parses():
    provider = _provider_returning(
        'Here is my verdict:\n```json\n{"total_claims": 2, "unsupported_claims": ["uses Redis"]}\n```'
    )
    result = score_summary(provider, _parsed_repo(), "summary", ContextVariant.RAW)
    assert result.judged is True
    assert result.hallucination_score == 0.5


def test_unparseable_verdict_marked_not_judged():
    provider = _provider_returning("I could not produce JSON, sorry.")
    result = score_summary(provider, _parsed_repo(), "summary", ContextVariant.RAW)
    assert result.judged is False
    assert result.hallucination_score == 0.0
    assert result.total_claims == 0


def test_zero_claims_does_not_divide_by_zero():
    provider = _provider_returning('{"total_claims": 0, "unsupported_claims": []}')
    result = score_summary(provider, _parsed_repo(), "", ContextVariant.RAW)
    assert result.judged is True
    assert result.hallucination_score == 0.0


def test_more_unsupported_than_total_is_clamped():
    provider = _provider_returning(
        '{"total_claims": 1, "unsupported_claims": ["a", "b", "c"]}'
    )
    result = score_summary(provider, _parsed_repo(), "summary", ContextVariant.RAW)
    # score must stay in [0, 1] even if the judge reports an inconsistent count
    assert result.hallucination_score == 1.0
    assert result.total_claims == 3
