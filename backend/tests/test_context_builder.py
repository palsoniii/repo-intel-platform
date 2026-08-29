"""Integration tests against a real Neo4j (skips gracefully if unreachable, see
conftest.py). Verifies the two implemented ContextVariant arms produce text that
actually reflects what was written to the graph, and that RAW is explicitly
rejected rather than silently returning something wrong."""

import pytest

from app.context.builder import ContextBuilderError, build_context
from app.graph.builder import write_parsed_repository
from app.schemas.llm_result import ContextVariant

pytestmark = pytest.mark.neo4j


def test_raw_variant_raises_not_implemented(neo4j_driver, sample_parsed_repository):
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    with pytest.raises(ContextBuilderError):
        build_context(neo4j_driver, sample_parsed_repository.metadata.name, ContextVariant.RAW)


def test_dependency_graph_variant_reflects_imports_and_external_deps(
    neo4j_driver, sample_parsed_repository
):
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    text = build_context(
        neo4j_driver, sample_parsed_repository.metadata.name, ContextVariant.DEPENDENCY_GRAPH
    )
    assert "app.js imports: services/user_service.js" in text
    assert "express" in text
    # Should NOT include class/function/endpoint detail -- that's knowledge_graph's job
    assert "UserService" not in text
    assert "/users" not in text


def test_knowledge_graph_variant_reflects_full_structure(neo4j_driver, sample_parsed_repository):
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    text = build_context(
        neo4j_driver, sample_parsed_repository.metadata.name, ContextVariant.KNOWLEDGE_GRAPH
    )
    assert "express" in text
    assert "app.js" in text
    assert "UserService" in text
    assert "POST /users -> createUser" in text
    assert "inline handler" in text  # the endpoint with no resolved handler
    assert "User" in text  # database entity name


def test_knowledge_graph_is_a_superset_of_dependency_graph(
    neo4j_driver, sample_parsed_repository
):
    """The ablation treats knowledge_graph as strictly more structured than
    dependency_graph, so every import edge the dependency_graph arm shows must also
    reach the knowledge_graph arm. It previously dropped IMPORTS entirely, leaving the
    two arms partially disjoint -- one had edges and no classes, the other classes and
    no edges -- so the comparison measured a difference in kind, not in structure."""
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    name = sample_parsed_repository.metadata.name
    dep = build_context(neo4j_driver, name, ContextVariant.DEPENDENCY_GRAPH)
    kg = build_context(neo4j_driver, name, ContextVariant.KNOWLEDGE_GRAPH)

    imported = [
        target
        for module in sample_parsed_repository.modules
        for target_id in module.imports
        for target in [
            next(
                (m.path for m in sample_parsed_repository.modules if m.id == target_id),
                None,
            )
        ]
        if target
    ]
    assert imported, "fixture must exercise at least one internal import edge"
    for path in imported:
        assert path in dep, f"{path} missing from dependency_graph"
        assert path in kg, f"{path} missing from knowledge_graph (the superset)"

    # and the richer arm still carries what the leaner one never had
    assert "UserService" in kg
    assert "UserService" not in dep


def test_knowledge_graph_variant_for_unknown_repo_is_handled_gracefully(neo4j_driver):
    text = build_context(neo4j_driver, "no-such-repo-in-graph", ContextVariant.KNOWLEDGE_GRAPH)
    assert "No graph data found" in text
