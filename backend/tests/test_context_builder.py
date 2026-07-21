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


def test_knowledge_graph_variant_for_unknown_repo_is_handled_gracefully(neo4j_driver):
    text = build_context(neo4j_driver, "no-such-repo-in-graph", ContextVariant.KNOWLEDGE_GRAPH)
    assert "No graph data found" in text
