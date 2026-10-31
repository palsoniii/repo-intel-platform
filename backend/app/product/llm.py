"""
The model behind the dashboard's summary and Ask: Groq's hosted API, or the local
Ollama model the study used.

    LLM_PROVIDER=groq     Groq (needs GROQ_API_KEY); falls back to Ollama per call
                          when Groq fails and LLM_FALLBACK isn't "none"
    LLM_PROVIDER=ollama   the local model only, nothing leaves the machine
    (unset)               groq if GROQ_API_KEY is set, otherwise ollama

Only the product layer goes through here. The research pipeline (pipeline.py,
evaluation/) keeps calling OllamaProvider directly, so nothing the paper measured
changes.

Groq speaks the OpenAI chat-completions protocol, called with httpx rather than an
SDK: two endpoints (models, chat/completions) don't justify another dependency.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Iterator

import httpx

log = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
# Retries on a rate limit or a 5xx, waiting what Groq's retry-after header asks for,
# capped so a visitor isn't left watching a spinner for a minute.
GROQ_RETRIES = 2
MAX_RETRY_WAIT_S = 12.0


# Tests swap in an httpx.MockTransport; None is the real network.
_TRANSPORT: httpx.BaseTransport | None = None


def _http(timeout: float) -> httpx.Client:
    return httpx.Client(base_url=_env("GROQ_BASE_URL") or GROQ_BASE_URL, timeout=timeout, transport=_TRANSPORT)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).split("#")[0].strip()


def provider() -> str:
    chosen = _env("LLM_PROVIDER").lower()
    if chosen in ("groq", "ollama"):
        return chosen
    return "groq" if _env("GROQ_API_KEY") else "ollama"


def ollama_model() -> str:
    return _env("PRODUCT_SUMMARY_MODEL") or _env("OLLAMA_MODEL_PRIMARY") or "qwen2.5-coder:7b"


def groq_model() -> str:
    return _env("GROQ_MODEL") or DEFAULT_GROQ_MODEL


def model() -> str:
    return groq_model() if provider() == "groq" else ollama_model()


def fallback_enabled() -> bool:
    return provider() == "groq" and _env("LLM_FALLBACK", "ollama").lower() != "none"


def label(provider_name: str, model_name: str) -> str:
    return f"{'Groq' if provider_name == 'groq' else 'Local'} · {model_name}"


class ModelError(Exception):
    """A failure worth showing the user as is."""


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


@dataclass
class StreamResult:
    """Filled in as a stream() runs: which backend answered, and its token counts."""

    provider: str = ""
    model: str = ""
    stats: dict = field(default_factory=dict)


# --- Groq -------------------------------------------------------------------------


def _groq_body(name: str, messages: list[dict], max_tokens: int, temperature: float, json_mode: bool) -> dict:
    body: dict = {
        "model": name,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    # Reasoning models think before answering. Keep that short and out of the text:
    # the summary must be bare JSON, and Ask streams straight to the screen.
    if name.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "low"
        body["include_reasoning"] = False
    elif name.startswith("qwen/qwen3"):
        body["reasoning_format"] = "hidden"
    return body


def _groq_headers() -> dict:
    key = _env("GROQ_API_KEY")
    if not key:
        raise ModelError("LLM_PROVIDER is groq but GROQ_API_KEY isn't set.")
    return {"Authorization": f"Bearer {key}"}


def _groq_error(resp: httpx.Response) -> ModelError:
    try:
        detail = resp.json().get("error", {}).get("message", "")
    except ValueError:
        detail = resp.text[:200]
    if resp.status_code == 429:
        return ModelError("The AI service is busy right now (rate limit reached). Try again in a minute.")
    if resp.status_code in (401, 403):
        return ModelError("Groq rejected the API key. Check GROQ_API_KEY.")
    if resp.status_code == 404:
        return ModelError(f"Groq doesn't offer the model '{groq_model()}'. Check GROQ_MODEL. ({detail})")
    return ModelError(f"Groq returned {resp.status_code}: {detail}")


def _retry_wait(resp: httpx.Response, attempt: int) -> float:
    try:
        wait = float(resp.headers.get("retry-after", ""))
    except ValueError:
        wait = 2.0 * (attempt + 1)
    return min(wait, MAX_RETRY_WAIT_S)


def _retryable(resp: httpx.Response) -> bool:
    return resp.status_code == 429 or resp.status_code >= 500


def _groq_complete(messages: list[dict], max_tokens: int, temperature: float, json_mode: bool) -> Completion:
    name = groq_model()
    body = _groq_body(name, messages, max_tokens, temperature, json_mode)
    start = time.monotonic()
    with _http(120) as client:
        for attempt in range(GROQ_RETRIES + 1):
            resp = client.post("/chat/completions", json=body, headers=_groq_headers())
            if resp.status_code == 200:
                break
            if attempt < GROQ_RETRIES and _retryable(resp):
                time.sleep(_retry_wait(resp, attempt))
                continue
            raise _groq_error(resp)
    data = resp.json()
    usage = data.get("usage") or {}
    return Completion(
        text=data["choices"][0]["message"].get("content") or "",
        provider="groq",
        model=name,
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        latency_ms=int((time.monotonic() - start) * 1000),
    )


def _groq_stream(messages: list[dict], max_tokens: int, temperature: float, result: StreamResult) -> Iterator[str]:
    name = groq_model()
    body = _groq_body(name, messages, max_tokens, temperature, json_mode=False)
    body["stream"] = True
    body["stream_options"] = {"include_usage": True}
    start = time.monotonic()
    with _http(120) as client:
        for attempt in range(GROQ_RETRIES + 1):
            with client.stream("POST", "/chat/completions", json=body, headers=_groq_headers()) as resp:
                if resp.status_code != 200:
                    resp.read()
                    if attempt < GROQ_RETRIES and _retryable(resp):
                        time.sleep(_retry_wait(resp, attempt))
                        continue
                    raise _groq_error(resp)
                result.provider, result.model = "groq", name
                usage: dict = {}
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage") or usage
                    for choice in chunk.get("choices") or []:
                        text = (choice.get("delta") or {}).get("content")
                        if text:
                            yield text
                result.stats = {
                    "input_tokens": usage.get("prompt_tokens"),
                    "output_tokens": usage.get("completion_tokens"),
                    "duration_ms": int((time.monotonic() - start) * 1000),
                }
                return


def groq_status() -> dict:
    try:
        with _http(5) as client:
            resp = client.get("/models", headers=_groq_headers())
        if resp.status_code != 200:
            return {"reachable": False, "error": str(_groq_error(resp))}
        models = [m["id"] for m in resp.json().get("data", [])]
        return {"reachable": True, "model_available": groq_model() in models}
    except (ModelError, httpx.HTTPError) as e:
        return {"reachable": False, "error": str(e)}


# --- Ollama -----------------------------------------------------------------------


def _ollama_client(timeout: float = 600):
    import ollama

    return ollama.Client(host=_env("OLLAMA_HOST") or "http://localhost:11434", timeout=timeout)


def _ollama_options(temperature: float, **extra) -> dict:
    from app.product.jobs import num_ctx

    return {"temperature": temperature, "num_ctx": num_ctx(), **extra}


def _ollama_error(e: Exception, name: str) -> ModelError:
    low = str(e).lower()
    if "not found" in low and "model" in low:
        return ModelError(f"The model '{name}' isn't installed. Run: ollama pull {name}")
    if "connect" in low or "connection" in low:
        return ModelError("Couldn't reach Ollama. Is it running? (ollama serve)")
    return ModelError(str(e))


def _ollama_complete(messages: list[dict], max_tokens: int, temperature: float, json_mode: bool) -> Completion:
    from app.product.jobs import KEEP_ALIVE

    name = ollama_model()
    start = time.monotonic()
    try:
        response = _ollama_client().chat(
            model=name,
            messages=messages,
            # seed 42: what OllamaProvider pins for the study's summaries.
            options=_ollama_options(temperature, num_predict=max_tokens, seed=42),
            keep_alive=KEEP_ALIVE,
        )
    except Exception as e:  # noqa: BLE001 -- connection and missing-model errors alike
        raise _ollama_error(e, name) from e
    return Completion(
        text=response.message.content or "",
        provider="ollama",
        model=name,
        input_tokens=response.prompt_eval_count or 0,
        output_tokens=response.eval_count or 0,
        latency_ms=int((time.monotonic() - start) * 1000),
    )


def _ollama_stream(messages: list[dict], max_tokens: int, temperature: float, result: StreamResult) -> Iterator[str]:
    from app.product.jobs import KEEP_ALIVE

    name = ollama_model()
    try:
        chunks = _ollama_client().chat(
            model=name, messages=messages, options=_ollama_options(temperature, num_predict=max_tokens),
            stream=True, keep_alive=KEEP_ALIVE,
        )
        result.provider, result.model = "ollama", name
        for chunk in chunks:
            text = chunk.message.content or ""
            if text:
                yield text
            if chunk.done:
                result.stats = {
                    "input_tokens": chunk.prompt_eval_count,
                    "output_tokens": chunk.eval_count,
                    "duration_ms": int((chunk.total_duration or 0) / 1e6),
                }
    except ModelError:
        raise
    except Exception as e:  # noqa: BLE001
        raise _ollama_error(e, name) from e


def ollama_prime(messages: list[dict]) -> None:
    """Has the local model read a prompt prefix now, so the next request reusing it
    starts sooner. Groq needs no warming."""
    from app.product.jobs import KEEP_ALIVE

    try:
        _ollama_client().chat(
            model=ollama_model(), messages=messages,
            options=_ollama_options(0.2, num_predict=1), keep_alive=KEEP_ALIVE,
        )
    except Exception:  # noqa: BLE001 -- an optimisation; the real request reports errors
        pass


def ollama_status() -> dict:
    try:
        models = [m.model for m in _ollama_client(timeout=3).list().models]
        name = ollama_model()
        return {
            "reachable": True,
            "models": models,
            "model_available": any(m == name or m.split(":")[0] == name for m in models),
        }
    except Exception as e:  # noqa: BLE001
        return {"reachable": False, "error": str(e)}


# --- Entry points -----------------------------------------------------------------


def complete(messages: list[dict], max_tokens: int, temperature: float = 0.0, json_mode: bool = False) -> Completion:
    if provider() == "ollama":
        return _ollama_complete(messages, max_tokens, temperature, json_mode)
    try:
        return _groq_complete(messages, max_tokens, temperature, json_mode)
    except (ModelError, httpx.HTTPError) as e:
        if not fallback_enabled():
            raise ModelError(str(e)) from e
        log.warning("Groq failed (%s); falling back to the local model", e)
        try:
            return _ollama_complete(messages, max_tokens, temperature, json_mode)
        except ModelError:
            raise ModelError(str(e)) from e


def stream(messages: list[dict], max_tokens: int, result: StreamResult, temperature: float = 0.2) -> Iterator[str]:
    """Yields the answer's text as it's written; `result` says who wrote it. Falls
    back to the local model only if Groq fails before its first word, so an answer
    is never stitched together from two models."""
    if provider() == "ollama":
        yield from _ollama_stream(messages, max_tokens, temperature, result)
        return
    started = False
    try:
        for text in _groq_stream(messages, max_tokens, temperature, result):
            started = True
            yield text
    except (ModelError, httpx.HTTPError) as e:
        if started or not fallback_enabled():
            raise ModelError(str(e)) from e
        log.warning("Groq failed (%s); falling back to the local model", e)
        try:
            yield from _ollama_stream(messages, max_tokens, temperature, result)
        except ModelError:
            raise ModelError(str(e)) from e


def status() -> dict:
    current = provider()
    out: dict = {"provider": current, "model": model(), "label": label(current, model())}
    out["llm"] = groq_status() if current == "groq" else ollama_status()
    return out
