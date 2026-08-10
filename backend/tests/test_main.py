"""
Tests for main.py's error handling -- in particular the CORS-headers-on-error fix.
An earlier manual browser test surfaced a real FastAPI/Starlette gotcha: an
unhandled exception's default 500 response is generated OUTSIDE CORSMiddleware, so
it arrives at the browser with no CORS headers and looks exactly like a network
failure, even though the backend responded. These tests exercise both the
specific (PipelineInfrastructureError -> 503) and catch-all (anything else -> 500,
but still with CORS headers) paths.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.pipeline import AnalysisError, PipelineInfrastructureError
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

# raise_server_exceptions=False: these tests specifically inspect error responses
# (status/body/headers), including the catch-all handler's -- the default True
# would re-raise the exception in-process instead of returning its response,
# which is a TestClient convenience for catching unintentional bugs, not what we
# want when the error response itself is the thing under test.
client = TestClient(app, raise_server_exceptions=False)
ORIGIN = "http://localhost:5180"


def test_analysis_error_returns_400_with_cors_headers():
    with patch("app.main.generate_repository_summary", side_effect=AnalysisError("bad url")):
        response = client.post(
            "/summarize", json={"url": "not-a-url"}, headers={"Origin": ORIGIN}
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "bad url"
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_infrastructure_error_returns_503_with_cors_headers():
    with patch(
        "app.main.generate_repository_summary",
        side_effect=PipelineInfrastructureError("Couldn't reach Neo4j -- is it running?"),
    ):
        response = client.post(
            "/summarize",
            json={"url": "https://github.com/test/repo"},
            headers={"Origin": ORIGIN},
        )
    assert response.status_code == 503
    assert "Neo4j" in response.json()["detail"]
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_unexpected_exception_still_gets_cors_headers():
    """The actual bug this catches: without the global exception handler, this
    response has status 500 but NO access-control-allow-origin header, and the
    browser reports it to JS as an opaque network error instead of a readable one."""
    with patch(
        "app.main.generate_repository_summary", side_effect=RuntimeError("totally unexpected")
    ):
        response = client.post(
            "/summarize",
            json={"url": "https://github.com/test/repo"},
            headers={"Origin": ORIGIN},
        )
    assert response.status_code == 500
    assert "totally unexpected" in response.json()["detail"]
    assert response.headers["access-control-allow-origin"] == ORIGIN


def _fake_parsed_repository() -> ParsedRepository:
    return ParsedRepository(
        metadata=RepoMetadata(
            name="fake-repo",
            source_url="https://github.com/test/fake-repo",
            detected_language="javascript",
            detected_framework="express",
        )
    )


def test_diagram_endpoint_returns_mermaid():
    with patch(
        "app.main.generate_repository_diagram",
        return_value=(_fake_parsed_repository(), "graph TD\n  mod_0[\"app.js\"]"),
    ):
        response = client.post("/diagram", json={"url": "https://github.com/test/fake-repo"})
    assert response.status_code == 200
    body = response.json()
    assert body["repo_name"] == "fake-repo"
    assert "graph TD" in body["diagram_mermaid"]


def test_compare_endpoint_maps_scored_results_to_comparison_runs():
    from app.evaluation.hallucination import HallucinationResult
    from app.pipeline import ScoredResult

    fake_result = LLMResult(
        provider=ProviderName.OLLAMA,
        model="qwen2.5-coder:7b",
        task=LLMTask.SUMMARY,
        context_variant=ContextVariant.RAW,
        repo_name="fake-repo",
        output=LLMOutput(raw_text="{}"),
        metrics=LLMMetrics(
            latency_ms=1234, input_tokens=10, output_tokens=5, estimated_cost_usd=0.0
        ),
        status=RunStatus.SUCCESS,
    )
    fake_hallucination = HallucinationResult(
        repo_name="fake-repo",
        context_variant=ContextVariant.RAW,
        judge_model="llama3.1:8b",
        total_claims=4,
        unsupported_claims=["uses MongoDB"],
        hallucination_score=0.25,
        judged=True,
        judge_raw_output="{}",
    )
    scored = [ScoredResult(result=fake_result, hallucination=fake_hallucination)]
    with patch(
        "app.main.run_scored_ablation",
        return_value=(_fake_parsed_repository(), scored),
    ):
        response = client.post("/compare", json={"url": "https://github.com/test/fake-repo"})
    assert response.status_code == 200
    runs = response.json()["runs"]
    assert len(runs) == 1
    assert runs[0]["model"] == "qwen2.5-coder:7b"
    assert runs[0]["context_variant"] == "raw"
    assert runs[0]["latency_ms"] == 1234
    assert runs[0]["hallucination_score"] == 0.25
    assert runs[0]["hallucination_judged"] is True
    assert runs[0]["unsupported_claims"] == 1
    assert runs[0]["judge_model"] == "llama3.1:8b"
    assert runs[0]["self_judged"] is False
