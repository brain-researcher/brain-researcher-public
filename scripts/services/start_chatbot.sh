#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
START_SCRIPT="${ROOT_DIR}/scripts/services/start_services.sh"
STOP_SCRIPT="${ROOT_DIR}/scripts/services/stop_services.sh"

cleanup() {
  echo
  echo "Stopping shared service stack..."
  "${STOP_SCRIPT}"
}

trap cleanup EXIT
trap 'exit 0' INT TERM

echo "=== Starting Brain Researcher Chatbot ==="
echo "Legacy compatibility wrapper; delegating to scripts/services/start_services.sh"
echo

"${START_SCRIPT}"

echo
echo "Chatbot stack is running."
echo "Press Ctrl+C to stop all services via scripts/services/stop_services.sh"

while true; do
  sleep 5
done
