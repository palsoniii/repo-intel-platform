# Project & Environment Handover Context

Welcome, incoming agent! This document contains critical context regarding the HPC environment, recent bug fixes, and execution strategies for the `repo-intel-platform` project.

## 1. The Altair Portal & HPC Environment
The user runs jobs via an **Altair Access PBS Portal**.
* **Storage Separation:** The user's home directory (`~/pbs.XXXXXX...`) is volatile/ephemeral depending on the job. All persistent data, models, and outputs **MUST** be stored on the data drive: `/data/mpstme-dishank/`.
* **Portal "Terminate" vs Terminal Disconnect:** If the user clicks "Terminate" on the Altair web portal, the PBS scheduler forcefully kills the entire compute allocation (all processes, including backgrounded ones). However, closing the browser tab/SSH terminal is safe *if* processes are launched with `nohup ... &` and `disown`.
* **Ollama Installation:** Ollama is NOT installed system-wide. It is installed manually on the data drive.
  * **Binaries:** `/data/mpstme-dishank/ollama-dist/bin`
  * **CUDA Libs:** `/data/mpstme-dishank/ollama-dist/lib/ollama`
  * **Models:** `/data/mpstme-dishank/ollama` (Passed via `OLLAMA_MODELS` env var).
* **GPU Hardware:** NVIDIA H100 (often partitioned via MIG, giving ~40GB VRAM). The cluster container restricts `nvidia-smi` access, so GPU checks often print `[Insufficient Permissions], [N/A]`. **This is a false alarm.** Ollama successfully detects and uses the GPU (verified by >1000 tokens/s prompt evaluation rates).

## 2. Recent Errors & Resolutions (Yesterday & Today)

### A. Python Version Mismatch (Pydantic Core Crash)
* **Error:** `ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'` during `harness.py` execution.
* **Cause:** `run_battery.sh` installs Python dependencies via `pip install -t /data/mpstme-dishank/site-packages`. Because this is a persistent directory, if a previous interactive job used Python 3.12 and the current job uses Python 3.10, the pre-compiled C-extensions (like `pydantic_core.cpython-312.so`) become unreadable, causing instant crashes.
* **Fix:** We deleted the directory (`rm -rf /data/mpstme-dishank/site-packages`) to force `run_battery.sh` to download fresh wheels matching the current Python 3.10 kernel.

### B. Ollama "Command Not Found"
* **Error:** When opening a new interactive terminal, `ollama` commands fail.
* **Cause:** The custom `PATH` and `LD_LIBRARY_PATH` set by the setup Jupyter Notebook are lost in fresh terminal sessions.
* **Fix:** Manually re-export the variables pointing to `/data/mpstme-dishank/ollama-dist/...` before running manual smoke tests. (Note: `run_battery.sh` handles this automatically internally).

### C. The 900s Timeout Fix (Token Budgeting)
* **Error:** `qwen2.5-coder:32b` was hitting hard timeouts (900s) on `ack-nestjs-boilerplate`.
* **Cause:** The structured contexts (`dependency_graph` and `knowledge_graph`) were uncapped. For `ack-nestjs-boilerplate` (601 modules), this resulted in ~190,000 characters being stuffed into the prompt, breaking the 32B model. Smaller models survived purely because Ollama silently truncated them.
* **Fix:** We wrote a shared `token_budget.py` and implemented tiktoken-based truncation in `builder.py`. The `knowledge_graph` now drops excess modules/endpoints and safely inserts omission markers (`... N more modules omitted`) if it exceeds the ~6065 token budget. The `context_pack.json` was rebuilt successfully.

### D. VRAM OOM on Rejudge
* **Error:** Running the 32B generator and the 27B judge simultaneously causes the 40GB H100 to run out of memory (OOM).
* **Fix:** We modified the execution strategy to run sequentially.

## 3. Execution Strategy (The Chained Job)

Because we cannot load all models at once, we use a single, massive background chain that runs generators sequentially, followed by judges sequentially.

**The Launch Command:**
```bash
cd /data/mpstme-dishank/repo-intel-platform/hpc
nohup bash -c '
  bash run_battery.sh codellama:13b-instruct
  bash run_battery.sh qwen2.5-coder:14b
  bash run_battery.sh qwen2.5-coder:32b
  bash run_rejudge.sh gemma2:27b
  bash run_rejudge.sh mistral:7b-instruct
' > /data/mpstme-dishank/all_jobs_output.log 2>&1 &
disown
```
* **IMPORTANT:** The command MUST be run from inside the `hpc` directory. Running it from `~` will result in `Exit 127 (command not found)`.
* **Monitoring:** Use `tail -f /data/mpstme-dishank/all_jobs_output.log` to watch the pipeline progress. Output CSVs and `.db` files are written to `/data/mpstme-dishank/evaluation_results/`.

## 4. Pending Tasks for the Next Agent
1. **Analyze the Results:** Once the massive background job finishes, parse the resulting `.csv` files in `/data/mpstme-dishank/evaluation_results/`.
2. **Verify 32B Completion:** Ensure `qwen2.5-coder:32b` successfully completed `ack-nestjs-boilerplate` without hitting a 900s timeout, proving our token-budget fix worked in production.
3. **Commit Code:** The code changes to `builder.py`, `pipeline.py`, and `token_budget.py` exist locally in the `dishank-gpu` branch but **have not been committed/pushed yet** (per the user's explicit instructions to hold off). These will need to be pushed once the pipeline outputs are verified.
