"""
Structured Context Builder: Neo4j query results -> a plain-text context string,
handed to the Ollama orchestration layer as `context` in
BaseLLMProvider.generate_summary(). Implements 2 of the 3 ContextVariant arms.

RAW is intentionally NOT implemented here -- it doesn't touch the graph at all
(SCHEMA.md), and needs the repo's raw source text, which analyze_repository()
doesn't retain past its cleanup step. That's Week 3 ablation work, and needs an
explicit decision about where raw source gets cached across the pipeline.
"""

from __future__ import annotations

from neo4j import Driver, ManagedTransaction

from app.schemas.llm_result import ContextVariant


class ContextBuilderError(Exception):
    """Raised when a context can't be built for the requested variant/repo."""


def build_context(driver: Driver, repo_name: str, variant: ContextVariant) -> str:
    if variant == ContextVariant.RAW:
        raise ContextBuilderError(
            "RAW context requires the repo's raw source text, which isn't retained "
            "past analyze_repository()'s cleanup step -- not implemented until "
            "Week 3's representation ablation work."
        )

    with driver.session() as session:
        if variant == ContextVariant.DEPENDENCY_GRAPH:
            rows = session.execute_read(_query_dependency_graph, repo_name)
            return _format_dependency_graph(rows)

        data = session.execute_read(_query_knowledge_graph, repo_name)
        return _format_knowledge_graph(data)


def _query_dependency_graph(tx: ManagedTransaction, repo_name: str) -> list[dict]:
    result = tx.run(
        """
        MATCH (r:Repository {name: $repo_name})-[:HAS_MODULE]->(m:Module)
        OPTIONAL MATCH (m)-[:IMPORTS]->(target:Module)
        OPTIONAL MATCH (r)-[:DEPENDS_ON]->(dep:ExternalDependency)
        RETURN m.path AS module_path,
               collect(DISTINCT target.path) AS imports,
               collect(DISTINCT dep.name) AS external_dependencies
        """,
        repo_name=repo_name,
    )
    return [dict(record) for record in result]


def _format_dependency_graph(rows: list[dict]) -> str:
    if not rows:
        return "No modules found for this repository."

    lines = ["Module dependency graph:"]
    all_external: set[str] = set()
    for row in rows:
        imports = [i for i in row["imports"] if i]
        lines.append(f"- {row['module_path']} imports: {', '.join(imports) or '(none)'}")
        all_external.update(d for d in row["external_dependencies"] if d)

    lines.append("")
    lines.append(f"External dependencies: {', '.join(sorted(all_external)) or '(none)'}")
    return "\n".join(lines)


def _query_knowledge_graph(tx: ManagedTransaction, repo_name: str) -> dict:
    # Kept in sync with schema.cypher's "knowledge_graph variant" reference query.
    result = tx.run(
        """
        MATCH (r:Repository {name: $repo_name})
        OPTIONAL MATCH (r)-[:HAS_MODULE]->(m:Module)
        OPTIONAL MATCH (m)-[:IMPORTS]->(target:Module)
        OPTIONAL MATCH (m)-[:DEFINES]->(c:Class)
        WITH r, m,
             collect(DISTINCT target.path) AS module_imports,
             collect(DISTINCT c.name) AS module_classes
        WITH r, collect({
                 path: m.path, imports: module_imports, classes: module_classes
             }) AS module_rows
        OPTIONAL MATCH (r)-[:HAS_ENDPOINT]->(e:Endpoint)
        OPTIONAL MATCH (e)-[:HANDLED_BY]->(handler:Function)
        OPTIONAL MATCH (r)-[:DEPENDS_ON]->(dep:ExternalDependency)
        OPTIONAL MATCH (r)-[:HAS_CONFIG]->(cfg:ConfigFile)
        OPTIONAL MATCH (r)-[:HAS_DATABASE_ENTITY]->(db:DatabaseEntity)
        RETURN r.detected_framework AS framework,
               r.framework_version AS framework_version,
               module_rows,
               collect(DISTINCT {method: e.method, path: e.path, handler: handler.name}) AS endpoints,
               collect(DISTINCT dep.name) AS external_dependencies,
               collect(DISTINCT cfg.path) AS config_files,
               collect(DISTINCT db.name) AS database_entities
        """,
        repo_name=repo_name,
    )
    record = result.single()
    return dict(record) if record else {}


def _format_knowledge_graph(data: dict) -> str:
    if not data:
        return "No graph data found for this repository."

    module_rows = [m for m in data.get("module_rows", []) if m and m.get("path")]
    module_rows.sort(key=lambda m: m["path"])
    classes = sorted({c for m in module_rows for c in (m.get("classes") or []) if c})
    endpoints = [e for e in data.get("endpoints", []) if e.get("path")]
    deps = sorted(d for d in data.get("external_dependencies", []) if d)
    configs = sorted(c for c in data.get("config_files", []) if c)
    db_entities = sorted(d for d in data.get("database_entities", []) if d)

    lines: list[str] = []
    lines.append(
        f"Framework: {data.get('framework') or 'unknown'} "
        f"({data.get('framework_version') or 'version unknown'})"
    )
    lines.append("")

    # Each module carries its own import edges and the classes it defines. Emitting the
    # relationships (rather than three flat lists) is what makes this variant a superset
    # of dependency_graph: previously it dropped IMPORTS entirely, so the two arms were
    # partially disjoint -- knowledge_graph had entity names and no edges, while
    # dependency_graph had edges and no classes. Comparing them could not measure
    # "more structure" because neither contained the other.
    lines.append(f"Modules ({len(module_rows)}):")
    if module_rows:
        for m in module_rows:
            imports = sorted(i for i in (m.get("imports") or []) if i)
            defines = sorted(c for c in (m.get("classes") or []) if c)
            lines.append(f"- {m['path']}")
            lines.append(f"    imports: {', '.join(imports) or '(none)'}")
            if defines:
                lines.append(f"    defines: {', '.join(defines)}")
    else:
        lines.append("(none)")
    lines.append("")

    lines.append(f"Classes ({len(classes)}):")
    lines.extend([f"- {c}" for c in classes] or ["(none)"])
    lines.append("")

    lines.append(f"API endpoints ({len(endpoints)}):")
    if endpoints:
        for e in endpoints:
            handler = e.get("handler") or "(inline handler, no stable function reference)"
            lines.append(f"- {e['method']} {e['path']} -> {handler}")
    else:
        lines.append("(none)")
    lines.append("")

    lines.append(f"External dependencies: {', '.join(deps) or '(none)'}")
    lines.append(f"Config files: {', '.join(configs) or '(none)'}")
    lines.append(f"Database entities: {', '.join(db_entities) or '(none)'}")

    return "\n".join(lines)
