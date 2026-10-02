#!/usr/bin/env bash
# One command for the demo machine: checks Ollama, starts Neo4j (Docker), the API and
# the dashboard, and stops them all on Ctrl-C.
#
#   ./demo.sh          start everything
#   ./demo.sh --seed   also pre-analyse the repositories in demo_repos.txt first
#
# Ollama runs natively rather than in Docker on purpose: on a Mac, Docker can't use
# the GPU, and a 7B model on CPU is several times slower.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
LOGS="$ROOT/backend/data/logs"
mkdir -p "$LOGS"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

env_value() { grep -E "^$1=" "$BACKEND/.env" 2>/dev/null | head -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*//'; }

[ -f "$BACKEND/.env" ] || fail "backend/.env is missing (cp backend/.env.example backend/.env)"
[ -x "$BACKEND/venv/bin/python" ] || fail "backend/venv is missing (see README: python3.13 -m venv venv && pip install -r requirements.txt)"
[ -d "$FRONTEND/node_modules" ] || { say "Installing frontend packages"; (cd "$FRONTEND" && npm install --silent); }

MODEL="$(env_value PRODUCT_SUMMARY_MODEL)"; MODEL="${MODEL:-$(env_value OLLAMA_MODEL_PRIMARY)}"; MODEL="${MODEL:-qwen2.5-coder:7b}"

say "Checking Ollama"
curl -sf http://localhost:11434/api/tags >/dev/null || fail "Ollama isn't running. Start the Ollama app (or: ollama serve)."
curl -sf http://localhost:11434/api/tags | grep -q "\"$MODEL\"" || fail "Model $MODEL isn't pulled. Run: ollama pull $MODEL"

say "Starting Neo4j"
if docker info >/dev/null 2>&1; then
  NEO4J_PASSWORD="$(env_value NEO4J_PASSWORD)" docker compose -f "$ROOT/docker-compose.yml" up -d neo4j >/dev/null
else
  echo "    Docker isn't running: continuing without Neo4j (every dashboard view still works;"
  echo "    only the 'Stored in Neo4j' step and the Neo4j Browser are unavailable)."
fi

if [ "${1:-}" = "--seed" ]; then
  say "Pre-analysing demo repositories (this runs the model; allow ~1 min per repository)"
  (cd "$BACKEND" && venv/bin/python -m app.product.seed)
fi

pids=()
cleanup() { say "Stopping"; for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

say "Starting API on http://localhost:8000  (log: backend/data/logs/api.log)"
(cd "$BACKEND" && exec venv/bin/uvicorn app.main:app --port 8000 >"$LOGS/api.log" 2>&1) &
pids+=($!)

say "Starting dashboard on http://localhost:5180  (log: backend/data/logs/web.log)"
(cd "$FRONTEND" && exec npm run dev -- --strictPort >"$LOGS/web.log" 2>&1) &
pids+=($!)

for _ in $(seq 1 40); do curl -sf http://localhost:8000/api/system >/dev/null && break; sleep 0.5; done
curl -sf http://localhost:8000/api/system >/dev/null || fail "API didn't start; see $LOGS/api.log"
sleep 1
say "Ready: http://localhost:5180   (Ctrl-C to stop)"
command -v open >/dev/null && open http://localhost:5180 || true
wait
