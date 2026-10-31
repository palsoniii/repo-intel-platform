"""The dashboard's model gateway (Groq or local) and the public-mode rate limits, with
Groq's HTTP API replaced by a mock transport: no key or network needed."""

import json

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.product import llm, ratelimit

MESSAGES = [{"role": "user", "content": "hi"}]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("LLM_PROVIDER", "GROQ_API_KEY", "GROQ_MODEL", "LLM_FALLBACK", "PUBLIC_MODE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    yield
    llm._TRANSPORT = None
    ratelimit.reset()


def _groq(monkeypatch, handler):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    llm._TRANSPORT = httpx.MockTransport(handler)


def test_provider_follows_the_key_unless_set_explicitly(monkeypatch):
    assert llm.provider() == "ollama"
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert llm.provider() == "groq"
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert llm.provider() == "ollama"


def test_groq_completion_hides_reasoning_and_asks_for_json(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"a": 1}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        })

    _groq(monkeypatch, handler)
    out = llm.complete(MESSAGES, max_tokens=50, json_mode=True)
    assert (out.text, out.provider, out.input_tokens) == ('{"a": 1}', "groq", 10)
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["include_reasoning"] is False and seen["reasoning_effort"] == "low"


def test_rate_limit_is_retried_then_reported_plainly(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "1"}, json={"error": {"message": "slow down"}})

    _groq(monkeypatch, handler)
    monkeypatch.setenv("LLM_FALLBACK", "none")
    with pytest.raises(llm.ModelError, match="rate limit"):
        llm.complete(MESSAGES, max_tokens=50)
    assert len(calls) == llm.GROQ_RETRIES + 1


def test_groq_failure_falls_back_to_the_local_model(monkeypatch):
    _groq(monkeypatch, lambda r: httpx.Response(500, json={"error": {"message": "down"}}))
    local = llm.Completion(text="local answer", provider="ollama", model="qwen2.5-coder:7b")
    monkeypatch.setattr(llm, "_ollama_complete", lambda *a, **k: local)
    assert llm.complete(MESSAGES, max_tokens=50) is local


def _sse(*chunks: dict) -> bytes:
    return b"".join(f"data: {json.dumps(c)}\n\n".encode() for c in chunks) + b"data: [DONE]\n\n"


def test_stream_yields_text_and_records_usage(monkeypatch):
    body = _sse(
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2}},
    )
    _groq(monkeypatch, lambda r: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    result = llm.StreamResult()
    assert "".join(llm.stream(MESSAGES, 50, result)) == "Hello"
    assert (result.provider, result.stats["input_tokens"], result.stats["output_tokens"]) == ("groq", 7, 2)


def test_stream_falls_back_only_before_the_first_word(monkeypatch):
    _groq(monkeypatch, lambda r: httpx.Response(503, json={"error": {"message": "busy"}}))

    def local(messages, max_tokens, temperature, result):
        result.provider, result.model = "ollama", "qwen2.5-coder:7b"
        yield "from local"

    monkeypatch.setattr(llm, "_ollama_stream", local)
    result = llm.StreamResult()
    assert "".join(llm.stream(MESSAGES, 50, result)) == "from local"
    assert result.provider == "ollama"


def _request(ip: str) -> Request:
    return Request({"type": "http", "client": (ip, 1234), "headers": [], "method": "POST", "path": "/"})


def test_rate_limits_apply_per_visitor_and_only_in_public_mode(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ANALYSES_PER_HOUR", "2")
    for _ in range(5):
        ratelimit.check(_request("1.1.1.1"), "analyses")  # off by default

    monkeypatch.setenv("PUBLIC_MODE", "true")
    ratelimit.check(_request("1.1.1.1"), "analyses")
    ratelimit.check(_request("1.1.1.1"), "analyses")
    with pytest.raises(HTTPException) as e:
        ratelimit.check(_request("1.1.1.1"), "analyses")
    assert e.value.status_code == 429
    ratelimit.check(_request("2.2.2.2"), "analyses")  # another visitor is unaffected
