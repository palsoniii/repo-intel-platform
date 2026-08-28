#!/bin/bash
# Generate the granite-code writer arm: 18 repos x 3 representations, judged by gemma2 -- selected empirically as the better judge (rho=+0.661 vs oracle, specificity 0.803) over mistral (+0.475, 0.654), and it is not a writer here so there is NO self-judging.
#
# DESIGN: this replaces gemma2:9b as the third writer, giving an all-code writer set
# (qwen2.5-coder, codellama, granite-code) with a single general-purpose judge (mistral).
# That removes the writer-heterogeneity confound documented in PROJECT_HANDOFF.md section 7
# -- gemma2 was the only general-purpose writer AND the one whose results diverged most,
# so model identity and model type were not separable.
#
# BATCHED DELIBERATELY: the harness writes its CSV and SQLite only when a model FINISHES
# (handoff gotcha 6). A single 54-row invocation that gets killed at the deadline would
# lose everything. Six repos per batch means at most one batch is ever at risk.
#
# Writer/judge swapping: OLLAMA_MAX_LOADED_MODELS=1 forces an evict-and-reload on every
# writer<->judge transition. granite (6.0 GB) + mistral (5.6 GB) cycles through a 9.7 GB
# budget -- comparable to the gemma2 (6.4 GB) writer arm that completed in Run 2, and well
# clear of the deepseek footprint (8.3 GB) that made that model unusable.

set -u
cd /app || exit 1
R=/app/evaluation_results
LOG=$R/granite_writer.log
DB=$R/battery_v3_granite_gemma2judge.db

say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

mapfile -t ALL < /app/18_repo_urls.txt 2>/dev/null || {
    say "FATAL: /app/18_repo_urls.txt not readable"; exit 1; }
say "loaded ${#ALL[@]} repo urls"

BATCH=6
total=${#ALL[@]}
n=0
for ((i=0; i<total; i+=BATCH)); do
    n=$((n+1))
    chunk=("${ALL[@]:i:BATCH}")
    say "=== BATCH $n : ${#chunk[@]} repos ==="
    for u in "${chunk[@]}"; do say "    $u"; done

    python -m app.evaluation.harness "${chunk[@]}" \
        --models granite-code:8b-instruct \
        --judge-model gemma2:9b \
        --annotations-dir /app/annotations \
        --out "$R/granite_writer_batch${n}.csv" \
        --sqlite "$DB" \
        >> "$LOG" 2>&1

    rc=$?
    say "=== BATCH $n exited rc=$rc ==="
    rows=$(python - <<PY
import sqlite3
try:
    c=sqlite3.connect("$DB")
    print(c.execute("SELECT COUNT(*) FROM evaluation_runs").fetchone()[0])
except Exception:
    print(0)
PY
)
    say "    cumulative rows in $DB: $rows"
done

say "ALL BATCHES DONE"
