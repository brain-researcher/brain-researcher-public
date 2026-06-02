#!/usr/bin/env bash
set -euo pipefail

# TRIBE Discovery Action Executor (companion to run_live_watchdog.sh).
#
# The watchdog is a decision producer: every cycle it writes
# `decision_cycle_NN.json`. This executor is the execution consumer: it polls
# that directory, picks up each new, non-no_action decision, and invokes the
# actual downstream runner (run_closed_loop.py --rounds 1).
#
# Separation of concerns:
#   watchdog   = reads state → writes decision JSON (fast, cheap, bounded)
#   executor   = reads decision JSON → runs closed loop (slow, GPU, one-at-a-time)
#
# Concurrency: at most one run_closed_loop subprocess at a time. If a run is
# already in flight when a new decision arrives, this cycle is skipped
# (not queued) — the next watchdog decision will pick up fresh state anyway.
#
# Dedupe: tracks the last-processed cycle id in `last_processed.txt` so
# restart-safe.
#
# Bounds: MAX_EXECUTIONS, MAX_HOURS (mirror watchdog defaults).
#
# Env:
#   DISCOVERY_PROJECT_ROOT  canonical project root (default: /data/.../project)
#   BRAIN_RESEARCHER_ROOT   repo root for runtime imports
#   CONDA_SH / CONDA_ENV    runtime activation (must include torch + langchain_core)
#   WATCHDOG_STATE_ROOT     where decision_cycle_*.json live
#   EXECUTOR_STATE_ROOT     where execution_cycle_*.json go
#   POLL_SECONDS            how often to scan for new decisions (default 30)
#   MAX_EXECUTIONS          hard cap on launches (default 48)
#   MAX_HOURS               wall-clock cap (default 72)
#   DEVICE                  --device (default cuda)
#   MANIFEST_INDEX          --manifest-index (optional; defaults inside run_closed_loop)
#   DRY_RUN                 set to 1 to log-only, do not launch subprocess
#   PERSISTENT_LOOP_ROOT    --loop-root pinned across launches so checkpoint
#                           (and len(rounds)) accumulates → freeze eligibility
#                           thresholds (min_rounds_before_freeze_eligible) can
#                           actually be reached. Default: <project>/artifacts/
#                           closed_loop/persistent_main
#   PERSISTENT_CHECKPOINT   --checkpoint path; default <PERSISTENT_LOOP_ROOT>/
#                           closed_loop_checkpoint.json

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${DISCOVERY_PROJECT_ROOT:=/data/brain_researcher/research/discovery/project}"
: "${BRAIN_RESEARCHER_ROOT:=/home/ubuntu/brain_researcher}"
: "${CONDA_SH:=/home/ubuntu/miniconda3/etc/profile.d/conda.sh}"
: "${CONDA_ENV:=tribe}"
: "${WATCHDOG_STATE_ROOT:=${DISCOVERY_PROJECT_ROOT}/artifacts/autoresearch/discovery_live_watchdog}"
: "${EXECUTOR_STATE_ROOT:=${DISCOVERY_PROJECT_ROOT}/artifacts/autoresearch/discovery_live_executor}"
: "${LOG_DIR:=${EXECUTOR_STATE_ROOT}/logs}"
: "${POLL_SECONDS:=30}"
: "${MAX_EXECUTIONS:=48}"
: "${MAX_HOURS:=72}"
: "${DEVICE:=cuda}"
: "${MANIFEST_INDEX:=}"
: "${DRY_RUN:=0}"
: "${EXECUTOR_NAME:=discovery_live_executor}"
: "${PERSISTENT_LOOP_ROOT:=${DISCOVERY_PROJECT_ROOT}/artifacts/closed_loop/persistent_main}"
: "${PERSISTENT_CHECKPOINT:=${PERSISTENT_LOOP_ROOT}/closed_loop_checkpoint.json}"

RUN_CLOSED_LOOP="${DISCOVERY_PROJECT_ROOT}/scripts/controller/run_closed_loop.py"
STATUS_LOG="${LOG_DIR}/executor_status.log"
LAST_PROCESSED="${EXECUTOR_STATE_ROOT}/last_processed.txt"
STOP_PATH="${EXECUTOR_STATE_ROOT}/stop.json"
LOCKFILE="${EXECUTOR_STATE_ROOT}/.run.lock"

mkdir -p "${EXECUTOR_STATE_ROOT}" "${LOG_DIR}"

timestamp_utc() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

activate_runtime() {
  # shellcheck disable=SC1090
  source "${CONDA_SH}"
  conda activate "${CONDA_ENV}"
  export PYTHONPATH="${BRAIN_RESEARCHER_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
}

