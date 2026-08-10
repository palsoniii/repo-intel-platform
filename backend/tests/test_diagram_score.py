"""
Unit tests for the diagram graph-diff scorer. Pure logic -- no LLM, no Neo4j -- so
fully offline. Covers structure extraction from a ParsedRepository, precision/
recall/F1 arithmetic, the missing/extra diffs, the both-empty vacuous-perfect case,
and JSON annotation loading.
"""

import json

from app.evaluation.diagram_score import (
    GraphStructure,
    extract_actual_structure,
    load_expected,
    score_diagram,
)
from app.schemas.parser_schema import (
    ApiEndpoint,
    Dependencies,
    HttpMethod,
    InternalDependencyEdge,
    ModuleNode,
    ParsedRepository,
    RepoMetadata,
)


def _parsed() -> ParsedRepository:
    return ParsedRepository(
        metadata=RepoMetadata(
            name="repo-a", source_url="u", detected_language="javascript", detected_framework="express"
        ),
        modules=[
            ModuleNode(id="mod_0", path="app.js"),
            ModuleNode(id="mod_1", path="routes/users.js"),
        ],
        api_endpoints=[ApiEndpoint(id="mod_1_ep_0", method=HttpMethod.GET, path="/users")],
        dependencies=Dependencies(
            internal=[InternalDependencyEdge(from_module_id="mod_0", to_module_id="mod_1")]
        ),
    )


def test_extract_actual_maps_module_ids_to_paths():
    actual = extract_actual_structure(_parsed())
    assert set(actual.modules) == {"app.js", "routes/users.js"}
    assert actual.imports == [("app.js", "routes/users.js")]
    assert actual.endpoints == ["GET /users"]


def test_perfect_match_scores_one():
    actual = extract_actual_structure(_parsed())
    expected = GraphStructure(
        modules=["app.js", "routes/users.js"],
        imports=[("app.js", "routes/users.js")],
        endpoints=["GET /users"],
    )
    score = score_diagram(actual, expected, "repo-a")
    assert score.modules.f1 == 1.0
    assert score.imports.f1 == 1.0
    assert score.endpoints.f1 == 1.0
    assert score.overall_f1 == 1.0


def test_missing_module_lowers_recall():
    actual = GraphStructure(modules=["app.js"])
    expected = GraphStructure(modules=["app.js", "routes/users.js"])
    score = score_diagram(actual, expected, "repo-a")
    assert score.modules.precision == 1.0  # everything produced was correct
    assert score.modules.recall == 0.5  # only found 1 of 2
    assert score.modules.missing == ["routes/users.js"]
    assert score.modules.extra == []


def test_extra_module_lowers_precision():
    actual = GraphStructure(modules=["app.js", "routes/users.js", "phantom.js"])
    expected = GraphStructure(modules=["app.js", "routes/users.js"])
    score = score_diagram(actual, expected, "repo-a")
    assert score.modules.recall == 1.0  # found everything expected
    assert round(score.modules.precision, 4) == 0.6667  # 2 of 3 produced were real
    assert score.modules.extra == ["phantom.js"]


def test_import_direction_matters():
    actual = GraphStructure(imports=[("b.js", "a.js")])
    expected = GraphStructure(imports=[("a.js", "b.js")])
    score = score_diagram(actual, expected, "repo-a")
    assert score.imports.f1 == 0.0  # reversed edge is not a match


def test_both_empty_category_is_vacuously_perfect():
    score = score_diagram(GraphStructure(), GraphStructure(), "repo-a")
    assert score.modules.f1 == 1.0
    assert score.imports.f1 == 1.0
    assert score.endpoints.f1 == 1.0
    assert score.overall_f1 == 1.0


def test_produced_when_none_expected_is_penalized():
    actual = GraphStructure(endpoints=["GET /surprise"])
    expected = GraphStructure(endpoints=[])
    score = score_diagram(actual, expected, "repo-a")
    assert score.endpoints.f1 == 0.0
    assert score.endpoints.extra == ["GET /surprise"]


def test_load_expected_from_json(tmp_path):
    path = tmp_path / "repo-a.json"
    path.write_text(
        json.dumps(
            {
                "modules": ["app.js", "routes/users.js"],
                "imports": [["app.js", "routes/users.js"]],
                "endpoints": ["GET /users"],
            }
        )
    )
    expected = load_expected(path)
    assert expected.modules == ["app.js", "routes/users.js"]
    assert expected.imports == [("app.js", "routes/users.js")]  # JSON arrays -> tuples


def test_end_to_end_extract_then_score_against_annotation(tmp_path):
    path = tmp_path / "repo-a.json"
    path.write_text(
        json.dumps(
            {
                "modules": ["app.js", "routes/users.js"],
                "imports": [["app.js", "routes/users.js"]],
                "endpoints": ["GET /users", "POST /users"],
            }
        )
    )
    actual = extract_actual_structure(_parsed())
    score = score_diagram(actual, load_expected(path), "repo-a")
    # modules + imports perfect; endpoints: found GET /users, missed POST /users
    assert score.modules.f1 == 1.0
    assert score.imports.f1 == 1.0
    assert score.endpoints.recall == 0.5
    assert score.endpoints.missing == ["POST /users"]
