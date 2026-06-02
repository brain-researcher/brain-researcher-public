#!/usr/bin/env bash
set -euo pipefail

# TRIBE Discovery Live Watchdog.
#
# Mirrors scripts/autoresearch/fc/run_live_watchdog.sh in structure: each cycle
# invokes discovery_meta_controller.py on the latest research state and routes
# the emitted action to the appropriate downstream step.
#
# Inputs (env):
# - DISCOVERY_PROJECT_ROOT:  canonical discovery project root on the worker
# - BRAIN_RESEARCHER_ROOT:   repo root for script deployment
# - CONDA_SH / CONDA_ENV:    runtime env
# - MAX_CYCLES:              hard cycle cap (default 20)
# - MAX_HOURS:               wall-clock cap (default 72)
# - MAX_STALL_CYCLES:        consecutive no_action cycles before bail (default 3)
# - POLICY_PATH:             exploration_policy.yaml
# - SURPRISES_PATH:          optional path to nearest_neighbor_surprises.jsonl
#
# Outputs:
# - STATE_ROOT/state.json           — watchdog state snapshot per cycle
# - STATE_ROOT/decision_cycle_XX.json — meta-controller decision per cycle
# - STATE_ROOT/stop.json            — final status on exit
# - LOG_DIR/discovery_watchdog_*.log
#
# Usage:
#   bash scripts/autoresearch/discovery/run_live_watchdog.sh
#
# NOTE: The cycle body currently persists the meta-controller decision and logs
# it. Invoking the per-action handler (resume/spawn) is left to the downstream
# orchestration layer until generate_next_round_proposal.py + materialize flow
# is wired to consume meta-controller output directly. This keeps the watchdog
# useful as a monitoring loop today while the handler pieces are landed.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${DISCOVERY_PROJECT_ROOT:=/data/brain_researcher/research/discovery/project}"
: "${BRAIN_RESEARCHER_ROOT:=/home/ubuntu/brain_researcher}"
: "${CONDA_SH:=/home/ubuntu/miniconda3/etc/profile.d/conda.sh}"
: "${CONDA_ENV:=brain_researcher}"
: "${STATE_ROOT:=${DISCOVERY_PROJECT_ROOT}/artifacts/autoresearch/discovery_live_watchdog}"
: "${LOG_DIR:=${STATE_ROOT}/logs}"
: "${MAX_CYCLES:=20}"
: "${MAX_HOURS:=72}"
: "${MAX_STALL_CYCLES:=3}"
: "${POLICY_PATH:=${DISCOVERY_PROJECT_ROOT}/configs/exploration_policy.yaml}"
: "${STATE_PATH:=${DISCOVERY_PROJECT_ROOT}/state/latest_research_state.json}"
: "${SURPRISES_PATH:=}"
: "${FRONTIER_PATH:=${DISCOVERY_PROJECT_ROOT}/state/frontier/seeds.json}"
: "${FRONTIER_COOLDOWN_SECONDS:=3600}"
: "${CYCLE_SLEEP_SECONDS:=60}"
: "${WATCHDOG_NAME:=discovery_live_watchdog}"
# Opt-in autonomous frontier generation. When set to 1, the watchdog invokes
# discovery_frontier_seed_writer.py on NEEDS_FRONTIER_GENERATION. Default (0)
# preserves the LLM-gated thesis: the watchdog only surfaces the signal.
: "${FRONTIER_AUTO_GENERATE:=0}"
# Optional: path to a pre-saved kg_hypothesis_workflow response JSON. When set
# AND FRONTIER_AUTO_GENERATE=1, writer runs in --from-json adapter-only mode
# (no live MCP call; safe on VMs without full MCP deps).
: "${FRONTIER_FROM_JSON:=}"
: "${FRONTIER_MIN_LEVERAGE:=0.40}"

META_CONTROLLER="${DISCOVERY_PROJECT_ROOT}/scripts/controller/discovery_meta_controller.py"
FRONTIER_SEED_WRITER="${DISCOVERY_PROJECT_ROOT}/scripts/controller/discovery_frontier_seed_writer.py"
WATCHDOG_STATE="${STATE_ROOT}/state.json"
STOP_PATH="${STATE_ROOT}/stop.json"
STATUS_LOG="${LOG_DIR}/watchdog_status.log"

mkdir -p "${STATE_ROOT}" "${LOG_DIR}"

timestamp_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

