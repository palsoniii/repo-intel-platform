#!/usr/bin/env bash
# Single-entrypoint runner for the whole remaining evaluation. Upload as the
# "Job Script" in Altair Access (Applications -> Batch or Shell Script).
#
# No custom saved image required -- submit with the standard pytorch_pbs image.
# The script bootstraps Ollama and Python deps from /data/<user>/ at start.
#
# Resources (same form fields as run_battery.sh / run_rejudge.sh):
#
#   Container Image               pytorch_pbs:25.12-py3   (standard image, NOT custom)
#   Number of Nodes               1
#   Number of Processors per Node 8
#   Number of GPUs per Node       1
#   Amount of Memory (MB)         32000
#   Queue                         workq
#
# Pass an optional phase in "Job Script Arguments":
#
#   (no argument)   everything, in order: judges -> human -> quality
#   judges          only the two secondary judges (gemma2:27b, mistral:7b-instruct)
#   human           only sample + full-claims rejudge + review sheet
#   quality         only G-Eval + text overlap
#
# SAFE TO RE-RUN. Every step dedupes on (repo, model, variant) against its own
# output file, so if the walltime kills the job you resubmit the identical line
# and it resumes from where it stopped -- at most the row in flight is lost.
#
# A phase that fails is logged and the remaining phases still run; the script
# exits non-zero if any phase failed, and prints a summary table of outcomes.
#
# The battery jobs (run_battery.sh) MUST have completed and all three output DBs
# downloaded into $OUT_DIR before submitting this job.
#
# Deliberately NOT set -e: a failing phase must not abort the phases after it.
set -uo pipefail

usage() {
  cat <<'EOF'
usage: run_all.sh [all|judges|human|quality]

  (no argument) / all   run every phase in order: judges -> human -> quality
  judges                secondary judges only: gemma2:27b then mistral:7b-instruct
  human                 human-validation sample + full-claims rejudge + review sheet
  quality               G-Eval quality + text-overlap rejudge

environment overrides:
  DATA          persistent root                (default /data/$USER)
  PROJ          repo checkout                  (default $DATA/repo-intel-platform)
  OUT_DIR       results directory              (default $DATA/evaluation_results)
  PACK          context pack                   (default $DATA/context_pack.json)
  NO_BERTSCORE  1 = skip BERTScore in quality  (default 1 -- bert-score is not
                installed on the cluster and roberta-large cannot be downloaded
                from a network-isolated compute node)
EOF
}

case "${1:-}" in
  -h|--help|help) usage; exit 0 ;;
esac

PHASE="${1:-all}"
case "$PHASE" in
  all|judges|human|quality) ;;
  *)
    echo "FATAL: unknown phase '$PHASE'." >&2
    usage >&2
    exit 2 ;;
esac

USER_NAME="${USER:-$(id -un)}"
DATA="${DATA:-/data/${USER_NAME}}"
PROJ="${PROJ:-${DATA}/repo-intel-platform}"
OUT_DIR="${OUT_DIR:-${DATA}/evaluation_results}"
PACK="${PACK:-${DATA}/context_pack.json}"
export PATH="${DATA}/ollama-dist/bin:${DATA}/bin:/usr/local/bin:${PATH}"
export LD_LIBRARY_PATH="${DATA}/ollama-dist/lib/ollama:${LD_LIBRARY_PATH:-}"

# The judge being validated against the human reviewer. Pinned explicitly rather
# than left to the script default -- the primary judge under test must be visible
# in the command that produced the numbers.
PRIMARY_JUDGE="gemma2:9b"
SECONDARY_JUDGES=(gemma2:27b mistral:7b-instruct)
DB_STEMS=(codellama13b qwen14b qwen32b)

# --- logging ------------------------------------------------------------------
# Nothing is written to $HOME: home directories on this cluster are volatile.
mkdir -p "$OUT_DIR" || { echo "FATAL: cannot create $OUT_DIR" >&2; exit 2; }
LOG="${OUT_DIR}/run_all.log"

