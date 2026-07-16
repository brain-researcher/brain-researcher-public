#!/usr/bin/env bash
set -uo pipefail

# Run the release-readiness contract from a clean, non-local clone of the exact
# source commit. The gate is deliberately verification-only: it does not tag,
# push, publish, install a deployment, or start services.
#
# Inputs:
#   --release-version VERSION  Expected Python package version (required).
#   --output-dir PATH          Evidence directory (default: a temporary path).
# Environment:
#   BR_RELEASE_GATE_WORK_PARENT  Parent for the disposable fresh clone.
#   BR_RELEASE_GATE_PIP_CACHE_DIR Reusable pip cache for clean-install smokes.
# Outputs:
#   release-gate-report.json, source-commit.txt, versions.json, logs/,
#   SHA256SUMS, and release-gate-evidence.tar.gz below --output-dir.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"

usage() {
  cat <<'EOF'
Usage: scripts/ci/clean_clone_gate.sh --release-version VERSION [--output-dir PATH]

Verify release readiness from a fresh clone of the source HEAD and write a
self-contained evidence bundle. This command never tags or publishes a release.
EOF
}

RELEASE_VERSION=""
OUTPUT_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --release-version)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      RELEASE_VERSION="$2"
      shift 2
      ;;
    --output-dir)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      OUTPUT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${RELEASE_VERSION}" ]] ||
   [[ ! "${RELEASE_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z][0-9A-Za-z.-]*)?$ ]]; then
  echo "error: --release-version must be a semantic version" >&2
  usage >&2
  exit 2
fi

if [[ -z "${OUTPUT_DIR}" ]]; then
  OUTPUT_DIR="${TMPDIR:-/tmp}/brain-researcher-release-gate-${PPID}-$$"
fi
OUTPUT_DIR="$(realpath -m -- "${OUTPUT_DIR}")"
if [[ "${OUTPUT_DIR}" == "${SOURCE_ROOT}" ||
      "${OUTPUT_DIR}" == "${SOURCE_ROOT}/"* ||
      "${OUTPUT_DIR}" == "/" ]]; then
  echo "error: --output-dir must be outside the source checkout" >&2
  exit 2
fi

WORK_PARENT="${BR_RELEASE_GATE_WORK_PARENT:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}}"
mkdir -p -- "${WORK_PARENT}" "${OUTPUT_DIR}"
WORK_PARENT="$(cd -- "${WORK_PARENT}" && pwd -P)"
if [[ "${WORK_PARENT}" == "${SOURCE_ROOT}" ||
      "${WORK_PARENT}" == "${SOURCE_ROOT}/"* ]]; then
  echo "error: BR_RELEASE_GATE_WORK_PARENT must be outside the source checkout" >&2
  exit 2
fi

LOG_DIR="${OUTPUT_DIR}/logs"
rm -rf -- "${LOG_DIR}"
rm -f -- \
  "${OUTPUT_DIR}/release-gate-report.json" \
  "${OUTPUT_DIR}/source-commit.txt" \
  "${OUTPUT_DIR}/versions.json" \
  "${OUTPUT_DIR}/SHA256SUMS" \
  "${OUTPUT_DIR}/release-gate-evidence.tar.gz"
mkdir -p -- "${LOG_DIR}"

WORK_ROOT="$(mktemp -d "${WORK_PARENT}/brain-researcher-release-gate.XXXXXX")"
CLONE_ROOT="${WORK_ROOT}/source"
STEPS_FILE="${WORK_ROOT}/steps.tsv"
: >"${STEPS_FILE}"

SOURCE_SHA="$(git -C "${SOURCE_ROOT}" rev-parse --verify HEAD 2>/dev/null || printf 'unavailable')"
printf '%s\n' "${SOURCE_SHA}" >"${OUTPUT_DIR}/source-commit.txt"

PACKAGE_VERSION="unavailable"
EXPECTED_TAG="v${RELEASE_VERSION}"
MCP_CONTRACT_VERSION="unavailable"
OVERALL_STATUS=0
STEP_COUNT=0
FINALIZED=0
declare -A TOOL_VERSIONS=()
declare -A TOOL_STATES=()

mark_failure() {
  local status="${1:-1}"
  if [[ "${status}" -eq 0 ]]; then
    status=1
  fi
  if [[ "${OVERALL_STATUS}" -eq 0 ]]; then
    OVERALL_STATUS="${status}"
  fi
}

json_escape() {
  local value="${1-}"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "${value}"
}

capture_tool_version() {
  local key="$1"
  local executable="$2"
  shift 2
  local output
  local status

  if ! command -v "${executable}" >/dev/null 2>&1; then
    TOOL_VERSIONS["${key}"]="missing"
    TOOL_STATES["${key}"]="missing"
    echo "error: required tool is missing: ${key}" >&2
    return 1
  fi

  output="$("$@" 2>&1)"
  status=$?
  output="${output//$'\r'/ }"
  output="${output//$'\n'/; }"
  if [[ "${status}" -ne 0 || -z "${output}" ]]; then
    TOOL_VERSIONS["${key}"]="unavailable"
    TOOL_STATES["${key}"]="error"
    echo "error: could not determine ${key} version" >&2
    return 1
  fi
  TOOL_VERSIONS["${key}"]="${output}"
  TOOL_STATES["${key}"]="available"
  printf '%s=%s\n' "${key}" "${output}"
}

preflight_tools() {
  local status=0
  local python_minor=""
  local node_major=""
  local npm_major=""
  local uv_version=""

  capture_tool_version git git git --version || status=1
  capture_tool_version python python python --version || status=1
  capture_tool_version node node node --version || status=1
  capture_tool_version npm npm npm --version || status=1
  capture_tool_version uv uv uv --version || status=1
  capture_tool_version docker docker docker --version || status=1
  capture_tool_version docker_compose docker docker compose version || status=1
  capture_tool_version docker_buildx docker docker buildx version || status=1
  capture_tool_version helm helm helm version --short || status=1
  capture_tool_version tar tar tar --version || status=1
  capture_tool_version sha256sum sha256sum sha256sum --version || status=1

  if [[ "${TOOL_STATES[python]:-missing}" == "available" ]]; then
    python_minor="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
    if [[ "${python_minor}" != "3.11" ]]; then
      echo "error: release gate requires Python 3.11; found ${python_minor:-unknown}" >&2
      status=1
    fi
  fi
  if [[ "${TOOL_STATES[node]:-missing}" == "available" ]]; then
    node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || true)"
    if [[ "${node_major}" != "20" ]]; then
      echo "error: release gate requires Node 20; found ${node_major:-unknown}" >&2
      status=1
    fi
  fi
  if [[ "${TOOL_STATES[npm]:-missing}" == "available" ]]; then
    npm_major="$(npm --version 2>/dev/null | cut -d. -f1 || true)"
    if [[ "${npm_major}" != "10" ]]; then
      echo "error: release gate requires npm 10; found ${npm_major:-unknown}" >&2
      status=1
    fi
  fi
  if [[ "${TOOL_STATES[uv]:-missing}" == "available" ]]; then
    uv_version="$(uv --version 2>/dev/null | awk '{print $2}' || true)"
    if [[ "${uv_version}" != "0.9.21" ]]; then
      echo "error: release gate requires uv 0.9.21; found ${uv_version:-unknown}" >&2
      status=1
    fi
  fi
  return "${status}"
}

verify_source_clean() {
  local dirty
  dirty="$(git -C "${SOURCE_ROOT}" status --porcelain=v1 --untracked-files=all)" || return
  if [[ -n "${dirty}" ]]; then
    echo "error: source checkout is not clean" >&2
    printf '%s\n' "${dirty}" >&2
    return 1
  fi
  echo "source checkout clean: PASS"
}

create_fresh_clone() {
  if [[ "${SOURCE_SHA}" == "unavailable" ]]; then
    echo "error: source HEAD is unavailable" >&2
    return 1
  fi
  git clone --quiet --no-local --no-checkout -- "${SOURCE_ROOT}" "${CLONE_ROOT}" || return
  git -C "${CLONE_ROOT}" checkout --quiet --detach "${SOURCE_SHA}" || return
  local clone_sha
  clone_sha="$(git -C "${CLONE_ROOT}" rev-parse --verify HEAD)" || return
  if [[ "${clone_sha}" != "${SOURCE_SHA}" ]]; then
    echo "error: fresh clone resolved ${clone_sha}, expected ${SOURCE_SHA}" >&2
    return 1
  fi
  if [[ -n "$(git -C "${CLONE_ROOT}" status --porcelain=v1 --untracked-files=all)" ]]; then
    echo "error: fresh clone is not clean" >&2
    return 1
  fi
  printf 'fresh clone exact source commit: %s\n' "${clone_sha}"
}

validate_release_metadata() {
  if [[ ! -d "${CLONE_ROOT}" ]]; then
    echo "error: fresh clone is unavailable" >&2
    return 1
  fi

  PACKAGE_VERSION="$(python - "${CLONE_ROOT}/pyproject.toml" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    print(tomllib.load(handle)["project"]["version"])
PY
  )" || return
  EXPECTED_TAG="v${PACKAGE_VERSION}"
  MCP_CONTRACT_VERSION="$(tr -d '[:space:]' <"${CLONE_ROOT}/contracts/VERSION")" || return

  python - \
    "${CLONE_ROOT}" \
    "${RELEASE_VERSION}" \
    "${PACKAGE_VERSION}" \
    "${MCP_CONTRACT_VERSION}" <<'PY'
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
requested_version = sys.argv[2]
package_version = sys.argv[3]
contract_version = sys.argv[4]
manifest = json.loads((root / "release" / "manifest.json").read_text(encoding="utf-8"))
pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

assert requested_version == package_version, (
    f"release_version input {requested_version!r} does not match package version "
    f"{package_version!r}"
)
assert manifest["schema_version"] == "brain-researcher-release-v1"
assert manifest["software_release"]["version"] == package_version
assert manifest["software_release"]["git_tag"] == f"v{package_version}"
source_binding = manifest["software_release"]["source_commit_binding"]
assert source_binding["mode"] == "release_gate"
assert source_binding["value"] is None
assert source_binding["evidence"] == "release-gate-report.json"
assert manifest["python"]["distribution"] == "brain_researcher"
assert manifest["python"]["version"] == package_version
assert manifest["python"]["requires_python"] == pyproject["project"]["requires-python"]
assert manifest["mcp_contract"]["version"] == contract_version
assert manifest["mcp_contract"]["version_file"] == "contracts/VERSION"
assert manifest["containers"]["tag"] == f"{package_version}-oss-preview"
assert manifest["containers"]["status"] == "not_published"
assert manifest["helm"]["chart_version"] == package_version
assert manifest["helm"]["app_version"] == f"{package_version}-oss-preview"
assert manifest["helm"]["status"] == "experimental_static_only"
print(f"package_version={package_version}")
print(f"expected_tag=v{package_version}")
print(f"mcp_contract_version={contract_version}")
PY
}

