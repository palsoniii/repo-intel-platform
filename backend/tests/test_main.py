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
