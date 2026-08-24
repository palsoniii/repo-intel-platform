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
    """Router-relative paths are composed with the prefix the router is mounted at.
    The fixture does `app.use('/api/users', usersRouter)`, so `router.get('/')` in
    routes/users.js is really GET /api/users -- the path a client actually calls.
    Routes registered straight on `app` (GET /health) are already absolute."""
    assert len(parsed.api_endpoints) == 4
    routes = {(ep.method, ep.path) for ep in parsed.api_endpoints}
    assert (HttpMethod.GET, "/health") in routes
    assert (HttpMethod.GET, "/api/users") in routes
    assert (HttpMethod.POST, "/api/users") in routes
    assert (HttpMethod.DELETE, "/api/users/:id") in routes


def test_resolves_named_handler_to_function_id(parsed):
    get_route = next(
        ep
        for ep in parsed.api_endpoints
        if ep.method == HttpMethod.GET and ep.path == "/api/users"
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


def test_test_files_are_excluded_but_recorded(parsed):
    """Test trees aren't application architecture, so they must not become modules --
    but the exclusion is recorded rather than silent, so it can be audited."""
    paths = {m.path for m in parsed.modules}
    assert "tests/users.test.js" not in paths
    assert any("tests/users.test.js" in s for s in parsed.metadata.files_skipped)


def test_internal_imports_resolve_to_module_ids(parsed):
    """Regression guard for a silent path-normalisation bug: candidate paths were
    .resolve()d while the lookup table was keyed on unresolved paths, so on macOS
    (where a temp clone under /var/folders resolves to /private/var/folders) *every*
    internal import edge was dropped. The parse looked clean -- just no edges."""
    app_module = next(m for m in parsed.modules if m.path == "app.js")
    users_module = next(m for m in parsed.modules if m.path == "routes/users.js")
    assert users_module.id in app_module.imports
    edges = {(e.from_module_id, e.to_module_id) for e in parsed.dependencies.internal}
    assert (app_module.id, users_module.id) in edges
