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

**As of 2026-08-24** (dataset + metrics expansion for IEEE-publication readiness):
the evaluation dataset grew from 6 to **18 repositories** (9 Express, 9 NestJS,
hand-verified annotations + LLM-drafted reference summaries for all 18 --
`backend/annotations/README.md`), and five new evaluation modules were added --
`text_overlap.py` (BLEU-4/ROUGE-L/METEOR/BERTScore), `quality_judge.py` (G-Eval
rubric scoring), `calibration.py` (logprob-based confidence), `stats.py` (paired
Wilcoxon significance testing), `failure_analysis.py` (failure taxonomy) -- all
wired into the harness except `calibration.py` (needs a follow-up to expose the
generation prompt; runs standalone for now). Two more real Express parser bugs
were found and fixed while building the new annotations (see the Express parser's
Known gaps note below). 129 tests passing (16 skipped, live-infra-gated).
**Nothing in this expansion has been run against live Ollama/Neo4j yet** -- that
needs to happen on the designated evaluation machine before any new numbers go in
the paper; see `docs/REPORT.md` Appendix A for the run command.

As of the merge before that (branches `anjali` @ 2026-08-14 and `eval-annotations` @
2026-08-11 combined), all 8 build phases (Weeks 1-4) are done: both framework
parsers (Express parser now combines chained-route support from `anjali` with
mount-prefix resolution from `eval-annotations` -- see the Express parser's Known
gaps note below), the Neo4j graph builder, the context builder, the Ollama
orchestration layer, Mermaid diagram generation (rendered visually via mermaid.js,
not raw text), the 3-way representation ablation, the LLM-as-judge hallucination
scorer plus its companion coverage/recall scorer (`app/evaluation/coverage.py` --
how much of the parser's ground truth a summary actually mentions, not just
whether its claims are true), the diagram graph-diff scorer, the batch evaluation
harness, and all 4 dashboard pages wired to real backend endpoints -- all
validated against live infrastructure (not just mocks), not just unit tests.
`README.md`'s "What exists right now" section has the detailed, phase-by-phase log
of what was built, what broke, and what got fixed -- read that before assuming
something isn't implemented.

**The first full evaluation battery has been run** (54 rows: 3 models x 3
representations x 6 repos, zero failures) using `gemma2:9b` as an independent 4th
judge so no arm is self-judged. Results, methodology, and threats to validity are
in `backend/evaluation_results/RESULTS.md`; the report draft is `docs/REPORT.md`.

**Highest-priority task: re-run the battery.** That run predates the three parser
defect fixes merged from `eval-annotations` (see `docs/REPORT.md` §5.4a) --
most importantly a path-normalisation bug that silently dropped **every** internal
import edge, leaving the `dependency_graph` arm nearly empty -- *and* predates
`anjali`'s chained-route (`app.route(...).get(...)`) support being merged in, which
changes what the Express arm extracts too. The reported numbers are stale on both
counts. Both RESULTS.md and REPORT.md carry staleness banners; don't quote those
figures until the battery is regenerated.

Run one generator at a time -- this is a 16GB laptop that throttles under sustained
multi-model load:

```bash
python -m app.evaluation.harness <6 repo urls> --models qwen2.5-coder:7b \
  --judge-model gemma2:9b --annotations-dir ./annotations \
  --out clean_qwen.csv --sqlite study_clean.db
```

**Blocked on team decisions, not code:**
- The 6-repo evaluation set is a *candidate* set (vetted and annotated in
  `backend/annotations/`), not yet ratified by the team. The 2 "held-back" repos
  (untouched by anyone until demo day, to prove genuine generalization) still
  haven't been chosen -- don't pick these yourself, and note the repos used for
  development/testing so far (`heroku/node-js-getting-started`,
  `nestjs/typescript-starter`, `lujakob/nestjs-realworld-example-app`,
  `osandadeshan/expressjs-restful-apis-demo`) are disqualified from the held-back
  set since they've already been extensively exercised.
- The "designated evaluation machine" (roadmap Section 1's Day-0 step, for
  response-time comparisons to be meaningful) -- the user designated this machine
  on 2026-08-11, which also makes the Mistral-for-gpt-oss:20b substitution final,
  but confirm that still holds across the team before reporting latency figures.
  Latency figures still need re-measuring under controlled conditions -- the
  existing ones come from chunked runs with varying thermal state.
- Related work (`docs/REPORT.md` §2) is deliberately an empty scaffold: it needs a
  genuine literature review. Do not populate it with unverified citations.
- Report drafting (methodology/related-work were supposed to start in Week 3;
  results/discussion needs the evaluation battery above), slides, and demo
  rehearsal haven't started.

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
