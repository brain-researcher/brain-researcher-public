#!/usr/bin/env bash
set -euo pipefail

# Merge duplicated artifact/log/test folders into canonical locations and
# replace legacy paths with symlinks so existing scripts keep working.
#
# Default mode is dry-run. Use --apply to execute.
#
# Example:
#   scripts/ops/merge_artifact_paths.sh
#   scripts/ops/merge_artifact_paths.sh --apply

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

APPLY=0
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
elif [[ -n "${1:-}" ]]; then
  echo "Unknown argument: ${1}"
  echo "Usage: $0 [--apply]"
  exit 2
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
STATE_ROOT="${REPO_ROOT}/tmp/merge_artifact_paths_${STAMP}"
CONFLICT_ROOT="${STATE_ROOT}/conflicts"
LOG_FILE="${STATE_ROOT}/run.log"

mkdir -p "${STATE_ROOT}" "${CONFLICT_ROOT}"
touch "${LOG_FILE}"

run() {
  if [[ "${APPLY}" -eq 1 ]]; then
    "$@"
  else
    echo "[dry-run] $*"
  fi
}

log() {
  local msg="$1"
  echo "${msg}" | tee -a "${LOG_FILE}"
}

merge_one() {
  local src_rel="$1"
  local dst_rel="$2"

  local src="${REPO_ROOT}/${src_rel}"
  local dst="${REPO_ROOT}/${dst_rel}"
  local safe_src="${src_rel//\//__}"
  local conflict_dir="${CONFLICT_ROOT}/${safe_src}"

  if [[ -L "${src}" ]]; then
    log "SKIP (already symlink): ${src_rel}"
    return 0
  fi

  if [[ ! -e "${src}" ]]; then
    log "SKIP (missing): ${src_rel}"
    return 0
  fi

  if [[ "${src}" == "${dst}" ]]; then
    log "SKIP (same path): ${src_rel}"
    return 0
  fi

  log "MERGE ${src_rel} -> ${dst_rel}"
  run mkdir -p "${dst}"

  if [[ "${APPLY}" -eq 1 ]]; then
    # Move non-conflicting files first.
    rsync -a --remove-source-files --ignore-existing "${src}/" "${dst}/"

    # Any leftovers (typically name collisions) are preserved for manual review.
    if find "${src}" -type f -print -quit | grep -q .; then
      mkdir -p "${conflict_dir}"
      rsync -a --remove-source-files "${src}/" "${conflict_dir}/"
      log "  WARN leftover files moved to ${conflict_dir}"
    fi

    # Best-effort cleanup.
    find "${src}" -depth -type d -empty -delete || true
    if [[ -d "${src}" ]] && [[ -z "$(find "${src}" -mindepth 1 -print -quit)" ]]; then
      rmdir "${src}" || true
    fi

    # If anything still exists at source, preserve it in state dir.
    if [[ -e "${src}" && ! -L "${src}" ]]; then
      local residual="${STATE_ROOT}/residual/${safe_src}"
      mkdir -p "$(dirname "${residual}")"
      mv "${src}" "${residual}"
      log "  WARN residual source moved to ${residual}"
    fi

    mkdir -p "$(dirname "${src}")"
    ln -sfn "${dst}" "${src}"
    log "  LINK ${src_rel} -> ${dst_rel}"
  else
    log "  [dry-run] mkdir -p ${dst}"
    log "  [dry-run] rsync -a --remove-source-files --ignore-existing ${src}/ ${dst}/"
    log "  [dry-run] rsync leftovers to ${conflict_dir} (if any)"
    log "  [dry-run] ln -sfn ${dst} ${src}"
  fi
}

# Ordered mapping:
# 1) Nested paths first
# 2) Parent paths later
MAP=(
  "outputs/out/tmp_tests/pytest-of-zijiaochen|.pytest_tmp/pytest-of-zijiaochen"
  "artifacts/tests/results|test-results/artifacts-tests"
  "outputs/test_logs|artifacts/tests/logs"
  "outputs/test_outputs|artifacts/tests/outputs"
  "outputs/logs|logs/outputs"
  "artifacts/logs|logs/artifacts"
  "data/logs|logs/data"
  "artifacts/mcp_runs|data/runs/mcp_runs"
)

log "== merge_artifact_paths.sh =="
log "repo_root: ${REPO_ROOT}"
log "mode: $([[ "${APPLY}" -eq 1 ]] && echo apply || echo dry-run)"
log "state_root: ${STATE_ROOT}"
log ""

for item in "${MAP[@]}"; do
  src_rel="${item%%|*}"
  dst_rel="${item##*|}"
  merge_one "${src_rel}" "${dst_rel}"
done

log ""
log "DONE. State/logs: ${STATE_ROOT}"
