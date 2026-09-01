#!/usr/bin/env bash
# Job entrypoint: start Ollama, verify the GPU and the staged models, run one
# generator's battery from a context pack, exit.
#
# Everything this script needs must already exist -- it never clones a repo, never
# reaches a database, and never pulls a model. That is what makes it safe on a compute
# node with no network. It fails before the allocation is spent if anything is missing,
# rather than an hour in.
#
# Required:
#   CONTEXT_PACK   path to a pack from scripts/build_context_pack.py
#   MODEL          generator, e.g. qwen2.5-coder:7b
#   JUDGE_MODEL    judge -- must NOT equal MODEL (self-judging reverses the ranking of
#                  representations; see docs/REPORT.md 6.2)
# Optional:
#   OUT_DIR        default /app/evaluation_results
#   RUN_TAG        suffix for output filenames, default the model name
#   ANNOTATIONS_DIR, REFERENCE_SUMMARIES_DIR
set -euo pipefail

: "${CONTEXT_PACK:?set CONTEXT_PACK to a pack built by scripts/build_context_pack.py}"
: "${MODEL:?set MODEL to the generator, e.g. qwen2.5-coder:7b}"
: "${JUDGE_MODEL:?set JUDGE_MODEL to a model that is NOT the generator}"
OUT_DIR="${OUT_DIR:-/app/evaluation_results}"
RUN_TAG="${RUN_TAG:-$(echo "$MODEL" | tr ':/' '__')}"

if [[ "$MODEL" == "$JUDGE_MODEL" ]]; then
  echo "FATAL: MODEL and JUDGE_MODEL are both '$MODEL'." >&2
  echo "An arm that grades its own output inverts the result this study reports." >&2
  exit 2
fi
[[ -f "$CONTEXT_PACK" ]] || { echo "FATAL: no context pack at $CONTEXT_PACK" >&2; exit 2; }
mkdir -p "$OUT_DIR"

echo "=== GPU visibility ==="
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true
else
  echo "WARNING: nvidia-smi not found. If this job is meant to use a GPU, it is not." >&2
fi

echo "=== starting ollama ==="
ollama serve &
OLLAMA_PID=$!
# Kill the server on any exit path, so a scheduler that reuses the container or a
# failed run partway through does not leave it holding the GPU.
trap 'kill "$OLLAMA_PID" 2>/dev/null || true' EXIT

for i in $(seq 1 60); do
  if ollama list >/dev/null 2>&1; then break; fi
  if [[ $i -eq 60 ]]; then echo "FATAL: ollama did not become ready in 60s" >&2; exit 3; fi
  sleep 1
done
echo "ollama ready"

echo "=== staged models ==="
ollama list
for m in "$MODEL" "$JUDGE_MODEL"; do
  if ! ollama list | awk 'NR>1 {print $1}' | grep -qx "$m"; then
    echo "FATAL: model '$m' is not present in the mounted model store." >&2
    echo "Stage it where there IS network ('ollama pull $m' against the same volume)," >&2
    echo "then mount that directory at /root/.ollama. This node may have no route out." >&2
    exit 4
  fi
done

echo "=== running battery: generator=$MODEL judge=$JUDGE_MODEL ==="
ARGS=(--context-pack "$CONTEXT_PACK"
      --models "$MODEL"
      --judge-model "$JUDGE_MODEL"
      --no-bertscore
      --out "$OUT_DIR/battery_${RUN_TAG}.csv"
      --sqlite "$OUT_DIR/battery_${RUN_TAG}.db")
[[ -n "${ANNOTATIONS_DIR:-}" ]] && ARGS+=(--annotations-dir "$ANNOTATIONS_DIR")
[[ -n "${REFERENCE_SUMMARIES_DIR:-}" ]] && ARGS+=(--reference-summaries-dir "$REFERENCE_SUMMARIES_DIR")

# `time` so the job log records wall-clock next to the per-row latencies, which is the
# only way to tell scheduler overhead apart from generation time after the fact.
time python -m app.evaluation.harness "${ARGS[@]}"

echo "=== done: $OUT_DIR/battery_${RUN_TAG}.{csv,db} ==="
