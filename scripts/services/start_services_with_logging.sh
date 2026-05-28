#!/usr/bin/env bash

# Start the BR-KG API with a dedicated tee'd log for debugging.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs

if ! command -v br >/dev/null 2>&1; then
  echo "br command not found. Install the repo first with: pip install -e '.[all]'" >&2
  exit 1
fi

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

LOG_PATH="logs/neurokg.debug.log"

echo "Stopping existing BR-KG process on port 5000, if any..."
lsof -ti:5000 | xargs kill 2>/dev/null || true
sleep 2

echo "Starting BR-KG Graph API on port 5000..."
(br serve kg --host 0.0.0.0 --port 5000 2>&1 | tee "$LOG_PATH") &
GRAPH_PID=$!
echo "$GRAPH_PID" > /tmp/BR-KG-debug.pid

echo "Waiting for API to be ready..."
for _ in {1..45}; do
  if curl -fsS http://127.0.0.1:5000/health >/dev/null 2>&1; then
    echo "Graph API is ready"
    echo
    echo "Graph API: http://localhost:5000"
    echo "Logs:      tail -f $LOG_PATH"
    echo "Stop:      kill $GRAPH_PID"
    exit 0
  fi
  sleep 1
done

echo "Graph API failed to start. Check $LOG_PATH" >&2
exit 1
