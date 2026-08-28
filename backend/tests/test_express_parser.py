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
    Routes registered straight on `app` (GET /health) are already absolute. The
    fixture also has `app.get('port')` (via `app.listen(app.get('port'))`) -- the
    single-argument app-settings getter, not a route -- which must NOT appear."""
    assert len(parsed.api_endpoints) == 4
    routes = {(ep.method, ep.path) for ep in parsed.api_endpoints}
    assert (HttpMethod.GET, "/health") in routes
    assert (HttpMethod.GET, "/api/users") in routes
    assert (HttpMethod.POST, "/api/users") in routes
    assert (HttpMethod.DELETE, "/api/users/:id") in routes


def test_app_get_settings_getter_is_not_a_route(parsed):
    """app.get('port') -- Express's single-argument app-settings getter overload --
    must not be misread as a handler-less GET route."""
    assert all(ep.path != "port" for ep in parsed.api_endpoints)


def test_static_middleware_mount_does_not_corrupt_own_prefix(parsed):
    """routes/users.js does `router.use('/docs', express.static('docs'))` -- a plain
    middleware mount, not a same-file router. It must not be attributed as this
    module's own prefix, which would corrupt the real /api/users prefix (mounted by
    app.js) into something like /docs/api/users."""
    routes = {(ep.method, ep.path) for ep in parsed.api_endpoints}
    assert (HttpMethod.GET, "/api/users") in routes
    assert not any("/docs" in path for _, path in routes)


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


ESM_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "express-app-esm"


@pytest.fixture
def parsed_esm():
    parser = ExpressParser()
    assert parser.detect(ESM_FIXTURE_PATH) is True
    return parser.parse(ESM_FIXTURE_PATH)


def test_es_module_imports_are_resolved(parsed_esm):
    """routes/posts.js is written in `import ... from` syntax rather than
    require() -- before this fix, only require() calls were ever extracted, so a
    file like this had an entirely empty imports list regardless of what it
    actually imported."""
    module_by_path = {m.path: m for m in parsed_esm.modules}
    posts = module_by_path["routes/posts.js"]
    post_service = module_by_path["services/postService.js"]
    assert post_service.id in posts.imports
    edges = {(e.from_module_id, e.to_module_id) for e in parsed_esm.dependencies.internal}
    assert (posts.id, post_service.id) in edges


def test_es_module_file_still_gets_its_mount_prefix(parsed_esm):
    """The ESM-style file's own routes must still resolve through the normal
    require()-based mount chain (app.js requires and mounts it via CommonJS) --
    ESM import support is additive, not a replacement for require() handling."""
    routes = {(ep.method, ep.path) for ep in parsed_esm.api_endpoints}
    assert (HttpMethod.GET, "/api/posts") in routes


MOUNT_CHAIN_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "express-app-mount-chain"


@pytest.fixture
def parsed_mount_chain():
    parser = ExpressParser()
    assert parser.detect(MOUNT_CHAIN_FIXTURE_PATH) is True
    return parser.parse(MOUNT_CHAIN_FIXTURE_PATH)


def test_multi_hop_mount_prefix_composes_fully(parsed_mount_chain):
    """app.js mounts routes/api.js at /api; routes/api.js itself mounts
    routes/v1/health.js at /v1 -- a two-hop chain. Before this fix, the flat
    module_id -> prefix map had no way to know routes/api.js was itself mounted
    anywhere, so this endpoint resolved to just /v1/ping instead of the full
    /api/v1/ping a client would actually call."""
    routes = {(ep.method, ep.path) for ep in parsed_mount_chain.api_endpoints}
    assert (HttpMethod.GET, "/api/v1/ping") in routes
    assert (HttpMethod.GET, "/v1/ping") not in routes
