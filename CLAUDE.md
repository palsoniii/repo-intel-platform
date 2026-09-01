# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AI-Powered Repository Intelligence Platform: a capstone project that takes a GitHub
URL for an Express.js or NestJS repo, statically parses it, builds a Neo4j knowledge
graph, and asks local LLMs (via Ollama) to generate a summary and (deterministically,
no LLM) a Mermaid architecture diagram. The research question is how different
structured repository representations (raw code / dependency graph / full knowledge
graph) affect LLM-generated summary quality -- see `README.md`'s intro and
`Capstone_Roadmap.docx` for the full research framing, negotiated scope, and
week-by-week plan this project follows.

**Locked scope** (do not reintroduce these without checking with the team first --
they were deliberately cut from a larger original proposal): Neo4j only (not
NetworkX), Express.js + NestJS only (not Spring Boot), 3 free local Ollama models
only (no paid commercial APIs), a 3-way representation ablation (not 5-way).

## Current status / what to do next

**As of 2026-08-29.** All 8 build phases are done and **three full evaluation
batteries have been run** against live Ollama/Neo4j. The dataset is **18 repositories**
(9 Express, 9 NestJS) with hand-verified annotations and reference summaries --
`backend/annotations/README.md`. 168 test functions, of which 19 are infra-gated
(17 `@pytest.mark.neo4j`, 2 `@pytest.mark.integration`) and skip without Neo4j.

| Battery | Writers | Judge | Rows |
|---|---|---|---|
| `battery.db` | qwen2.5-coder:7b, codellama:7b-instruct | gemma2:9b | 108 / 108 |
| `battery_v2.db` | qwen2.5-coder:7b, codellama:7b-instruct, gemma2:9b | mistral:7b-instruct | 162 / 157 |
| `battery_v3_granite_gemma2judge.db` | granite-code:8b-instruct | gemma2:9b | 54 / 53 |

**The re-run called for by earlier drafts is done.** Do not redo it. `docs/REPORT.md`
§7.1 records what it closed.

**The headline finding changed.** The paper is now primarily a methodology result
about LLM-as-judge failure (`REPORT.md` §5.6): the harness discarded any judge verdict
that did not match the fact list byte-for-byte and scored each discarded miss as
*covered*, giving 86.4% perfect scores and chance-level accuracy over 9,777 decisions.
Re-scoring the same summaries with the same model under a corrected parser moves rank
correlation from -0.002 to +0.475. The representation effect is contribution four of
six, and §6.6 disclaims novelty on its direction.

**Coverage is measured deterministically.** `app/evaluation/oracle.py` scores against
parser-extracted facts with no model involved -- 10,062 fact-level decisions, under a
minute, reproducible. It runs on the live `/compare` endpoint alongside the LLM judge;
both are reported, because the oracle cannot credit paraphrase and the judge is
unreliable in both directions.

**Known measurement limits, all quantified, all open:**
- Ground truth is **51% npm dependency names** (600 of 1,184 facts). Endpoints are 238,
  class/service names 310.
- `database_entities`, `CALLS` and `RELATES_TO` are declared in the schema and **never
  populated** -- 0 edges across all 18 repos.
- **12 of 18 endpoint annotations are byte-identical to parser output.** One was
  confirmed wrong (`domain-driven-hexagon`, F1 corrected 1.00 -> 0.00), one confirmed
  right. The rest are unverified; treat endpoint F1 as an upper bound.

Run one generator at a time -- a 16GB laptop throttles under sustained multi-model load:

```bash
python -m app.evaluation.harness $(cat ../18_repo_urls.txt) \
  --models qwen2.5-coder:7b --judge-model gemma2:9b \
  --annotations-dir ./annotations --out clean_qwen.csv --sqlite study_clean.db
```

**The judge must not be one of the generators.** `run_scored_ablation()` now refuses
the run if it is, because self-judging reverses the ranking of representations
(`REPORT.md` §6.2). Note `.env.example` lists `gemma2:9b` as `OLLAMA_MODEL_DIVERSITY`,
so a dashboard set up from it collides with the default judge -- change one of the two
before running `/compare`.

