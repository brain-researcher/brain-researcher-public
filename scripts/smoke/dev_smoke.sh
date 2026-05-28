#!/usr/bin/env bash
# Minimal smoke-profile launcher for Agent (stubbed chat/datasets) and Next.js.
# Usage: ./scripts/smoke/dev_smoke.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Load env (OPENAI_API_KEY etc.)
set -a
source "$ROOT_DIR/.env"
set +a

echo "[dev_smoke] Starting Agent on :8000 (SMOKE_TEST_MODE=1, auth disabled)"
SMOKE_TEST_MODE=1 DISABLE_AUTH_FOR_DEV=1 \
  FLASK_APP=brain_researcher.services.agent.web_service \
  python -m flask run --host 0.0.0.0 --port 8000 \
  > /tmp/agent-smoke.log 2>&1 &
AGENT_PID=$!
echo "[dev_smoke] Agent pid=$AGENT_PID (logs: /tmp/agent-smoke.log)"

echo "[dev_smoke] Starting Next.js dev on :3000"
cd "$ROOT_DIR/apps/web-ui"
PORT=3000 HOSTNAME=0.0.0.0 \
  npm run dev -- --hostname 0.0.0.0 --port 3000 \
  > /tmp/webui-dev.log 2>&1 &
NEXT_PID=$!
echo "[dev_smoke] Next.js pid=$NEXT_PID (logs: /tmp/webui-dev.log)"

echo "[dev_smoke] Waiting 8s for services..."
sleep 8

echo "[dev_smoke] Quick health check"
curl -sf http://127.0.0.1:8000/api/health >/dev/null && echo "  Agent ok"
curl -sf http://127.0.0.1:3000/api/health >/dev/null && echo "  Next proxy ok"

echo "[dev_smoke] To stop: kill $AGENT_PID $NEXT_PID"
