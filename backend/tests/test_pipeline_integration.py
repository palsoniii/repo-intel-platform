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


def test_analyze_real_nestjs_repo():
    result = analyze_repository(
        "https://github.com/nestjs/typescript-starter", max_size_mb=50
    )
    assert result.metadata.detected_framework == "nestjs"
    assert result.metadata.commit_sha
    assert len(result.api_endpoints) >= 1
    assert any(d.name == "@nestjs/core" for d in result.dependencies.external)
    # test/app.e2e-spec.ts and src/app.controller.spec.ts must not be treated as
    # source -- a real bug this exact repo caught during development.
    assert not any(m.path.endswith("spec.ts") for m in result.modules)
