#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:3000}"

echo "Smoke: GET /api/health via ${BASE_URL}"
curl -sf "${BASE_URL}/api/health" >/dev/null
echo "✔ health"

echo "Smoke: POST /api/chat"
curl -sf -X POST "${BASE_URL}/api/chat" \
  -H "content-type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello smoke"}]}' >/dev/null
echo "✔ chat"

echo "Smoke: SSE /api/chat/stream (coding)"
curl -sN -X POST "${BASE_URL}/api/chat/stream" \
  -H "content-type: application/json" \
  -d '{"messages":[{"role":"user","content":"list files"}],"ctx":{"tools":{"mode":"coding"}}}' | head -n 5 >/dev/null
echo "✔ chat/stream (first events)"

echo "Smoke: threads snapshot"
curl -sf "${BASE_URL}/api/threads/default/messages" >/dev/null
echo "✔ threads/default/messages"

echo "All chat smoke checks passed."
