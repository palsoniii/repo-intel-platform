# HPC Pipeline & Project Update Summary

This document serves as a comprehensive record of the architectural changes, bug fixes, and new pipeline scripts implemented to get the LLM evaluation battery running successfully on the Altair Access HPC cluster.

---

## 1. The Altair Access Portal & Cluster Environment

The HPC cluster environment introduced several strict constraints that broke the standard local execution flow. We had to adapt the pipeline to respect these rules:

* **Volatile Home Directories:** The home directory (`~` or `/home/...`) is temporary and resets. We enforced that all persistent data, Pip caches, Ollama binaries, and output databases are strictly stored in `/data/mpstme-dishank/`.
* **Execution Strategy & MIG Slices:** The cluster partitions its GPUs using Multi-Instance GPU (MIG) slices. Running the battery sequentially in an interactive terminal using `nohup bash -c 'a; b; c'` wastes parallelism and exposes the jobs to the interactive session's walltime limits. The intended workflow is to submit jobs via the Altair Web Portal (Applications -> Batch or Shell Script) so they run in parallel across independent MIG slices, ensuring that if one model crashes, it doesn't block the others.
* **Network & Database Isolation:** The compute nodes (GPU slices) often lack outbound network access to GitHub and do not have Neo4j installed. The standard `pytorch_pbs:25.12-py3` image lacks many pipeline dependencies by default.

---

## 2. Core Bug Fixes & Architectural Changes

### A. The Context Window Token Budget Fix
* **The Problem:** The massive `ack-nestjs-boilerplate` repository generated a structured context graph of ~190,000 characters. When passed to `qwen2.5-coder:32b`, it completely blew out the context window, causing a hard 900-second (15 minute) HTTP timeout and failing the run.
* **The Fix:** We implemented a strict token budget (capped at ~6,065 tokens) for structured graphs. If a repository's graph exceeds this budget, the pipeline explicitly truncates the tail-end facts and injects a `... N more modules omitted` marker.
* **The Result:** The 32B model successfully digested the massive repository in ~60 seconds. *Trade-off:* Because facts were explicitly hidden to prevent a crash, the smaller models (`codellama`, `qwen14b`) saw a slight drop in coverage and an expected timeout behavior on truncated edges.

### B. Zero-Network Parse Phase (`scripts/rejudge.py`)
* **The Problem:** The secondary judge script (`run_rejudge.sh`) failed 100% of the time with `error="no cached parse"`. The parse phase was attempting to execute 18 live `git clone` operations on the compute node, which failed due to cluster network isolation.
* **The Fix:** We rewrote `phase_parse()` to accept a `--context-pack` argument. Instead of cloning repos, it directly extracts the `ParsedRepository` JSON schemas from the pre-built `context_pack.json` (which was generated upstream).
* **Why:** This reduces network dependency to zero on the compute node, matching the resilience of the primary battery script.

### C. Deferred Python Imports
* **The Problem:** The cluster evaluation crashed immediately with `ModuleNotFoundError` for `neo4j` and `tree_sitter` because they aren't listed in `requirements-cluster.txt`.
* **The Fix:** We pushed all graph database and AST parsing imports into `if TYPE_CHECKING:` blocks or inside specific functions.
* **Why:** The GPU node only needs to run the generation phase. By deferring the imports, the script avoids looking for dependencies it doesn't need to run inference.

### D. Defensive Ollama Binding
* **The Problem:** Background Ollama processes occasionally remained alive after a job ended, causing subsequent runs to fail silently with a `bind: address already in use` error.
* **The Fix:** We added a defensive kill switch (`fuser -k 11434/tcp` or `ss`) to `hpc/run_rejudge.sh` right before starting `ollama serve`. 

---

## 3. The Human Validation Pipeline

To validate the LLM judge's reliability, we needed a robust, blinded way for a human to grade a stratified sample of the summaries.

### A. Per-Claim Hallucination Schema
* **The Problem:** The original hallucination prompt only asked the LLM to return `unsupported_claims`. This made it impossible to know *which* claims it evaluated and deemed "Supported". 
* **The Fix:** We extended `HallucinationResult` in `backend/app/evaluation/hallucination.py` with an `all_claims` list. We rewrote the prompt to mandate that the judge evaluate *every* claim and return it with a `supported: bool` flag. `total_claims` and `unsupported_claims` are now derived dynamically to maintain backward compatibility.

### B. Full-Claims Rejudge Script (`rejudge_full_claims.py`)
* **What it does:** Modeled after the existing rejudge script, this script accepts a 40-row stratified sample manifest. It reads the previously generated `summary_text` from the SQLite database and pushes it through the newly patched `score_summary()` method.
* **Why:** It forces the judge to output the full `all_claims` list for our selected sample *without* having to regenerate the expensive summaries from scratch.

### C. Review Sheet Builder (`build_review_sheet.py`)
* **What it does:** Reads the full claims JSON output and generates a blinded Excel workbook (`.xlsx`) using `openpyxl`. 
* **Features:**
  * **Blinding:** The model names and context variants are stripped out so the human reviewer isn't biased.
  * **Ground-Truth Context:** It dynamically pulls the AST facts (Dependencies, Endpoints, Framework) from `context_pack.json` and embeds them directly at the top of each repository's block in the Excel sheet.
  * **Data Validation:** Adds dropdown menus (Supported, Unsupported, Unsure) for the reviewer.
  * **Answer Key:** Generates a hidden worksheet mapping the blinded IDs back to the actual model and variant.

### D. Scoring & Overlap Scripts
* **`score_human_validation.py`:** Calculates Cohen's Kappa (inter-rater reliability between the human and the LLM judge) and Spearman correlation.
* **`rejudge_quality_and_overlap.py`:** A resumable script that calculates G-Eval (quality metrics like conciseness and cohesiveness) and BERTScore (n-gram text overlap) on the successful runs.
