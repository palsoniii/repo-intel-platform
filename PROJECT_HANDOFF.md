# repo-intel-platform — full handoff

> ## ⚠️ Superseded in three places (2026-08-29)
>
> 1. **The branch table and "push to `battery-followup`" are dead.** That branch no
>    longer exists locally or on the remote. Everything it held — along with
>    `god_saviour`, `dishank`, `anjali` and `eval-annotations` — is merged into
>    **`main`**, which is the branch to work on and push to. Every commit this document
>    tells you to cherry-pick (`884baad`, `3574290`, `38ed0a6`, `b61b290`) is already an
>    ancestor of `main`.
> 2. **`granite-code:8b-instruct` was NOT "downloaded, never used".** It ran as a
>    *writer* — `battery_v3_granite_gemma2judge.db`, 54 rows / 53 successful across 18
>    repos, judged by `gemma2:9b` (commit `5808f5f`). Task 4 below describes granite as a
>    prospective second *judge*; that is not what happened.
> 3. **Task 3 (human validation) is superseded, not outstanding.** The 24-row human
>    sample was replaced by 10,062 deterministic fact-level decisions from
>    `app/evaluation/oracle.py` — `REPORT.md` §7.1.
>
> The machine notes, model footprints, Docker/WSL setup and the deepseek diagnosis below
> remain accurate and useful.

Written for an agentic AI picking this project up cold. Everything here is verified
against the machine and the repository, not recalled. Dates are 2026.

---

## 1. What the project is

**Research question.** Given a fixed repository, a fixed model and a fixed prompt,
does supplying a more *structured* representation of the repository produce a more
factually faithful and more complete summary — and at what cost in latency and input
tokens?

**Method.** A pipeline clones a JavaScript/TypeScript web-service repo, parses it
statically with tree-sitter, materialises the parse as a Neo4j graph, and renders
**three representations from the same parse**:

| Representation | What the model receives |
|---|---|
| `raw` | Concatenated source text, truncated to 24,000 chars |
| `dependency_graph` | Module/import structure only |
| `knowledge_graph` | Full structural digest: modules, classes, endpoints, deps, config |

The representation is the **independent variable**. Models are a control dimension —
they exist to show the effect isn't one model's quirk, not because model comparison is
the point.

**Scoring.** An LLM-as-judge checks each summary against **parser-extracted ground
truth**, not a human-written gold summary. Two measures:

- `coverage_score` (0–1) — of the facts the parser found, how many did the summary mention
- `hallucination_score` (0–1, lower better) — of the summary's specific claims, how many are unsupported

Also collected: latency, input/output tokens, BLEU-4 / ROUGE-L / METEOR against
reference summaries, diagram graph-diff F1.

**Dataset.** 18 public repos (9 Express, 9 NestJS), listed in `18_repo_urls.txt` at
repo root. Hand-written annotations in `backend/annotations/` (18 files) and reference
summaries in `backend/reference_summaries/` (18 files).

**Context.** Undergraduate capstone. Deliverables are `docs/REPORT.md` and a paper.

---

## 2. Repository and branches

**`https://github.com/palsoniii/repo-intel-platform`**

| Branch | Head | Meaning |
|---|---|---|
| `main` | `b61b290` | baseline |
| `dishank` | `3574290` | upstream dev branch; parser fixes + Tier-0 metrics originate here |
| **`battery-followup`** | **`884baad`** | **CURRENT WORKING BRANCH — push here** |
| `god_saviour` | `38ed0a6` | Run-1 results live here; created earlier in the project |
| `anjali`, `eval-annotations` | — | other people's branches, untouched |

**Push to `battery-followup`.** Do not push to `dishank` or `main`.

### Commits made during this work

On `battery-followup`:
- `e3bdf5d` — Ollama request timeout + created missing `18_repo_urls.txt`
- `550e57a` — Run-2 results (162 rows) + `human_validation_sample.csv`
- `884baad` — replaced dropped deepseek with gemma2 in UI/config; fixed dashboard self-judging

On `god_saviour`:
- `3063497` — Run-1 results (108 rows) + REPORT.md §5.5
- `38ed0a6` — improved §5.5.1 deepseek diagnosis

> **Important:** `god_saviour` is NOT merged into `battery-followup`
> (`git merge-base --is-ancestor` returns false). `battery-followup` carries an
> **older** §5.5.1 (says "two independent attempts"). The better version — three
> attempts, footprint table, thermals ruled out — is only on `god_saviour`.
> Retrieve with: `git show 38ed0a6:docs/REPORT.md`

---

## 3. The machine