activate_runtime() {
  # shellcheck disable=SC1090
  source "${CONDA_SH}"
  conda activate "${CONDA_ENV}"
  export PYTHONPATH="${BRAIN_RESEARCHER_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
}

run_meta_controller() {
  local cycle="$1"
  local out_path="${STATE_ROOT}/decision_cycle_$(printf '%02d' "${cycle}").json"
  local args=(
    --state "${STATE_PATH}"
    --policy "${POLICY_PATH}"
    --out "${out_path}"
  )
  if [[ -n "${SURPRISES_PATH}" ]]; then
    args+=(--surprises "${SURPRISES_PATH}")
  fi
  if [[ -n "${FRONTIER_PATH}" ]]; then
    args+=(--frontier "${FRONTIER_PATH}")
  fi
  set +e
  python3 "${META_CONTROLLER}" "${args[@]}" >/dev/null
  local status=$?
  set -e
  printf '%s\n' "${out_path}"
  return "${status}"
}

read_action() {
  local decision_path="$1"
  python3 - "${decision_path}" <<'PY'
import json, sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text())
print(payload.get("action") or "")
PY
}

read_needs_frontier() {
  local decision_path="$1"
  python3 - "${decision_path}" <<'PY'
import json, sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text())
print("1" if payload.get("needs_frontier_generation") else "0")
PY
}

run_frontier_seed_writer() {
  local cycle="$1"
  local out_log="${LOG_DIR}/frontier_cycle_$(printf '%02d' "${cycle}").log"
  if [[ ! -f "${FRONTIER_SEED_WRITER}" ]]; then
    printf '[watchdog] %s frontier writer missing: %s\n' "$(timestamp_utc)" "${FRONTIER_SEED_WRITER}" | tee -a "${STATUS_LOG}"
    return 1
  fi
  local args=(
    --state "${STATE_PATH}"
    --out "${FRONTIER_PATH}"
    --cooldown-seconds "${FRONTIER_COOLDOWN_SECONDS}"
    --min-leverage "${FRONTIER_MIN_LEVERAGE}"
  )
  if [[ -n "${FRONTIER_FROM_JSON}" ]]; then
    args+=(--from-json "${FRONTIER_FROM_JSON}")
  fi
  set +e
  python3 "${FRONTIER_SEED_WRITER}" "${args[@]}" >"${out_log}" 2>&1
  local status=$?
  set -e
  printf '[watchdog] %s frontier_seed_writer rc=%s log=%s\n' "$(timestamp_utc)" "${status}" "${out_log}" | tee -a "${STATUS_LOG}"
  return "${status}"
}

