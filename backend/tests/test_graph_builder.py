"""
Integration tests against a real Neo4j (see conftest.py's neo4j_driver fixture --
skips gracefully if none is reachable). Exercises every node/edge type in SCHEMA.md,
including HAS_METHOD/IMPLEMENTS/CALLS/RELATES_TO, which the current Express parser
never actually populates (no classes in idiomatic Express apps) -- so this is the
only place those code paths get run against a real database.
"""

import pytest

from app.graph.builder import ensure_constraints, write_parsed_repository

pytestmark = pytest.mark.neo4j


def _run(driver, query, **params):
    with driver.session() as session:
        return [dict(r) for r in session.run(query, **params)]


def test_write_parsed_repository_creates_all_node_types(neo4j_driver, sample_parsed_repository):
    ensure_constraints(neo4j_driver)
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    repo_name = sample_parsed_repository.metadata.name

    counts = _run(
        neo4j_driver,
        """
        MATCH (r:Repository {name: $repo_name})
        OPTIONAL MATCH (r)-[:HAS_MODULE]->(m:Module)
        OPTIONAL MATCH (r)-[:HAS_ENDPOINT]->(e:Endpoint)
        OPTIONAL MATCH (r)-[:HAS_DATABASE_ENTITY]->(d:DatabaseEntity)
        OPTIONAL MATCH (r)-[:DEPENDS_ON]->(x:ExternalDependency)
        OPTIONAL MATCH (r)-[:HAS_CONFIG]->(cf:ConfigFile)
        RETURN count(DISTINCT m) AS modules, count(DISTINCT e) AS endpoints,
               count(DISTINCT d) AS db_entities, count(DISTINCT x) AS deps,
               count(DISTINCT cf) AS configs
        """,
        repo_name=repo_name,
    )[0]

    assert counts["modules"] == 2
    assert counts["endpoints"] == 2
    assert counts["db_entities"] == 1
    assert counts["deps"] == 1
    assert counts["configs"] == 1


def test_imports_edge(neo4j_driver, sample_parsed_repository):
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    rows = _run(
        neo4j_driver,
        "MATCH (:Module {repo_name: $r, id: 'mod_0'})-[:IMPORTS]->(m:Module) RETURN m.id AS id",
        r=sample_parsed_repository.metadata.name,
    )
    assert [row["id"] for row in rows] == ["mod_1"]


def test_has_method_uses_function_class_id_not_class_methods_list(
    neo4j_driver, sample_parsed_repository
):
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    rows = _run(
        neo4j_driver,
        "MATCH (c:Class {repo_name: $r, id: 'mod_1_cls_0'})-[:HAS_METHOD]->(f:Function) "
        "RETURN f.id AS id",
        r=sample_parsed_repository.metadata.name,
    )
    assert [row["id"] for row in rows] == ["mod_1_fn_0"]


def test_implements_edge(neo4j_driver, sample_parsed_repository):
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    rows = _run(
        neo4j_driver,
        "MATCH (c:Class {repo_name: $r, id: 'mod_1_cls_0'})-[:IMPLEMENTS]->(i:Class) "
        "RETURN i.name AS name",
        r=sample_parsed_repository.metadata.name,
    )
    assert [row["name"] for row in rows] == ["BaseService"]


def test_calls_edge(neo4j_driver, sample_parsed_repository):
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    rows = _run(
        neo4j_driver,
        "MATCH (:Function {repo_name: $r, id: 'mod_1_fn_0'})-[:CALLS]->(f:Function) "
        "RETURN f.name AS name",
        r=sample_parsed_repository.metadata.name,
    )
    assert [row["name"] for row in rows] == ["validateUser"]


def test_handled_by_edge_only_for_endpoints_with_a_resolved_handler(
    neo4j_driver, sample_parsed_repository
):
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    rows = _run(
        neo4j_driver,
        "MATCH (e:Endpoint {repo_name: $r})-[:HANDLED_BY]->(f:Function) "
        "RETURN e.id AS endpoint_id, f.name AS handler_name",
        r=sample_parsed_repository.metadata.name,
    )
    assert rows == [{"endpoint_id": "mod_1_ep_0", "handler_name": "createUser"}]
    # mod_1_ep_1 (inline handler) should have NO handled_by edge at all


def test_relates_to_edge(neo4j_driver, sample_parsed_repository):
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    rows = _run(
        neo4j_driver,
        "MATCH (:Function {repo_name: $r, id: 'mod_1_fn_0'})-[:RELATES_TO]->(d:DatabaseEntity) "
        "RETURN d.name AS name",
        r=sample_parsed_repository.metadata.name,
    )
    assert [row["name"] for row in rows] == ["User"]


def test_rerunning_is_idempotent(neo4j_driver, sample_parsed_repository):
    """MERGE-based writes: running twice must not duplicate nodes or edges."""
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    write_parsed_repository(neo4j_driver, sample_parsed_repository)

    rows = _run(
        neo4j_driver,
        "MATCH (r:Repository {name: $r})-[:HAS_MODULE]->(m:Module) RETURN count(m) AS n",
        r=sample_parsed_repository.metadata.name,
    )
    assert rows[0]["n"] == 2


def test_two_repos_with_colliding_ids_stay_isolated(neo4j_driver, sample_parsed_repository):
    """Regression test for SCHEMA.md gap #3: two repos both using id 'mod_0' must
    not merge into the same node."""
    from app.schemas.parser_schema import ParsedRepository

    repo_b = ParsedRepository(
        metadata=sample_parsed_repository.metadata.model_copy(
            update={"name": sample_parsed_repository.metadata.name + "-b"}
        ),
        modules=sample_parsed_repository.modules,
    )
    write_parsed_repository(neo4j_driver, sample_parsed_repository)
    write_parsed_repository(neo4j_driver, repo_b)

    # Scoped to just these two repo_names -- a bare `id: 'mod_0'` match would also
    # pick up unrelated repos already in a shared, persistent Neo4j instance (a real
    # id like "mod_0" is common enough that other repos legitimately have one too;
    # this test only cares about isolation between its own two repos).
    rows = _run(
        neo4j_driver,
        "MATCH (m:Module {id: 'mod_0'}) WHERE m.repo_name IN $repo_names "
        "RETURN m.repo_name AS repo_name ORDER BY repo_name",
        repo_names=[sample_parsed_repository.metadata.name, repo_b.metadata.name],
    )
    repo_names = {row["repo_name"] for row in rows}
    assert sample_parsed_repository.metadata.name in repo_names
    assert repo_b.metadata.name in repo_names
    assert len(rows) == 2  # two distinct nodes, not one shared node
