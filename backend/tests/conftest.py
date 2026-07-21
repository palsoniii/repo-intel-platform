"""
Shared fixtures. `neo4j_driver` connects to a real Neo4j test instance and is used
by tests marked `@pytest.mark.neo4j` -- those tests SKIP (not fail) if no instance
is reachable, so `pytest tests/ -v -m "not integration"` still passes offline; run
with a real Neo4j up (see README setup) to actually exercise the graph/context
builders end-to-end.
"""

from __future__ import annotations

import os

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from app.schemas.parser_schema import (
    ApiEndpoint,
    ClassNode,
    ConfigFile,
    ConfigFileType,
    DatabaseEntity,
    Dependencies,
    DependencyType,
    ExternalDependency,
    FunctionNode,
    HttpMethod,
    InternalDependencyEdge,
    ModuleNode,
    ParsedRepository,
    RepoMetadata,
)

NEO4J_TEST_URI = os.environ.get("NEO4J_TEST_URI", "bolt://localhost:7687")
NEO4J_TEST_USER = os.environ.get("NEO4J_TEST_USER", "neo4j")
NEO4J_TEST_PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD", "testpassword123")

TEST_REPO_PREFIX = "test-graph-builder-"


@pytest.fixture
def neo4j_driver():
    driver = GraphDatabase.driver(NEO4J_TEST_URI, auth=(NEO4J_TEST_USER, NEO4J_TEST_PASSWORD))
    try:
        driver.verify_connectivity()
    except (ServiceUnavailable, Neo4jError, OSError) as e:
        driver.close()
        pytest.skip(f"No reachable Neo4j test instance at {NEO4J_TEST_URI}: {e}")

    yield driver

    with driver.session() as session:
        session.run(
            "MATCH (n) WHERE n.repo_name STARTS WITH $prefix DETACH DELETE n",
            prefix=TEST_REPO_PREFIX,
        )
    driver.close()


@pytest.fixture
def sample_parsed_repository() -> ParsedRepository:
    """Hand-built (not parser-derived) so every node/edge type in SCHEMA.md is
    exercised, including classes/calls/interfaces that the current Express parser
    never populates (it has no classes in idiomatic Express apps -- see gap
    discussion in SCHEMA.md and README's Phase 1 known gaps)."""
    repo_name = f"{TEST_REPO_PREFIX}sample"
    return ParsedRepository(
        metadata=RepoMetadata(
            name=repo_name,
            source_url="https://github.com/test/sample",
            detected_language="javascript",
            detected_framework="express",
            framework_version="^4.18.0",
        ),
        modules=[
            ModuleNode(id="mod_0", path="app.js", imports=["mod_1"]),
            ModuleNode(id="mod_1", path="services/user_service.js"),
        ],
        classes=[
            ClassNode(
                id="mod_1_cls_0",
                name="UserService",
                module_id="mod_1",
                interfaces_implemented=["mod_1_cls_1"],
            ),
            ClassNode(
                id="mod_1_cls_1",
                name="BaseService",
                module_id="mod_1",
                is_interface=True,
            ),
        ],
        functions=[
            FunctionNode(
                id="mod_1_fn_0",
                name="createUser",
                module_id="mod_1",
                class_id="mod_1_cls_0",
                calls=["mod_1_fn_1"],
                is_api_handler=True,
            ),
            FunctionNode(id="mod_1_fn_1", name="validateUser", module_id="mod_1"),
        ],
        api_endpoints=[
            ApiEndpoint(
                id="mod_1_ep_0",
                method=HttpMethod.POST,
                path="/users",
                handler_function_id="mod_1_fn_0",
                framework_annotation="router.post",
            ),
            ApiEndpoint(
                id="mod_1_ep_1",
                method=HttpMethod.GET,
                path="/users/:id",
                handler_function_id=None,  # inline handler, no stable id
                framework_annotation="router.get",
            ),
        ],
        database_entities=[
            DatabaseEntity(
                id="mod_1_db_0",
                name="User",
                source_path="services/user_service.js",
                related_function_ids=["mod_1_fn_0"],
            ),
        ],
        dependencies=Dependencies(
            internal=[InternalDependencyEdge(from_module_id="mod_0", to_module_id="mod_1")],
            external=[
                ExternalDependency(name="express", version="^4.18.0", dep_type=DependencyType.RUNTIME),
            ],
        ),
        config_files=[ConfigFile(path="package.json", config_type=ConfigFileType.BUILD)],
    )
