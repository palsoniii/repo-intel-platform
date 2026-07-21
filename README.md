# AI-Powered Repository Intelligence Platform

## Status: Full pipeline works end-to-end -- GitHub URL to real summary in the dashboard

This project is being built incrementally, module by module, per the build order below.
Phase 1 is a real, working, tested slice: give it a GitHub URL for an Express.js repo
and it clones it, detects the framework, and statically extracts modules, functions,
routes, dependencies, and config files -- verified against both a hand-built fixture
and a live public repo (`heroku/node-js-getting-started`).

Phases 2 (Neo4j graph builder), 3 (context builder), 4 (Ollama layer), and the
dashboard wiring now form one real, no-mocks pipeline: paste a GitHub URL into the
dashboard's Analyze page, it calls `POST /summarize`, which runs parser -> Neo4j ->
knowledge_graph context -> Ollama (Qwen2.5-Coder by default) -> parsed JSON summary,
rendered on the Summary page. Verified for real: a local Ollama install (3 models
pulled -- Qwen2.5-Coder, Llama 3.1, Mistral 7B in place of gpt-oss:20b, see Known
limitations for why) and a live Neo4j produced a correct summary for
`heroku/node-js-getting-started` in ~15s, visible in the actual browser UI with zero
console errors.

### What exists right now

**Phase 0 (contracts):**
- `backend/app/schemas/parser_schema.py` -- `ParsedRepository` and friends: the
  common intermediate schema every framework parser (Express, NestJS) must emit.
- `backend/app/schemas/llm_result.py` -- `LLMResult` and friends: the standard object
  returned for every local Ollama model run. Includes the `ContextVariant` enum
  (raw / dependency_graph / knowledge_graph) that is the core independent variable
  of the research comparison, scoped to the 3-way ablation locked in the roadmap.
- `backend/app/parsers/base.py`, `backend/app/providers/base.py` -- abstract interfaces.

**Phase 1 (acquisition + first working parser):**
- `backend/app/acquisition/clone.py` -- GitHub URL validation + shallow clone (depth=1)
  with size limits. Tested against a real repo.
- `backend/app/acquisition/detect.py` -- fast language/framework detection from
  `package.json` / `pom.xml` / `build.gradle` signatures.
- `backend/app/parsers/express_parser.py` -- full Express.js parser using
  `tree-sitter-javascript`: extracts modules, functions, `app.*`/`router.*` routes
  (both named-handler and inline-handler forms), resolves internal `require()` imports
  to module ids, resolves named route handlers to function ids, and reads
  `package.json` for external dependencies.
- `backend/app/parsers/registry.py` -- dispatches to the right parser via `detect()`.
  NestJS is checked *before* Express: a NestJS repo often lists `express` directly
  too (it's NestJS's default HTTP adapter via `@nestjs/platform-express`), so
  `ExpressParser.detect()` can also return `True` for a NestJS repo -- NestJS's
  `@nestjs/core`/`@nestjs/common` signal is more specific.
- `backend/app/pipeline.py` -- `analyze_repository(url)`: the single entrypoint tying
  acquisition + detection + parsing together.
- `backend/app/main.py` -- `POST /analyze` endpoint wired to the pipeline, with clean
  400 errors on bad input.
- `backend/tests/` -- 9 fixture-based unit tests (fast, no network) + 1 real-network
  integration test. All 10 passing.

