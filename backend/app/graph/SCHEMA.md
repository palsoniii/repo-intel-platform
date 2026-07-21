# Neo4j Knowledge Graph Schema (design)

Roadmap Week 1 task (Dishank, Thu-Fri Jul 24-25): design only, no build yet. The
real builder (`ParsedRepository` -> Cypher `MERGE` calls) is Week 2's Phase 2 task.
This maps every field in `backend/app/schemas/parser_schema.py` to a node label or
relationship type, so the Week 2 build has an unambiguous target.

## Node labels

| Label | Source (`parser_schema.py`) | Key properties |
|---|---|---|
| `Repository` | `RepoMetadata` | `name` (see uniqueness note below), `source_url`, `commit_sha`, `detected_language`, `detected_framework`, `framework_version`, `parsed_at` |
| `Module` | `ModuleNode` | `id`, `path`, `kind` |
| `Class` | `ClassNode` | `id`, `name`, `is_interface` |
| `Function` | `FunctionNode` | `id`, `name`, `is_api_handler` |
| `Endpoint` | `ApiEndpoint` | `id`, `method`, `path`, `framework_annotation` |
| `DatabaseEntity` | `DatabaseEntity` | `id`, `name`, `source_path` |
| `ExternalDependency` | `ExternalDependency` | `name`, `version`, `dep_type` |
| `ConfigFile` | `ConfigFile` | `path`, `config_type` |

## Relationship types

| Relationship | From -> To | Source |
|---|---|---|
| `HAS_MODULE` | `Repository` -> `Module` | implicit (every module belongs to the parsed repo) |
| `IMPORTS` | `Module` -> `Module` | `Dependencies.internal` (`InternalDependencyEdge`) |
| `DEFINES` | `Module` -> `Class` \| `Function` | `ClassNode.module_id` / `FunctionNode.module_id` |
| `HAS_METHOD` | `Class` -> `Function` | `FunctionNode.class_id` (canonical -- see gap #2 below) |
| `IMPLEMENTS` | `Class` -> `Class` | `ClassNode.interfaces_implemented` |
| `CALLS` | `Function` -> `Function` | `FunctionNode.calls` |
| `HANDLED_BY` | `Endpoint` -> `Function` | `ApiEndpoint.handler_function_id` (nullable -- inline handlers have no edge, see Phase 1 known gaps in README) |
| `RELATES_TO` | `Function` -> `DatabaseEntity` | `DatabaseEntity.related_function_ids` |
| `DEPENDS_ON` | `Repository` -> `ExternalDependency` | `Dependencies.external` |
| `HAS_CONFIG` | `Repository` -> `ConfigFile` | `config_files` |

`Endpoint` is attached to `Repository` directly (`Repository -[:HAS_ENDPOINT]-> Endpoint`)
rather than to `Module`, because `ApiEndpoint` currently has no `module_id` field --
see gap #1.

## Open gaps to resolve before the Week 2 build (found while doing this design pass)

1. **`ApiEndpoint` has no `module_id`.** `express_parser.py` encodes it positionally
   in the generated id (`f"{module_id}_ep_{route_index}"`), but that's a string
   convention, not a schema field -- fragile for the graph builder to parse back out.
   Recommend adding `module_id: str` to `ApiEndpoint` in `parser_schema.py` before
   Week 2, and populating it in `express_parser.py`'s `_extract_routes`. Not made
   here since this task is schema design, not a parser change.

2. **`ClassNode.methods` and `FunctionNode.class_id` are two directions of the same
   fact** (class-to-function and function-to-class) and nothing currently guarantees
   they agree. The graph builder should pick one as canonical (`FunctionNode.class_id`,
   since it's set at the point the function is parsed) and treat `ClassNode.methods`
   as a value to validate against, not a second source of `HAS_METHOD` edges --
   otherwise a bug in one could silently double up or contradict edges from the other.

3. **Node ids from the parser are only unique within one parse, not across repos.**
   `express_parser.py` generates ids like `mod_0`, `mod_0_fn_1` fresh for every repo
   it parses -- so two different repos in the fixed 6-repo (+2 held-back) evaluation
   set will both produce a node with id `mod_0`. If the graph builder's `MERGE` keys
   on `id` alone, the second repo's ingestion will silently merge into / overwrite the
   first repo's nodes. **Every node key must be scoped by repo**, e.g. `MERGE (m:Module
   {repo_name: $repo_name, id: $id})` with a composite uniqueness constraint on
   `(repo_name, id)`, not a bare constraint on `id`. This matters as soon as more than
   one repo is loaded into the same Neo4j instance -- i.e. by Week 3's ablation runs
   across multiple repos, and definitely by Week 4's 6+2 evaluation set.

4. **`ExternalDependency` and `ConfigFile` have no `id` field at all** (just `name`/`path`).
   Same repo-scoping problem as #3, worse because there's no id to composite against --
   recommend keying `ExternalDependency` on `(repo_name, name)` and `ConfigFile` on
   `(repo_name, path)`.

## Uniqueness constraints (apply once per Neo4j instance, not per repo)

See `schema.cypher` for the exact `CREATE CONSTRAINT` statements, written to key
every per-repo node type on `(repo_name, id)` per gap #3/#4 above, not on `id` alone.

## How this maps to the 3-way representation ablation

This is the schema the Week 2 "Context Builder" and Week 3 "3-way ablation" tasks
will query against:

- **`raw`** -- doesn't touch the graph at all; uses the repo's raw source text.
- **`dependency_graph`** -- queries only `Module`/`IMPORTS` (+ `Repository`/`DEPENDS_ON`/
  `ExternalDependency`) -- the shallowest structured representation.
- **`knowledge_graph`** -- queries the full schema above (modules, classes, functions,
  endpoints, calls, database entities, config) -- the richest representation.

Example queries for each are in `schema.cypher`'s "Representation queries" section --
these are the literal Cypher the Structured Context Builder (Week 2, Phase 3) will
wrap in Python and hand to the Ollama orchestration layer as the `context` string.

## Validated

Docker was available locally, so rather than leaving `schema.cypher` as hand-verified
only, it was run end-to-end against a throwaway Neo4j 5.26 Community Edition container:

- All 8 composite (`repo_name`, `id`/`name`/`path`) uniqueness constraints apply
  cleanly on **Community Edition** -- composite property uniqueness constraints
  (not "node key" constraints) don't require Enterprise.
- Ingested two fake repos (`repo-alpha`, `repo-beta`) that deliberately reuse the same
  parser-style ids (`mod_0`, `mod_1`) -- confirming gap #3 is real (ids do collide
  across repos) and that the `(repo_name, id)` composite keying correctly keeps both
  repos' data isolated: both the `dependency_graph` and `knowledge_graph` representation
  queries returned correct, non-cross-contaminated results for each repo.
- The original "sanity-check" query in an earlier draft (checking for shared bare
  `id` values across repos) was misleading -- that's expected behavior, not a bug, so
  it always returns rows. Replaced it with a check for relationships that cross
  `repo_name` boundaries (the actual bug pattern to guard against, e.g. a Week 2
  `MATCH` that forgets to scope one side by `repo_name`). Verified it returns zero
  rows normally, and correctly detects a deliberately-introduced cross-repo edge when
  one is forced in, so the check has real teeth.

## Not yet done (explicitly out of scope for this design pass)

- No Python graph-builder module (`app/graph/builder.py` or similar) -- that's Week 2.
  The validation above used raw Cypher via the `neo4j` Python driver directly, not
  any code that will ship in the repo.
