# AI-Powered Repository Intelligence Platform

## Status: Phase 1 done, Phase 4 (Ollama layer) started

This project is being built incrementally, module by module, per the build order below.
Phase 1 is a real, working, tested slice: give it a GitHub URL for an Express.js repo
and it clones it, detects the framework, and statically extracts modules, functions,
routes, dependencies, and config files -- verified against both a hand-built fixture
and a live public repo (`heroku/node-js-getting-started`).

Phase 4's `OllamaProvider` is built and unit-tested against a mocked Ollama client
(no local Ollama daemon required to run the test suite). It has not yet been
exercised against a real running Ollama instance with the 3 pulled models --
that's still the Day-0 hardware-check step from the roadmap.

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

**Phase 4 (Ollama orchestration layer, in progress):**
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
tests/test_ollama_provider.py::test_provider_name_is_ollama PASSED
tests/test_ollama_provider.py::test_generate_summary_success PASSED
tests/test_ollama_provider.py::test_identical_call_shape_across_models PASSED
tests/test_ollama_provider.py::test_connection_failure_raises_provider_call_error_and_records_failed_status PASSED
tests/test_ollama_provider.py::test_call_model_wraps_errors_as_provider_call_error PASSED
================= 15 passed (14 offline + 1 network-dependent) =================
```

**Phase 8 (dashboard shell, started):**
- `frontend/` -- Vite + React 19 + TypeScript + Tailwind CSS v4, routed with
  `react-router-dom`. Four pages: Analyze (URL input), Summary, Diagram, Comparison --
  all built against `frontend/src/lib/mockData.ts`, not a real backend yet.
- `frontend/src/lib/types.ts` mirrors the backend's `ContextVariant` (3-way) and the 3
  Ollama models, so swapping in real `/analyze` responses later doesn't require
  reshaping the page components.
- Diagram page shows raw Mermaid source in a `<pre>` block, not yet rendered --
  real Mermaid rendering is Week 3 (diagram generation branches off the Neo4j graph
  directly, not the LLM).
- Comparison page is a table of all 3 models x 3 representations (latency, tokens,
  a placeholder hallucination score, $0 cost) -- the ablation the research question
  is about, though the numbers themselves are fake until Week 4's evaluation battery.
- Verified manually in-browser: all 4 routes render, form navigation and direct-URL
  SPA routing both work, no console errors.

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
- [~] **Phase 4** -- Ollama orchestration layer (3 local models: Qwen2.5-Coder 7B, Llama 3.1 8B, gpt-oss:20b/Mistral 7B -- no paid APIs). `OllamaProvider` built + unit-tested; not yet run against a real Ollama daemon.
- [ ] **Phase 5** -- Summary + architecture diagram generation
- [ ] **Phase 6** -- NestJS parser
- [ ] **Phase 7** -- Evaluation harness (LLM-as-judge hallucination metric, diagram graph-diff scorer, CSV export)
- [~] **Phase 8** -- React dashboard. Shell + routing + fake-data pages built; not yet wired to the real backend.

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

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173 -- fake-data dashboard, no backend needed yet
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
