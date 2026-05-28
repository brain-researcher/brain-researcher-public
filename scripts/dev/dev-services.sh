#!/usr/bin/env bash
# Start Brain Researcher services for local development.
# Usage: ./scripts/dev/dev-services.sh [--no-neurokg] [--no-agent] [--no-orchestrator] [--no-ui]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

START_NEUROKG=true
START_AGENT=true
START_ORCHESTRATOR=true
START_UI=true
DISABLE_AGENT_AUTH=false
PIDS=()

for arg in "$@"; do
  case $arg in
    --no-neurokg) START_NEUROKG=false ;;
    --no-agent) START_AGENT=false ;;
    --no-orchestrator) START_ORCHESTRATOR=false ;;
    --no-ui) START_UI=false ;;
    --disable-agent-auth) DISABLE_AGENT_AUTH=true ;;
    --help)
      echo "Usage: $0 [--no-neurokg] [--no-agent] [--no-orchestrator] [--no-ui]"
      echo "       $0 [--disable-agent-auth]"
      exit 0
      ;;
  esac
done

if ! command -v br >/dev/null 2>&1; then
  echo "br command not found. Install the repo first with: pip install -e '.[all]'" >&2
  exit 1
fi

if [[ -f .env.local || -f .env ]]; then
  echo "Loading local auth/runtime env..."
  set -a
  [[ -f .env ]] && source .env
  [[ -f .env.local ]] && source .env.local
  set +a
fi

if [[ -n "${JWT_SECRET_KEY:-}" && -n "${NEXTAUTH_SECRET:-}" && "${JWT_SECRET_KEY}" != "${NEXTAUTH_SECRET}" ]]; then
  echo "Warning: JWT_SECRET_KEY and NEXTAUTH_SECRET differ in local dev; using JWT_SECRET_KEY for both." >&2
  export NEXTAUTH_SECRET="${JWT_SECRET_KEY}"
elif [[ -n "${JWT_SECRET_KEY:-}" && -z "${NEXTAUTH_SECRET:-}" ]]; then
  export NEXTAUTH_SECRET="${JWT_SECRET_KEY}"
elif [[ -z "${JWT_SECRET_KEY:-}" && -n "${NEXTAUTH_SECRET:-}" ]]; then
  export JWT_SECRET_KEY="${NEXTAUTH_SECRET}"
fi

export NEUROKG_API_URL="${NEUROKG_API_URL:-http://localhost:5000}"
export NEUROKG_URL="${NEUROKG_URL:-http://localhost:5000}"
export AGENT_URL="${AGENT_URL:-http://localhost:8000}"
export BR_ORCHESTRATOR_URL="${BR_ORCHESTRATOR_URL:-http://localhost:3001}"

cleanup() {
  echo
  echo "Shutting down services..."
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "Done."
}
trap cleanup EXIT INT TERM

wait_for_http() {
  local url="$1"
  local name="$2"
  local attempts="${3:-45}"
  for ((i=1; i<=attempts; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "  ✓ $name is ready at $url"
      return 0
    fi
    sleep 1
  done
  echo "  ✗ $name failed health check: $url" >&2
  return 1
}

if $START_NEUROKG; then
  echo "Starting BR-KG on port 5000..."
  nohup br serve kg --host 0.0.0.0 --port 5000 > logs/neurokg.log 2>&1 &
  PIDS+=("$!")
  wait_for_http "http://127.0.0.1:5000/health" "BR-KG"
fi

if $START_AGENT; then
  echo "Starting Agent on port 8000..."
  if $DISABLE_AGENT_AUTH; then
    export DISABLE_AUTH_FOR_DEV=1
  else
    unset DISABLE_AUTH_FOR_DEV || true
  fi
  nohup br serve agent --host 0.0.0.0 --port 8000 > logs/agent.log 2>&1 &
  PIDS+=("$!")
  wait_for_http "http://127.0.0.1:8000/health" "Agent"
fi

if $START_ORCHESTRATOR; then
  echo "Starting Orchestrator on port 3001..."
  nohup br serve orchestrator --host 0.0.0.0 --port 3001 > logs/orchestrator.log 2>&1 &
  PIDS+=("$!")
  wait_for_http "http://127.0.0.1:3001/health" "Orchestrator"
fi

if $START_UI; then
  echo "Starting Next.js Web UI on port 3000..."
  nohup br serve web --host 0.0.0.0 --port 3000 > logs/web_ui.log 2>&1 &
  PIDS+=("$!")
  wait_for_http "http://127.0.0.1:3000/api/health" "Web UI" 90
fi

echo
echo "Services started:"
$START_NEUROKG && echo "  BR-KG:      http://127.0.0.1:5000"
$START_AGENT && echo "  Agent:        http://127.0.0.1:8000"
$START_ORCHESTRATOR && echo "  Orchestrator: http://127.0.0.1:3001"
$START_UI && echo "  Web UI:       http://127.0.0.1:3000"
echo
echo "Press Ctrl+C to stop all services."

echo
wait
