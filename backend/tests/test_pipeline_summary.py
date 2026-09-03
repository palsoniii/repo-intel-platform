"""
Unit tests for generate_repository_summary's orchestration, run against mocked
Neo4j driver + LLM provider so they're fast and don't need live infra. Real
end-to-end behavior against a live Neo4j is covered by test_graph_builder.py /
test_context_builder.py; live Ollama behavior isn't exercised anywhere yet (no
Ollama daemon available in this environment -- see README's known limitations).
"""

from unittest.mock import MagicMock, patch

import pytest
from neo4j.exceptions import ServiceUnavailable

from app.pipeline import PipelineInfrastructureError, analyze_repository, generate_repository_summary
from app.schemas.llm_result import (
    ContextVariant,
    LLMMetrics,
    LLMOutput,
    LLMResult,
    LLMTask,
    ProviderName,
    RunStatus,
)
from app.schemas.parser_schema import ParsedRepository, RepoMetadata


def _fake_parsed_repository() -> ParsedRepository:
    return ParsedRepository(
        metadata=RepoMetadata(
            name="fake-repo",
            source_url="https://github.com/test/fake-repo",
            detected_language="javascript",
            detected_framework="express",
        )
    )


def _fake_llm_result(raw_text: str, status: RunStatus = RunStatus.SUCCESS) -> LLMResult:
    return LLMResult(
        provider=ProviderName.OLLAMA,
        model="qwen2.5-coder:7b",
        task=LLMTask.SUMMARY,
        context_variant=ContextVariant.KNOWLEDGE_GRAPH,
        repo_name="fake-repo",
        output=LLMOutput(raw_text=raw_text),
        metrics=LLMMetrics(latency_ms=100, input_tokens=10, output_tokens=5, estimated_cost_usd=0.0),
        status=status,
    )


@pytest.fixture
def mock_driver():
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = MagicMock()
    return driver


@pytest.fixture(autouse=True)
def mock_analyze(monkeypatch):
    monkeypatch.setattr(
        "app.pipeline.analyze_repository", lambda url, max_size_mb=200: _fake_parsed_repository()
    )


def test_orchestration_calls_graph_and_context_before_provider(mock_driver):
    provider = MagicMock()
    provider.default_model = "qwen2.5-coder:7b"
    provider.generate_summary.return_value = _fake_llm_result(
        '{"overview": "x", "tech_stack": [], "services": [], "dependencies": []}'
    )

    with patch("app.graph.builder.ensure_constraints") as mock_constraints, patch(
        "app.graph.builder.write_parsed_repository"
    ) as mock_write, patch("app.context.builder.build_context", return_value="fake context") as mock_ctx:
        parsed, result = generate_repository_summary(
            "https://github.com/test/fake-repo", driver=mock_driver, provider=provider
        )

    mock_constraints.assert_called_once_with(mock_driver)
    mock_write.assert_called_once()
    mock_ctx.assert_called_once_with(mock_driver, "fake-repo", ContextVariant.KNOWLEDGE_GRAPH)
    provider.generate_summary.assert_called_once()
    assert provider.generate_summary.call_args.kwargs["context"] == "fake context"
    assert provider.generate_summary.call_args.kwargs["model"] == "qwen2.5-coder:7b"
    assert parsed.metadata.name == "fake-repo"
    assert result.output.parsed == {
        "overview": "x", "tech_stack": [], "services": [], "dependencies": [],
    }
    assert result.output.valid is True


def test_injected_driver_is_not_closed(mock_driver):
    """A caller-supplied driver is reused across requests -- the pipeline must not
    close a connection it doesn't own."""
    provider = MagicMock()
    provider.default_model = "qwen2.5-coder:7b"
    provider.generate_summary.return_value = _fake_llm_result("not json")

    with patch("app.graph.builder.ensure_constraints"), patch("app.graph.builder.write_parsed_repository"), patch(
        "app.context.builder.build_context", return_value="ctx"
    ):
        generate_repository_summary(
            "https://github.com/test/fake-repo", driver=mock_driver, provider=provider
        )

    mock_driver.close.assert_not_called()


def test_owned_driver_is_closed_even_if_context_build_fails(mock_driver):
    provider = MagicMock()
    provider.default_model = "qwen2.5-coder:7b"

    with patch("app.db.neo4j_client.get_driver", return_value=mock_driver), patch(
        "app.graph.builder.ensure_constraints"
    ), patch("app.graph.builder.write_parsed_repository"), patch(
        "app.context.builder.build_context", side_effect=RuntimeError("graph query failed")
    ):
        with pytest.raises(RuntimeError):
            generate_repository_summary("https://github.com/test/fake-repo", provider=provider)

    mock_driver.close.assert_called_once()


def test_neo4j_connection_failure_wrapped_as_infrastructure_error(mock_driver):
    """Found via manual browser testing: /summarize against a real-but-down Neo4j
    raised a raw neo4j.exceptions.ServiceUnavailable, which is a 500-shaped
    unhandled exception at the API layer (and, worse, one that arrives at the
    browser with no CORS headers -- see test_main.py). This should be a clean,
    distinguishable error instead."""
    provider = MagicMock()
    provider.default_model = "qwen2.5-coder:7b"

    with patch("app.graph.builder.ensure_constraints"), patch("app.graph.builder.write_parsed_repository"), patch(
        "app.context.builder.build_context",
        side_effect=ServiceUnavailable("Couldn't connect to localhost:7687"),
    ):
        with pytest.raises(PipelineInfrastructureError, match="Neo4j"):
            generate_repository_summary(
                "https://github.com/test/fake-repo", driver=mock_driver, provider=provider
            )

    mock_driver.close.assert_not_called()  # injected driver, not owned -- shouldn't be closed


def test_malformed_model_output_marked_invalid_not_raised(mock_driver):
    provider = MagicMock()
    provider.default_model = "qwen2.5-coder:7b"
    provider.generate_summary.return_value = _fake_llm_result("this is not JSON at all")

    with patch("app.graph.builder.ensure_constraints"), patch("app.graph.builder.write_parsed_repository"), patch(
        "app.context.builder.build_context", return_value="ctx"
    ):
        _, result = generate_repository_summary(
            "https://github.com/test/fake-repo", driver=mock_driver, provider=provider
        )

    assert result.output.valid is False
    assert result.output.parsed is None


def test_missing_required_keys_marked_invalid(mock_driver):
    provider = MagicMock()
    provider.default_model = "qwen2.5-coder:7b"
    provider.generate_summary.return_value = _fake_llm_result('{"overview": "x"}')  # missing keys

    with patch("app.graph.builder.ensure_constraints"), patch("app.graph.builder.write_parsed_repository"), patch(
        "app.context.builder.build_context", return_value="ctx"
    ):
        _, result = generate_repository_summary(
            "https://github.com/test/fake-repo", driver=mock_driver, provider=provider
        )

    assert result.output.valid is False


def test_failed_llm_run_is_not_json_parsed(mock_driver):
    """If the provider itself reports FAILED (e.g. Ollama daemon unreachable),
    there's no raw_text worth trying to parse."""
    provider = MagicMock()
    provider.default_model = "qwen2.5-coder:7b"
    provider.generate_summary.return_value = _fake_llm_result("", status=RunStatus.FAILED)

    with patch("app.graph.builder.ensure_constraints"), patch("app.graph.builder.write_parsed_repository"), patch(
        "app.context.builder.build_context", return_value="ctx"
    ):
        _, result = generate_repository_summary(
            "https://github.com/test/fake-repo", driver=mock_driver, provider=provider
        )

    assert result.output.parsed is None
    assert result.output.valid is False
