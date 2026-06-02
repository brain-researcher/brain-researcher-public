#!/usr/bin/env bash
set -euo pipefail

echo "=== Starting Brain Researcher Agent (Adaptive Port) ==="
echo

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

if ! command -v br >/dev/null 2>&1; then
  echo "br command not found. Install the repo first with: pip install -e '.[all]'" >&2
  exit 1
fi

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

export BR_KG_API_URL="${BR_KG_API_URL:-http://localhost:5000}"
export BR_KG_URL="${BR_KG_URL:-http://localhost:5000}"

find_free_port() {
  local start_port=$1
  local port=$start_port

  while [ $port -lt $((start_port + 100)) ]; do
    if ! lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
      echo $port
      return 0
    fi
    port=$((port + 1))
  done
  return 1
}

AGENT_PORT=$(find_free_port 8000)
echo "Starting Agent API on port $AGENT_PORT..."
nohup br serve agent --host 0.0.0.0 --port "$AGENT_PORT" > logs/agent.log 2>&1 &
AGENT_PID=$!

for i in {1..30}; do
  if curl -fsS "http://localhost:$AGENT_PORT/health" >/dev/null 2>&1; then
    echo "✓ Agent API is running on port $AGENT_PORT"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "✗ Agent API failed to start" >&2
    kill "$AGENT_PID" 2>/dev/null || true
    exit 1
  fi
  sleep 1
done

echo
echo "=== Agent API is running ==="
echo "🔌 Agent API: http://localhost:$AGENT_PORT"
echo "📚 BR-KG:   ${BR_KG_API_URL}"
echo
echo "To start the Web UI, run:"
echo "  br serve web --port 3000"
echo "Or from the app directory:"
echo "  cd apps/web-ui && npm run dev"
echo
echo "Press Ctrl+C to stop the service"

cleanup() {
  echo
  echo "Shutting down agent..."
  kill "$AGENT_PID" 2>/dev/null || true
  wait "$AGENT_PID" 2>/dev/null || true
  echo "Agent stopped."
  exit 0
}
trap cleanup INT TERM

while true; do
  if ! kill -0 "$AGENT_PID" 2>/dev/null; then
    echo "Agent process died unexpectedly!" >&2
    exit 1
  fi
  sleep 5
done