**Blocked on team decisions, not code:**
- The 18-repo evaluation set is a *candidate* set (vetted and annotated in
  `backend/annotations/`), not yet ratified by the team. The 2 "held-back" repos
  (untouched by anyone until demo day, to prove genuine generalization) still
  haven't been chosen -- don't pick these yourself, and note the repos used for
  development/testing so far (`heroku/node-js-getting-started`,
  `nestjs/typescript-starter`, `lujakob/nestjs-realworld-example-app`,
  `osandadeshan/expressjs-restful-apis-demo`) are disqualified from the held-back
  set since they've already been extensively exercised.
- The "designated evaluation machine" (roadmap Section 1's Day-0 step, for
  response-time comparisons to be meaningful) -- the user designated this machine
  on 2026-08-11, but the batteries were then run on a different machine (an RTX 3050,
  4GB VRAM, under CPU offload -- `REPORT.md` §5.5.1), so confirm which machine counts
  before reporting latency figures. Token figures are hardware-independent and do not
  carry this caveat.
  Latency figures still need re-measuring under controlled conditions -- the
  existing ones come from chunked runs with varying thermal state.
- Related work (`docs/REPORT.md` §2) is deliberately an empty scaffold: it needs a
  genuine literature review. Do not populate it with unverified citations.
- Report drafting: `REPORT.md` is substantially written, but §2 Related Work is still
  an empty scaffold, and one citation in §6.6 (SE-Jury, arXiv 2505.20854) is cited for
  the opposite of what it argues -- it is a positive result about judge ensembles.
  Slides and demo rehearsal haven't started.
- The granite arm (`battery_v3`) is reported in `evaluation_results/GRANITE_ARM_RESULTS.txt`
  but appears nowhere in `REPORT.md`. Its replication table also compares main-study
  *oracle* scores against granite *judge* scores; oracle-to-oracle is the valid
  comparison and is tighter (dependency_graph 0.5765 vs 0.5768).

See `README.md`'s "Known limitations" and the two "Known gaps" sections (Express
parser, NestJS parser) for specific, real (not hypothetical) limitations already
identified -- check there before treating a gap you find as new.

## Commands

### Backend (Python / FastAPI)

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in Neo4j creds / Ollama host

pytest tests/ -v                                      # everything, including real network clone
pytest tests/ -v -m "not integration"                 # skip the network-dependent test
pytest tests/ -v -m "not integration and not neo4j"   # offline only, no infra needed at all
pytest tests/test_nestjs_parser.py -v                 # a single file
pytest tests/test_nestjs_parser.py::test_detects_nestjs -v   # a single test

uvicorn app.main:app --reload   # http://localhost:8000
```

`@pytest.mark.neo4j` tests connect to `bolt://localhost:7687` (override via
`NEO4J_TEST_URI`/`NEO4J_TEST_USER`/`NEO4J_TEST_PASSWORD`) and **skip silently** if
nothing is reachable there -- they are not offline by default, unlike most of the
suite. `POST /summarize`, `/diagram`, and `/compare` all need both a running Neo4j
and a running Ollama with models pulled (`ollama pull qwen2.5-coder:7b` etc.) to
actually succeed; `/analyze` only needs the parser, no infra.

### Frontend (Vite / React / TypeScript)

```bash
cd frontend
npm install
npm run dev      # http://localhost:5180 (pinned in vite.config.ts -- 5173 is often
                  # taken by other local projects on a shared dev machine)
npx tsc -b       # type-check (no separate lint/test script configured beyond this)
```

Every page has its own URL-input form and calls a real backend endpoint; visiting a
page without submitting (e.g. via the nav bar) shows fallback mock data instead, so
the shell is browsable with no backend running at all.

## Architecture

**Pipeline** (`backend/app/pipeline.py` is the single orchestration point --
FastAPI routes in `main.py` are thin wrappers around these functions):

