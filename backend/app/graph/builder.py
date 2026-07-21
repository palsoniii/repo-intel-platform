"""
Graph Builder: ParsedRepository -> Neo4j, per the schema designed in SCHEMA.md /
schema.cypher. Everything is scoped by repo_name and keyed on (repo_name, id) so
multiple repos can share one Neo4j instance without the id collisions described in
SCHEMA.md gap #3 (the parser generates ids like "mod_0" fresh per parse).

Writing one repo's graph is a single transaction -- either the whole repo lands or
none of it does, so a partial parse never leaves a half-written graph behind.
"""

from __future__ import annotations

from neo4j import Driver, ManagedTransaction

from app.schemas.parser_schema import (
    ApiEndpoint,
    ClassNode,
    ConfigFile,
    DatabaseEntity,
    ExternalDependency,
    FunctionNode,
    InternalDependencyEdge,
    ModuleNode,
    ParsedRepository,
)

# Keep in sync with the "Constraints" section of schema.cypher.
CONSTRAINTS = [
    "CREATE CONSTRAINT repository_name IF NOT EXISTS FOR (r:Repository) REQUIRE r.name IS UNIQUE",
    "CREATE CONSTRAINT module_repo_id IF NOT EXISTS FOR (m:Module) REQUIRE (m.repo_name, m.id) IS UNIQUE",
    "CREATE CONSTRAINT class_repo_id IF NOT EXISTS FOR (c:Class) REQUIRE (c.repo_name, c.id) IS UNIQUE",
    "CREATE CONSTRAINT function_repo_id IF NOT EXISTS FOR (f:Function) REQUIRE (f.repo_name, f.id) IS UNIQUE",
    "CREATE CONSTRAINT endpoint_repo_id IF NOT EXISTS FOR (e:Endpoint) REQUIRE (e.repo_name, e.id) IS UNIQUE",
    "CREATE CONSTRAINT dbentity_repo_id IF NOT EXISTS FOR (d:DatabaseEntity) REQUIRE (d.repo_name, d.id) IS UNIQUE",
    "CREATE CONSTRAINT extdep_repo_name IF NOT EXISTS FOR (x:ExternalDependency) REQUIRE (x.repo_name, x.name) IS UNIQUE",
    "CREATE CONSTRAINT config_repo_path IF NOT EXISTS FOR (cf:ConfigFile) REQUIRE (cf.repo_name, cf.path) IS UNIQUE",
]


def ensure_constraints(driver: Driver) -> None:
    with driver.session() as session:
        for statement in CONSTRAINTS:
            session.run(statement)


def write_parsed_repository(driver: Driver, parsed: ParsedRepository) -> None:
    repo_name = parsed.metadata.name
    with driver.session() as session:
        session.execute_write(_write_all, repo_name, parsed)


def _write_all(tx: ManagedTransaction, repo_name: str, parsed: ParsedRepository) -> None:
    _write_repository(tx, repo_name, parsed)
    _write_modules(tx, repo_name, parsed.modules)
    _write_internal_dependencies(tx, repo_name, parsed.dependencies.internal)
    _write_classes(tx, repo_name, parsed.classes)
    _write_implements(tx, repo_name, parsed.classes)
    _write_functions(tx, repo_name, parsed.functions)  # also writes HAS_METHOD
    _write_calls(tx, repo_name, parsed.functions)
    _write_endpoints(tx, repo_name, parsed.api_endpoints)  # also writes HANDLED_BY
    _write_database_entities(tx, repo_name, parsed.database_entities)
    _write_relates_to(tx, repo_name, parsed.database_entities)
    _write_external_dependencies(tx, repo_name, parsed.dependencies.external)
    _write_config_files(tx, repo_name, parsed.config_files)