Windows 11, user `Krishna Shetty`. **The Claude session has no admin rights.**

| | |
|---|---|
| GPU | NVIDIA RTX 3050 Laptop, **4096 MiB VRAM (~3.4 GB usable)**, driver 592.00, CUDA 13.1 |
| System RAM | 15.6 GB |
| WSL | Ubuntu-24.04, runs as **root with passwordless sudo**, systemd enabled |
| WSL limits | 10 GB memory cap, 8 GB swap, 16 CPUs (set in `C:\Users\Krishna Shetty\.wslconfig`) |
| Docker | **Docker Engine 29.7.2 + Compose v5.5.0 installed INSIDE WSL** — not Docker Desktop |
| NVIDIA Container Toolkit | installed in WSL; GPU passthrough verified inside containers |

**Docker Desktop is not used and previously failed to start on this machine.** Do not
try to install it — the session has no admin rights and it is not needed.

### Two working trees — this trips people up

| Path | Purpose |
|---|---|
| `/root/repo-intel-platform` (WSL) | **The real working tree.** Docker runs here. All batteries execute from here. |
| `C:\Users\Krishna Shetty\repo-intel-platform` | **Push from here.** Git Credential Manager works on Windows; WSL's GitHub connection is unreliable. |

**WSL→GitHub is intermittently broken.** A `git clone` in WSL once managed 124 KB in
five minutes, and a mid-run collapse cost 27 rows. Workflow that works: fetch/clone on
Windows, then sync into WSL via a local remote:

```bash
cd /root/repo-intel-platform
git remote add win "/mnt/c/Users/Krishna Shetty/repo-intel-platform"
git fetch win && git checkout -B battery-followup win/battery-followup
git config core.autocrlf false && git reset --hard HEAD   # kills CRLF noise
```

---

## 4. Models on disk (in the Docker volume `repo-intel-platform_ollama_models`)

| Model | Size | Org | Type | Role |
|---|---|---|---|---|
| `qwen2.5-coder:7b` | 4.7 GB | Alibaba | code | writer |
| `codellama:7b-instruct` | 3.8 GB | Meta | code | writer |
| `gemma2:9b` | 5.4 GB | Google | general | Run-1 **judge**, Run-2 **writer** |
| `mistral:7b-instruct` | 4.4 GB | Mistral AI | general | Run-2 **judge** |
| `granite-code:8b-instruct` | 4.6 GB | IBM | code | **downloaded, never used** — Task 4 judge |
| `deepseek-coder:6.7b-instruct` | 3.8 GB | DeepSeek | code | **UNUSABLE — see below** |

### Measured resident footprints at `num_ctx=8192` (from `ollama ps`)

| Model | Resident | CPU/GPU split |
|---|---|---|
| qwen2.5-coder:7b | 5.4 GB | 58% / 42% |
| mistral:7b-instruct | 5.6 GB | 60% / 40% |
| gemma2:9b | 6.4 GB | 69% / 31% |
| **deepseek-coder:6.7b-instruct** | **8.3 GB** | 73% / 27% |

**Why deepseek is excluded — do not retry it.** It needs 8.3 GB resident despite having
*fewer* parameters than qwen; its KV cache at 8192 tokens dominates. Against a 9.7 GB
container budget with `OLLAMA_MAX_LOADED_MODELS=1` forcing full evict-and-reload on
every writer↔judge swap, each transition moves ~15 GB through 9.7 GB. Host swap was in
active use. Three attempts stalled at repo 13, then 12, then 11 — progressively earlier.
GPU thermals (53 °C, all `nvidia-smi` slowdown flags inactive) and host RAM were
explicitly ruled out. Lowering `num_ctx` would fix it but break comparability with the
other models. **This is a hardware limit of this machine, not a model defect.**

---

## 5. The two runs and their results

### Run 1 — `battery.db` (on `god_saviour`)

- Writers: `qwen2.5-coder:7b`, `codellama:7b-instruct`
- Judge: `gemma2:9b`
- **108 rows, 108 successful**
- Result: **structured context beat raw on coverage**, dependency_graph vs raw
  p=0.0003 (codellama), p=0.0023 (qwen), 3–4× improvement
- Faithfulness: **null** — nothing significant, direction reversed between models

### Run 2 — `battery_v2.db` (on `battery-followup`)

- Writers: `qwen2.5-coder:7b`, `codellama:7b-instruct`, `gemma2:9b`
- Judge: `mistral:7b-instruct`
- **162 rows, 157 successful**

Coverage means (mistral judge):

