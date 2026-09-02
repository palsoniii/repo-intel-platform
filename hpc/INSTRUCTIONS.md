# HPC Instructions — repo-intel-platform final scaling run

**Altair Access portal**: `https://10.126.1.10:4443/`
**Cluster username**: `mpstme-dishank`
**Your persistent storage on the cluster**: `/data/mpstme-dishank/`

> **Security note**: Your password is never stored in this file or any file in
> this repository. Do not add it. Use the portal's login page directly.

Everything below is **step-by-step and in order**. Each step is labeled
**PORTAL** (done inside Altair Access, on the cluster) or **LOCAL** (done on
your own machine, off-cluster). Do not mix them up — the portal jobs have no
outbound internet to PyPI or GitHub during execution.

---

## Generator roster

| Model | Family | Size (Q4_K_M) | Role |
|---|---|---|---|
| `codellama:13b-instruct` | Meta | ~8 GB | Cross-org comparison anchor |
| `qwen2.5-coder:14b` | Alibaba | ~9 GB | Scale-matched vs codellama:13b |
| `qwen2.5-coder:32b` | Alibaba | ~20 GB | Two-point within-family check |
| `gemma2:9b` | Google | ~6 GB | **Sole primary judge** — never a generator |
| `mistral:7b-instruct` | Mistral AI | ~5 GB | Secondary judge (rejudge pass only) |
| `gemma2:27b` | Google | ~17 GB | Secondary judge (rejudge pass only) |

> **Do not substitute `qwen3-coder:30b` for `qwen2.5-coder:32b`.**
> They are different model families; swapping them breaks cross-run comparability.

---

## Step 1 — LOCAL: build the context pack

If you already have `context_pack.json` from a prior run, skip this step.
Otherwise, run from the repo root on your own machine:

```bash
cd /path/Downloads/repo-intel-platform/backend
python -m scripts.build_context_pack $(cat ../18_repo_urls.txt) \
    --out ../context_pack.json
```

> This step needs Neo4j running locally and a GitHub connection.
> It produces all three representations (raw / dependency_graph / knowledge_graph)
> and freezes them into `context_pack.json` — the cluster never needs Neo4j or
> GitHub after this point.

The resulting `context_pack.json` is ~5–10 MB. Upload it to the cluster in Step 3.

---

## Step 2 — PORTAL: one-time setup (install Ollama + pull models + warm pip cache)

> Skip to Step 3 if `/data/mpstme-dishank/ollama-dist/bin/ollama` already exists,
> all 6 models are in `/data/mpstme-dishank/ollama/`, and
> `/data/mpstme-dishank/site-packages/` is populated.

**Open the portal**: `https://10.126.1.10:4443/`
Log in as `mpstme-dishank`. Go to **Applications → Jupyter** and submit:

| Field | Value |
|---|---|
| Container Image | `pytorch_pbs:25.12-py3` |
| Number of Nodes | 1 |
| Number of Processors per Node | **8** (default is 1 — change it) |
| Number of GPUs per Node | **1** |
| Amount of Memory (MB) | **32000** (default is 10 MB — change it) |
| Queue | `workq` |

Open the notebook `hpc/00_setup_gpu_image.ipynb` from inside the Jupyter
session and run all cells **in order**:

1. **Section 1** — confirms GPU/RAM/network. Read the output before continuing.
2. **Section 2** — installs Ollama to `/data/mpstme-dishank/ollama-dist/`.
   Detects root vs non-root automatically.
3. **Section 3** — clones/uploads the project and installs Python deps.
4. **Section 4** — pulls all models onto `/data/mpstme-dishank/ollama/`.
   - Generators: `codellama:13b-instruct`, `qwen2.5-coder:14b`, `qwen2.5-coder:32b`
   - Primary judge: `gemma2:9b`
   - Secondary judges: `mistral:7b-instruct`, `gemma2:27b`
   - This cell takes 20–60 minutes pulling ~55 GB cold.
