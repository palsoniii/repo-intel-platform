"""Product insights and views against the parser's own fixtures -- no network, no infra."""

from pathlib import Path

from app.parsers.registry import parse_repository
from app.product.insights import _express_route_calls, classify_layer, compute_insights
from app.product import views
from app.product.ask import build_prompt, retrieve

FIXTURES = Path(__file__).parent / "fixtures"


def _analyse(name: str):
    root = FIXTURES / name
    parsed = parse_repository(root)
    files = {m.path: (root / m.path).read_text() for m in parsed.modules}
    return parsed, files, compute_insights(parsed, files)


def test_layer_classification():
    assert classify_layer("src/users/users.controller.ts") == "route"
    assert classify_layer("src/users/users.service.ts") == "service"
    assert classify_layer("src/users/users.module.ts") == "module"
    assert classify_layer("src/users/entities/user.entity.ts") == "data"
    assert classify_layer("src/routes/index.js") == "route"
    assert classify_layer("src/index.js") == "entry"
    assert classify_layer("src/models/index.js") == "data"
    assert classify_layer("test/app.e2e-spec.ts") == "test"


def test_express_chained_routes_carry_path_middleware_and_handler():
    src = """
router
  .route('/:userId')
  .get(auth('getUsers'), validate(v.getUser), userController.getUser)
  .delete(auth('manageUsers'), userController.deleteUser);
router.post('/login', authCtrl.login);
"""
    calls = _express_route_calls(src)
    assert [(c["method"], c["path"], c["handler_expr"]) for c in calls] == [
        ("get", "/:userId", "userController.getUser"),
        ("delete", "/:userId", "userController.deleteUser"),
        ("post", "/login", "authCtrl.login"),
    ]
    assert calls[0]["middleware"] == ["auth('getUsers')", "validate(v.getUser)"]


def test_nestjs_fixture_views_are_consistent():
    parsed, files, insights = _analyse("nestjs-app")
    graph = views.knowledge_graph(parsed, insights)
    ids = {n["data"]["id"] for n in graph["nodes"]}
    # Every edge must connect two nodes that exist, or Cytoscape refuses the graph.
    assert all(e["data"]["source"] in ids and e["data"]["target"] in ids for e in graph["edges"])

    endpoints = views.endpoints_view(parsed, insights)
    assert endpoints and all(e["file"] and e["line"] for e in endpoints)
    assert all(e["trace"][0]["kind"] == "endpoint" for e in endpoints)

    arch = views.architecture_diagram(parsed, insights)
    assert arch["mermaid"].startswith("graph LR")


def test_express_fixture_views_are_consistent():
    parsed, files, insights = _analyse("express-app")
    graph = views.knowledge_graph(parsed, insights)
    ids = {n["data"]["id"] for n in graph["nodes"]}
    assert all(e["data"]["source"] in ids and e["data"]["target"] in ids for e in graph["edges"])
    endpoints = views.endpoints_view(parsed, insights)
    assert endpoints and all(e["line"] for e in endpoints)


def test_ask_retrieval_prefers_the_named_file():
    parsed, files, insights = _analyse("express-app")
    target = next(m.path for m in parsed.modules if "users" in m.path and "test" not in m.path)
    sources = retrieve(parsed, insights, files, "How do the users routes work?")
    assert sources and sources[0]["path"] == target
    prompt, _ = build_prompt(parsed, insights, files, "How do the users routes work?")
    assert target in prompt and "Question: How do the users routes work?" in prompt
