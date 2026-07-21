"""
Smoke tests for the Express.js parser, run against a small hand-built fixture repo
(tests/fixtures/express-app) so they're fast and don't depend on network access.
Network-dependent end-to-end tests live in test_pipeline_integration.py.
"""

from pathlib import Path

import pytest

from app.parsers.express_parser import ExpressParser
from app.schemas.parser_schema import HttpMethod

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "express-app"


@pytest.fixture
def parsed():
    parser = ExpressParser()
    assert parser.detect(FIXTURE_PATH) is True
    return parser.parse(FIXTURE_PATH)


def test_detects_express(parsed):
    assert parsed.metadata.detected_framework == "express"


def test_finds_all_modules(parsed):
    paths = {m.path for m in parsed.modules}
    assert paths == {"app.js", "routes/users.js"}


def test_resolves_internal_import(parsed):
    app_module = next(m for m in parsed.modules if m.path == "app.js")
    users_module = next(m for m in parsed.modules if m.path == "routes/users.js")
    assert users_module.id in app_module.imports


def test_finds_named_functions(parsed):
    names = {f.name for f in parsed.functions}
    assert names == {"listUsers", "createUser"}


def test_finds_all_routes(parsed):
    assert len(parsed.api_endpoints) == 4
    routes = {(ep.method, ep.path) for ep in parsed.api_endpoints}
    assert (HttpMethod.GET, "/health") in routes
    assert (HttpMethod.GET, "/") in routes
    assert (HttpMethod.POST, "/") in routes
    assert (HttpMethod.DELETE, "/:id") in routes


def test_resolves_named_handler_to_function_id(parsed):
    get_route = next(
        ep for ep in parsed.api_endpoints if ep.method == HttpMethod.GET and ep.path == "/"
    )
    list_users_fn = next(f for f in parsed.functions if f.name == "listUsers")
    assert get_route.handler_function_id == list_users_fn.id


def test_inline_handler_has_no_function_id(parsed):
    health_route = next(ep for ep in parsed.api_endpoints if ep.path == "/health")
    assert health_route.handler_function_id is None


def test_external_dependencies_from_package_json(parsed):
    dep_names = {d.name for d in parsed.dependencies.external}
    assert "express" in dep_names
    assert "cors" in dep_names
    assert "jest" in dep_names


def test_config_files_detected(parsed):
    config_paths = {c.path for c in parsed.config_files}
    assert "package.json" in config_paths
