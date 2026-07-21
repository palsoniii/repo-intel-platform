# AI-Powered Repository Intelligence Platform

## Status: Phase 1 -- Acquisition + Express.js Parser (working, tested)

This project is being built incrementally, module by module, per the build order below.
Phase 1 is a real, working, tested slice: give it a GitHub URL for an Express.js repo
and it clones it, detects the framework, and statically extracts modules, functions,
routes, dependencies, and config files -- verified against both a hand-built fixture
and a live public repo (`heroku/node-js-getting-started`).

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
- `backend/app/pipeline.py` -- `analyze_repository(url)`: the single entrypoint tying
  acquisition + detection + parsing together.
- `backend/app/main.py` -- `POST /analyze` endpoint wired to the pipeline, with clean
  400 errors on bad input.
- `backend/tests/` -- 9 fixture-based unit tests (fast, no network) + 1 real-network
  integration test. All 10 passing.

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
================= 10 passed =================
```

### Known gaps in the Phase 1 parser (real, not hypothetical -- worth noting in your paper)

- Inline/anonymous route handlers (`app.get('/x', (req, res) => {...})`) are detected
  as endpoints but have no resolvable `handler_function_id`, since there's no stable
  name to link to. This is expected behavior, not a bug -- flagged explicitly in code.
- `.ts`/`.tsx` files are currently skipped (logged to `files_skipped`), reserved for
  the NestJS parser in Phase 6 which will use `tree-sitter-typescript`.
- Import resolution only handles relative `require()` paths, not ES module `import`
  syntax or path aliases (e.g. webpack/tsconfig `paths`).
- No handling yet for Express apps split across many nested routers
  (`router.use('/sub', subRouter)`) -- route ownership across mounted sub-routers
  isn't traced yet.

### Build order (matches the original spec, section 6)

- [x] **Phase 0** -- Contracts (parser schema, LLM result schema) + skeleton
- [x] **Phase 1** -- Repository Acquisition + Express.js parser (tested, working)
- [ ] **Phase 2** -- Knowledge Graph Builder (Neo4j)
- [ ] **Phase 3** -- Structured Context Builder (3-way ablation: raw / dependency graph / full Neo4j context)
- [ ] **Phase 4** -- Ollama orchestration layer (3 local models: Qwen2.5-Coder 7B, Llama 3.1 8B, gpt-oss:20b/Mistral 7B -- no paid APIs)
- [ ] **Phase 5** -- Summary + architecture diagram generation
- [ ] **Phase 6** -- NestJS parser
- [ ] **Phase 7** -- Evaluation harness (LLM-as-judge hallucination metric, diagram graph-diff scorer, CSV export)
- [ ] **Phase 8** -- React dashboard

This build order reflects the negotiated scope in `Capstone_Roadmap.docx` (Neo4j, Express+NestJS only,
3 free local Ollama models, 3-way ablation, no commercial LLM APIs, no conference paper) -- not the
original, broader proposal.

### Setup

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in Neo4j creds (Phase 2) / Ollama host (Phase 4) -- not needed yet

# run tests
pytest tests/ -v                    # all tests, including real network clone
pytest tests/ -v -m "not integration"   # fast, offline-only

# run the API
uvicorn app.main:app --reload
# then: curl -X POST localhost:8000/analyze -H "Content-Type: application/json" \
#         -d '{"url": "https://github.com/heroku/node-js-getting-started"}'
```

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
