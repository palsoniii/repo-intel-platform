#!/usr/bin/env bash
# One generator's battery, on one MIG slice. Upload as the "Job Script" in Altair
# Access (Applications -> Batch or Shell Script) after saving the repo-intel-gpu image.
#
# Resources come from the submission form, not from here. Set them to:
#
#   Container Image               repo-intel-gpu
#   Number of Nodes               1
#   Number of Processors per Node 8          <- the form defaults to 1
#   Number of GPUs per Node       1
#   Amount of Memory (MB)         32000      <- the form defaults to 10, which is 10 MB
#   Queue                         workq
#
# Pass the generator in "Job Script Arguments":  qwen2.5-coder:7b
#
# Submit this three times, once per generator, rather than looping over models here.
# Three jobs run on three of the four MIG slices at once and finish in roughly the time
# of one; a loop would take three times as long on a single slice. It also means one
# model crashing does not take the other two down with it.
set -euo pipefail

MODEL="${1:-${MODEL:-}}"
: "${MODEL:?usage: run_battery.sh <generator-model>   e.g. qwen2.5-coder:7b}"
JUDGE_MODEL="${JUDGE_MODEL:-gemma2:9b}"

USER_NAME="${USER:-$(id -un)}"
DATA="${DATA:-/data/${USER_NAME}}"
PROJ="${PROJ:-${DATA}/repo-intel-platform}"
PACK="${PACK:-${DATA}/context_pack.json}"
OUT_DIR="${OUT_DIR:-${DATA}/evaluation_results}"
RUN_TAG="$(echo "$MODEL" | tr ':/' '__')"

export OLLAMA_MODELS="${OLLAMA_MODELS:-${DATA}/ollama}"
export OLLAMA_HOST="http://127.0.0.1:11434"
export OLLAMA_NUM_CTX="${OLLAMA_NUM_CTX:-8192}"   # pinned: changing it invalidates comparability
export OLLAMA_MAX_LOADED_MODELS=1                 # generator and judge never co-resident
export OLLAMA_NUM_PARALLEL=1

echo "=== configuration ==="
printf '  %-14s %s\n' generator "$MODEL" judge "$JUDGE_MODEL" pack "$PACK" out "$OUT_DIR" models "$OLLAMA_MODELS"

# --- refuse the two mistakes that produce plausible-looking wrong numbers -------------
if [[ "$MODEL" == "$JUDGE_MODEL" ]]; then
  echo "FATAL: generator and judge are both '$MODEL'." >&2
  echo "An arm grading its own output inverts the result this study reports (REPORT.md 6.2)." >&2
  exit 2
fi
[[ -f "$PACK" ]] || { echo "FATAL: no context pack at $PACK. Build it off-cluster first:" >&2
                      echo "  python -m scripts.build_context_pack \$(cat 18_repo_urls.txt) --out context_pack.json" >&2
                      exit 2; }
[[ -d "$PROJ/backend" ]] || { echo "FATAL: project not found at $PROJ" >&2; exit 2; }
mkdir -p "$OUT_DIR"

# --- prove we are on a GPU before spending the allocation ------------------------------
echo "=== GPU ==="
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
  nvidia-smi -L
else
  echo "FATAL: no nvidia-smi. This job is not on a GPU; every latency figure would be" >&2
  echo "meaningless and generation would take days. Check 'Number of GPUs per Node'." >&2
  exit 3
fi

# --- ollama ----------------------------------------------------------------------------
echo "=== starting ollama ==="
ollama serve > "$OUT_DIR/ollama_${RUN_TAG}.log" 2>&1 &
OLLAMA_PID=$!
trap 'kill "$OLLAMA_PID" 2>/dev/null || true' EXIT

for i in $(seq 1 90); do
  ollama list >/dev/null 2>&1 && break
  [[ $i -eq 90 ]] && { echo "FATAL: ollama not ready after 90s" >&2; tail -30 "$OUT_DIR/ollama_${RUN_TAG}.log" >&2; exit 3; }
  sleep 1
done
echo "ollama ready"; ollama list

for m in "$MODEL" "$JUDGE_MODEL"; do
  ollama list | awk 'NR>1 {print $1}' | grep -qx "$m" || {
    echo "FATAL: model '$m' is not in $OLLAMA_MODELS." >&2
    echo "Stage it once (notebook 00_setup_gpu_image.ipynb, section 4) -- this node may have no route out." >&2
    exit 4; }
done

# --- run --------------------------------------------------------------------------------
cd "$PROJ/backend"
ARGS=(--context-pack "$PACK"
      --models "$MODEL"
      --judge-model "$JUDGE_MODEL"
      --no-bertscore
      --out "$OUT_DIR/battery_${RUN_TAG}.csv"
      --sqlite "$OUT_DIR/battery_${RUN_TAG}.db")
[[ -d "$PROJ/backend/annotations" ]] && ARGS+=(--annotations-dir "$PROJ/backend/annotations")

echo "=== running: $MODEL judged by $JUDGE_MODEL ==="
# `time` so the log records wall clock beside the per-row latencies: the gap between
# them is scheduler and model-load overhead, which must not be reported as generation time.
time python -m app.evaluation.harness "${ARGS[@]}"

echo "=== done -> $OUT_DIR/battery_${RUN_TAG}.{csv,db} ==="
echo "Score locally: the oracle is pure CPU and needs no GPU."