write_watchdog_state() {
  local cycle="$1"
  local stall_count="$2"
  local last_action="$3"
  local decision_path="$4"
  python3 - "${WATCHDOG_STATE}" "${WATCHDOG_NAME}" "${cycle}" "${stall_count}" "${last_action}" "${decision_path}" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path

(out_path, name, cycle, stall, action, decision_path) = sys.argv[1:]
payload = {
    "schema_version": "discovery-live-watchdog-v1",
    "watchdog_name": name,
    "cycle": int(cycle),
    "stall_count": int(stall),
    "last_action": action or None,
    "last_decision_path": decision_path,
    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
}
Path(out_path).parent.mkdir(parents=True, exist_ok=True)
Path(out_path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

write_stop() {
  local final_status="$1"
  local reason="$2"
  local cycle="$3"
  local stall_count="$4"
  python3 - "${STOP_PATH}" "${WATCHDOG_NAME}" "${final_status}" "${reason}" "${cycle}" "${stall_count}" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
(out_path, name, final_status, reason, cycle, stall) = sys.argv[1:]
payload = {
    "schema_version": "discovery-live-watchdog-v1",
    "watchdog_name": name,
    "final_status": final_status,
    "stop_reason": reason,
    "cycle": int(cycle),
    "stall_count": int(stall),
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
}
Path(out_path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

ensure_prereqs() {
  test -f "${META_CONTROLLER}"   || { echo "Missing meta_controller: ${META_CONTROLLER}" >&2; exit 1; }
  test -f "${POLICY_PATH}"       || { echo "Missing policy: ${POLICY_PATH}" >&2; exit 1; }
  test -f "${STATE_PATH}"        || { echo "Missing state: ${STATE_PATH}" >&2; exit 1; }
  test -f "${CONDA_SH}"          || { echo "Missing conda activation: ${CONDA_SH}" >&2; exit 1; }
  command -v python3 >/dev/null 2>&1 || { echo "Missing python3" >&2; exit 1; }
}

ensure_prereqs
activate_runtime

start_epoch="$(date +%s)"
deadline_epoch="$((start_epoch + MAX_HOURS * 3600))"
cycle=0
stall_count=0

while true; do
  now_epoch="$(date +%s)"
  if (( now_epoch >= deadline_epoch )); then
    write_stop "bounded_limit_reached" "max_hours_elapsed" "${cycle}" "${stall_count}"
    printf '[watchdog] %s stop bounded_limit_reached: max_hours\n' "$(timestamp_utc)" | tee -a "${STATUS_LOG}"
    break
  fi
  if (( cycle >= MAX_CYCLES )); then
    write_stop "bounded_limit_reached" "max_cycles_reached" "${cycle}" "${stall_count}"
    printf '[watchdog] %s stop bounded_limit_reached: max_cycles\n' "$(timestamp_utc)" | tee -a "${STATUS_LOG}"
    break
  fi
  if (( stall_count >= MAX_STALL_CYCLES )); then
    # stall = 3 consecutive no_action. This is a human-review anomaly (per
    # discovery_meta_controller.py semantics: no_action is not normal
    # termination for the discovery loop).
    write_stop "needs_human_review" "max_stall_cycles_no_action" "${cycle}" "${stall_count}"
    printf '[watchdog] %s stop needs_human_review: no_action x %s\n' "$(timestamp_utc)" "${stall_count}" | tee -a "${STATUS_LOG}"
    break
  fi

  cycle=$((cycle + 1))
  decision_path="$(run_meta_controller "${cycle}" || true)"
  action="$(read_action "${decision_path}")"
  if [[ -z "${action}" ]]; then
    action="no_action"
  fi

  if [[ "${action}" == "no_action" ]]; then
    stall_count=$((stall_count + 1))
    # When the meta-controller flags needs_frontier_generation, surface it in
    # the status log so an operator (or outer LLM-driven orchestrator with MCP
    # access) can invoke kg_hypothesis_workflow and write state/frontier/seeds.json.
    # The watchdog itself does NOT call MCP: frontier question selection is an
    # LLM-gated act, not an autonomous one.
    needs_frontier="$(read_needs_frontier "${decision_path}")"
    if [[ "${needs_frontier}" == "1" ]]; then
      if [[ "${FRONTIER_AUTO_GENERATE}" == "1" ]]; then
        printf '[watchdog] %s NEEDS_FRONTIER_GENERATION cycle=%s — invoking frontier_seed_writer (AUTO)\n' \
          "$(timestamp_utc)" "${cycle}" | tee -a "${STATUS_LOG}"
        if run_frontier_seed_writer "${cycle}"; then
          # Re-decide this cycle now that frontier seeds may exist. Do not
          # increment stall_count further — frontier generation is progress.
          decision_path="$(run_meta_controller "${cycle}" || true)"
          action="$(read_action "${decision_path}")"
          if [[ -z "${action}" ]]; then action="no_action"; fi
          if [[ "${action}" != "no_action" ]]; then
            stall_count=$((stall_count - 1))
            if (( stall_count < 0 )); then stall_count=0; fi
          fi
        fi
      else
        printf '[watchdog] %s NEEDS_FRONTIER_GENERATION cycle=%s — operator/LLM must run discovery_frontier_seed_writer.py (set FRONTIER_AUTO_GENERATE=1 to autoinvoke)\n' \
          "$(timestamp_utc)" "${cycle}" | tee -a "${STATUS_LOG}"
      fi
    fi
  else
    stall_count=0
  fi

  write_watchdog_state "${cycle}" "${stall_count}" "${action}" "${decision_path}"
  printf '[watchdog] %s cycle=%s action=%s stall=%s decision=%s\n' \
    "$(timestamp_utc)" "${cycle}" "${action}" "${stall_count}" "${decision_path}" | tee -a "${STATUS_LOG}"

  # Action handlers are delegated to downstream orchestration: the decision
  # JSON is the public interface. Operators (or a higher-level orchestrator)
  # consume decision_cycle_XX.json to drive proposal generation / materialize
  # / run_closed_loop. The watchdog's role is to keep meta-controller state
  # fresh and bound the loop, not to execute campaigns itself.

  sleep "${CYCLE_SLEEP_SECONDS}"
done
