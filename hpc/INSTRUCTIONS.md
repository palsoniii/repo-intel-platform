# HPC Instructions — repo-intel-platform final scaling run

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
cd /path/to/repo-intel-platform/backend
python -m scripts.build_context_pack $(cat ../18_repo_urls.txt) \
    --out ../context_pack.json
```

The resulting `context_pack.json` is ~5–10 MB. Upload it to the cluster in
Step 3 alongside the repo zip.

---

## Step 2 — PORTAL: build the saved cluster image (one-time setup)

> Skip to Step 3 if you already have a saved `repo-intel-gpu` image with all
> models pulled. Check via **Altair Access → My Images**.

**Submit a Jupyter job:**

| Field | Value |
|---|---|
| Application | Jupyter |
| Container Image | `pytorch_pbs:25.12-py3` |
| Number of Nodes | 1 |
| Number of Processors per Node | **8** |
| Number of GPUs per Node | **1** |
| Amount of Memory (MB) | **32000** |
| Queue | `workq` |

Open the notebook `hpc/00_setup_gpu_image.ipynb` from inside the Jupyter
session and run all cells **in order**:

1. **Section 1** — confirms GPU/RAM/network. Read the output before continuing.
2. **Section 2** — installs Ollama (needs GitHub; use the fallback cell if blocked).
3. **Section 3** — uploads/clones the project and installs Python deps.
4. **Section 4** — pulls all models onto `/data/$USER/ollama/`.
   - Pulls generators: `codellama:13b-instruct`, `qwen2.5-coder:14b`, `qwen2.5-coder:32b`
   - Pulls primary judge: `gemma2:9b`
   - Pulls secondary judges: `mistral:7b-instruct`, `gemma2:27b`
   - This cell takes 20–40 minutes if pulling ~55 GB cold.
5. **Section 5** — smoke test with `qwen2.5-coder:14b`. Must print `OK` and show
   GPU memory in use. If GPU memory stays near 0, the model is on CPU — stop and
   investigate before proceeding.
6. **Section 6** — save the container as `repo-intel-gpu` via **Custom Actions
   → Save Docker Container**. Set Working Directory to `/data`.

---

## Step 3 — PORTAL: upload files

In Altair Access, use **+Upload** to copy these files into `/data/$USER/`:

- `context_pack.json` (built in Step 1)
- `repo-intel-platform.zip` (or clone via git if GitHub is reachable)

Unzip if needed:

```bash
unzip /data/$USER/repo-intel-platform.zip -d /data/$USER/
```

---

## Step 4 — PORTAL: submit the three battery jobs

Submit `hpc/run_battery.sh` **three times**, once per generator. Use
**Applications → Batch or Shell Script**.

**Form fields (same for all three jobs):**

| Field | Value |
|---|---|
| Container Image | `repo-intel-gpu` |
| Number of Nodes | 1 |
| Number of Processors per Node | **8** |
| Number of GPUs per Node | **1** |
| Amount of Memory (MB) | **32000** |
| Queue | `workq` |
| Job Script | `run_battery.sh` |

**Job Script Arguments** — change this for each of the three submissions:

| Submission | Job Script Arguments |
|---|---|
| 1st | `codellama:13b-instruct` |
| 2nd | `qwen2.5-coder:14b` |
| 3rd | `qwen2.5-coder:32b` |

Each job writes to `/data/$USER/evaluation_results/`:
- `battery_codellama13b.{csv,db}`
- `battery_qwen14b.{csv,db}`
- `battery_qwen32b.{csv,db}`

Existing `battery.db`, `battery_v2.db`, and all prior output files are **never
touched** by this job.

Expected wall time per job: ~1–3 hours depending on MIG slice allocation.

---

## Step 5 — LOCAL: download battery results

Once all three jobs show status **Completed**, download from `/data/$USER/evaluation_results/`:

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

Place all `.db` and `.csv` files in `backend/evaluation_results/` locally.

---

## Step 6 — PORTAL: submit the two rejudge jobs

Submit `hpc/run_rejudge.sh` **twice**, once per secondary judge. Same form
fields as Step 4.

**Job Script Arguments** — change for each submission:

| Submission | Job Script Arguments |
|---|---|
| 1st | `mistral:7b-instruct` |
| 2nd | `gemma2:27b` |

Each job reads the three battery DBs from Step 4, runs the secondary judge
over every stored summary, and writes:

```
rejudge_mistral__7b-instruct_battery_codellama13b.{csv,db}
rejudge_mistral__7b-instruct_battery_qwen14b.{csv,db}
rejudge_mistral__7b-instruct_battery_qwen32b.{csv,db}
rejudge_gemma2__27b_battery_codellama13b.{csv,db}
rejudge_gemma2__27b_battery_qwen14b.{csv,db}
rejudge_gemma2__27b_battery_qwen32b.{csv,db}
```

> The rejudge job requires the battery DBs to already be in `$OUT_DIR`.
> If a battery DB is missing the job prints a WARNING and skips that arm;
> if all three are missing it exits with FATAL.

Expected wall time: 2–5 hours per job.

---

## Step 7 — LOCAL: download rejudge results

Download all `rejudge_*.{csv,db}` files from `/data/$USER/evaluation_results/`
into `backend/evaluation_results/`.

---

## Step 8 — LOCAL: run the master report

From `backend/`:

```bash
cd /path/to/repo-intel-platform/backend
python -m scripts.build_paper_report
```

Output: `evaluation_results/PAPER_REPORT.md` and per-table CSVs alongside it.

The script runs cleanly even if rejudge results are not yet downloaded — those
table cells print `PENDING — awaiting cluster run` and the rest of the report
is complete. Re-run after downloading rejudge results to fill them in.

---

## Step 9 — LOCAL: export the human-validation sample

```bash
cd /path/to/repo-intel-platform/backend
python -m scripts.export_human_validation
```

Output: `evaluation_results/human_validation_sample_final.csv` — N=40,
fixed seed=42, stratified across model × representation cells, with blank
`human_coverage_verdict`, `human_hallucination_verdict`, and `notes` columns
for the hand-scorer to fill in.

This does **not** overwrite the existing `human_validation_sample.csv`
(drawn from the old Run 2 data).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Battery job exits with `FATAL: model not in $OLLAMA_MODELS` | Re-run Step 2 (save the image after pulling models); the saved image bakes in Ollama + deps but **not** the model weights — those live on `/data`. If `/data` was wiped, re-pull. |
| Smoke test shows GPU memory near 0 | Ollama is not using the GPU. Check that `nvidia-smi` sees the device and that Ollama's CUDA runtime matches the driver. |
| Rejudge job says `WARNING: battery_X.db not found` | The battery job for that arm hasn't finished yet or its output wasn't uploaded. Finish/upload it and resubmit the rejudge job. |
| `build_paper_report.py` shows all new tables as PENDING | The new battery DBs are not yet in `evaluation_results/`. Download them from the cluster first. |
| `qwen2.5-coder:32b` pull fails / tag not found | Check `https://ollama.com/library/qwen2.5-coder` for the exact tag. Do **not** substitute `qwen3-coder:30b`. |