check_lock_freshness() {
  cd -- "${CLONE_ROOT}" || return
  UV_BIN="$(command -v uv)" \
    BR_LOCK_PYTHON="$(command -v python)" \
    scripts/setup/refresh_locks.sh --check
}

clean_install_profile() {
  local profile="$1"
  cd -- "${CLONE_ROOT}" || return
  BR_CLEAN_INSTALL_PYTHON="$(command -v python)" \
    BR_CLEAN_INSTALL_ROOT="${WORK_ROOT}/venvs" \
    BR_CLEAN_INSTALL_LOG_DIR="${WORK_ROOT}/clean-install-logs" \
    BR_CLEAN_INSTALL_PIP_CACHE_DIR="${BR_RELEASE_GATE_PIP_CACHE_DIR:-${WORK_ROOT}/pip-cache}" \
    scripts/setup/smoke_clean_install.sh "${profile}"
}

run_python_shard() {
  local shard="$1"
  cd -- "${CLONE_ROOT}" || return
  PYTHON_BIN="${WORK_ROOT}/venvs/ci/bin/python" tests/run_tests.sh "${shard}"
}

run_release_gate_contract() {
  cd -- "${CLONE_ROOT}" || return
  PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="${CLONE_ROOT}/src" \
    "${WORK_ROOT}/venvs/ci/bin/python" -m pytest -q \
      tests/unit/config/test_release_gate_contract.py \
      tests/unit/config/test_software_release_contract.py \
      --noconftest -p no:cacheprovider --tb=short
}

