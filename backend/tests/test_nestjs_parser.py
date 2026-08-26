"""
Smoke tests for the NestJS parser, run against a small hand-built fixture repo
(tests/fixtures/nestjs-app) so they're fast and don't depend on network access.
Mirrors test_express_parser.py's structure/coverage for the equivalent framework.
"""

from pathlib import Path

import pytest

from app.parsers.nestjs_parser import NestJSParser
from app.schemas.parser_schema import HttpMethod

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nestjs-app"


@pytest.fixture
def parsed():
    parser = NestJSParser()
    assert parser.detect(FIXTURE_PATH) is True
    return parser.parse(FIXTURE_PATH)


def test_detects_nestjs(parsed):
    assert parsed.metadata.detected_framework == "nestjs"
    assert parsed.metadata.detected_language == "typescript"


def test_both_spec_file_conventions_are_excluded(parsed):
    """Path.suffix only ever returns '.ts' (never '.spec.ts'), and NestJS scaffolds
    two different test-file conventions (*.spec.ts for unit tests, *.e2e-spec.ts for
    e2e) -- found missing against the real nestjs/typescript-starter repo."""
    paths = {m.path for m in parsed.modules}
    assert "src/users/users.controller.spec.ts" not in paths
    assert "test/app.e2e-spec.ts" not in paths
    assert set(parsed.metadata.files_skipped) == {
        "src/users/users.controller.spec.ts (test file, skipped)",
        "test/app.e2e-spec.ts (test file, skipped)",
    }


def test_finds_all_modules(parsed):
    paths = {m.path for m in parsed.modules}
    assert paths == {
        "src/main.ts",
        "src/app.module.ts",
        "src/users/users.module.ts",
        "src/users/users.service.ts",
        "src/users/users.controller.ts",
        "src/files/files.controller.ts",
    }


def test_resolves_internal_imports(parsed):
    module_by_path = {m.path: m for m in parsed.modules}
    controller = module_by_path["src/users/users.controller.ts"]
    service = module_by_path["src/users/users.service.ts"]
    assert service.id in controller.imports

    app_module = module_by_path["src/app.module.ts"]
    users_module = module_by_path["src/users/users.module.ts"]
    assert users_module.id in app_module.imports


def test_finds_classes_with_correct_module_ownership(parsed):
    names_by_module_path = {}
    module_path_by_id = {m.id: m.path for m in parsed.modules}
    for cls in parsed.classes:
        names_by_module_path.setdefault(module_path_by_id[cls.module_id], []).append(cls.name)

    assert names_by_module_path["src/users/users.controller.ts"] == ["UsersController"]
    assert names_by_module_path["src/users/users.service.ts"] == ["UsersService"]
    assert names_by_module_path["src/app.module.ts"] == ["AppModule"]
    assert names_by_module_path["src/users/users.module.ts"] == ["UsersModule"]


def test_class_implements_interface(parsed):
    service = next(c for c in parsed.classes if c.name == "UsersService")
    assert service.interfaces_implemented == ["UserRepository"]


def test_methods_are_owned_by_their_class_not_free_functions(parsed):
    controller = next(c for c in parsed.classes if c.name == "UsersController")
    controller_methods = [f for f in parsed.functions if f.class_id == controller.id]
    method_names = {f.name for f in controller_methods}
    assert method_names == {"findAll", "findOne", "create"}
    # constructor is deliberately excluded -- it's not a meaningful graph node
    assert "constructor" not in method_names


def test_finds_all_routes_with_correct_controller_prefix(parsed):
    routes = {(e.method, e.path) for e in parsed.api_endpoints}
    assert routes == {
        (HttpMethod.GET, "/users"),
        (HttpMethod.GET, "/users/:id"),
        (HttpMethod.POST, "/users"),
        (HttpMethod.POST, "/files/upload"),
        (HttpMethod.GET, "/files/:path"),
    }


def test_object_form_controller_prefix_is_resolved(parsed):
    """@Controller({ path: 'files', version: '1' }) must yield the same prefix as
    @Controller('files'). Only the string form was handled previously, so every
    controller in an options-object codebase silently lost its prefix and its routes
    collapsed to bare method paths (/upload instead of /files/upload)."""
    paths = {e.path for e in parsed.api_endpoints}
    assert "/files/upload" in paths
    assert "/upload" not in paths


def test_routes_resolve_to_handler_function_id(parsed):
    """Unlike Express, NestJS route handlers are always named class methods --
    there's no inline-handler case, so every endpoint should resolve."""
    function_by_id = {f.id: f for f in parsed.functions}
    for endpoint in parsed.api_endpoints:
        assert endpoint.handler_function_id is not None
        assert endpoint.handler_function_id in function_by_id


def test_non_route_methods_are_not_api_handlers(parsed):
    service_methods = [f for f in parsed.functions if f.name in ("find", "create") and f.class_id]
    service_only = [f for f in service_methods if not f.is_api_handler]
    # UsersService.find/create should NOT be marked as API handlers (no route decorator)
    assert any(f.name == "find" for f in service_only)
    assert any(f.name == "create" for f in service_only)


def test_external_dependencies_from_package_json(parsed):
    names = {d.name for d in parsed.dependencies.external}
    assert "@nestjs/common" in names
    assert "@nestjs/core" in names
    assert "typescript" in names


def test_config_files_detected(parsed):
    paths = {c.path for c in parsed.config_files}
    assert "package.json" in paths


TSCONFIG_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nestjs-app-tsconfig"


@pytest.fixture
def parsed_tsconfig():
    parser = NestJSParser()
    assert parser.detect(TSCONFIG_FIXTURE_PATH) is True
    return parser.parse(TSCONFIG_FIXTURE_PATH)


def test_tsconfig_path_alias_is_resolved(parsed_tsconfig):
    """notifications.service.ts imports UsersService via the '@app/*' tsconfig
    alias ('@app/users/users.service') rather than a relative path. Before this
    fix, any non-relative import was assumed to be an external package and
    never resolved to an internal module id -- this edge would have been
    silently dropped even though the target file is right there in the repo."""
    module_by_path = {m.path: m for m in parsed_tsconfig.modules}
    notifications = module_by_path["src/notifications/notifications.service.ts"]
    users_service = module_by_path["src/users/users.service.ts"]
    assert users_service.id in notifications.imports
    edges = {
        (e.from_module_id, e.to_module_id) for e in parsed_tsconfig.dependencies.internal
    }
    assert (notifications.id, users_service.id) in edges


def test_tsconfig_jsonc_comments_and_trailing_commas_do_not_break_parsing(parsed_tsconfig):
    """The fixture's tsconfig.json has a comment and a trailing comma after the
    'paths' object -- both of which the Nest CLI's own scaffolded tsconfig.json
    routinely includes, and which plain json.loads rejects on its own. This just
    re-asserts the alias resolved at all, i.e. that _read_jsonc's fallback
    stripping actually ran rather than silently returning no aliases."""
    module_by_path = {m.path: m for m in parsed_tsconfig.modules}
    notifications = module_by_path["src/notifications/notifications.service.ts"]
    assert len(notifications.imports) == 1
