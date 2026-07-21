"""
Unit tests for OllamaProvider, run against a fake ollama.Client so they're fast and
don't require a local Ollama daemon. Real-model integration (against an actually
running Ollama with the 3 pulled models) is exercised manually per the roadmap's
Day-0 hardware check, not by this offline suite.
"""

from unittest.mock import MagicMock

import pytest

from app.providers.base import ProviderCallError
from app.providers.ollama_provider import OllamaProvider
from app.schemas.llm_result import ContextVariant, ProviderName, RunStatus


def _fake_response(content="mocked summary", prompt_eval_count=42, eval_count=7):
    response = MagicMock()
    response.message.content = content
    response.prompt_eval_count = prompt_eval_count
    response.eval_count = eval_count
    return response


@pytest.fixture
def provider(monkeypatch):
    p = OllamaProvider(host="http://fake-host:11434")
    p._client = MagicMock()
    return p


def test_provider_name_is_ollama(provider):
    assert provider.provider_name == ProviderName.OLLAMA


def test_generate_summary_success(provider):
    provider._client.chat.return_value = _fake_response()

    result = provider.generate_summary(
        context="repo context blob",
        repo_name="test-repo",
        context_variant=ContextVariant.KNOWLEDGE_GRAPH,
        prompt_template="Summarize: {context}",
        model="qwen2.5-coder:7b",
    )

    assert result.status == RunStatus.SUCCESS
    assert result.output.raw_text == "mocked summary"
    assert result.metrics.input_tokens == 42
    assert result.metrics.output_tokens == 7
    assert result.metrics.estimated_cost_usd == 0.0
    assert result.model == "qwen2.5-coder:7b"
    assert result.context_variant == ContextVariant.KNOWLEDGE_GRAPH


def test_identical_call_shape_across_models(provider):
    """Same runModel-style call, only the model name differs -- this is the
    roadmap's requirement that all 3 models go through one identical interface."""
    provider._client.chat.return_value = _fake_response()

    for model_name in ("qwen2.5-coder:7b", "llama3.1:8b", "gpt-oss:20b"):
        result = provider.generate_summary(
            context="ctx",
            repo_name="repo",
            context_variant=ContextVariant.RAW,
            prompt_template="{context}",
            model=model_name,
        )
        assert result.model == model_name
        assert result.status == RunStatus.SUCCESS


def test_connection_failure_raises_provider_call_error_and_records_failed_status(provider):
    provider._client.chat.side_effect = ConnectionError("daemon not running")

    result = provider.generate_summary(
        context="ctx",
        repo_name="repo",
        context_variant=ContextVariant.RAW,
        prompt_template="{context}",
        model="qwen2.5-coder:7b",
    )

    assert result.status == RunStatus.FAILED
    assert "daemon not running" in result.error
    assert result.metrics.estimated_cost_usd == 0.0


def test_call_model_wraps_errors_as_provider_call_error(provider):
    provider._client.chat.side_effect = RuntimeError("model not pulled")

    with pytest.raises(ProviderCallError):
        provider._call_model("qwen2.5-coder:7b", "system", "user")
