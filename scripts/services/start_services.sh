#!/usr/bin/env bash

# Start the active Brain Researcher local service matrix.
# Services: web (3000), agent (8000), orchestrator (3001), kg (5000), mcp (7000).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs

if ! command -v br >/dev/null 2>&1; then
  echo "br command not found. Install the repo first with: pip install -e '.[all]'" >&2
  exit 1
fi

if [[ -f .env.local || -f .env ]]; then
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

export NODE_ENV="${NODE_ENV:-production}"
export ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://localhost:3001}"
export BR_ORCHESTRATOR_URL="${BR_ORCHESTRATOR_URL:-$ORCHESTRATOR_URL}"
export AGENT_URL="${AGENT_URL:-http://localhost:8000}"
export BR_KG_API_URL="${BR_KG_API_URL:-http://localhost:5000}"
export BR_KG_URL="${BR_KG_URL:-http://localhost:5000}"
export BR_MCP_HTTP_URL="${BR_MCP_HTTP_URL:-http://localhost:7000/mcp}"

check_port() {
  local port="$1"
  lsof -Pi :"$port" -sTCP:LISTEN -t >/dev/null 2>&1
}

wait_for_http() {
  local url="$1"
  local name="$2"
  local attempts="${3:-45}"

  for ((i=1; i<=attempts; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "✅ $name is ready at $url"
      return 0
    fi
    sleep 1
  done

  echo "❌ $name failed health check: $url" >&2
  return 1
}

start_service() {
  local name="$1"
  local port="$2"
  local url="$3"
  local attempts="$4"
  local pidfile="/tmp/${name}.pid"
  shift 4

  echo "Starting $name on port $port..."
  if check_port "$port"; then
    echo "✅ $name is already running on port $port"
    echo
    return 0
  fi

  nohup "$@" > "logs/${name}.log" 2>&1 &
  local pid=$!
  echo "$pid" > "$pidfile"

  if wait_for_http "$url" "$name" "$attempts"; then
    echo "✅ $name started successfully (PID: $pid)"
    echo
    return 0
  fi

  echo "❌ Failed to start $name. Check logs/${name}.log for details" >&2
  kill "$pid" 2>/dev/null || true
  rm -f "$pidfile"
  exit 1
}

echo "========================================="
echo "Starting Brain Researcher Services"
echo "========================================="
echo

start_service "kg" 5000 "http://127.0.0.1:5000/health" 45 \
  br serve kg --host 0.0.0.0 --port 5000
start_service "orchestrator" 3001 "http://127.0.0.1:3001/health" 45 \
  br serve orchestrator --host 0.0.0.0 --port 3001
start_service "agent" 8000 "http://127.0.0.1:8000/health" 45 \
  br serve agent --host 0.0.0.0 --port 8000
start_service "mcp" 7000 "http://127.0.0.1:7000/healthz" 45 \
  env BR_MCP_HOST=0.0.0.0 BR_MCP_PORT=7000 bash scripts/mcp/start_http_local.sh
start_service "web" 3000 "http://127.0.0.1:3000/api/health" 90 \
  br serve web --host 0.0.0.0 --port 3000

echo "========================================="
echo "Service Status"
echo "========================================="
echo

echo "✅ Web UI:       http://localhost:3000"
echo "✅ Agent API:    http://localhost:8000"
echo "✅ BR-KG API:  http://localhost:5000"
echo "✅ Orchestrator: http://localhost:3001"
echo "✅ MCP HTTP:     http://localhost:7000/mcp"
echo
echo "Logs:"
echo "  tail -f logs/web.log"
echo "  tail -f logs/agent.log"
echo "  tail -f logs/kg.log"
echo "  tail -f logs/orchestrator.log"
echo "  tail -f logs/mcp.log"
echo
echo "Stop services: ./scripts/services/stop_services.sh"
