#!/usr/bin/env bash
set -euo pipefail

# Hosted-cloud runtimes must boot with a per-pod marimo auth token mounted at
# /run/secrets/br_marimo_runtime_token (mode 0400/0600). Refuse to start if it's
# missing or world-readable so orchestrator → marimo cell injection is safely
# authenticated. Dev / local modes fall back to no-token.
BR_MARIMO_RUNTIME_TOKEN_PATH="${BR_MARIMO_RUNTIME_TOKEN_PATH:-/run/secrets/br_marimo_runtime_token}"
if [[ "${BR_PRODUCT_MODE:-}" == "hosted-cloud" ]]; then
  if [[ ! -s "${BR_MARIMO_RUNTIME_TOKEN_PATH}" ]]; then
    echo "br-marimo: runtime token file ${BR_MARIMO_RUNTIME_TOKEN_PATH} missing or empty (hosted-cloud)" >&2
    exit 78
  fi
  # The token is exposed via a projected-volume symlink; dereference (-L) so we
  # read the real file's mode (e.g. 0440) rather than the symlink's (lrwxrwxrwx/777).
  token_mode="$(stat -L -c '%a' "${BR_MARIMO_RUNTIME_TOKEN_PATH}" 2>/dev/null || echo '')"
  case "${token_mode}" in
    400|440|600|640)
      ;;
    *)
      echo "br-marimo: runtime token file mode ${token_mode:-unknown} (expected 0400/0440/0600/0640)" >&2
      exit 78
      ;;
  esac
fi

# Materialize Notebook Intelligence settings only when this runtime explicitly
# enables the separate NBI integration layer. Hosted marimo now defaults to the
# native marimo AI/MCP path to keep the kernel on the same dependency surface as
# the BR agent runtime.
if [[ "${BR_NOTEBOOK_INTELLIGENCE_ENABLED:-false}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
  python -m brain_researcher.integrations.notebook_intelligence.bootstrap \
    --write-extension-metadata \
    --write-user-config \
    --user-home "${HOME}"
fi

python -m brain_researcher.integrations.marimo.bootstrap \
  --user-home "${HOME}"

if [[ "${BR_MARIMO_ENABLE_XVFB:-true}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]] \
  && [[ -z "${DISPLAY:-}" ]] \
  && command -v Xvfb >/dev/null 2>&1; then
  xvfb_display="${BR_MARIMO_XVFB_DISPLAY:-:99}"
  xvfb_screen="${BR_MARIMO_XVFB_SCREEN:-1920x1080x24}"
  xvfb_log="${BR_MARIMO_XVFB_LOG:-/tmp/br_marimo_xvfb.log}"
  Xvfb "${xvfb_display}" -screen 0 "${xvfb_screen}" -nolisten tcp >"${xvfb_log}" 2>&1 &
  export BR_MARIMO_XVFB_PID="$!"
  export DISPLAY="${xvfb_display}"
fi

template_root="${BR_TEMPLATE_ROOT:-/app/notebooks/templates}"
workspace_root="${BR_MARIMO_RUNTIME_WORKSPACE_HOME:-${PWD}}"
workspace_notebooks_dir="${workspace_root%/}/notebooks"

if [[ -d "${template_root}" ]]; then
  mkdir -p "${workspace_notebooks_dir}"
  while IFS= read -r -d '' template_path; do
    template_name="$(basename "${template_path}")"
    target_path="${workspace_notebooks_dir}/${template_name}"
    if [[ ! -f "${target_path}" ]]; then
      cp "${template_path}" "${target_path}"
    fi
  done < <(find "${template_root}" -maxdepth 1 -type f -name '*.py' -print0)
fi

taskbeacon_repo="${BR_MARIMO_RUNTIME_TASKBEACON_REPO:-}"
taskbeacon_target_path="${BR_MARIMO_RUNTIME_TASKBEACON_TARGET_PATH:-}"
taskbeacon_ref="${BR_MARIMO_RUNTIME_TASKBEACON_REF:-}"

if [[ -n "${taskbeacon_repo}" && -n "${taskbeacon_target_path}" ]]; then
  taskbeacon_args=(
    -m brain_researcher.services.orchestrator.taskbeacon_handoff
    --workspace-root "${workspace_root}"
    --repo "${taskbeacon_repo}"
    --target-path "${taskbeacon_target_path}"
  )
  if [[ -n "${taskbeacon_ref}" ]]; then
    taskbeacon_args+=(--ref "${taskbeacon_ref}")
  fi
  if ! python "${taskbeacon_args[@]}"; then
    echo "TaskBeacon import failed for ${taskbeacon_repo}; continuing runtime startup." >&2
  fi
fi

# Wait for the BR MCP server to be reachable before launching marimo. marimo's
# MCP client connects on startup and, on a single failure, marks the server as
# ERROR and removes it from monitoring WITHOUT retrying — so a boot-time race
# (the MCP service briefly unreachable, e.g. during its own redeploy or before
# k8s service DNS settles) would permanently leave this runtime with no MCP
# tools and a broken AI sidebar. Poll until the MCP endpoint answers (any HTTP
# status = reachable), bounded by a timeout; if it never comes up we still launch
# marimo so the notebook itself works (just without MCP tools).
if [[ -n "${BR_MCP_HTTP_URL:-}" ]] \
  && [[ "${BR_MARIMO_WAIT_FOR_MCP:-true}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]] \
  && command -v curl >/dev/null 2>&1; then
  mcp_wait_timeout="${BR_MARIMO_MCP_WAIT_TIMEOUT_S:-45}"
  mcp_wait_deadline=$(( SECONDS + mcp_wait_timeout ))
  until curl -sS -o /dev/null --max-time 3 "${BR_MCP_HTTP_URL}"; do
    if (( SECONDS >= mcp_wait_deadline )); then
      echo "br-marimo: MCP server ${BR_MCP_HTTP_URL} not reachable after ${mcp_wait_timeout}s; launching marimo anyway (MCP tools may be unavailable until restart)" >&2
      break
    fi
    echo "br-marimo: waiting for MCP server ${BR_MCP_HTTP_URL} to become reachable..." >&2
    sleep 2
  done
fi

exec "$@"
