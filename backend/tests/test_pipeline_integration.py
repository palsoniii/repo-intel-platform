"""
Network-dependent integration test: real clone of a small, known-stable public repo.
Marked so it can be skipped in offline/CI-without-network environments via
`pytest -m "not integration"`.
"""

import pytest

from app.pipeline import analyze_repository

pytestmark = pytest.mark.integration


def test_analyze_real_express_repo():
    result = analyze_repository(
        "https://github.com/heroku/node-js-getting-started", max_size_mb=50
    )
    assert result.metadata.detected_framework == "express"
    assert result.metadata.commit_sha
    assert len(result.api_endpoints) >= 1
    assert any(d.name == "express" for d in result.dependencies.external)
