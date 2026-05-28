#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

export BR_MCP_TRANSPORT="${BR_MCP_TRANSPORT:-streamable-http}"
export BR_MCP_HOST="${BR_MCP_HOST:-127.0.0.1}"
export BR_MCP_PORT="${BR_MCP_PORT:-7000}"
export BR_MCP_MOUNT_PATH="${BR_MCP_MOUNT_PATH:-/mcp}"
export BR_MCP_STATELESS_HTTP="${BR_MCP_STATELESS_HTTP:-1}"

if [[ "${BR_MCP_TRANSPORT}" != "streamable-http" && "${BR_MCP_TRANSPORT}" != "sse" ]]; then
  echo "BR_MCP_TRANSPORT must be streamable-http or sse for HTTP mode." >&2
  exit 1
fi

# Local convenience: if BR_MCP_AUTH_TOKEN is not set, reuse resolved BR_MCP_TOKEN
# as a break-glass bearer token so smoke checks can run without JWT setup.
if [[ "${BR_MCP_AUTO_AUTH_TOKEN:-1}" == "1" && -z "${BR_MCP_AUTH_TOKEN:-}" ]]; then
  if resolved_token="$("${REPO_ROOT}/scripts/mcp/resolve_br_mcp_token.sh" 2>/dev/null)"; then
    export BR_MCP_AUTH_TOKEN="${resolved_token}"
  fi
fi

echo "[mcp-http] transport=${BR_MCP_TRANSPORT}"
echo "[mcp-http] health=http://${BR_MCP_HOST}:${BR_MCP_PORT}/healthz"
echo "[mcp-http] rpc=http://${BR_MCP_HOST}:${BR_MCP_PORT}${BR_MCP_MOUNT_PATH}"
echo "[mcp-http] auth_mode=${BR_MCP_AUTH_MODE:-auto}"
echo "[mcp-http] auth_token_set=$([[ -n "${BR_MCP_AUTH_TOKEN:-}" ]] && echo yes || echo no)"
echo "[mcp-http] stateless_http=${BR_MCP_STATELESS_HTTP}"

cd "${REPO_ROOT}"
exec python -m brain_researcher.services.mcp.server
