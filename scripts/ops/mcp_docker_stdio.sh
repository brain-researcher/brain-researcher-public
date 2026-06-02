#!/usr/bin/env bash
set -euo pipefail

# Run Brain Researcher MCP server in Docker over stdio (for Claude/Codex MCP clients).
#
# Why this wrapper exists:
# - Running the container as root can leave root-owned files on the host when bind-mounting.
# - Running as a non-root UID/GID can break libraries that write caches under /root.
# - This wrapper runs the container with the host UID/GID and redirects HOME/cache dirs to /app/tmp.
#
# Usage:
#   scripts/ops/mcp_docker_stdio.sh
#
# Optional env overrides:
#   BR_MCP_DOCKER_IMAGE          (default: brain_researcher-mcp; fallback: brain-researcher-mcp)
#   BR_MCP_HOST_DATA_DIR         (default: <repo>/data)
#   BR_MCP_HOST_ARTIFACTS_DIR    (default: <repo>/artifacts)
#   BR_MCP_HOST_TMP_DIR          (default: <repo>/tmp)
#   BR_MCP_LOG_LEVEL             (default: INFO)
#   BR_MCP_ALLOW_NETWORK         (default: unset -> server default)
#   BR_MCP_ALLOW_DANGEROUS       (default: unset -> server default)
#   BR_MCP_ENABLE_TOOL_EXECUTE   (default: unset -> server default)
#   BR_MCP_TOOL_EXECUTE_ALLOWLIST(default: unset -> server default)

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Run Brain Researcher MCP server in Docker over stdio.

This is intended for MCP clients that support "stdio" transport (Claude Desktop / Codex CLI).

Examples:
  scripts/ops/mcp_docker_stdio.sh

Env:
  BR_MCP_DOCKER_IMAGE          Default: brain_researcher-mcp
  BR_MCP_HOST_DATA_DIR         Default: <repo>/data
  BR_MCP_HOST_ARTIFACTS_DIR    Default: <repo>/artifacts
  BR_MCP_HOST_TMP_DIR          Default: <repo>/tmp
EOF
  exit 0
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"

HOST_DATA_DIR="${BR_MCP_HOST_DATA_DIR:-${REPO_ROOT}/data}"
HOST_ARTIFACTS_DIR="${BR_MCP_HOST_ARTIFACTS_DIR:-${REPO_ROOT}/artifacts}"
HOST_TMP_DIR="${BR_MCP_HOST_TMP_DIR:-${REPO_ROOT}/tmp}"

mkdir -p "${HOST_DATA_DIR}" "${HOST_ARTIFACTS_DIR}" "${HOST_TMP_DIR}"
mkdir -p "${HOST_TMP_DIR}/home" "${HOST_TMP_DIR}/cache" "${HOST_TMP_DIR}/matplotlib"

IMAGE="${BR_MCP_DOCKER_IMAGE:-brain_researcher-mcp}"
if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
  ALT_IMAGE="brain-researcher-mcp"
  if docker image inspect "${ALT_IMAGE}" >/dev/null 2>&1; then
    IMAGE="${ALT_IMAGE}"
  else
    echo "MCP Docker image not found: ${IMAGE}" >&2
    echo "Build it from repo root:" >&2
    echo "  docker build -f infrastructure/docker/Dockerfile.mcp -t brain-researcher-mcp ." >&2
    echo "Or with compose:" >&2
    echo "  docker compose -f docker-compose.prod.yml build mcp" >&2
    exit 1
  fi
fi

UID_GID="1000:1000"
if command -v id >/dev/null 2>&1; then
  UID_GID="$(id -u):$(id -g)"
fi

ENV_ARGS=(
  -e "BR_MCP_TRANSPORT=stdio"
  -e "BR_MCP_LOG_LEVEL=${BR_MCP_LOG_LEVEL:-INFO}"
  -e "HOME=/app/tmp/home"
  -e "XDG_CACHE_HOME=/app/tmp/cache"
  -e "MPLCONFIGDIR=/app/tmp/matplotlib"
)

PASSTHROUGH_VARS=(
  BR_MCP_ALLOWED_ROOTS
  BR_MCP_RUN_ROOT
  BR_MCP_RUN_ROOT_ALIASES
  BR_MCP_ALLOW_NETWORK
  BR_MCP_ALLOW_DANGEROUS
  BR_MCP_ENABLE_TOOL_EXECUTE
  BR_MCP_TOOL_EXECUTE_ALLOWLIST
  BR_MCP_TOOL_TIMEOUT_S
  GOOGLE_API_KEY
  GEMINI_API_KEY
  OPENAI_API_KEY
  NEO4J_URI
  NEO4J_USER
  NEO4J_PASSWORD
  NEO4J_DATABASE
)
for var in "${PASSTHROUGH_VARS[@]}"; do
  if [[ -n "${!var:-}" ]]; then
    ENV_ARGS+=(-e "${var}=${!var}")
  fi
done

exec docker run --rm -i \
  --user "${UID_GID}" \
  "${ENV_ARGS[@]}" \
  -v "${HOST_ARTIFACTS_DIR}:/app/artifacts" \
  -v "${HOST_DATA_DIR}:/app/data" \
  -v "${HOST_TMP_DIR}:/app/tmp" \
  "${IMAGE}"