5. **Section 5** — smoke test with `qwen2.5-coder:14b`. Must print `OK` and show
   GPU memory in use. If eval rate is < 5 tok/s, the model is on CPU — restart
   `ollama serve` with the `LD_LIBRARY_PATH` fix (Section 5 diagnostic cell).
6. **Section 6** — pre-warms the pip package cache at
   `/data/mpstme-dishank/site-packages/`. Takes ~2 minutes on first run.

> **No "Save Container" step.** The portal does not allow custom images in batch
> jobs. Instead, battery and rejudge jobs use `pytorch_pbs:25.12-py3` directly
> and self-bootstrap from `/data/mpstme-dishank/` at start (~60 s overhead).

---

## Step 3 — PORTAL: upload files

Go to `https://10.126.1.10:4443/` → **+Upload** and copy these files into
`/data/mpstme-dishank/`:

- `context_pack.json` (built in Step 1)
- `repo-intel-platform.zip` (zip of the repo root, or clone via git if reachable)

Unzip if needed (run in a Jupyter terminal or Shell job):

```bash
unzip /data/mpstme-dishank/repo-intel-platform.zip -d /data/mpstme-dishank/
```

---

## Step 4 — PORTAL: submit the three battery jobs

Go to `https://10.126.1.10:4443/` → **Applications → Batch or Shell Script**.

Submit `hpc/run_battery.sh` **three times**, once per generator.

**Form fields (same for all three jobs):**

| Field | Value |
|---|---|
| Container Image | `pytorch_pbs:25.12-py3` |
| Number of Nodes | 1 |
| Number of Processors per Node | **8** |
| Number of GPUs per Node | **1** |
| Amount of Memory (MB) | **32000** |
| Queue | `workq` |
| Job Script | `run_battery.sh` (upload from `hpc/run_battery.sh`) |

**Job Script Arguments** — change this for each of the three submissions:

| Submission | Job Script Arguments | Output files |
|---|---|---|
| 1st | `codellama:13b-instruct` | `battery_codellama13b.{csv,db}` |
| 2nd | `qwen2.5-coder:14b` | `battery_qwen14b.{csv,db}` |
| 3rd | `qwen2.5-coder:32b` | `battery_qwen32b.{csv,db}` |

All output lands in `/data/mpstme-dishank/evaluation_results/`.
Existing `battery.db`, `battery_v2.db`, and all prior output files are **never
touched**.

Expected wall time per job: ~1–3 hours depending on MIG slice allocation.

---

## Step 5 — LOCAL: download battery results

Once all three jobs show **Completed** in the portal, download from
`/data/mpstme-dishank/evaluation_results/`:

```
battery_codellama13b.csv
battery_codellama13b.db
battery_qwen14b.csv
battery_qwen14b.db
battery_qwen32b.csv
battery_qwen32b.db
ollama_codellama13b.log    (latency reference)
ollama_qwen14b.log
ollama_qwen32b.log
```

Place all `.db` and `.csv` files in:

```
/path/Downloads/repo-intel-platform/backend/evaluation_results/
```

---

## Step 5.5 — LOCAL → PORTAL: upload the parse cache before rejudge

The rejudge jobs' parse phase calls `analyze_repository()`, which clones from
GitHub — and GitHub **may be blocked** on the cluster node.

All 18 parse-cache JSON files already exist locally. Upload them so the rejudge
parse phase finds every repo cached and skips cloning entirely.

**LOCAL** — zip the cache:

```bash
cd /path/Downloads/repo-intel-platform/backend
zip -r parse_cache.zip evaluation_results/parse_cache/
```

**PORTAL** — upload `parse_cache.zip` via **+Upload** into `/data/mpstme-dishank/`,
then unzip (Jupyter terminal or Shell job):

```bash
mkdir -p /data/mpstme-dishank/evaluation_results/parse_cache
unzip /data/mpstme-dishank/parse_cache.zip -d /data/mpstme-dishank/
# Result: /data/mpstme-dishank/evaluation_results/parse_cache/<18 .json files>
```

Without this step, the rejudge parse phase will attempt to clone 18 repos from
GitHub. If GitHub is unreachable, those rows will be skipped and rejudge output
will be empty.