def _write_repository(tx: ManagedTransaction, repo_name: str, parsed: ParsedRepository) -> None:
    meta = parsed.metadata
    tx.run(
        """
        MERGE (r:Repository {name: $repo_name})
        SET r.source_url = $source_url,
            r.commit_sha = $commit_sha,
            r.detected_language = $detected_language,
            r.detected_framework = $detected_framework,
            r.framework_version = $framework_version,
            r.parsed_at = $parsed_at
        """,
        repo_name=repo_name,
        source_url=meta.source_url,
        commit_sha=meta.commit_sha,
        detected_language=meta.detected_language,
        detected_framework=meta.detected_framework,
        framework_version=meta.framework_version,
        parsed_at=meta.parsed_at.isoformat(),
    )


def _write_modules(tx: ManagedTransaction, repo_name: str, modules: list[ModuleNode]) -> None:
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (r:Repository {name: $repo_name})
        MERGE (m:Module {repo_name: $repo_name, id: row.id})
        SET m.path = row.path, m.kind = row.kind
        MERGE (r)-[:HAS_MODULE]->(m)
        """,
        repo_name=repo_name,
        rows=[{"id": m.id, "path": m.path, "kind": m.kind} for m in modules],
    )


def _write_internal_dependencies(
    tx: ManagedTransaction, repo_name: str, edges: list[InternalDependencyEdge]
) -> None:
    if not edges:
        return
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (from:Module {repo_name: $repo_name, id: row.from_id})
        MATCH (to:Module {repo_name: $repo_name, id: row.to_id})
        MERGE (from)-[:IMPORTS]->(to)
        """,
        repo_name=repo_name,
        rows=[{"from_id": e.from_module_id, "to_id": e.to_module_id} for e in edges],
    )


def _write_classes(tx: ManagedTransaction, repo_name: str, classes: list[ClassNode]) -> None:
    if not classes:
        return
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (m:Module {repo_name: $repo_name, id: row.module_id})
        MERGE (c:Class {repo_name: $repo_name, id: row.id})
        SET c.name = row.name, c.is_interface = row.is_interface
        MERGE (m)-[:DEFINES]->(c)
        """,
        repo_name=repo_name,
        rows=[
            {"id": c.id, "name": c.name, "module_id": c.module_id, "is_interface": c.is_interface}
            for c in classes
        ],
    )


def _write_implements(tx: ManagedTransaction, repo_name: str, classes: list[ClassNode]) -> None:
    rows = [
        {"class_id": c.id, "iface_id": iface_id}
        for c in classes
        for iface_id in c.interfaces_implemented
    ]
    if not rows:
        return
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (c:Class {repo_name: $repo_name, id: row.class_id})
        MATCH (i:Class {repo_name: $repo_name, id: row.iface_id})
        MERGE (c)-[:IMPLEMENTS]->(i)
        """,
        repo_name=repo_name,
        rows=rows,
    )


def _write_functions(tx: ManagedTransaction, repo_name: str, functions: list[FunctionNode]) -> None:
    if functions:
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (m:Module {repo_name: $repo_name, id: row.module_id})
            MERGE (f:Function {repo_name: $repo_name, id: row.id})
            SET f.name = row.name, f.is_api_handler = row.is_api_handler
            MERGE (m)-[:DEFINES]->(f)
            """,
            repo_name=repo_name,
            rows=[
                {
                    "id": f.id,
                    "name": f.name,
                    "module_id": f.module_id,
                    "is_api_handler": f.is_api_handler,
                }
                for f in functions
            ],
        )

    # FunctionNode.class_id is the canonical source of HAS_METHOD (SCHEMA.md gap #2) --
    # ClassNode.methods is a denormalized duplicate, not written as a second edge source.
    method_rows = [{"class_id": f.class_id, "func_id": f.id} for f in functions if f.class_id]
    if method_rows:
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (c:Class {repo_name: $repo_name, id: row.class_id})
            MATCH (f:Function {repo_name: $repo_name, id: row.func_id})
            MERGE (c)-[:HAS_METHOD]->(f)
            """,
            repo_name=repo_name,
            rows=method_rows,
        )


