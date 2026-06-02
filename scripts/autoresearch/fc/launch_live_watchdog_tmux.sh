#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bash scripts/autoresearch/fc/launch_live_watchdog_tmux.sh [session_name]
#
# Starts the FC live watchdog in a detached tmux session on the current machine.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION_NAME="${1:-fc_live_watchdog}"
WATCHDOG_SCRIPT="${SCRIPT_DIR}/run_live_watchdog.sh"

if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
  echo "tmux session already exists: ${SESSION_NAME}" >&2
  exit 1
fi

tmux new-session -d -s "${SESSION_NAME}" "bash ${WATCHDOG_SCRIPT}"
echo "session=${SESSION_NAME}"
echo "monitor=tmux attach -t ${SESSION_NAME}"