---

## Step 6 — PORTAL: submit the two rejudge jobs

Go to `https://10.126.1.10:4443/` → **Applications → Batch or Shell Script**.

Submit `hpc/run_rejudge.sh` **twice**, once per secondary judge.

**Form fields (same for both jobs — identical to battery jobs):**

| Field | Value |
|---|---|
| Container Image | `pytorch_pbs:25.12-py3` |
| Number of Nodes | 1 |
| Number of Processors per Node | **8** |
| Number of GPUs per Node | **1** |
| Amount of Memory (MB) | **32000** |
| Queue | `workq` |
| Job Script | `run_rejudge.sh` (upload from `hpc/run_rejudge.sh`) |

**Job Script Arguments** — change for each submission:

| Submission | Job Script Arguments |
|---|---|
| 1st | `mistral:7b-instruct` |
| 2nd | `gemma2:27b` |

Each job reads the three battery DBs, re-scores all stored summaries with one
secondary judge, and writes six output files:

```
rejudge_mistral__7b-instruct_battery_codellama13b.{csv,db}
rejudge_mistral__7b-instruct_battery_qwen14b.{csv,db}
rejudge_mistral__7b-instruct_battery_qwen32b.{csv,db}
rejudge_gemma2__27b_battery_codellama13b.{csv,db}
rejudge_gemma2__27b_battery_qwen14b.{csv,db}
rejudge_gemma2__27b_battery_qwen32b.{csv,db}
```

> The rejudge job requires the three battery DBs to already be in
> `/data/mpstme-dishank/evaluation_results/`. If a DB is missing the job
> prints a WARNING and skips that arm; if all three are missing it exits FATAL.

Expected wall time: 2–5 hours per job.

---

## Step 7 — LOCAL: download rejudge results

Download all `rejudge_*.{csv,db}` files from
`/data/mpstme-dishank/evaluation_results/` into:

```
/path/Downloads/repo-intel-platform/backend/evaluation_results/
```

---

## Step 8 — LOCAL: run the master report

```bash
cd /path/Downloads/repo-intel-platform/backend
python -m scripts.build_paper_report
```

Output: `evaluation_results/PAPER_REPORT.md` and per-table CSVs alongside it.

The script runs cleanly even if rejudge results are not yet downloaded — those
table cells print `PENDING — awaiting cluster run`. Re-run after Step 7 to fill
them in.

---

## Step 9 — LOCAL: export the human-validation sample

```bash
cd /path/Downloads/repo-intel-platform/backend
python -m scripts.export_human_validation
```

Output: `evaluation_results/human_validation_sample_final.csv` — N=40,
fixed seed=42, stratified across model × representation cells, with blank
`human_coverage_verdict`, `human_hallucination_verdict`, and `notes` columns
for hand-scoring.

Does **not** overwrite the existing `human_validation_sample.csv` (old Run 2 data).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Can't reach `https://10.126.1.10:4443/` | You must be on the SVKM campus network or VPN. |
| Battery job exits `FATAL: model not in $OLLAMA_MODELS` | Models live on `/data/mpstme-dishank/ollama/` — not inside the image. If `/data` was wiped, re-pull via Step 2 Section 4. |
| Smoke test shows GPU memory near 0 | Ollama is not using the GPU. Check `nvidia-smi` output in Section 1. Try the fallback base image `pytorch_pbs:23.06-py3`. |
| Rejudge job: `WARNING: battery_X.db not found` | That battery arm hasn't finished yet or its DB wasn't uploaded to `/data/mpstme-dishank/evaluation_results/`. Complete Step 4–5 first. |
| Rejudge parse phase fails for all repos | Upload `parse_cache.zip` (Step 5.5) — GitHub is likely blocked on that node. |
| `build_paper_report.py` shows all new tables as PENDING | Download the battery `.db` files into `backend/evaluation_results/` first (Step 5). |
| `qwen2.5-coder:32b` pull fails / tag not found | Check `https://ollama.com/library/qwen2.5-coder`. Do **not** substitute `qwen3-coder:30b`. |