**Phase 6 (NestJS parser, built):**
- `backend/app/parsers/nestjs_parser.py` -- full NestJS parser using
  `tree-sitter-typescript`: extracts classes (controllers/services/modules) with
  their methods correctly owned via `class_id` (unlike Express, NestJS is genuinely
  class-based, so `HAS_METHOD`/`IMPLEMENTS` graph edges get exercised by real parser
  output for the first time, not just the hand-built test fixture in
  `test_graph_builder.py`), decorator-based routes (`@Get`/`@Post`/etc. combined
  with the controller's `@Controller('prefix')`), ES `import` resolution, and
  `package.json` dependencies.
- Unlike Express, NestJS route handlers are always named class methods -- there's
  no inline-handler-with-no-function-id case here.
- Grammar facts (field names, sibling structure) were verified empirically against
  real tree-sitter-typescript output before writing extraction code, not guessed --
  this caught a real gotcha: a class's decorators are NOT its immediate preceding
  sibling when `export`/`export default` sit in between (`export class Foo` parses
  as siblings `[decorator*, export, class_declaration]`), so naively checking only
  the immediate previous sibling would silently miss `@Controller`.
- Validated against the real `nestjs/typescript-starter` repo, which surfaced a
  real bug: `Path.suffix` only ever returns `.ts` (never `.spec.ts`), and the repo's
  own scaffolded `test/app.e2e-spec.ts` used a naming convention
  (`.e2e-spec.ts`) the filter didn't cover -- fixed to catch both `*.spec.ts` and
  `*.e2e-spec.ts`.
- `backend/tests/test_nestjs_parser.py` -- 12 fixture-based unit tests. Plus a new
  real-network integration test in `test_pipeline_integration.py` against
  `nestjs/typescript-starter` itself.

**Phase 4 (Ollama orchestration layer, validated live):**
- `backend/app/providers/ollama_provider.py` -- `OllamaProvider(BaseLLMProvider)`: the
  one class all 3 comparison models run through (Qwen2.5-Coder, Llama 3.1,
  gpt-oss/Mistral) -- model choice is just the `model` argument, so the call shape is
  identical across all three per the roadmap's Week 1 requirement. Wraps the `ollama`
  Python client's `.chat()`, reading `prompt_eval_count`/`eval_count` for token counts.
- `backend/app/providers/pricing.py` -- always returns $0 (local models, no billing).
- `backend/tests/test_ollama_provider.py` -- 5 unit tests against a mocked Ollama
  client (no local Ollama daemon needed to run these).
- Fixed a real bug found while writing these tests: `BaseLLMProvider.generate_summary()`
  and `.generate_architecture_diagram()` accepted a `model` argument but never passed
  it to `_run()`, so model selection silently no-op'd and every call used
  `default_model` regardless of what was requested.
- `backend/app/pipeline.py` -- `generate_repository_summary()`: the real, no-mocks
  Week 2 pipeline (parse -> Neo4j -> knowledge_graph context -> Ollama -> JSON
  summary), exposed as `POST /summarize` in `main.py`. `driver`/`provider` are
  injectable so tests don't need live infra; JSON parsing of the model's raw output
  happens here (downstream of the provider, per `providers/base.py`'s design), and
  malformed/off-schema output is marked invalid rather than raised, since that's a
  real possibility with local models, not just a hypothetical.
- `backend/tests/test_pipeline_summary.py` -- 7 offline unit tests (mocked Neo4j
  driver + LLM provider) covering orchestration order, driver-ownership/cleanup,
  malformed-JSON handling, and Neo4j-unreachable error wrapping.
- **Validated for real**: installed Ollama (Homebrew), freed ~15GB of stale Docker
  build cache/dangling images to make room, pulled all 3 models (Qwen2.5-Coder,
  Llama 3.1, Mistral 7B substituted for gpt-oss:20b -- this dev machine has 16GB
  RAM, not the ~16GB gpt-oss:20b alone needs), started a real Neo4j via Docker, and
  ran `POST /summarize` against `heroku/node-js-getting-started` for real: correct
  JSON summary in ~15s, $0 cost, zero errors.
- Two real bugs found only by testing against live infra (not just mocks):
  1. `generate_repository_summary` let raw `neo4j.exceptions.ServiceUnavailable`
     propagate as an unhandled exception when Neo4j was down. Added
     `PipelineInfrastructureError` (caught in `main.py`, returned as a clean 503)
     -- catches both `Neo4jError` (server-side errors) and `DriverError`
     (connection-level errors), not the driver's `GqlError` common base, since
     that's an explicitly-labeled preview feature that could change without a
     deprecation cycle.
  2. A FastAPI/Starlette gotcha: Starlette routes handlers registered for the bare
     `Exception` class to `ServerErrorMiddleware`, which wraps `CORSMiddleware`
     from the *outside* -- so a global `@app.exception_handler(Exception)` never
     gets CORS headers from the middleware, no matter how CORS is configured. An
     unrelated backend bug looked, from the browser, indistinguishable from a
     CORS/network failure. Fixed by setting `Access-Control-Allow-Origin`
     manually in that handler. Caught first via manual browser testing, then
     regression-tested in `tests/test_main.py` (which deliberately disables
     `TestClient`'s `raise_server_exceptions` to inspect the response instead of
     having pytest re-raise it).
  3. `.env` has been documented and depended on (`NEO4J_PASSWORD`, `OLLAMA_HOST`,
     ...) since Phase 0, but nothing ever actually called `load_dotenv()` --
     `python-dotenv` was a dependency, never used. Only surfaced after restarting
     the server without inline env vars and getting a Neo4j auth error that made no
     sense until this was noticed. Fixed with one `load_dotenv()` call in
     `main.py`.

### Verified test results (this session)

```
tests/test_express_parser.py::test_detects_express PASSED
tests/test_express_parser.py::test_finds_all_modules PASSED
tests/test_express_parser.py::test_resolves_internal_import PASSED
tests/test_express_parser.py::test_finds_named_functions PASSED
tests/test_express_parser.py::test_finds_all_routes PASSED
tests/test_express_parser.py::test_resolves_named_handler_to_function_id PASSED
tests/test_express_parser.py::test_inline_handler_has_no_function_id PASSED
tests/test_express_parser.py::test_external_dependencies_from_package_json PASSED
tests/test_express_parser.py::test_config_files_detected PASSED
tests/test_pipeline_integration.py::test_analyze_real_express_repo PASSED
tests/test_pipeline_integration.py::test_analyze_real_nestjs_repo PASSED
tests/test_nestjs_parser.py:: (12 tests, fixture-based) PASSED
tests/test_ollama_provider.py::test_provider_name_is_ollama PASSED
tests/test_ollama_provider.py::test_generate_summary_success PASSED
tests/test_ollama_provider.py::test_identical_call_shape_across_models PASSED
tests/test_ollama_provider.py::test_connection_failure_raises_provider_call_error_and_records_failed_status PASSED
tests/test_ollama_provider.py::test_call_model_wraps_errors_as_provider_call_error PASSED
tests/test_pipeline_summary.py:: (7 tests, mocked Neo4j + LLM provider) PASSED
tests/test_graph_builder.py:: (9 tests, real Neo4j -- @pytest.mark.neo4j) PASSED
tests/test_context_builder.py:: (4 tests, real Neo4j -- @pytest.mark.neo4j) PASSED
tests/test_main.py:: (3 tests, CORS-header-on-error regression) PASSED
======= 51 passed total (35 always-offline + 2 network + 13 neo4j-gated) =======

# plus two real, manual, no-mocks runs of the whole pipeline:
POST /summarize {"url": "https://github.com/heroku/node-js-getting-started"}
-> 200 OK in ~15s, correct JSON summary, $0 cost (see Status at the top of this file)
POST /summarize {"url": "https://github.com/nestjs/typescript-starter"}
-> 200 OK in ~23s, correct JSON summary, $0 cost -- first real NestJS repo through
   the full pipeline (parser -> Neo4j -> context -> Ollama), confirming Phase 6
   works end-to-end, not just in isolation
```

The 13 `neo4j`-marked tests SKIP (not fail) when no Neo4j is reachable -- see Setup
below for how to run them for real.

**Phase 2 (Neo4j knowledge graph, built):**
- `backend/app/graph/SCHEMA.md` -- maps every `ParsedRepository` field (`parser_schema.py`)
  to a Neo4j node label or relationship type, keyed on `(repo_name, id)` rather than
  bare `id` so multiple repos can share one Neo4j instance without collision (the
  parser generates ids like `mod_0` fresh per parse, so bare ids collide across repos).
  Documents 7 real gaps/bugs found across the design and build passes.
- `backend/app/graph/schema.cypher` -- constraints + reference queries, validated
  against a live Neo4j 5.26 Community Edition container.
- `backend/app/graph/builder.py` -- `write_parsed_repository()`: the real
  `ParsedRepository` -> Neo4j builder. One atomic transaction per repo (a partial
  parse never leaves a half-written graph), MERGE-based (idempotent -- re-running
  is safe), covers every node/edge type including `HAS_METHOD`/`IMPLEMENTS`/`CALLS`/
  `RELATES_TO`, which the current Express parser never actually populates (no
  classes in idiomatic Express apps) -- those code paths are only exercised by
  `tests/test_graph_builder.py`'s hand-built fixture.
- `backend/app/db/neo4j_client.py` -- thin driver factory reading `NEO4J_URI`/
  `NEO4J_USER`/`NEO4J_PASSWORD` from the environment.
- `backend/tests/test_graph_builder.py` -- 9 tests against a real Neo4j instance
  (marked `@pytest.mark.neo4j`, skip gracefully if none is reachable -- see Setup).
  Confirmed idempotency and that two repos with intentionally colliding parser ids
  stay isolated.

**Phase 3 (structured context builder, 2 of 3 representations built):**
- `backend/app/context/builder.py` -- `build_context()` for `dependency_graph` and
  `knowledge_graph` (queries Neo4j and formats results into the text blob handed to
  the LLM). `raw` deliberately raises `ContextBuilderError` -- it needs the repo's
  raw source text, which isn't retained past `analyze_repository()`'s cleanup step;
  that's Week 3 ablation work with an open design question about where raw source
  gets cached.
- Found and fixed a real Cypher bug while testing against a live Neo4j: chaining
  `OPTIONAL MATCH (r)-[:HAS_ENDPOINT]->(e:Endpoint)-[:HANDLED_BY]->(handler:Function)`
  as one pattern drops the endpoint entirely (not just the handler) when there's no
  `HANDLED_BY` edge -- e.g. inline route handlers vanished from the context instead
  of appearing with a null handler. Fixed by splitting into two `OPTIONAL MATCH`
  clauses (see SCHEMA.md's "Update (Week 2 build)" section for detail).
- `backend/app/providers/prompts.py` -- `SUMMARY_PROMPT_TEMPLATE`, asking for JSON
  matching `{overview, tech_stack, services, dependencies}` -- deliberately mirrors
  `frontend/src/lib/types.ts`'s `RepoSummary` shape.
- `backend/tests/test_context_builder.py` -- 4 tests against a real Neo4j instance.

**Phase 8 (dashboard shell + real wiring):**
- `frontend/` -- Vite + React 19 + TypeScript + Tailwind CSS v4, routed with
  `react-router-dom`. Four pages: Analyze, Summary, Diagram, Comparison.
- `frontend/src/lib/types.ts` mirrors the backend's `ContextVariant` (3-way) and the 3
  Ollama models. Diagram and Comparison pages still use `mockData.ts` -- there's no
  backend yet for diagram generation (Phase 5) or multi-model/multi-representation
  comparison (Week 3), so there's nothing real for them to show.
- `frontend/src/lib/api.ts` -- `summarizeRepository()`: calls the real `POST
  /summarize`, with a snake_case -> camelCase mapping at the boundary (the model's
  own JSON output stays snake_case, matching the prompt). The Analyze page now
  actually submits to this instead of only navigating to mock data, with loading
  and error states; the Summary page renders the real result when it has one
  (via router state), falling back to `mockData.ts` when visited directly (e.g. from
  the nav bar) so the shell is still browsable without a live backend.
- Backend: added `CORSMiddleware` (regex-matched to any `localhost`/`127.0.0.1`
  port, since Vite's default 5173 is often taken by other local projects) and a
  global exception handler -- see the CORS bug under Phase 4 above, which this
  wiring work is what actually surfaced it.
- Verified for real in-browser: submitted a live GitHub URL through the Analyze
  page, watched it hit the real backend, and got a correct rendered summary on the
  Summary page with zero console errors (see Status above).

### Known gaps in the Phase 1 parser (real, not hypothetical -- worth noting in your paper)

- Inline/anonymous route handlers (`app.get('/x', (req, res) => {...})`) are detected
  as endpoints but have no resolvable `handler_function_id`, since there's no stable
  name to link to. This is expected behavior, not a bug -- flagged explicitly in code.
- `.ts` files are now handled by the NestJS parser (Phase 6, below); `.tsx` is still
  skipped everywhere (logged to `files_skipped`) -- NestJS backends don't use JSX,
  so there was never a reason to add it.
- Import resolution only handles relative `require()` paths, not ES module `import`
  syntax or path aliases (e.g. webpack/tsconfig `paths`).
- No handling yet for Express apps split across many nested routers
  (`router.use('/sub', subRouter)`) -- route ownership across mounted sub-routers
  isn't traced yet.

### Known gaps in the Phase 6 NestJS parser (same spirit as Phase 1's, above)

- `@Module()` metadata (`controllers`/`providers`/`imports` arrays) isn't parsed --
  module-to-controller/service wiring isn't in the graph, only the plain `IMPORTS`
  edges from each file's own `import` statements.
- Decorator arguments beyond a single string literal aren't resolved -- `@Controller({
  path: 'users', version: '1' })` or `@Controller(['v1/users', 'v2/users'])`
  resolve to an empty-string prefix rather than being parsed further.
- No ORM entity extraction (e.g. TypeORM `@Entity()` classes) -- `database_entities`
  is always empty for NestJS repos, same as Express.
- Barrel-file re-exports (`export { X } from './y'`, `export * from './y'`) aren't
  resolved as import edges -- only `import ... from` statements are.
- Dependency injection isn't modeled -- constructor parameter types (e.g. `private
  readonly usersService: UsersService`) aren't turned into graph edges, even though
  they're the actual wiring NestJS uses at runtime.

### Build order (matches the original spec, section 6)

- [x] **Phase 0** -- Contracts (parser schema, LLM result schema) + skeleton
- [x] **Phase 1** -- Repository Acquisition + Express.js parser (tested, working)
- [x] **Phase 2** -- Knowledge Graph Builder (Neo4j). `write_parsed_repository()` built and tested against a live Neo4j instance.
- [~] **Phase 3** -- Structured Context Builder. `dependency_graph` and `knowledge_graph` built and tested live; `raw` deferred to Week 3 (needs raw-source retention, an open design question).
- [x] **Phase 4** -- Ollama orchestration layer (3 local models: Qwen2.5-Coder 7B, Llama 3.1 8B, Mistral 7B substituted for gpt-oss:20b on this dev machine's 16GB RAM -- no paid APIs). Built, unit-tested, and validated against a real running Ollama daemon with all 3 models pulled.
- [ ] **Phase 5** -- Architecture diagram generation (summary generation is done, folded into Phase 4's pipeline)
- [x] **Phase 6** -- NestJS parser. Built and validated against a real repo (`nestjs/typescript-starter`).
- [ ] **Phase 7** -- Evaluation harness (LLM-as-judge hallucination metric, diagram graph-diff scorer, CSV export)
- [x] **Phase 8** -- React dashboard. Shell + routing built; Analyze/Summary pages wired to the real `POST /summarize` backend, verified end-to-end in-browser. Diagram/Comparison still on mock data (nothing real for them to show until Phase 5/Week 3 exist).

This build order reflects the negotiated scope in `Capstone_Roadmap.docx` (Neo4j, Express+NestJS only,
3 free local Ollama models, 3-way ablation, no commercial LLM APIs, no conference paper) -- not the
original, broader proposal.

### Setup

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in Neo4j creds / Ollama host -- required for /summarize, not /analyze

# run tests
pytest tests/ -v                    # all tests, including real network clone
pytest tests/ -v -m "not integration"   # offline + neo4j (neo4j tests skip if none reachable)
pytest tests/ -v -m "not integration and not neo4j"   # always-offline only, no infra needed

# to actually run the neo4j-marked tests: start a throwaway Neo4j first
docker run -d --name neo4j-test -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/testpassword123 neo4j:5.26
NEO4J_TEST_PASSWORD=testpassword123 pytest tests/ -v -m neo4j
docker rm -f neo4j-test   # when done

# run the API
uvicorn app.main:app --reload
```

**For `/summarize` to actually work** (not just `/analyze`), you need a running Neo4j
*and* Ollama with the models pulled, matching whatever `.env` points at:

```bash
# Neo4j (persistent, not the throwaway test one above -- match .env's NEO4J_PASSWORD)
docker run -d --name neo4j-dev -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/<your-password> neo4j:5.26

# Ollama (macOS)
brew install ollama && brew services start ollama
ollama pull qwen2.5-coder:7b
ollama pull llama3.1:8b
ollama pull gpt-oss:20b   # or: ollama pull mistral:7b if your machine has <=16GB RAM

curl -X POST localhost:8000/summarize -H "Content-Type: application/json" \
        -d '{"url": "https://github.com/heroku/node-js-getting-started"}'
# ~15s, real cloned repo, real Neo4j graph, real model inference -- this exact
# command produced a correct summary in the session that built this pipeline.
```

```bash
cd frontend
npm install
npm run dev   # http://localhost:5180 (Vite config pins this -- 5173 is often taken
              # by other local projects). Analyze/Summary pages need the backend
              # running (above) to show real data; Diagram/Comparison still work
              # off mock data with no backend at all.
```

The backend's CORS is regex-matched to any `localhost`/`127.0.0.1` port, so it
doesn't matter which port Vite actually lands on if 5180 is also taken.

### How to add a new framework parser (once the pattern is established in Phase 1)

1. Subclass `BaseParser` in `app/parsers/`
2. Implement `detect()` (cheap file-signature check) and `parse()` (returns a
   `ParsedRepository`)
3. Register it in `app/parsers/registry.py` (added in Phase 1)

### How to add a new LLM provider

1. Subclass `BaseLLMProvider` in `app/providers/`
2. Implement `_call_model()` (the one vendor-specific method) and `estimate_cost()`
3. Everything else -- retry logic, latency timing, `LLMResult` construction -- is
   inherited from the base class

### Known limitations (flagged upfront, see conversation history for full rationale)

- NestJS parsing will be heuristic-based (tree-sitter + decorator pattern matching),
  not a full semantic parser -- expect lower precision than the Express parser.
- Mermaid diagram validation is structural, not a true Mermaid-spec parse.
- The hallucination metric is an LLM-as-judge (one local model checking another's
  summary against parser ground truth), validated against only a small manually
  scored sample -- not a fully validated NLP metric.
- All three comparison models run locally via Ollama; response-time comparisons are
  only meaningful when run on the single designated evaluation machine (see roadmap
  Section 1).
- This dev machine substitutes Mistral 7B for gpt-oss:20b (16GB RAM total isn't
  enough to comfortably load a ~13GB model alongside Neo4j/Docker/the OS -- exactly
  the case the roadmap's own fallback note anticipates). Whoever ends up as the
  designated evaluation machine (roadmap Section 1) should re-check this: more RAM
  might mean gpt-oss:20b is viable there instead.
- Docker on this machine had ~36GB of stale build cache/dangling images from other
  projects (`civicpulse`, `qann-dashboard`) before the model pulls fit -- worth a
  `docker image prune -a` / `docker builder prune -a` check on a fresh machine that's
  been used for other Docker projects before assuming there's room for the models.
- The `raw` `ContextVariant` isn't implemented (`ContextBuilderError` if requested) --
  it needs the repo's raw source text, which isn't retained past
  `analyze_repository()`'s cleanup step. Needs a design decision in Week 3: cache raw
  source somewhere during acquisition, or re-clone for the raw arm of the ablation.
