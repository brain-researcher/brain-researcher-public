#!/usr/bin/env bash
set -euo pipefail

# Build a fresh Python 3.11 venv from one tracked lock and verify the installed
# project entrypoints. This installs the checkout in editable mode because the
# runtime config contract currently uses the clone's repo-level configs/ tree.
#
# Inputs:
#   One profile: core, mcp, agent, br-kg, dev, or all (default: core).
# Outputs:
#   Fresh venvs below BR_CLEAN_INSTALL_ROOT and one log per profile.
# Environment:
#   BR_CLEAN_INSTALL_PYTHON: Python 3.11 interpreter (default: python).
#   BR_CLEAN_INSTALL_ROOT: venv/log root (default: $TMPDIR/brain-researcher-clean-install).
#   BR_CLEAN_INSTALL_LOG_DIR: persistent log directory override.
# Logs:
#   $BR_CLEAN_INSTALL_LOG_DIR/<profile>.log, plus mirrored stdout/stderr.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_BIN="${BR_CLEAN_INSTALL_PYTHON:-python}"
SMOKE_ROOT="${BR_CLEAN_INSTALL_ROOT:-${TMPDIR:-/tmp}/brain-researcher-clean-install}"
LOG_DIR="${BR_CLEAN_INSTALL_LOG_DIR:-${SMOKE_ROOT}/logs}"

PROFILES=(core mcp agent br-kg dev)
declare -A EXTRAS=(
  [core]=""
  [mcp]="mcp"
  [agent]="agent"
  [br-kg]="br-kg"
  [dev]="all"
)

usage() {
  echo "Usage: scripts/setup/smoke_clean_install.sh [core|mcp|agent|br-kg|dev|all]"
}

requested="${1:-core}"
if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
fi
case "${requested}" in
  core|mcp|agent|br-kg|dev|all) ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

command -v "${PYTHON_BIN}" >/dev/null 2>&1 || {
  echo "error: Python interpreter not found: ${PYTHON_BIN}" >&2
  exit 1
}
python_version="$(${PYTHON_BIN} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "${python_version}" != "3.11" ]]; then
  echo "error: clean-install smoke requires Python 3.11; found ${python_version}" >&2
  exit 1
fi

mkdir -p -- "${SMOKE_ROOT}" "${LOG_DIR}"