def _write_calls(tx: ManagedTransaction, repo_name: str, functions: list[FunctionNode]) -> None:
    rows = [
        {"caller_id": f.id, "callee_id": callee_id}
        for f in functions
        for callee_id in f.calls
    ]
    if not rows:
        return
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (caller:Function {repo_name: $repo_name, id: row.caller_id})
        MATCH (callee:Function {repo_name: $repo_name, id: row.callee_id})
        MERGE (caller)-[:CALLS]->(callee)
        """,
        repo_name=repo_name,
        rows=rows,
    )


def _write_endpoints(tx: ManagedTransaction, repo_name: str, endpoints: list[ApiEndpoint]) -> None:
    if not endpoints:
        return
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (r:Repository {name: $repo_name})
        MERGE (e:Endpoint {repo_name: $repo_name, id: row.id})
        SET e.method = row.method, e.path = row.path, e.framework_annotation = row.framework_annotation
        MERGE (r)-[:HAS_ENDPOINT]->(e)
        """,
        repo_name=repo_name,
        rows=[
            {
                "id": e.id,
                "method": e.method.value,
                "path": e.path,
                "framework_annotation": e.framework_annotation,
            }
            for e in endpoints
        ],
    )

    handled_rows = [
        {"endpoint_id": e.id, "handler_id": e.handler_function_id}
        for e in endpoints
        if e.handler_function_id
    ]
    if handled_rows:
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (e:Endpoint {repo_name: $repo_name, id: row.endpoint_id})
            MATCH (f:Function {repo_name: $repo_name, id: row.handler_id})
            MERGE (e)-[:HANDLED_BY]->(f)
            """,
            repo_name=repo_name,
            rows=handled_rows,
        )


def _write_database_entities(
    tx: ManagedTransaction, repo_name: str, entities: list[DatabaseEntity]
) -> None:
    if not entities:
        return
    # DatabaseEntity has no module_id field (same gap as ApiEndpoint, SCHEMA.md gap #1) --
    # attached directly to Repository via HAS_DATABASE_ENTITY, same pattern as HAS_ENDPOINT.
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (r:Repository {name: $repo_name})
        MERGE (d:DatabaseEntity {repo_name: $repo_name, id: row.id})
        SET d.name = row.name, d.source_path = row.source_path
        MERGE (r)-[:HAS_DATABASE_ENTITY]->(d)
        """,
        repo_name=repo_name,
        rows=[{"id": e.id, "name": e.name, "source_path": e.source_path} for e in entities],
    )


def _write_relates_to(
    tx: ManagedTransaction, repo_name: str, entities: list[DatabaseEntity]
) -> None:
    rows = [
        {"entity_id": e.id, "func_id": func_id}
        for e in entities
        for func_id in e.related_function_ids
    ]
    if not rows:
        return
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (f:Function {repo_name: $repo_name, id: row.func_id})
        MATCH (d:DatabaseEntity {repo_name: $repo_name, id: row.entity_id})
        MERGE (f)-[:RELATES_TO]->(d)
        """,
        repo_name=repo_name,
        rows=rows,
    )


def _write_external_dependencies(
    tx: ManagedTransaction, repo_name: str, deps: list[ExternalDependency]
) -> None:
    if not deps:
        return
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (r:Repository {name: $repo_name})
        MERGE (x:ExternalDependency {repo_name: $repo_name, name: row.name})
        SET x.version = row.version, x.dep_type = row.dep_type
        MERGE (r)-[:DEPENDS_ON]->(x)
        """,
        repo_name=repo_name,
        rows=[{"name": d.name, "version": d.version, "dep_type": d.dep_type.value} for d in deps],
    )


def _write_config_files(tx: ManagedTransaction, repo_name: str, configs: list[ConfigFile]) -> None:
    if not configs:
        return
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (r:Repository {name: $repo_name})
        MERGE (cf:ConfigFile {repo_name: $repo_name, path: row.path})
        SET cf.config_type = row.config_type
        MERGE (r)-[:HAS_CONFIG]->(cf)
        """,
        repo_name=repo_name,
        rows=[{"path": c.path, "config_type": c.config_type.value} for c in configs],
    )