run_strict_docs() {
  cd -- "${CLONE_ROOT}" || return
  "${WORK_ROOT}/venvs/ci/bin/python" -m mkdocs build --strict --clean || return
  PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="${CLONE_ROOT}/src" \
    "${WORK_ROOT}/venvs/ci/bin/python" -m pytest -q \
      tests/unit/config/test_docs_integrity.py \
      --noconftest -p no:cacheprovider --tb=short
}

run_services() {
  cd -- "${CLONE_ROOT}" || return
  PYTHON_BIN="${WORK_ROOT}/venvs/ci-services/bin/python" tests/run_tests.sh services
}

install_web() {
  cd -- "${CLONE_ROOT}" || return
  npm --prefix apps/web-ui ci
}

run_web() {
  cd -- "${CLONE_ROOT}" || return
  CI=true \
    NEXT_TELEMETRY_DISABLED=1 \
    PYTHON_BIN="${WORK_ROOT}/venvs/ci/bin/python" \
    NPM_BIN="$(command -v npm)" \
    tests/run_tests.sh web
}

run_deployment_static() {
  cd -- "${CLONE_ROOT}" || return
  PYTHON_BIN="${WORK_ROOT}/venvs/ci/bin/python" tests/run_tests.sh deployment-static
}

verify_source_commit_unchanged() {
  local clone_sha
  clone_sha="$(git -C "${CLONE_ROOT}" rev-parse --verify HEAD)" || return
  [[ "${clone_sha}" == "${SOURCE_SHA}" ]] || {
    echo "error: clone HEAD changed during verification" >&2
    return 1
  }
  git -C "${CLONE_ROOT}" diff --quiet || return
  git -C "${CLONE_ROOT}" diff --cached --quiet || return
  echo "source commit remained unchanged: PASS"
}