| Model | dependency_graph | knowledge_graph | raw |
|---|---|---|---|
| codellama:7b-instruct | 0.8917 | 0.9893 | 0.9558 |
| gemma2:9b | 0.7587 | 0.7933 | **1.0000** (CI [1.0, 1.0]) |
| qwen2.5-coder:7b | 0.8904 | 0.9690 | 0.8409 |

Only significant paired comparisons — **both favour raw**:
- gemma2, dependency_graph vs raw: p=0.0273
- gemma2, knowledge_graph vs raw: p=0.0178

Faithfulness means: 0.24–0.39 across all cells, **nothing significant** — replicates
Run 1's null.

The 5 failures, all timeout-killed generations on the largest NestJS repos:
```
ack-nestjs-boilerplate / codellama / dependency_graph
ack-nestjs-boilerplate / gemma2    / dependency_graph
ack-nestjs-boilerplate / gemma2    / knowledge_graph
ack-nestjs-boilerplate / qwen      / raw
nestjs-boilerplate     / gemma2    / dependency_graph
```

---

## 6. THE CRITICAL FINDING — the "wrong output"

**The mistral judge is degenerate for coverage.**

```
coverage_score == 1.00   →  133 of 157 rows  (85%)
empty missing_facts_list →  136 of 157 rows
gemma2/raw               →  mean 1.0, CI [1.0, 1.0]  across all 18 repos
```

mistral finds **zero missing facts in 85% of summaries**. A perfect score with zero
variance across 18 different repositories is not a measurement — it is a judge with no
discriminative power.

**Consequently the coverage conclusion inverts between the two runs:**

| Judge | Conclusion |
|---|---|
| gemma2:9b (Run 1) | structured beats raw, 3–4×, p=0.0003 |
| mistral:7b-instruct (Run 2) | saturates at 1.0; where significant, **raw wins** |

Same summaries. Same repos. Same prompts. **Only the judge changed.**

### How to treat this

- **DO NOT report Run 2's coverage numbers as a representation effect.** They measure
  the judge, not the representations.
- **DO report the judge disagreement as the headline finding.** It is a real,
  publishable result about LLM-as-judge methodology — a warning for a technique the
  field increasingly relies on without validation. It is stronger and more original
  than "graphs beat raw code" would have been.
- `docs/REPORT.md` §6.1 already documents judge sensitivity from an earlier
  self-judging incident. This is the same phenomenon, far more starkly.
- The faithfulness null replicates across both judges and **is** safe to report.

---

## 7. Other real problems found

**Raw-arm truncation confound (unresolved, must be disclosed).**
`DEFAULT_MAX_RAW_CHARS = 24000` in `backend/app/pipeline.py`. The raw arm sees ~24k
chars (~600 lines); the structured arms receive a digest of the *entire* repo. Coverage
counts facts from the whole repo, so raw literally cannot mention what it never saw —
for `ack-nestjs-boilerplate` (601 modules) it sees a tiny fraction. **The coverage
result is partly measuring truncation.** Mitigation without new runs: reframe around
`coverage_per_1k_input_tokens` (already implemented in `stats.py`), which normalises for
input budget, and report what fraction of each repo the raw arm actually saw.

**Dashboard was self-judging (FIXED in `884baad`).** `compareModels` in
`frontend/src/lib/api.ts` sent `{url, models}` with no `judge_model`, so the backend fell
back to `provider.default_model` = `qwen2.5-coder:7b` — itself a writer. Every dashboard
comparison graded qwen with qwen. Now sends `mistral:7b-instruct` as
`DEFAULT_JUDGE_MODEL`. **Any `/compare` results that reached slides or the report were
self-judged and need regenerating.**

**Very large repos break every model.** `ack-nestjs-boilerplate` (601 modules) hung
deepseek, stalled qwen twice, and cost codellama and gemma2 rows. Reproducible across
four models — report as a genuine limitation of local 7–9B models at `num_ctx=8192`.

**Writer-set heterogeneity (unplanned).** Two writers are code-specialised (qwen-coder,
codellama), one is general-purpose (gemma2). gemma2 only became a writer because
deepseek failed. With n=1 general-purpose model you cannot separate model identity from
model type — and gemma2 is the model whose results diverge most. Disclose in Threats to
Validity.

**Word-overlap metrics are useless here.** BLEU-4 ≈ 0.015 with no signal. Worth
reporting as a negative result justifying the fact-checking approach.

---

## 8. Code changes made

### Committed

