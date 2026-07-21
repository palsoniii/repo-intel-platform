// Neo4j schema + practice queries -- design pass only (see SCHEMA.md for rationale).
// Constraints and every query below were run against a live Neo4j 5.26 Community
// Edition container (a throwaway Docker instance, since none was running yet on the
// team's designated evaluation machine) -- see SCHEMA.md "Validated" section.
//
// Every per-repo node type is keyed on (repo_name, id) rather than bare `id`, because
// the parser generates ids that are only unique within a single parse (SCHEMA.md gap #3) --
// this lets multiple repos (the 6 fixed + 2 held-back evaluation repos) coexist in one
// Neo4j instance without one repo's MERGE silently overwriting another's nodes.

// ---------------------------------------------------------------------------
// Constraints (run once per Neo4j instance)
// ---------------------------------------------------------------------------

CREATE CONSTRAINT repository_name IF NOT EXISTS
FOR (r:Repository) REQUIRE r.name IS UNIQUE;

CREATE CONSTRAINT module_repo_id IF NOT EXISTS
FOR (m:Module) REQUIRE (m.repo_name, m.id) IS UNIQUE;

CREATE CONSTRAINT class_repo_id IF NOT EXISTS
FOR (c:Class) REQUIRE (c.repo_name, c.id) IS UNIQUE;

CREATE CONSTRAINT function_repo_id IF NOT EXISTS
FOR (f:Function) REQUIRE (f.repo_name, f.id) IS UNIQUE;

CREATE CONSTRAINT endpoint_repo_id IF NOT EXISTS
FOR (e:Endpoint) REQUIRE (e.repo_name, e.id) IS UNIQUE;

CREATE CONSTRAINT dbentity_repo_id IF NOT EXISTS
FOR (d:DatabaseEntity) REQUIRE (d.repo_name, d.id) IS UNIQUE;

CREATE CONSTRAINT extdep_repo_name IF NOT EXISTS
FOR (x:ExternalDependency) REQUIRE (x.repo_name, x.name) IS UNIQUE;

CREATE CONSTRAINT config_repo_path IF NOT EXISTS
FOR (cf:ConfigFile) REQUIRE (cf.repo_name, cf.path) IS UNIQUE;

// ---------------------------------------------------------------------------
// Ingestion practice (illustrative shape of what the Week 2 builder will generate
// per-row from ParsedRepository -- not the final Python-generated queries)
// ---------------------------------------------------------------------------

// One repository node
MERGE (r:Repository {name: $repo_name})
SET r.source_url = $source_url,
    r.detected_language = $detected_language,
    r.detected_framework = $detected_framework,
    r.framework_version = $framework_version,
    r.parsed_at = $parsed_at;

// One module, linked to its repository
MERGE (m:Module {repo_name: $repo_name, id: $module_id})
SET m.path = $path, m.kind = $kind
WITH m
MATCH (r:Repository {name: $repo_name})
MERGE (r)-[:HAS_MODULE]->(m);

// An IMPORTS edge (from Dependencies.internal)
MATCH (from:Module {repo_name: $repo_name, id: $from_module_id})
MATCH (to:Module {repo_name: $repo_name, id: $to_module_id})
MERGE (from)-[:IMPORTS]->(to);

// A function defined in a module, optionally owned by a class
MERGE (f:Function {repo_name: $repo_name, id: $function_id})
SET f.name = $name, f.is_api_handler = $is_api_handler
WITH f
MATCH (m:Module {repo_name: $repo_name, id: $module_id})
MERGE (m)-[:DEFINES]->(f)
WITH f
CALL {
  WITH f
  MATCH (c:Class {repo_name: $repo_name, id: $class_id})
  MERGE (c)-[:HAS_METHOD]->(f)
}
RETURN f;

// A CALLS edge (FunctionNode.calls)
MATCH (caller:Function {repo_name: $repo_name, id: $caller_id})
MATCH (callee:Function {repo_name: $repo_name, id: $callee_id})
MERGE (caller)-[:CALLS]->(callee);

// An endpoint (attached to Repository -- see SCHEMA.md gap #1 on missing module_id)
MERGE (e:Endpoint {repo_name: $repo_name, id: $endpoint_id})
SET e.method = $method, e.path = $path, e.framework_annotation = $framework_annotation
WITH e
MATCH (r:Repository {name: $repo_name})
MERGE (r)-[:HAS_ENDPOINT]->(e)
WITH e
CALL {
  WITH e
  MATCH (h:Function {repo_name: $repo_name, id: $handler_function_id})
  MERGE (e)-[:HANDLED_BY]->(h)
}
RETURN e;

// ---------------------------------------------------------------------------
// Representation queries -- what the Structured Context Builder (Week 2 Phase 3)
// will run for each ContextVariant to build the LLM's context string
// ---------------------------------------------------------------------------

// dependency_graph variant: modules + their import edges + external deps only
MATCH (r:Repository {name: $repo_name})-[:HAS_MODULE]->(m:Module)
OPTIONAL MATCH (m)-[:IMPORTS]->(target:Module)
OPTIONAL MATCH (r)-[:DEPENDS_ON]->(dep:ExternalDependency)
RETURN m.path AS module_path,
       collect(DISTINCT target.path) AS imports,
       collect(DISTINCT dep.name) AS external_dependencies;

// knowledge_graph variant: full structured context (everything)
MATCH (r:Repository {name: $repo_name})
OPTIONAL MATCH (r)-[:HAS_MODULE]->(m:Module)
OPTIONAL MATCH (m)-[:DEFINES]->(c:Class)
OPTIONAL MATCH (c)-[:HAS_METHOD]->(fn:Function)
OPTIONAL MATCH (m)-[:DEFINES]->(freeFn:Function) WHERE NOT (freeFn)<-[:HAS_METHOD]-()
OPTIONAL MATCH (r)-[:HAS_ENDPOINT]->(e:Endpoint)-[:HANDLED_BY]->(handler:Function)
OPTIONAL MATCH (fnAny:Function)-[:CALLS]->(callee:Function)
  WHERE fnAny.repo_name = $repo_name
OPTIONAL MATCH (r)-[:DEPENDS_ON]->(dep:ExternalDependency)
OPTIONAL MATCH (r)-[:HAS_CONFIG]->(cfg:ConfigFile)
RETURN r.detected_framework AS framework,
       collect(DISTINCT m.path) AS modules,
       collect(DISTINCT c.name) AS classes,
       collect(DISTINCT {method: e.method, path: e.path, handler: handler.name}) AS endpoints,
       collect(DISTINCT dep.name) AS external_dependencies,
       collect(DISTINCT cfg.path) AS config_files;

// Sanity-check query: verify no relationship connects nodes from two DIFFERENT
// repos -- this is the real regression to guard against (e.g. a MATCH clause in the
// Week 2 builder that forgets to scope one side by repo_name and accidentally wires
// an edge between two unrelated repos). Should always return zero rows.
//
// (Note: checking for shared `id` values across repos, as an earlier draft of this
// query did, is NOT a useful check -- ids like `mod_0` are *expected* to collide
// across repos by design, per gap #3. That's exactly what (repo_name, id) composite
// keys exist to handle; this query instead confirms edges never leak across that
// boundary.)
MATCH (a)-[rel]->(b)
WHERE a.repo_name IS NOT NULL AND b.repo_name IS NOT NULL AND a.repo_name <> b.repo_name
RETURN type(rel) AS relationship_type, a.repo_name AS from_repo, b.repo_name AS to_repo,
       count(*) AS occurrences;