log() {
  printf '[executor] %s %s\n' "$(timestamp_utc)" "$*" | tee -a "${STATUS_LOG}"
}

write_stop() {
  local final_status="$1"; local reason="$2"; local n_exec="$3"
  python3 - "${STOP_PATH}" "${EXECUTOR_NAME}" "${final_status}" "${reason}" "${n_exec}" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
(out_path, name, final_status, reason, n_exec) = sys.argv[1:]
Path(out_path).write_text(json.dumps({
    "schema_version": "discovery-live-executor-v1",
    "executor_name": name,
    "final_status": final_status,
    "stop_reason": reason,
    "n_executions": int(n_exec),
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

write_execution_record() {
  local cycle_id="$1"; local action="$2"; local branch_id="$3"
  local run_log="$4"; local exit_code="$5"; local started="$6"; local finished="$7"
  local decision_path="$8"
  local out_path="${EXECUTOR_STATE_ROOT}/execution_cycle_${cycle_id}.json"
  python3 - "${out_path}" "${cycle_id}" "${action}" "${branch_id}" "${run_log}" "${exit_code}" "${started}" "${finished}" "${decision_path}" <<'PY'
import json, sys
from pathlib import Path
(out, cid, action, branch, rlog, rc, started, finished, dpath) = sys.argv[1:]
Path(out).write_text(json.dumps({
    "schema_version": "discovery-execution-cycle-v1",
    "decision_cycle_id": cid,
    "decision_path": dpath,
    "action": action,
    "branch_id": branch or None,
    "run_log": rlog,
    "exit_code": int(rc),
    "started_at_utc": started,
    "finished_at_utc": finished,
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

latest_decision() {
  # Print "<cycle_id>\t<path>" of highest-numbered decision_cycle_*.json, or empty.
  ls "${WATCHDOG_STATE_ROOT}"/decision_cycle_*.json 2>/dev/null \
    | awk -F'decision_cycle_' '{print $2}' \
    | awk -F'.json' '{print $1}' \
    | sort -n | tail -1 \
    | while read cid; do
        [[ -n "${cid}" ]] && printf '%s\t%s/decision_cycle_%s.json\n' "${cid}" "${WATCHDOG_STATE_ROOT}" "${cid}"
      done
}

read_field() {
  local path="$1"; local key="$2"
  python3 - "${path}" "${key}" <<'PY'
import json, sys
from pathlib import Path
try:
    d = json.loads(Path(sys.argv[1]).read_text())
    v = d.get(sys.argv[2])
    print("" if v is None else v)
except Exception:
    print("")
PY
}

already_processed() {
  local cycle_id="$1"
  [[ -f "${LAST_PROCESSED}" ]] || return 1
  local last
  last="$(cat "${LAST_PROCESSED}" 2>/dev/null || echo '')"
  [[ "${last}" == "${cycle_id}" ]]
}

mark_processed() {
  printf '%s\n' "$1" > "${LAST_PROCESSED}"
}

ensure_prereqs() {
  test -f "${RUN_CLOSED_LOOP}" || { echo "Missing run_closed_loop: ${RUN_CLOSED_LOOP}" >&2; exit 1; }
  test -f "${CONDA_SH}"        || { echo "Missing conda activation: ${CONDA_SH}" >&2; exit 1; }
  test -d "${WATCHDOG_STATE_ROOT}" || { echo "Missing watchdog state root: ${WATCHDOG_STATE_ROOT}" >&2; exit 1; }
  command -v python3 >/dev/null 2>&1 || { echo "Missing python3" >&2; exit 1; }
}

run_closed_loop_once() {
  local cycle_id="$1"; local action="$2"; local branch_id="$3"; local decision_path="$4"
  local started finished rc
  local run_log="${LOG_DIR}/run_closed_loop_cycle_${cycle_id}.log"
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  if [[ "${DRY_RUN}" == "1" ]]; then
    log "DRY_RUN: would launch run_closed_loop for cycle=${cycle_id} action=${action} branch=${branch_id}"
    rc=0
    finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "DRY_RUN" > "${run_log}"
    write_execution_record "${cycle_id}" "${action}" "${branch_id}" "${run_log}" "${rc}" "${started}" "${finished}" "${decision_path}"
    return 0
  fi

  # Compute next --rounds target = len(checkpoint.rounds) + 1 so this launch
  # runs exactly one additional round against the persistent checkpoint.
  local target_rounds
  target_rounds="$(python3 - "${PERSISTENT_CHECKPOINT}" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
n = 0
if p.exists():
    try:
        n = len(json.loads(p.read_text()).get("rounds") or [])
    except Exception:
        n = 0
print(n + 2)
PY
)"

  (
    flock -n 9 || { log "already running; skipping cycle=${cycle_id}"; exit 75; }
    mkdir -p "${PERSISTENT_LOOP_ROOT}"
    local args=(
      --rounds "${target_rounds}"
      --device "${DEVICE}"
      --loop-root "${PERSISTENT_LOOP_ROOT}"
      --checkpoint "${PERSISTENT_CHECKPOINT}"
    )
    [[ -n "${MANIFEST_INDEX}" ]] && args+=(--manifest-index "${MANIFEST_INDEX}")
    log "launch cycle=${cycle_id} action=${action} branch=${branch_id} target_rounds=${target_rounds} loop_root=${PERSISTENT_LOOP_ROOT}"
    cd "${DISCOVERY_PROJECT_ROOT}"
    python3 "${RUN_CLOSED_LOOP}" "${args[@]}" >"${run_log}" 2>&1
  ) 9>"${LOCKFILE}"
  rc=$?
  finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  if [[ ${rc} -eq 75 ]]; then
    # skipped due to lock; do not mark processed, do not write execution record
    return 75
  fi

  log "finished cycle=${cycle_id} rc=${rc} log=${run_log}"
  write_execution_record "${cycle_id}" "${action}" "${branch_id}" "${run_log}" "${rc}" "${started}" "${finished}" "${decision_path}"

  # Promote latest per-round research_state.json → project-root
  # latest_research_state.json so meta_controller picks up new branch
  # decisions (freeze_candidate / freeze) on the next watchdog tick. Without
  # this, accumulated rounds in persistent_main never surface to the
  # controller and frontier seeds stay parked indefinitely.
  if [[ ${rc} -eq 0 ]]; then
    local latest_round_state top_level_state backup
    latest_round_state="$(ls -t "${PERSISTENT_LOOP_ROOT}"/state/research_state_round_*.json 2>/dev/null | head -1 || true)"
    top_level_state="${DISCOVERY_PROJECT_ROOT}/state/latest_research_state.json"
    if [[ -n "${latest_round_state}" && -f "${latest_round_state}" ]]; then
      backup="${top_level_state}.bak_$(date -u +%Y%m%dT%H%M%SZ)"
      cp "${top_level_state}" "${backup}" 2>/dev/null || true
      cp "${latest_round_state}" "${top_level_state}"
      log "promoted state $(basename "${latest_round_state}") → latest_research_state.json (backup=${backup})"
    else
      log "WARN: no research_state_round_*.json found to promote under ${PERSISTENT_LOOP_ROOT}/state/"
    fi
  fi

  return "${rc}"
}

ensure_prereqs
activate_runtime

start_epoch="$(date +%s)"
deadline_epoch="$((start_epoch + MAX_HOURS * 3600))"
n_executions=0

log "start executor state_root=${EXECUTOR_STATE_ROOT} watchdog_root=${WATCHDOG_STATE_ROOT} poll=${POLL_SECONDS}s max_exec=${MAX_EXECUTIONS} max_hours=${MAX_HOURS}"

while true; do
  now_epoch="$(date +%s)"
  if (( now_epoch >= deadline_epoch )); then
    write_stop "bounded_limit_reached" "max_hours_elapsed" "${n_executions}"
    log "stop bounded_limit_reached: max_hours"
    break
  fi
  if (( n_executions >= MAX_EXECUTIONS )); then
    write_stop "bounded_limit_reached" "max_executions_reached" "${n_executions}"
    log "stop bounded_limit_reached: max_executions=${n_executions}"
    break
  fi

  row="$(latest_decision || true)"
  if [[ -z "${row}" ]]; then
    sleep "${POLL_SECONDS}"
    continue
  fi
  cycle_id="$(printf '%s' "${row}" | cut -f1)"
  decision_path="$(printf '%s' "${row}" | cut -f2)"

  if already_processed "${cycle_id}"; then
    sleep "${POLL_SECONDS}"
    continue
  fi

  action="$(read_field "${decision_path}" action)"
  branch_id="$(read_field "${decision_path}" branch_id)"

  if [[ -z "${action}" || "${action}" == "no_action" ]]; then
    log "skip cycle=${cycle_id} action=${action:-<empty>} (nothing to execute)"
    mark_processed "${cycle_id}"
    sleep "${POLL_SECONDS}"
    continue
  fi

  set +e
  run_closed_loop_once "${cycle_id}" "${action}" "${branch_id}" "${decision_path}"
  rc=$?
  set -e

  if [[ ${rc} -eq 75 ]]; then
    # Lock contention — another run in flight. Don't mark processed; retry.
    sleep "${POLL_SECONDS}"
    continue
  fi

  mark_processed "${cycle_id}"
  n_executions=$((n_executions + 1))
  sleep "${POLL_SECONDS}"
done