| Change | File | Commit |
|---|---|---|
| Request timeout, `timeout: float = 900.0`, env `OLLAMA_TIMEOUT_S` | `backend/app/providers/ollama_provider.py` | `e3bdf5d` |
| Created the 18-URL list (Task 1's command reads it but it didn't exist) | `18_repo_urls.txt` | `e3bdf5d` |
| UI model list deepseek → gemma2:9b | `frontend/src/lib/types.ts` | `884baad` |
| Dashboard sends independent judge | `frontend/src/lib/api.ts` | `884baad` |
| `OLLAMA_MODEL_DIVERSITY` deepseek → gemma2:9b | `docker-compose.yml`, `backend/.env.example` | `884baad` |
| §5.5.1 deepseek diagnosis rewrite | `docs/REPORT.md` | `38ed0a6` (**god_saviour only**) |

The timeout fix is load-bearing: gemma2 hit 3 wedged calls in Run 2 and recorded them
as failures instead of hanging, preserving its other 48 rows.

### Deliberately NOT committed — machine-specific, lives only in the WSL tree

`docker-compose.yml` in `/root/repo-intel-platform` additionally carries:

```yaml
  ollama:
    environment:
      OLLAMA_MAX_LOADED_MODELS: "1"     # writer and judge never co-resident
      OLLAMA_NUM_PARALLEL: "1"
    sysctls:
      - net.ipv6.conf.all.disable_ipv6=1
    deploy:
      resources:
        reservations:
          devices: [{driver: nvidia, count: all, capabilities: [gpu]}]
  neo4j:
    environment:
      NEO4J_server_memory_heap_max__size: 512m
      NEO4J_server_memory_pagecache_size: 512m
```

**The GPU block must not be committed** — it breaks `docker compose up` on any machine
without an NVIDIA runtime. **But it is silently lost on every branch switch**, which
already caused one regression where a run went 100% CPU. **Re-apply and verify after any
checkout:**

```bash
docker exec repo-intel-platform-ollama-1 nvidia-smi   # must list the GPU
docker exec repo-intel-platform-ollama-1 ollama ps    # must show a CPU/GPU split, not 100% CPU
```

### Also critical: the container bakes in application code

`docker-compose.yml` mounts only `evaluation_results`, `annotations` and
`reference_summaries`. **Application code is copied at build time.** After any code
change or branch switch you MUST rebuild, or you silently run stale code:

```bash
docker compose build backend && docker compose up -d --force-recreate backend
```

This was caught once — the container had **zero** of the parser fixes while the working
tree had them all.

---

## 9. Judge API — get this right, the first attempt was wrong

```python
from app.evaluation.hallucination import score_summary      # NOT score_hallucination
from app.evaluation.coverage import score_coverage
from app.providers.ollama_provider import OllamaProvider

score_summary(provider, parsed, summary_text, context_variant, judge_model=...)
    # -> .hallucination_score, .total_claims, .unsupported_claims
score_coverage(provider, parsed, summary_text, context_variant, judge_model=...)
    # -> .coverage_score, .total_facts, .missing_facts
```

Both take **provider first**. `parsed` comes from `app.pipeline.analyze_repository(url)`
— cache it per repo (18 parses, not 157).

`battery_v2.db` persists `summary_text`, `unsupported_claims_list`,
`missing_facts_list`, `facts_by_category`, so **re-judging needs no regeneration**.

---

## 10. Outstanding tasks

**Task 3 — human validation. HIGHEST VALUE. Needs a human, not an AI.**
`backend/evaluation_results/human_validation_sample.csv` — 24 rows, already generated
and committed, with summary text, both judge scores, and the specific claims flagged.
Columns `human_verdict` and `human_notes` are empty. A person reads each summary against
the real repo and fills them in; then compute percent agreement or Cohen's kappa.
**This is the only way to determine which judge, if either, tracks human judgement** —
and with two judges contradicting each other, the conclusions rest on it.

**Task 4 — granite second judge. Script ready, never run.**
`/root/task4_granite.py` (also at `C:\Users\Krishna Shetty\task4_granite.py`), rewritten
against the verified API above. Re-judges Run 2's stored summaries with
`granite-code:8b-instruct`. No regeneration; ~1–2 hours. It prints the granite coverage
distribution at the end. **If granite discriminates like gemma2, mistral is the outlier.
If granite also saturates near 1.0, the coverage PROMPT is too lenient rather than the
judge.** Either answer resolves the central ambiguity.

**Task 5 — confirm parser fixes.** Compare `dependency_graph`/`knowledge_graph` input
sizes in `battery_v2.db` against the old `battery.db` (kept at
`/root/old_run_artifacts/battery.db`). Richer counts confirm the ES-module, path-alias
and mount-chain fixes recovered edges.