```
GitHub URL
  -> acquisition/clone.py (shallow clone, size-limited)
  -> parsers/registry.py -> {express_parser.py | nestjs_parser.py} (tree-sitter)
  -> ParsedRepository (schemas/parser_schema.py -- the contract every parser emits
     and everything downstream consumes; a new parser only needs to populate this)
  -> graph/builder.py: write_parsed_repository() -- MERGEs into Neo4j, keyed on
     (repo_name, id) so multiple repos share one instance without id collisions
     (parser-generated ids like "mod_0" are only unique within one parse)
  -> context/builder.py: build_context() for dependency_graph/knowledge_graph
     variants (raw needs pipeline.py's own _read_raw_source(), read during a
     dedicated clone before cleanup -- build_context()'s Neo4j-only signature can't
     produce it)
  -> providers/ollama_provider.py: OllamaProvider -- one class all 3 comparison
     models run through, model choice is just an argument
  -> LLMResult (schemas/llm_result.py) -- JSON-parsed downstream in pipeline.py,
     not by the provider (see providers/base.py's docstring for why)
```

Three pipeline entrypoints, one per dashboard capability:
- `generate_repository_summary()` -> `POST /summarize` -- one model, one
  representation (knowledge_graph)
- `generate_repository_diagram()` -> `POST /diagram` -- no LLM, `graph/diagram.py`
  queries Neo4j directly and formats Mermaid text
- `run_scored_ablation()` -> `POST /compare` -- runs `run_representation_ablation()`
  (all 3 models x all 3 representations, `len(models) * 3` results; clones/parses/
  writes-to-graph once and reuses it across every model), then grades each
  successful result with two LLM-as-judge metrics: hallucination
  (`evaluation/hallucination.py`, precision-like -- are its claims true) and
  coverage (`evaluation/coverage.py`, recall-like -- how much of the parser's
  ground truth did it mention). That's up to 2 extra judge calls per result on top
  of the `len(models) * 3` generations.

**Parser registry order matters**: `NestJSParser` is checked before `ExpressParser`
in `parsers/registry.py` -- NestJS repos often list `express` directly too (their
default HTTP adapter via `@nestjs/platform-express`), which would otherwise let
`ExpressParser.detect()` misfire on a NestJS repo.

**Error handling in `main.py`**: two exception types map to specific HTTP statuses
(`AnalysisError` -> 400, `PipelineInfrastructureError` -> 503), and a global
`@app.exception_handler(Exception)` catches everything else. That handler sets
`Access-Control-Allow-Origin` **manually** rather than relying on `CORSMiddleware`
-- Starlette routes handlers registered for the bare `Exception` class to
`ServerErrorMiddleware`, which wraps `CORSMiddleware` from the outside, so the
middleware never gets a chance to add CORS headers to that response. Keep this in
mind if you add new global exception handling -- it's a genuine Starlette gotcha,
not specific to this codebase, and easy to reintroduce by accident.

**Frontend** (`frontend/src/`): `lib/api.ts` is the only place that talks to the
backend (one shared `postJson()` helper, one `ApiError` class, snake_case ->
camelCase mapping at the boundary). `lib/types.ts` mirrors backend enums
(`ContextVariant`, the 3 model names) so the two ends agree on shape without a
shared package. Each page in `pages/` falls back to `lib/mockData.ts` when there's
no real result yet (no route-state passed in), which is what keeps the dashboard
browsable without any backend running.

**Extending the system:**
- New framework parser: subclass `BaseParser` in `app/parsers/`, implement
  `detect()`/`parse()`, register in `app/parsers/registry.py`.
- New LLM provider: subclass `BaseLLMProvider` in `app/providers/`, implement only
  `_call_model()` and `estimate_cost()` -- retry/latency/result-construction is
  inherited.

## Local dev environment notes

Ollama model choice is machine-dependent: the roadmap's 3 models are Qwen2.5-Coder
7B, Llama 3.1 8B, and gpt-oss:20b, but gpt-oss:20b needs ~13GB+ RAM just for the
model -- on a 16GB machine, substitute Mistral 7B (`ollama pull mistral:7b`) instead
and set `OLLAMA_MODEL_DIVERSITY=mistral:7b` in `.env`. Check available RAM before
assuming the default works. Similarly, if the machine has been used for other
Docker projects, `docker system df` before assuming there's disk space free for
Neo4j + the ~14GB of Ollama models -- stale build cache/dangling images are usually
the actual problem, not a real shortage (`docker image prune -a` / `docker builder
prune -a` are safe: they don't touch anything referenced by a running or stopped
container, or any volume).
