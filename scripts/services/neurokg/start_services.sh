#!/usr/bin/env bash
# Start the BR-KG API only.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
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

echo "Starting BR-KG service..."
nohup br serve kg --host 0.0.0.0 --port "${PORT:-5000}" > logs/neurokg.service.log 2>&1 &
API_PID=$!

echo "Waiting for BR-KG API to start..."
sleep 3

API_PORT=$(lsof -Pan -p "$API_PID" -i 2>/dev/null | awk '/LISTEN/ {print $9}' | cut -d: -f2 | head -1)
if [[ -z "$API_PORT" ]]; then
  API_PORT="${PORT:-5000}"
fi

echo "API started on port $API_PORT (PID: $API_PID)"
echo "API is running at http://localhost:$API_PORT"
echo "Explore the graph at http://localhost:3000/en/kg/explore"
echo "To stop service, run: kill $API_PID"

wait
