"""
Architecture diagram generator: Neo4j graph -> Mermaid flowchart syntax, entirely
deterministic Cypher + string formatting -- no LLM call, per the roadmap's Week 3
task ("diagram generation branches off the graph directly, not the LLM").

Mermaid node ids use our own stable ids (ModuleNode.id, ApiEndpoint.id, e.g.
"mod_0", "mod_1_ep_0") rather than sanitizing file paths -- those ids are already
alphanumeric-plus-underscore, which Mermaid accepts as bare identifiers, so there's
no quoting/escaping-sensitive-characters problem to solve.
"""

from __future__ import annotations

from neo4j import Driver, ManagedTransaction


def generate_architecture_diagram(driver: Driver, repo_name: str) -> str:
    with driver.session() as session:
        data = session.execute_read(_query_diagram_data, repo_name)
    return _format_mermaid(data)


def _query_diagram_data(tx: ManagedTransaction, repo_name: str) -> dict:
    modules = [
        dict(r)
        for r in tx.run(
            "MATCH (:Repository {name: $repo_name})-[:HAS_MODULE]->(m:Module) "
            "RETURN m.id AS id, m.path AS path",
            repo_name=repo_name,
        )
    ]
    imports = [
        dict(r)
        for r in tx.run(
            "MATCH (:Repository {name: $repo_name})-[:HAS_MODULE]->(from:Module) "
            "MATCH (from)-[:IMPORTS]->(to:Module) "
            "RETURN from.id AS from_id, to.id AS to_id",
            repo_name=repo_name,
        )
    ]
    endpoints = [
        dict(r)
        for r in tx.run(
            "MATCH (:Repository {name: $repo_name})-[:HAS_ENDPOINT]->(e:Endpoint) "
            "OPTIONAL MATCH (e)-[:HANDLED_BY]->(:Function)<-[:DEFINES]-(m:Module) "
            "RETURN e.id AS id, e.method AS method, e.path AS path, m.id AS module_id",
            repo_name=repo_name,
        )
    ]
    return {"modules": modules, "imports": imports, "endpoints": endpoints}


def _mermaid_escape(text: str) -> str:
    return text.replace('"', "&quot;")


def _format_mermaid(data: dict) -> str:
    lines = ["graph TD"]

    if not data["modules"]:
        lines.append('  empty["No modules found for this repository"]')
        return "\n".join(lines)

    for m in data["modules"]:
        lines.append(f'  {m["id"]}["{_mermaid_escape(m["path"])}"]')

    for imp in data["imports"]:
        lines.append(f'  {imp["from_id"]} --> {imp["to_id"]}')

    for e in data["endpoints"]:
        label = _mermaid_escape(f'{e["method"]} {e["path"]}')
        lines.append(f'  {e["id"]}{{{{"{label}"}}}}')
        if e["module_id"]:
            lines.append(f'  {e["module_id"]} -.-> {e["id"]}')

    return "\n".join(lines)
