#!/usr/bin/env bash

# Stop all Brain Researcher services started by scripts/services/start_services.sh.

set -euo pipefail

echo "========================================="
echo "Stopping Brain Researcher Services"
echo "========================================="
echo

stop_service() {
  local name="$1"
  local pidfile="/tmp/${name}.pid"

  if [[ -f "$pidfile" ]]; then
    local pid
    pid="$(cat "$pidfile")"
    if ps -p "$pid" >/dev/null 2>&1; then
      echo "Stopping $name (PID: $pid)..."
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      echo "✅ $name stopped"
    else
      echo "⚠ $name process not found (stale PID file)"
    fi
    rm -f "$pidfile"
  else
    echo "ℹ $name is not running (no PID file)"
  fi
}

stop_service "web"
stop_service "mcp"
stop_service "orchestrator"
stop_service "agent"
stop_service "kg"

echo
echo "Checking for stray processes on service ports..."
for port in 3000 7000 3001 8000 5000; do
  pid="$(lsof -ti:"$port" 2>/dev/null || true)"
  if [[ -n "$pid" ]]; then
    echo "Stopping process on port $port (PID: $pid)..."
    kill $pid 2>/dev/null || true
  fi
done

echo
echo "✅ All services stopped"