_stamp() {
  while IFS= read -r line; do
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$line"
  done
}
exec > >(_stamp | tee -a "$LOG") 2>&1

echo $$ > "${OUT_DIR}/run_all.pid"

echo "=== run_all.sh phase=$PHASE pid=$$ ==="
echo "=== configuration ==="
printf '  %-14s %s\n' \
  phase "$PHASE" proj "$PROJ" out "$OUT_DIR" pack "$PACK" \
  log "$LOG" no_bertscore "${NO_BERTSCORE:-1}"

# --- preflight: everything this job depends on must already be on disk --------
[[ -d "$PROJ/backend" ]] || { echo "FATAL: project not found at $PROJ" >&2; exit 2; }

[[ -f "$PACK" ]] || {
  echo "FATAL: context pack not found at $PACK." >&2
  echo "The compute nodes have no route to GitHub, so the parse phases read repos" >&2
  echo "from the pack instead of cloning. Copy context_pack.json to \$DATA first," >&2
  echo "or point PACK= at it." >&2
  exit 2
}

MISSING_DBS=()
for stem in "${DB_STEMS[@]}"; do
  [[ -f "$OUT_DIR/battery_${stem}.db" ]] || MISSING_DBS+=("battery_${stem}.db")
done
[[ ${#MISSING_DBS[@]} -eq 0 ]] || {
  echo "FATAL: missing battery output DB(s) in $OUT_DIR: ${MISSING_DBS[*]}" >&2
  echo "All three arms are required. Run the battery jobs (run_battery.sh) and" >&2
  echo "copy their results into $OUT_DIR first." >&2
  exit 2
}

# --- Python deps bootstrap ----------------------------------------------------
PIP_TARGET="${DATA}/site-packages"
PIP_CACHE="${DATA}/pip-cache"
REQ="${PROJ}/backend/requirements-cluster.txt"
mkdir -p "$PIP_TARGET" "$PIP_CACHE"
echo "=== installing Python deps to $PIP_TARGET ==="
pip install --quiet --target "$PIP_TARGET" --cache-dir "$PIP_CACHE" -r "$REQ" \
  >> /tmp/pip_install.log 2>&1 \
  || { echo "FATAL: pip install failed. See /tmp/pip_install.log" >&2; exit 5; }
export PYTHONPATH="${PIP_TARGET}:${PYTHONPATH:-}"
echo "Python deps ready."

export OLLAMA_MODELS="${OLLAMA_MODELS:-${DATA}/ollama}"
export OLLAMA_HOST="http://127.0.0.1:11434"
export OLLAMA_NUM_CTX="${OLLAMA_NUM_CTX:-8192}"   # pinned invariant — changing invalidates comparability
# One judge at a time, no generator co-resident.
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_KEEP_ALIVE=${OLLAMA_KEEP_ALIVE:-30m}

# --- prove we are on a GPU before spending the allocation ---------------------
echo "=== GPU ==="
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
  nvidia-smi -L
else
  echo "FATAL: no nvidia-smi. This job is not on a GPU." >&2
  echo "gemma2:27b needs ~17 GB VRAM and will not finish on CPU." >&2
  echo "Check 'Number of GPUs per Node' in the submission form." >&2
  exit 3
fi

# --- ollama -------------------------------------------------------------------
# The judges phase delegates to run_rejudge.sh, which starts and tears down its
# own server. So the human/quality phases call ensure_ollama, which reuses a live
# server if there is one and otherwise starts a fresh one.
OLLAMA_PID=""

ensure_ollama() {
  if ollama list >/dev/null 2>&1; then
    echo "ollama already responding on 11434"
    return 0
  fi

  echo "=== starting ollama ==="
  # Kill any existing process on 11434 to prevent silent bind errors. A stale
  # binder is exactly what turned the last rejudge run into 658 empty rows.
  if command -v fuser >/dev/null 2>&1; then
    fuser -k 11434/tcp || true
  elif command -v ss >/dev/null 2>&1; then
    ss -ltnp | grep :11434 | awk '{print $6}' | cut -d, -f2 | cut -d= -f2 | xargs kill -9 2>/dev/null || true
  fi

  ollama serve > "${OUT_DIR}/ollama_run_all.log" 2>&1 &
  OLLAMA_PID=$!
  trap 'kill "${OLLAMA_PID:-}" 2>/dev/null || true' EXIT

  local i
  for i in $(seq 1 90); do
    ollama list >/dev/null 2>&1 && break
    if [[ $i -eq 90 ]]; then
      echo "FATAL: ollama not ready after 90s" >&2
      tail -30 "${OUT_DIR}/ollama_run_all.log" >&2
      return 3
    fi
    sleep 1
  done
  echo "ollama ready"; ollama list
  return 0
}

require_model() {
  local m="$1"
  if ollama list | awk 'NR>1 {print $1}' | grep -qx "$m"; then
    return 0
  fi
  echo "FATAL: model '$m' is not in $OLLAMA_MODELS." >&2
  echo "Stage it once (notebook 00_setup_gpu_image.ipynb, section 4) -- this node" >&2
  echo "may have no route out to the Ollama registry." >&2
  return 4
}

# --- phase bookkeeping --------------------------------------------------------
PHASE_NAMES=()
PHASE_RCS=()

run_phase() {
  local name="$1"; shift
  echo ""
  echo "############################################################"
  echo "### phase $name: START"
  echo "############################################################"
  "$@"
  local rc=$?
  if [[ $rc -eq 0 ]]; then
    echo "### phase $name: OK"
  else
    echo "### phase $name: FAILED (rc=$rc)"
  fi
  PHASE_NAMES+=("$name")
  PHASE_RCS+=("$rc")
  return 0
}

# --- phase 1: secondary judges ------------------------------------------------
# Strictly sequential, never parallel: gemma2:27b is ~17 GB and will not
# co-reside with a second judge on one MIG slice. A failing judge is logged and
# the other one still runs.
phase_judges() {
  local rc_all=0 J rc
  for J in "${SECONDARY_JUDGES[@]}"; do
    echo "--- secondary judge: $J ---"
    bash "$PROJ/hpc/run_rejudge.sh" "$J"
    rc=$?
    if [[ $rc -ne 0 ]]; then
      echo "WARNING: secondary judge $J failed (rc=$rc). Continuing with the next judge." >&2
      rc_all=1
    else
      echo "--- secondary judge $J done ---"
    fi
  done
  return $rc_all
}

# --- phase 2: human validation ------------------------------------------------
phase_human() {
  ensure_ollama || return $?
  require_model "$PRIMARY_JUDGE" || return $?

  local rc_all=0 stem rc
  local sample="evaluation_results/human_validation_sample_final.csv"
  local claims="evaluation_results/human_validation_claims.csv"

  if [[ ! -f "$sample" ]]; then
    echo "--- $sample absent: drawing the fixed-seed N=40 sample ---"
    python -m scripts.export_human_validation
    rc=$?
    if [[ $rc -ne 0 || ! -f "$sample" ]]; then
      echo "FATAL: could not create $sample (rc=$rc). Nothing downstream can run." >&2
      return ${rc:-1}
    fi
  else
    echo "--- reusing existing $sample ---"
  fi

  # All three arms append to the SAME claims CSV; each run skips rows already in
  # it, so this is resumable and must stay sequential.
  for stem in "${DB_STEMS[@]}"; do
    echo "--- full-claims rejudge: battery_${stem}.db (judge $PRIMARY_JUDGE) ---"
    python -m scripts.rejudge_full_claims \
      --src-db "evaluation_results/battery_${stem}.db" \
      --sample-csv "$sample" \
      --context-pack "$PACK" \
      --judge "$PRIMARY_JUDGE" \
      --out "$claims"
    rc=$?
    if [[ $rc -ne 0 ]]; then
      echo "WARNING: full-claims rejudge failed for battery_${stem}.db (rc=$rc)." >&2
      rc_all=1
    fi
  done

  echo "--- building blinded review sheet ---"
  python -m scripts.build_review_sheet --context-pack "$PACK"
  rc=$?
  [[ $rc -ne 0 ]] && { echo "WARNING: build_review_sheet failed (rc=$rc)." >&2; rc_all=1; }

  return $rc_all
}

# --- phase 3: G-Eval quality + text overlap -----------------------------------
phase_quality() {
  ensure_ollama || return $?
  require_model "$PRIMARY_JUDGE" || return $?

  local flags=()
  if [[ "${NO_BERTSCORE:-1}" == "1" ]]; then
    # bert-score is excluded from requirements-cluster.txt and roberta-large
    # cannot be fetched from a network-isolated node. BLEU-4, ROUGE-L and
    # METEOR still run; bertscore_f1 is left empty.
    flags+=(--no-bertscore)
    echo "--- BERTScore disabled (NO_BERTSCORE=1) ---"
  else
    echo "--- BERTScore ENABLED (NO_BERTSCORE=0) -- needs bert-score installed and a network route ---"
  fi

  python -m scripts.rejudge_quality_and_overlap ${flags[@]+"${flags[@]}"}
}

# --- run ----------------------------------------------------------------------
cd "$PROJ/backend" || { echo "FATAL: cannot cd to $PROJ/backend" >&2; exit 2; }

# rejudge_quality_and_overlap.py and rejudge_full_claims.py write to relative
# evaluation_results/ paths, so that name must resolve to the persistent $OUT_DIR.
if [[ ! -e evaluation_results ]]; then
  ln -s "$OUT_DIR" evaluation_results \
    || { echo "FATAL: could not symlink $PROJ/backend/evaluation_results -> $OUT_DIR" >&2; exit 2; }
  echo "symlinked $PROJ/backend/evaluation_results -> $OUT_DIR"
else
  echo "using existing $PROJ/backend/evaluation_results"
fi

case "$PHASE" in
  all)
    run_phase judges  phase_judges
    run_phase human   phase_human
    run_phase quality phase_quality
    ;;
  judges)  run_phase judges  phase_judges  ;;
  human)   run_phase human   phase_human   ;;
  quality) run_phase quality phase_quality ;;
