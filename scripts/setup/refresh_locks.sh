#!/usr/bin/env bash
set -euo pipefail

# Rebuild or verify the seven supported Python 3.11 dependency exports.
#
# Inputs:
#   pyproject.toml and uv.lock at the repository root.
# Outputs:
#   uv.lock and requirements/locks/{core,mcp,agent,br-kg,ci,ci-services,dev}-py311.txt.
# Environment:
#   UV_BIN overrides the uv executable (default: uv).
#   BR_LOCK_PYTHON overrides the Python 3.11 interpreter (default: python).
#   TMPDIR controls the temporary directory used by --check.
# Logs:
#   Progress and diagnostics are written to stdout/stderr; no persistent log is
#   created by this deterministic metadata operation.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
LOCK_DIR="${REPO_ROOT}/requirements/locks"
UV_BIN="${UV_BIN:-uv}"
PYTHON_BIN="${BR_LOCK_PYTHON:-python}"

PROFILES=(core mcp agent br-kg ci ci-services dev)
declare -A EXTRAS=(
  [core]=""
  [mcp]="mcp"
  [agent]="agent"
  [br-kg]="br-kg"
  [ci]="ci"
  [ci-services]="ci-services"
  [dev]="all"
)

usage() {
  cat <<'EOF'
Usage: scripts/setup/refresh_locks.sh [--check|--upgrade]

With no option, preserve the currently locked versions and regenerate the seven
requirements exports. --upgrade intentionally refreshes all versions. --check
is read-only and fails if uv.lock or any tracked export is stale.
EOF
}

mode="refresh"
case "${1:-}" in
  "") ;;
  --check) mode="check" ;;
  --upgrade) mode="upgrade" ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac
if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
fi

command -v "${UV_BIN}" >/dev/null 2>&1 || {
  echo "error: uv is required (expected version 0.9.21)" >&2
  exit 1
}
command -v "${PYTHON_BIN}" >/dev/null 2>&1 || {
  echo "error: Python interpreter not found: ${PYTHON_BIN}" >&2
  exit 1
}

python_version="$(${PYTHON_BIN} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "${python_version}" != "3.11" ]]; then
  echo "error: lock generation requires Python 3.11; found ${python_version}" >&2
  exit 1
fi

export_profile() {
  local profile="$1"
  local output_path="$2"
  local -a args=(
    export
    --quiet
    --locked
    --no-dev
    --no-emit-project
    --no-hashes
    --no-header
    --format requirements.txt
    --output-file "${output_path}"
    --extra build
  )
  if [[ -n "${EXTRAS[${profile}]}" ]]; then
    args+=(--extra "${EXTRAS[${profile}]}")
  fi
  "${UV_BIN}" "${args[@]}"
}

cd -- "${REPO_ROOT}"

if [[ "${mode}" == "check" ]]; then
  "${UV_BIN}" lock --quiet --check --python "${PYTHON_BIN}" --no-python-downloads
  tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/brain-researcher-lock-check.XXXXXX")"
  trap 'rm -rf -- "${tmp_dir}"' EXIT
  stale=0
  for profile in "${PROFILES[@]}"; do
    generated="${tmp_dir}/${profile}-py311.txt"
    tracked="${LOCK_DIR}/${profile}-py311.txt"
    export_profile "${profile}" "${generated}"
    if [[ ! -f "${tracked}" ]] || ! cmp -s -- "${generated}" "${tracked}"; then
      echo "stale lock export: requirements/locks/${profile}-py311.txt" >&2
      stale=1
    fi
  done
  if [[ "${stale}" -ne 0 ]]; then
    echo "run scripts/setup/refresh_locks.sh to regenerate exports" >&2
    exit 1
  fi
  echo "lock contract: PASS"
  exit 0
fi

mkdir -p -- "${LOCK_DIR}"
lock_args=(lock --quiet --python "${PYTHON_BIN}" --no-python-downloads)
if [[ "${mode}" == "upgrade" ]]; then
  lock_args+=(--upgrade)
fi
"${UV_BIN}" "${lock_args[@]}"

for profile in "${PROFILES[@]}"; do
  export_profile "${profile}" "${LOCK_DIR}/${profile}-py311.txt"
done

echo "updated uv.lock and seven Python 3.11 requirement exports"
