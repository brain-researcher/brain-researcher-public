#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "=== Starting Brain Researcher Chatbot UI ==="
echo "Legacy compatibility wrapper; delegating to scripts/services/start_chatbot.sh"
echo "If you only need the Next.js app, use: br serve web --host 0.0.0.0 --port 3000"
echo

exec "${ROOT_DIR}/scripts/services/start_chatbot.sh"