esac

# --- summary ------------------------------------------------------------------
echo ""
echo "############################################################"
echo "### phase summary"
echo "############################################################"
printf '  %-10s %-8s %s\n' PHASE RC RESULT
FAILED=0
for i in "${!PHASE_NAMES[@]}"; do
  rc="${PHASE_RCS[$i]}"
  if [[ "$rc" -eq 0 ]]; then
    printf '  %-10s %-8s %s\n' "${PHASE_NAMES[$i]}" "$rc" OK
  else
    printf '  %-10s %-8s %s\n' "${PHASE_NAMES[$i]}" "$rc" FAILED
    FAILED=1
  fi
done

echo ""
echo "=== files in $OUT_DIR ==="
ls -lh "$OUT_DIR" 2>/dev/null | tail -n +2

echo ""
echo "=== next step (run locally, off-cluster) ==="
echo "  1. Download $OUT_DIR/human_review.xlsx"
echo "  2. A reviewer fills the 'human_verdict' column on the 'Review' worksheet."
echo "     Model and context variant are hidden in the 'Answer Key' worksheet --"
echo "     leave it hidden, the sheet is blinded on purpose."
echo "  3. Then, from backend/:"
echo ""
echo "       python -m scripts.score_human_validation"
echo ""
echo "  Also download rejudge_*.{csv,db} and quality_and_overlap_*.csv, then run"
echo "  build_paper_report.py locally."

if [[ $FAILED -ne 0 ]]; then
  echo "=== run_all.sh finished WITH FAILURES (see summary above) ==="
  exit 1
fi
echo "=== run_all.sh complete: all phases OK ==="
exit 0
