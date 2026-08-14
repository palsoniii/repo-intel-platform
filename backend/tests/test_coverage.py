"""
Unit tests for the coverage/recall scorer, run against a mocked provider so they're
fast and don't need a live Ollama -- same approach as test_hallucination.py. These
cover the scoring mechanics: fact-list construction, verdict parsing, score
arithmetic, and the degenerate cases (unparseable verdict, no facts to check,
a judge inventing a fact that was never asked about).
"""

from unittest.mock import MagicMock

from app.evaluation.coverage import CoverageResult, build_coverable_facts, score_coverage
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
            ApiEndpoint(id="mod_0_ep_1", method=HttpMethod.POST, path="/users"),
        ],
        dependencies=Dependencies(
            external=[ExternalDependency(name="express", dep_type=DependencyType.RUNTIME)]
        ),
    )


def _empty_repo() -> ParsedRepository:
    return ParsedRepository(
        metadata=RepoMetadata(
            name="empty-repo",
            source_url="https://github.com/test/empty-repo",
            detected_language="",
            detected_framework=None,
        ),
    )


def _judge_result(raw_text: str, status: RunStatus = RunStatus.SUCCESS) -> LLMResult:
    return LLMResult(
        provider=ProviderName.OLLAMA,
        model="llama3.1:8b",
        task=LLMTask.COVERAGE_JUDGE,
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


def test_coverable_facts_include_every_category():
    facts = build_coverable_facts(_parsed_repo())
    assert "Framework: express ^4.18.0" in facts
    assert "Language: javascript" in facts
    assert "Dependency: express" in facts
    assert "Endpoint: GET /users" in facts
    assert "Endpoint: POST /users" in facts


def test_fully_covered_summary_scores_one():
    provider = _provider_returning('{"missing_facts": []}')
    result = score_coverage(
        provider,
        _parsed_repo(),
        "An Express (^4.18.0) app in javascript with a GET /users and POST /users endpoint, using express.",
        ContextVariant.KNOWLEDGE_GRAPH,
    )
    assert isinstance(result, CoverageResult)
    assert result.judged is True
    assert result.missing_facts == []
    assert result.coverage_score == 1.0


def test_missing_facts_lower_the_score():
    facts = build_coverable_facts(_parsed_repo())
    provider = _provider_returning(
        '{"missing_facts": ["Endpoint: POST /users"]}'
    )
    result = score_coverage(provider, _parsed_repo(), "An Express app with GET /users.", ContextVariant.RAW)
    assert result.total_facts == len(facts)
    assert result.missing_facts == ["Endpoint: POST /users"]
    assert result.coverage_score == (len(facts) - 1) / len(facts)
    assert result.context_variant == ContextVariant.RAW  # attributable to the arm judged


def test_judge_model_defaults_but_is_overridable():
    provider = _provider_returning('{"missing_facts": []}')
    score_coverage(provider, _parsed_repo(), "summary", ContextVariant.RAW, judge_model="qwen2.5-coder:7b")
    assert provider.judge.call_args.kwargs["model"] == "qwen2.5-coder:7b"
    assert provider.judge.call_args.kwargs["task"] == LLMTask.COVERAGE_JUDGE


def test_verdict_wrapped_in_prose_or_code_fence_still_parses():
    provider = _provider_returning(
        'Here is my verdict:\n```json\n{"missing_facts": ["Dependency: express"]}\n```'
    )
    result = score_coverage(provider, _parsed_repo(), "summary", ContextVariant.RAW)
    assert result.judged is True
    assert result.missing_facts == ["Dependency: express"]


def test_unparseable_verdict_marked_not_judged():
    provider = _provider_returning("I could not produce JSON, sorry.")
    result = score_coverage(provider, _parsed_repo(), "summary", ContextVariant.RAW)
    assert result.judged is False
    assert result.coverage_score == 0.0


def test_invented_fact_is_dropped_not_trusted():
    """The judge must copy fact strings verbatim -- an invented or reworded entry
    that doesn't match anything we actually asked about is dropped rather than
    silently corrupting the score."""
    provider = _provider_returning(
        '{"missing_facts": ["Endpoint: GET /users", "Something we never asked about"]}'
    )
    result = score_coverage(provider, _parsed_repo(), "summary", ContextVariant.RAW)
    assert result.missing_facts == ["Endpoint: GET /users"]


def test_no_ground_truth_facts_is_vacuously_fully_covered():
    provider = _provider_returning('{"missing_facts": []}')
    result = score_coverage(provider, _empty_repo(), "", ContextVariant.RAW)
    assert result.judged is True
    assert result.total_facts == 0
    assert result.coverage_score == 1.0
    provider.judge.assert_not_called()  # nothing to check -- no judge call spent
