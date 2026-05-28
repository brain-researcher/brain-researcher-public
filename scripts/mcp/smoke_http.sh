#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

TOKEN_RESOLVER="${REPO_ROOT}/scripts/mcp/resolve_br_mcp_token.sh"
MCP_HOST="${BR_MCP_HOST:-127.0.0.1}"
MCP_PORT="${BR_MCP_PORT:-7000}"
MCP_MOUNT_PATH="${BR_MCP_MOUNT_PATH:-/mcp}"
MCP_URL="${BR_MCP_HTTP_URL:-http://${MCP_HOST}:${MCP_PORT}${MCP_MOUNT_PATH}}"
SMOKE_CURL_TIMEOUT_SECONDS="${BR_MCP_SMOKE_CURL_TIMEOUT_SECONDS:-12}"
MCP_SESSION_ID=""

if [[ -n "${BR_MCP_TOKEN:-}" ]]; then
  MCP_TOKEN="${BR_MCP_TOKEN}"
else
  MCP_TOKEN="$("${TOKEN_RESOLVER}")"
fi

if [[ -z "${MCP_TOKEN}" ]]; then
  echo "Resolved BR_MCP_TOKEN is empty." >&2
  exit 1
fi

extract_first_sse_json() {
  local body_file="${1}"
  python - "${body_file}" <<'PY'
import json
import sys
from pathlib import Path

body_path = Path(sys.argv[1])
text = body_path.read_text(encoding="utf-8", errors="replace")

for raw_line in text.splitlines():
    line = raw_line.strip()
    if not line.startswith("data:"):
        continue
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        continue
    try:
        obj = json.loads(payload)
    except Exception:
        continue
    print(json.dumps(obj))
    raise SystemExit(0)

raise SystemExit(1)
PY
}

call_rpc() {
  local request_id="${1}"
  local method="${2}"
  local params="${3}"

  local payload_file body_file json_line status_code curl_exit
  payload_file="$(mktemp)"
  body_file="$(mktemp)"
  trap 'rm -f "${payload_file}" "${body_file}"' RETURN

  cat >"${payload_file}" <<JSON
{"jsonrpc":"2.0","id":"${request_id}","method":"${method}","params":${params}}
JSON

  curl_exit=0
  local -a session_header=()
  if [[ -n "${MCP_SESSION_ID}" ]]; then
    session_header=(-H "mcp-session-id: ${MCP_SESSION_ID}")
  fi

  status_code="$(
    curl -sS \
      -o "${body_file}" \
      -w '%{http_code}' \
      --max-time "${SMOKE_CURL_TIMEOUT_SECONDS}" \
      -X POST "${MCP_URL}" \
      -H "Authorization: Bearer ${MCP_TOKEN}" \
      -H "Content-Type: application/json" \
      -H "Accept: application/json, text/event-stream" \
      "${session_header[@]}" \
      --data-binary @"${payload_file}"
  )" || curl_exit=$?

  if [[ "${curl_exit}" -ne 0 && "${curl_exit}" -ne 28 ]]; then
    echo "[fail] ${method}: curl_exit=${curl_exit}" >&2
    head -c 800 "${body_file}" >&2 || true
    return 1
  fi

  if [[ "${status_code}" != "200" ]]; then
    echo "[fail] ${method}: http_status=${status_code}" >&2
    head -c 800 "${body_file}" >&2 || true
    return 1
  fi

  if ! json_line="$(extract_first_sse_json "${body_file}")"; then
    echo "[fail] ${method}: response did not contain parseable SSE data frame" >&2
    head -c 800 "${body_file}" >&2 || true
    return 1
  fi

  local check_result
  if ! check_result="$(
    python - "${json_line}" "${method}" <<'PY'
import json
import sys

obj = json.loads(sys.argv[1])
method = sys.argv[2]

if "error" in obj:
    print(f"rpc_error={obj['error']}")
    raise SystemExit(1)
if "result" not in obj:
    print("missing_result=true")
    raise SystemExit(1)

if method == "tools/list":
    result = obj["result"]
    tools = result.get("tools", []) if isinstance(result, dict) else []
    print(f"tool_count={len(tools)}")
else:
    print("ok=true")
PY
  )"; then
    echo "[fail] ${method}: ${check_result}" >&2
    return 1
  fi

  if [[ "${curl_exit}" -eq 28 ]]; then
    echo "[ok] ${method}: ${check_result} (stream_timeout_expected)"
  else
    echo "[ok] ${method}: ${check_result}"
  fi
}

prime_session() {
  local headers_file body_file status_code
  headers_file="$(mktemp)"
  body_file="$(mktemp)"
  trap 'rm -f "${headers_file}" "${body_file}"' RETURN

  status_code="$(
    curl -sS \
      -D "${headers_file}" \
      -o "${body_file}" \
      -w '%{http_code}' \
      --max-time "${SMOKE_CURL_TIMEOUT_SECONDS}" \
      -X GET "${MCP_URL}" \
      -H "Authorization: Bearer ${MCP_TOKEN}" \
      -H "Accept: application/json, text/event-stream"
  )" || status_code="000"

  if [[ "${status_code}" != "200" && "${status_code}" != "204" ]]; then
    echo "[warn] session prime GET returned status=${status_code}; proceeding without explicit mcp-session-id"
    return 0
  fi

  MCP_SESSION_ID="$(
    awk 'BEGIN{IGNORECASE=1} /^mcp-session-id:/ {gsub(/\r/,"",$2); print $2; exit}' "${headers_file}"
  )"
  if [[ -n "${MCP_SESSION_ID}" ]]; then
    echo "[ok] session prime: mcp-session-id captured"
  else
    echo "[warn] session prime: no mcp-session-id header; proceeding"
  fi
}

echo "[mcp-smoke] url=${MCP_URL}"
prime_session

call_rpc "smoke-init" "initialize" '{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke_http","version":"0.1.0"}}'
call_rpc "smoke-list" "tools/list" '{}'
call_rpc "smoke-info" "tools/call" '{"name":"server_info","arguments":{}}'

echo "[mcp-smoke] all checks passed."