run_step() {
  local step_id="$1"
  local description="$2"
  shift 2
  local sequence
  local log_relative
  local log_path
  local status

  STEP_COUNT=$((STEP_COUNT + 1))
  printf -v sequence '%02d' "${STEP_COUNT}"
  log_relative="logs/${sequence}-${step_id}.log"
  log_path="${OUTPUT_DIR}/${log_relative}"
  printf '[release-gate] %s\n' "${description}"
  if "$@" >"${log_path}" 2>&1; then
    status=0
    printf '[release-gate] PASS: %s\n' "${description}"
  else
    status=$?
    mark_failure "${status}"
    printf '[release-gate] FAIL (%s): %s; see %s\n' \
      "${status}" "${description}" "${log_relative}" >&2
  fi
  printf '%s\t%s\t%s\t%s\n' \
    "${step_id}" "${description}" "${status}" "${log_relative}" >>"${STEPS_FILE}"
}

write_versions_json() {
  local path="${OUTPUT_DIR}/versions.json"
  local keys=(python node npm docker docker_compose docker_buildx helm uv git tar sha256sum)
  local first=1
  local key
  {
    printf '{\n'
    printf '  "schema_version": "brain-researcher-release-gate-versions-v1",\n'
    printf '  "source_commit": "%s",\n' "$(json_escape "${SOURCE_SHA}")"
    printf '  "package_version": "%s",\n' "$(json_escape "${PACKAGE_VERSION}")"
    printf '  "expected_tag": "%s",\n' "$(json_escape "${EXPECTED_TAG}")"
    printf '  "mcp_contract_version": "%s",\n' "$(json_escape "${MCP_CONTRACT_VERSION}")"
    printf '  "tools": {\n'
    for key in "${keys[@]}"; do
      if [[ "${first}" -eq 0 ]]; then
        printf ',\n'
      fi
      first=0
      printf '    "%s": {"state": "%s", "version": "%s"}' \
        "$(json_escape "${key}")" \
        "$(json_escape "${TOOL_STATES[${key}]:-not_checked}")" \
        "$(json_escape "${TOOL_VERSIONS[${key}]:-not_checked}")"
    done
    printf '\n  }\n}\n'
  } >"${path}"
}

write_report_json() {
  local path="${OUTPUT_DIR}/release-gate-report.json"
  local gate_status="passed"
  local first=1
  local step_id description status log_relative check_status
  if [[ "${OVERALL_STATUS}" -ne 0 ]]; then
    gate_status="failed"
  fi
  {
    printf '{\n'
    printf '  "schema_version": "brain-researcher-release-gate-v1",\n'
    printf '  "status": "%s",\n' "${gate_status}"
    printf '  "exit_code": %s,\n' "${OVERALL_STATUS}"
    printf '  "source_commit": "%s",\n' "$(json_escape "${SOURCE_SHA}")"
    printf '  "package_version": "%s",\n' "$(json_escape "${PACKAGE_VERSION}")"
    printf '  "expected_tag": "%s",\n' "$(json_escape "${EXPECTED_TAG}")"
    printf '  "mcp_contract_version": "%s",\n' "$(json_escape "${MCP_CONTRACT_VERSION}")"
    printf '  "fresh_clone": {"transport": "git clone --no-local", "exact_commit_required": true},\n'
    printf '  "execution_boundaries": {"tagged": false, "pushed": false, "published": false, "services_started": false},\n'
    printf '  "checks": [\n'
    while IFS=$'\t' read -r step_id description status log_relative; do
      [[ -n "${step_id}" ]] || continue
      if [[ "${status}" -eq 0 ]]; then
        check_status="passed"
      else
        check_status="failed"
      fi
      if [[ "${first}" -eq 0 ]]; then
        printf ',\n'
      fi
      first=0
      printf '    {"id": "%s", "description": "%s", "status": "%s", "exit_code": %s, "log": "%s"}' \
        "$(json_escape "${step_id}")" \
        "$(json_escape "${description}")" \
        "${check_status}" \
        "${status}" \
        "$(json_escape "${log_relative}")"
    done <"${STEPS_FILE}"
    printf '\n  ],\n'
    printf '  "artifacts": {"versions": "versions.json", "checksums": "SHA256SUMS", "archive": "release-gate-evidence.tar.gz"}\n'
    printf '}\n'
  } >"${path}"
}