smoke_profile_inner() (
  set -euo pipefail
  local profile="$1"
  local venv_dir="${SMOKE_ROOT}/${profile}"
  local lock_file="${REPO_ROOT}/requirements/locks/${profile}-py311.txt"
  local install_target="${REPO_ROOT}"
  if [[ -n "${EXTRAS[${profile}]}" ]]; then
    install_target="${REPO_ROOT}[${EXTRAS[${profile}]}]"
  fi

  echo "profile=${profile}"
  echo "python=${PYTHON_BIN}"
  echo "venv=${venv_dir}"
  echo "lock=${lock_file}"

  [[ -f "${lock_file}" ]] || {
    echo "error: missing lock file: ${lock_file}" >&2
    exit 1
  }

  "${PYTHON_BIN}" -m venv --clear "${venv_dir}"
  mkdir -p -- \
    "${venv_dir}/home/.cache" \
    "${venv_dir}/home/.config" \
    "${venv_dir}/tmp" \
    "${SMOKE_ROOT}/pip-cache"

  run_clean() {
    local -a clean_env=(
      env -i
      HOME="${venv_dir}/home"
      XDG_CACHE_HOME="${venv_dir}/home/.cache"
      XDG_CONFIG_HOME="${venv_dir}/home/.config"
      TMPDIR="${venv_dir}/tmp"
      LANG="${LANG:-C.UTF-8}"
      PATH="${venv_dir}/bin:/usr/bin:/bin"
      VIRTUAL_ENV="${venv_dir}"
      BRAIN_RESEARCHER_SKIP_DOTENV=1
      BR_CONFIG_ROOT="${REPO_ROOT}"
      GIT_CONFIG_GLOBAL=/dev/null
      GIT_CONFIG_NOSYSTEM=1
      GIT_TERMINAL_PROMPT=0
      NO_COLOR=1
      PIP_CACHE_DIR="${SMOKE_ROOT}/pip-cache"
      PIP_CONFIG_FILE=/dev/null
      PIP_DISABLE_PIP_VERSION_CHECK=1
      PIP_NO_INPUT=1
      PYTHONNOUSERSITE=1
    )
    local variable
    for variable in \
      HTTP_PROXY HTTPS_PROXY NO_PROXY ALL_PROXY \
      http_proxy https_proxy no_proxy all_proxy \
      SSL_CERT_FILE REQUESTS_CA_BUNDLE CURL_CA_BUNDLE; do
      if [[ -n "${!variable:-}" ]]; then
        clean_env+=("${variable}=${!variable}")
      fi
    done
    "${clean_env[@]}" "$@"
  }

  run_clean "${venv_dir}/bin/python" -m pip install --quiet \
    -r "${lock_file}"
  run_clean "${venv_dir}/bin/python" -m pip install --quiet \
    --no-deps --no-build-isolation -e "${install_target}"
  run_clean "${venv_dir}/bin/python" -m pip check
  run_clean "${venv_dir}/bin/python" - "${venv_dir}/home" <<'PY'
import os
import sys
from pathlib import Path

assert Path.home().resolve() == Path(sys.argv[1]).resolve()
for name in (
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "NEO4J_AUTH",
    "NCBI_API_KEY",
    "OPENAI_API_KEY",
):
    assert name not in os.environ, name
print("isolated process environment: PASS")
PY

  run_clean "${venv_dir}/bin/brain-researcher" --help >/dev/null
  run_clean "${venv_dir}/bin/brain-researcher" --version
  run_clean "${venv_dir}/bin/brain-researcher-mcp" --help >/dev/null
  run_clean "${venv_dir}/bin/brain-researcher-mcp" --version
  run_clean "${venv_dir}/bin/python" "${REPO_ROOT}/scripts/setup/verify_environment.py" \
    --profile "${profile}"

  case "${profile}" in
    core)
      run_clean "${venv_dir}/bin/python" - <<'PY'
import sys
from typer.testing import CliRunner
from brain_researcher.cli.main import app

result = CliRunner().invoke(app, ["--help"])
assert result.exit_code == 0, result.output
for forbidden in ("mcp", "langgraph", "nibabel", "nilearn", "neo4j"):
    assert not any(
        name == forbidden or name.startswith(forbidden + ".")
        for name in sys.modules
    ), forbidden
print("core import boundary: PASS")
PY
      ;;
    mcp)
      run_clean "${venv_dir}/bin/python" -c \
        'import brain_researcher.services.mcp.server; print("mcp import: PASS")'
      ;;
    agent)
      run_clean "${venv_dir}/bin/brain-researcher" agent --help >/dev/null
      ;;
    br-kg)
      run_clean "${venv_dir}/bin/brain-researcher" br-kg --help >/dev/null
      ;;
    dev)
      run_clean "${venv_dir}/bin/brain-researcher" agent --help >/dev/null
      run_clean "${venv_dir}/bin/brain-researcher" br-kg --help >/dev/null
      run_clean "${venv_dir}/bin/python" -c \
        'import brain_researcher.services.mcp.server; print("mcp import: PASS")'
      ;;
  esac

  echo "clean-install ${profile}: PASS"
)

smoke_profile() {
  local profile="$1"
  local log_file="${LOG_DIR}/${profile}.log"
  local -a statuses

  if smoke_profile_inner "${profile}" 2>&1 | tee "${log_file}"; then
    return 0
  fi
  statuses=("${PIPESTATUS[@]}")
  if [[ "${statuses[0]}" -ne 0 ]]; then
    return "${statuses[0]}"
  fi
  return "${statuses[1]}"
}

if [[ "${requested}" == "all" ]]; then
  for profile in "${PROFILES[@]}"; do
    smoke_profile "${profile}"
  done
else
  smoke_profile "${requested}"
fi
