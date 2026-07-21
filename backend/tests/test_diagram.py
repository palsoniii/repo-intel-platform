"""Integration tests against a real Neo4j (skips gracefully if unreachable, see
conftest.py). Verifies the generated Mermaid text actually reflects the graph,
using the same comprehensive sample_parsed_repository fixture as
test_graph_builder.py/test_context_builder.py."""

import pytest

from app.graph.builder import write_parsed_repository
from app.graph.diagram import generate_architecture_diagram

pytestmark = pytest.mark.neo4j


def test_diagram_includes_modules_and_imports(neo4j_driver, sample_parsed_repository):
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    diagram = generate_architecture_diagram(neo4j_driver, sample_parsed_repository.metadata.name)

    assert diagram.startswith("graph TD")
    assert 'mod_0["app.js"]' in diagram
    assert 'mod_1["services/user_service.js"]' in diagram
    assert "mod_0 --> mod_1" in diagram


def test_diagram_includes_endpoints_linked_to_their_module(
    neo4j_driver, sample_parsed_repository
):
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    diagram = generate_architecture_diagram(neo4j_driver, sample_parsed_repository.metadata.name)

    assert 'mod_1_ep_0{{"POST /users"}}' in diagram
    assert "mod_1 -.-> mod_1_ep_0" in diagram
    # the inline-handler endpoint (mod_1_ep_1) has no resolvable module -- must
    # still appear as a node, just without a -.-> edge pointing at it
    assert 'mod_1_ep_1{{"GET /users/:id"}}' in diagram
    assert "-.-> mod_1_ep_1" not in diagram


def test_diagram_for_unknown_repo_is_handled_gracefully(neo4j_driver):
    diagram = generate_architecture_diagram(neo4j_driver, "no-such-repo-in-graph")
    assert "No modules found" in diagram