write_checksums() {
  local checksum_tmp="${WORK_ROOT}/SHA256SUMS"
  local relative
  local files=(release-gate-report.json source-commit.txt versions.json)
  while IFS= read -r -d '' relative; do
    files+=("${relative#${OUTPUT_DIR}/}")
  done < <(find "${LOG_DIR}" -type f -print0 | LC_ALL=C sort -z)

  : >"${checksum_tmp}"
  for relative in "${files[@]}"; do
    (
      cd -- "${OUTPUT_DIR}" || exit
      sha256sum -- "${relative}"
    ) >>"${checksum_tmp}" || return
  done
  mv -- "${checksum_tmp}" "${OUTPUT_DIR}/SHA256SUMS"
}

write_archive() {
  local archive_tmp="${WORK_ROOT}/release-gate-evidence.tar.gz"
  tar -czf "${archive_tmp}" -C "${OUTPUT_DIR}" \
    release-gate-report.json \
    source-commit.txt \
    versions.json \
    logs \
    SHA256SUMS || return
  mv -- "${archive_tmp}" "${OUTPUT_DIR}/release-gate-evidence.tar.gz"
}

finalize_evidence() {
  if [[ "${FINALIZED}" -eq 1 ]]; then
    return
  fi
  FINALIZED=1

  if ! command -v sha256sum >/dev/null 2>&1; then
    mark_failure 1
    : >"${OUTPUT_DIR}/SHA256SUMS"
  fi
  if ! command -v tar >/dev/null 2>&1; then
    mark_failure 1
  fi

  write_versions_json || mark_failure $?
  write_report_json || mark_failure $?
  if command -v sha256sum >/dev/null 2>&1; then
    write_checksums || mark_failure $?
  fi
  if command -v tar >/dev/null 2>&1; then
    write_archive || mark_failure $?
  else
    : >"${OUTPUT_DIR}/release-gate-evidence.tar.gz"
  fi

  # If packaging changed the outcome, refresh the status-bearing files and
  # their derived evidence once more.
  write_versions_json || true
  write_report_json || true
  if command -v sha256sum >/dev/null 2>&1; then
    write_checksums || true
  fi
  if command -v tar >/dev/null 2>&1; then
    write_archive || true
  fi
}

on_exit() {
  local shell_status=$?
  trap - EXIT
  if [[ "${shell_status}" -ne 0 ]]; then
    mark_failure "${shell_status}"
  fi
  finalize_evidence
  rm -rf -- "${WORK_ROOT}"
  exit "${OVERALL_STATUS}"
}
trap on_exit EXIT

run_step preflight-tools "verify required tool inventory and versions" preflight_tools
run_step source-clean "require a clean source checkout" verify_source_clean
run_step fresh-clone "clone with --no-local and check out the exact source SHA" create_fresh_clone
run_step release-metadata "validate release, package, container, Helm, and MCP version bindings" validate_release_metadata
run_step lock-freshness "verify uv.lock and all Python lock exports are fresh" check_lock_freshness
run_step clean-ci-install "create and verify the locked clean CI environment" clean_install_profile ci
run_step release-contract "validate the release gate and manual workflow contracts" run_release_gate_contract
run_step unit-pr-smoke "run the PR unit smoke shard" run_python_shard unit-pr-smoke
run_step contracts "run offline repository and public contract checks" run_python_shard contracts
run_step reproducibility "run offline reproducibility verifier checks" run_python_shard reproducibility
run_step docs "build strict documentation and validate internal links" run_strict_docs
run_step clean-ci-services-install "create and verify the locked CI services environment" clean_install_profile ci-services
run_step services "run focused service checks" run_services
run_step npm-ci "install the Web UI from package-lock.json" install_web
run_step web "lint, test, build, and validate the Web UI" run_web
run_step deployment-static "validate deployment assets without starting services" run_deployment_static
run_step source-unchanged "verify the fresh clone still resolves to the exact source commit" verify_source_commit_unchanged

exit "${OVERALL_STATUS}"
