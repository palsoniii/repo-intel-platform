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

> **Populated vs declared (measured across all 18 evaluation repos, 2026-08-29).**
> `IMPORTS` 3,861 · `DEFINES` 1,684 functions + 839 classes · `HAS_METHOD` 1,398 ·
> `DEPENDS_ON` 837 · `HANDLED_BY` 188 · `IMPLEMENTS` 144 · `HAS_CONFIG` 58.
> **`CALLS`, `RELATES_TO` and `HAS_DATABASE_ENTITY` are 0 — never once written.**
> All three have working `MERGE` statements in `graph/builder.py` that have never fired,
> because no parser populates `FunctionNode.calls`, `DatabaseEntity.related_function_ids`
> or `database_entities`. Treat them as designed-but-unbuilt, not as available signal.


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
| `HAS_DATABASE_ENTITY` | `Repository` -> `DatabaseEntity` | implicit (added while implementing the builder -- see gap #5) |

`Endpoint` and `DatabaseEntity` are both attached to `Repository` directly rather than
to `Module`, because neither `ApiEndpoint` nor `DatabaseEntity` has a `module_id`
field -- see gaps #1 and #5.

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

5. **`DatabaseEntity` also has no `module_id` field**, the same gap as `ApiEndpoint`
   (#1) -- found while writing `app/graph/builder.py` in the Week 2 build. Attached
   to `Repository` directly via the `HAS_DATABASE_ENTITY` relationship (same pattern
   as `HAS_ENDPOINT`) rather than to `Module`.

## Uniqueness constraints (apply once per Neo4j instance, not per repo)

See `schema.cypher` for the exact `CREATE CONSTRAINT` statements, written to key
every per-repo node type on `(repo_name, id)` per gap #3/#4 above, not on `id` alone.

## How this maps to the 3-way representation ablation

This is the schema the Week 2 "Context Builder" and Week 3 "3-way ablation" tasks
will query against:

- **`raw`** -- doesn't touch the graph at all; uses the repo's raw source text.
- **`dependency_graph`** -- queries only `Module`/`IMPORTS` (+ `Repository`/`DEPENDS_ON`/
  `ExternalDependency`) -- the shallowest structured representation.
- **`knowledge_graph`** -- modules with their `IMPORTS` edges and the classes each
  defines, plus endpoints (with handler name), external dependencies, config files and
  database entities. **It does NOT query functions or `CALLS`** -- only an endpoint's
  `HANDLED_BY` handler name. Import edges were added by `e2e2bd8` (2026-08-29); before
  that this variant contained no edges at all, which made it *disjoint from* rather than
  a superset of `dependency_graph` — see `docs/REPORT.md` Errata E3.

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

## Update (Week 2 build)

`app/graph/builder.py` and `app/context/builder.py` now implement this design (see
their module docstrings). Building them against a real Neo4j instance (via
`tests/test_graph_builder.py` and `tests/test_context_builder.py`, both marked
`@pytest.mark.neo4j` and skipped gracefully without one) surfaced two more real
issues beyond the 5 gaps above:

6. **`DatabaseEntity` needed the same `HAS_DATABASE_ENTITY` treatment as `Endpoint`**
   -- added to the relationship table above.
7. **A genuine Cypher semantics bug**, caught only by testing against a live
   database with an endpoint that has no handler: `OPTIONAL MATCH
   (r)-[:HAS_ENDPOINT]->(e:Endpoint)-[:HANDLED_BY]->(handler:Function)` as a single
   chained pattern drops the *entire* pattern -- including `e` -- for any endpoint
   with no `HANDLED_BY` edge (e.g. inline handlers), silently excluding it from
   results instead of returning `handler = null`. Fixed by splitting into two
   separate `OPTIONAL MATCH` clauses in both `schema.cypher` and
   `context/builder.py`. The two-repo Week 1 validation didn't catch this because
   that test data didn't include a handler-less endpoint.

## Not yet done

- Week 3's ablation runner (calling all 3 models against all 3 representations
  across the fixed evaluation set) and the RAW representation (needs raw source
  text retained past `analyze_repository()`'s cleanup, an open design question --
  see `context/builder.py`'s docstring).