**Task 6 — cross-hardware spot-check. BLOCKED — needs a second physical machine.**

**Task 7 — Tier-0 metrics. DONE**, output in
`backend/evaluation_results/BATTERY_V2_RESULTS.txt`
(`add_coverage_efficiency`, `category_coverage_breakdown`, `diagram_f1_report`).

**Report work.** Rewrite §5.5 for the Run-2 design (3 writers + mistral, new row counts).
Port the improved §5.5.1 from `god_saviour`. Lead with judge sensitivity rather than
burying it in Threats to Validity.

### A design change under consideration (not yet done)

All-code writers + general-purpose judge, buildable entirely from models already on disk:

| Role | Model |
|---|---|
| Writers | qwen2.5-coder:7b, codellama:7b-instruct, **granite-code:8b-instruct** |
| Judge | mistral:7b-instruct |
| Second judge | gemma2:9b (returns to judging) |

Removes the writer-heterogeneity confound and gives two judges by design. Costs a full
re-run (10–12 h) and granite's resident footprint is unverified. **Recommended only
after Task 3.**

---

## 11. Operational gotchas that cost real hours

1. **WSL shuts its VM down when idle**, killing every background job within ~12 s of the
   last command. `vmIdleTimeout=-1` in `.wslconfig` did NOT prevent it. **The fix that
   works** is a persistent Windows-side keepalive:
   ```powershell
   Start-Process wsl.exe -ArgumentList "-d","Ubuntu-24.04","-e","sleep","infinity" -WindowStyle Hidden
   ```
   It dies on reboot and must be restarted, or long runs silently stall.

2. **Sleep timeouts killed a 12-hour download.** Fixed with
   `powercfg /change standby-timeout-ac 0` (needs an admin terminal — the user must run
   it). Verify: `powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE` → want `0x00000000`.

3. **Corrupt partial Ollama blobs cause `Error: EOF`** that looks exactly like a network
   failure. Diagnosis: a tiny model (`smollm:135m`) pulls fine while the target fails.
   Fix: `find <volume>/models/blobs -name '*partial*' -delete`.

4. **`pkill -f "pattern"` matches its own command line.** This killed the wrong process
   three separate times. Use the bracket trick: `pkill -f "app[.]evaluation[.]harness"`.

5. **`grep -q "MARKER"` in a log the script also writes to matches its own message.**
   Fired an analysis chain hours early. Anchor it: `grep -qE "^===== MARKER"`.

6. **The harness writes CSV and SQLite only when a model FINISHES.** Never run multiple
   models in one invocation — one wedge discards everything. **One model per invocation,
   appending to the same `--sqlite` file.**

7. Docker Hub timeouts on large layers: `max-concurrent-downloads: 2` and
   `max-download-attempts: 10` in `/etc/docker/daemon.json` (merge — the NVIDIA runtime
   entry is already there).

---

## 12. Helper scripts already on the machine

In WSL `/root/`, mirrored at `C:\Users\Krishna Shetty\`:

| Script | Does |
|---|---|
| `eval_status.sh` | full status dump — start here |
| `resume_battery.sh` / `pause_battery.sh` | restart or stop all automation; safe to re-run |
| `run_battery_v2.sh` | the Run-2 battery, one model per invocation, stall watchdog |
| `complete_v2.sh` | fills gaps, probes GitHub before committing to a run |
| `post_battery_v2.py` | Tasks 2/3/5/7 analysis → `BATTERY_V2_RESULTS.txt` |
| `task4_granite.py` | Task 4 re-judge (corrected API) |
| `finish_and_push.sh` | copy WSL results → Windows clone → commit → push |

Progress logs written to Windows paths, openable in Notepad:
`battery_v2_progress.log`, `v2_models_progress.log`, `BATTERY_V2_RESULTS.txt`.

---

## 13. Current state

- Full stack running in WSL: `neo4j`, `ollama`, `backend`, `frontend`
- Dashboard http://localhost:5180 · API docs http://localhost:8000/docs · Neo4j http://localhost:7474
- `battery-followup` at `884baad`, pushed, working tree clean apart from the deliberate
  local `docker-compose.yml` GPU edits
- All Run-2 results committed and on GitHub

### Known-stale, not yet fixed

- `backend/app/pipeline.py` lines 189–190 default to `llama3.1:8b` and `gpt-oss:20b` if
  env vars are unset — neither is downloaded. Harmless under compose, confusing outside it.
- `backend/tests/test_quality_judge.py` still names deepseek as a fixture judge (cosmetic, it's a mock).
