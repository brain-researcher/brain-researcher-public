#!/usr/bin/env bash
set -euo pipefail

# Inputs:
# - FC_PROJECT_ROOT: canonical FC project root on the worker
# - BRAIN_RESEARCHER_ROOT: repo root on the worker for script deployment
# - CONDA_SH / CONDA_ENV: runtime env that can run the FC controller scripts
# - MAX_CYCLES / MAX_HOURS / MAX_STALL_CYCLES / TARGET_SCORE: watchdog bounds
#
# Outputs:
# - STATE_ROOT/state.json
# - STATE_ROOT/handoff.json
# - STATE_ROOT/stop.json (on exit)
# - STATE_ROOT/score_cycle_XX.json
# - LOG_DIR/fc_watchdog_*.log
#
# Usage:
#   bash scripts/autoresearch/fc/run_live_watchdog.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${FC_PROJECT_ROOT:=/data/brain_researcher/research/predictive/project}"
: "${BRAIN_RESEARCHER_ROOT:=/home/ubuntu/brain_researcher}"
: "${CONDA_SH:=/home/ubuntu/miniconda3/etc/profile.d/conda.sh}"
: "${CONDA_ENV:=brain_researcher}"
: "${STATE_ROOT:=${FC_PROJECT_ROOT}/artifacts/autoresearch/fc_live_watchdog}"
: "${LOG_DIR:=${STATE_ROOT}/logs}"
: "${TARGET_SCORE:=1.0}"
: "${MAX_CYCLES:=5}"
: "${MAX_HOURS:=24}"
: "${MAX_STALL_CYCLES:=3}"
: "${ALLOW_GCP:=0}"
: "${ALLOW_NO_ACTION_CLOSURE:=0}"
: "${BOOST_MAX_REAL_RUNS:=4}"
: "${CLOSURE_MAX_RUNS:=8}"
: "${WATCHDOG_NAME:=fc_live_watchdog}"

LEDGER_PATH="${FC_PROJECT_ROOT}/experiments.jsonl"
DIAGNOSTICS_DIR="${FC_PROJECT_ROOT}/artifacts/diagnostics"
PROMPTS_DIR="${FC_PROJECT_ROOT}/artifacts/prompts"
CONTROLLER_JSON="${DIAGNOSTICS_DIR}/autoresearch_meta_controller.json"
CONTROLLER_MD="${DIAGNOSTICS_DIR}/autoresearch_meta_controller.md"
PLAN_JSON="${DIAGNOSTICS_DIR}/next_campaign_plan.json"
PLAN_MD="${DIAGNOSTICS_DIR}/next_campaign_plan.md"
STATE_PATH="${STATE_ROOT}/state.json"
HANDOFF_PATH="${STATE_ROOT}/handoff.json"
STOP_PATH="${STATE_ROOT}/stop.json"
STATUS_LOG="${LOG_DIR}/watchdog_status.log"
SCORE_SCRIPT="${SCRIPT_DIR}/score_explicit.py"

mkdir -p "${STATE_ROOT}" "${LOG_DIR}" "${PROMPTS_DIR}"

timestamp_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

activate_runtime() {
  # shellcheck disable=SC1090
  source "${CONDA_SH}"
  conda activate "${CONDA_ENV}"
  export PYTHONPATH="${BRAIN_RESEARCHER_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
}

read_json_field() {
  local json_path="$1"
  local field_path="$2"
  python3 - "$json_path" "$field_path" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
value = payload
for part in sys.argv[2].split("."):
    if not part:
        continue
    if isinstance(value, dict):
        value = value.get(part)
    else:
        value = None
        break
if isinstance(value, (dict, list)):
    print(json.dumps(value))
elif value is None:
    print("")
else:
    print(value)
PY
}

count_ledger_runs() {
  python3 - "$LEDGER_PATH" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
if not path.exists():
    print(0)
else:
    print(sum(1 for line in path.read_text().splitlines() if line.strip()))
PY
}

refresh_controller_and_plan() {
  activate_runtime
  cd "${FC_PROJECT_ROOT}"
  python scripts/analysis/fc_benchmarking/meta_controller.py \
    --json-out "${CONTROLLER_JSON}" \
    --md-out "${CONTROLLER_MD}" >/dev/null
  python scripts/analysis/fc_benchmarking/next_campaign_generator.py \
    --controller-json "${CONTROLLER_JSON}" \
    --plan-json-out "${PLAN_JSON}" \
    --plan-md-out "${PLAN_MD}" >/dev/null
}

run_score() {
  local cycle="$1"
  local score_path="${STATE_ROOT}/score_cycle_$(printf '%02d' "${cycle}").json"
  python3 "${SCORE_SCRIPT}" \
    --ledger "${LEDGER_PATH}" \
    --output "${score_path}" >/dev/null
  printf '%s\n' "${score_path}"
}

score_improved() {
  local candidate="$1"
  local incumbent="$2"
  python3 - "$candidate" "$incumbent" <<'PY'
import sys

candidate = float(sys.argv[1])
incumbent = float(sys.argv[2])
raise SystemExit(0 if candidate > incumbent else 1)
PY
}

write_state() {
  local cycle="$1"
  local stall_count="$2"
  local current_stage="$3"
  local score_path="$4"
  local best_score="$5"
  local last_score="$6"
  python3 - "$STATE_PATH" "$WATCHDOG_NAME" "$cycle" "$stall_count" "$current_stage" "$FC_PROJECT_ROOT" "$best_score" "$last_score" "$LEDGER_PATH" "$CONTROLLER_JSON" "$PLAN_JSON" "$score_path" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

(path, watchdog_name, cycle, stall_count, current_stage, project_root, best_score, last_score,
 ledger_path, controller_json, plan_json, score_path) = sys.argv[1:]

payload = {
    "schema_version": "fc-live-watchdog-v1",
    "watchdog_name": watchdog_name,
    "cycle": int(cycle),
    "stall_count": int(stall_count),
    "current_stage": current_stage,
    "project_root": project_root,
    "best_score": None if best_score == "" else float(best_score),
    "last_score": None if last_score == "" else float(last_score),
    "paths": {
        "ledger_path": ledger_path,
        "controller_json": controller_json,
        "plan_json": plan_json,
        "last_score_path": score_path,
    },
    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
}
target = Path(path)
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

write_handoff() {
  local cycle="$1"
  local score_path="$2"
  python3 - "$HANDOFF_PATH" "$cycle" "$score_path" "$CONTROLLER_JSON" "$PLAN_JSON" "$STATE_PATH" "$ALLOW_NO_ACTION_CLOSURE" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

handoff_path, cycle, score_path, controller_path, plan_path, state_path, allow_no_action_closure = sys.argv[1:]
score = json.loads(Path(score_path).read_text())
controller = json.loads(Path(controller_path).read_text())
plan = json.loads(Path(plan_path).read_text())

next_campaign = controller.get("next_campaign") or {}
score_value = float(score.get("score") or 0.0)
contract_satisfied = bool(score.get("contract_satisfied"))
campaign_type = next_campaign.get("campaign_type") or "unknown"

if contract_satisfied and score_value >= 1.0:
    recommended = "stop_completed"
elif campaign_type == "no_action":
    recommended = (
        "restart_claude_for_contract_closure"
        if allow_no_action_closure == "1" and not contract_satisfied
        else "needs_human_review"
    )
elif campaign_type == "needs_diagnosis":
    recommended = "restart_claude_for_diagnosis"
else:
    recommended = "restart_claude_for_next_campaign"

payload = {
    "schema_version": "fc-live-watchdog-v1",
    "cycle": int(cycle),
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "best_results": {
        "score": score_value,
        "mean_r2_weak_targets": score.get("mean_r2_weak_targets"),
        "target_scores": score.get("target_scores"),
        "contract_satisfied": contract_satisfied,
    },
    "next_campaign": next_campaign,
    "plan": plan,
    "recommended_next_action": recommended,
    "pending_actions": [],
    "blocked_items": [],
    "notes": [
        "Read this handoff before opening the generated prompt for the next Claude cycle.",
        "External scorer output is the only truth for score/contract completion.",
    ],
    "source_artifacts": {
        "score_path": score_path,
        "controller_json": controller_path,
        "plan_json": plan_path,
        "state_json": state_path,
    },
}
if not contract_satisfied:
    payload["pending_actions"].append("satisfy_null_and_replicate contract if score rises again")
if campaign_type == "needs_diagnosis":
    payload["pending_actions"].append("write explicit diagnosis before any new batch")
elif campaign_type not in {"no_action", "needs_diagnosis"}:
    payload["pending_actions"].append("execute the recommended campaign prompt")

Path(handoff_path).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
}

build_no_action_override_prompt() {
  local cycle="$1"
  local score_path="$2"
  local mode="${3:-boost}"
  local cycle_prompt="${LOG_DIR}/fc_watchdog_override_$(printf '%02d' "${cycle}").md"
  python3 - "$LEDGER_PATH" "$score_path" "$cycle_prompt" "$FC_PROJECT_ROOT" "$CONTROLLER_JSON" "$HANDOFF_PATH" "$mode" "$BOOST_MAX_REAL_RUNS" "$CLOSURE_MAX_RUNS" <<'PY'
import json
import sys
from pathlib import Path

(
    ledger_path,
    score_path,
    out_path,
    project_root,
    controller_json,
    handoff_json,
    mode,
    boost_max_real_runs,
    closure_max_runs,
) = sys.argv[1:]

rows = [json.loads(line) for line in Path(ledger_path).read_text().splitlines() if line.strip()]
score = json.loads(Path(score_path).read_text())
controller = json.loads(Path(controller_json).read_text()) if Path(controller_json).exists() else {}

phase_rows = [row for row in rows if row.get("phase") == "phase9_weak_target_term_discovery"]
weak_targets = tuple(score.get("weak_targets") or ["PicSeq_Unadj", "ListSort_Unadj"])

def best_real_config(target: str) -> dict:
    incumbent = None
    for row in phase_rows:
        if row.get("config", {}).get("target") != target:
            continue
        tags = set(row.get("tags") or [])
        if "label-shuffle-control" in tags:
            continue
        if row.get("config", {}).get("hyperparameters", {}).get("replicate_id") is not None:
            continue
        s = row.get("scores", {}).get("gold_r2")
        if s is None:
            continue
        if incumbent is None or float(s) > incumbent["score"]:
            incumbent = {
                "score": float(s),
                "run_id": row.get("run_id"),
                "backbone": row.get("config", {}).get("backbone"),
                "term_index": row.get("config", {}).get("hyperparameters", {}).get("term_index"),
                "hyperparameters": row.get("config", {}).get("hyperparameters", {}),
            }
    return incumbent or {}

best_configs = {target: best_real_config(target) for target in weak_targets}
target_scores = dict(score.get("target_scores") or {})
lagging_target = min(target_scores, key=target_scores.get) if target_scores else weak_targets[0]
lagging_config = best_configs.get(lagging_target) or {}

null_counts = dict(score.get("null_counts") or {})
replicate_counts = dict(score.get("replicate_counts") or {})
missing_nulls = {target: max(0, 4 - int(null_counts.get(target, 0))) for target in weak_targets}
missing_reps = {target: max(0, 4 - int(replicate_counts.get(target, 0))) for target in weak_targets}

lines = [
    f"Work in {project_root}.",
    "",
    "Read AGENTS.md first and follow it strictly.",
    "",
    "Read these first:",
    f"- {handoff_json}",
    f"- {score_path}",
    f"- {controller_json}",
    "",
    "This is a bounded unattended FC autoresearch cycle.",
    "External scorer output is the source of truth.",
]

if mode == "boost":
    lines.extend(
        [
            "",
            "The controller returned `no_action`, but the external scorer says the weak-target contract is not actually finished yet.",
            "Treat this as a contract-closure override cycle focused on score improvement first, then contract completion.",
            "",
            "Current weak-target truth:",
            f"- score = {score.get('score')}",
            f"- mean_r2_weak_targets = {score.get('mean_r2_weak_targets')}",
            f"- target_scores = {json.dumps(target_scores, sort_keys=True)}",
            f"- lagging target = {lagging_target}",
            "",
            "Best current real configs:",
        ]
    )
    for target, cfg in best_configs.items():
        lines.append(
            f"- {target}: backbone={cfg.get('backbone')} term={cfg.get('term_index')} score={cfg.get('score')}"
        )
    lines.extend(
        [
            "",
            "Your job in this cycle:",
            f"1. Spend at most {boost_max_real_runs} new real runs.",
            f"2. Focus first on {lagging_target}.",
            "3. Stay inside phase9_weak_target_term_discovery and Lane B exact raw target settings.",
            "4. Prefer bounded alpha-grid tuning or nearby term probes around the current incumbent rather than broadening the search surface.",
            "5. Append every run to experiments.jsonl and end with a short closeout.",
        ]
    )
    if lagging_config.get("backbone") == "RidgeRegression":
        lines.extend(
            [
                "",
                "Highest-confidence first probes for this cycle:",
                f"- {lagging_target} + RidgeRegression + current incumbent term {lagging_config.get('term_index')} with a moderate alpha grid around the incumbent.",
                f"- Specifically try `[500, 1000, 2000, 3000, 5000, 8000]` if that grid has not been run yet.",
                "- If you still have budget after the best ridge retune, use one or two nearby bounded probes only.",
            ]
        )
else:
    lines.extend(
        [
            "",
            "The external score target is already reached, but the weak-target contract is still incomplete because null or replicate counts are missing.",
            "Treat this as a contract-closure cycle only. Do not reopen term search.",
            "",
            "Missing counts:",
        ]
    )
    for target in weak_targets:
        lines.append(
            f"- {target}: missing_nulls={missing_nulls[target]}, missing_replicates={missing_reps[target]}"
        )
    lines.extend(
        [
            "",
            "Best current real configs to close on:",
        ]
    )
    for target, cfg in best_configs.items():
        lines.append(
            f"- {target}: backbone={cfg.get('backbone')} term={cfg.get('term_index')} score={cfg.get('score')}"
        )
    lines.extend(
        [
            "",
            "Your job in this cycle:",
            f"1. Spend at most {closure_max_runs} new runs.",
            "2. Use label-shuffle controls and replicate runs only.",
            "3. Close missing counts for the current incumbents.",
            "4. Do not broaden the model or term search surface.",
            "",
            "Execute these first unless they already exist in experiments.jsonl:",
            f"- PicSeq_Unadj incumbent replicate: ridge term {best_configs.get('PicSeq_Unadj', {}).get('term_index')} with alpha grid {best_configs.get('PicSeq_Unadj', {}).get('alpha_grid')} and --replicate-id rep01",
            f"- ListSort_Unadj incumbent replicate: ridge term {best_configs.get('ListSort_Unadj', {}).get('term_index')} with alpha grid {best_configs.get('ListSort_Unadj', {}).get('alpha_grid')} and --replicate-id rep02",
            f"- PicSeq_Unadj label-shuffle null: ridge term {best_configs.get('PicSeq_Unadj', {}).get('term_index')} with alpha grid {best_configs.get('PicSeq_Unadj', {}).get('alpha_grid')} and --label-shuffle-seed 7001",
            f"- ListSort_Unadj label-shuffle null: ridge term {best_configs.get('ListSort_Unadj', {}).get('term_index')} with alpha grid {best_configs.get('ListSort_Unadj', {}).get('alpha_grid')} and --label-shuffle-seed 7002",
            "",
            "Use the same benchmark-exact Lane B raw-target command shape as the incumbent runs:",
            "- python scripts/analysis/fc_benchmarking/run_raw_target_experiment.py --lane B --feature-mode benchmark_exact --confound-strategy none --phase phase9_weak_target_term_discovery --status interesting_but_unconfirmed --proposal-source followup --target-column <TARGET> --clf-name ridge --term-index <TERM> --alpha-grid <GRID> [--replicate-id ... | --label-shuffle-seed ...]",
        ]
    )

lines.extend(
    [
        "",
        "End with:",
        "- exact runs executed",
        "- updated weak-target status",
        "- whether the contract should now be considered satisfied",
    ]
)

Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
  printf '%s\n' "${cycle_prompt}"
}

write_stop() {
  local final_status="$1"
  local stop_reason="$2"
  local cycle="$3"
  local stall_count="$4"
  local score_path="$5"
  python3 - "$STOP_PATH" "$WATCHDOG_NAME" "$final_status" "$stop_reason" "$cycle" "$stall_count" "$score_path" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

stop_path, watchdog_name, final_status, stop_reason, cycle, stall_count, score_path = sys.argv[1:]
score_payload = {}
if Path(score_path).exists():
    score_payload = json.loads(Path(score_path).read_text())
payload = {
    "schema_version": "fc-live-watchdog-v1",
    "watchdog_name": watchdog_name,
    "final_status": final_status,
    "stop_reason": stop_reason,
    "cycle": int(cycle),
    "stall_count": int(stall_count),
    "last_score": score_payload.get("score"),
    "last_score_path": score_path,
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
}
Path(stop_path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

build_cycle_prompt() {
  local cycle="$1"
  local prompt_path="$2"
  local score_path="$3"
  local cycle_prompt="${LOG_DIR}/fc_watchdog_prompt_$(printf '%02d' "${cycle}").md"
  cp "${prompt_path}" "${cycle_prompt}"
  cat >> "${cycle_prompt}" <<EOF

Supervisor state:
- handoff json: ${HANDOFF_PATH}
- score truth: $(read_json_field "${score_path}" score)
- controller json: ${CONTROLLER_JSON}
- plan json: ${PLAN_JSON}
- allow bounded GCP if clearly needed: ${ALLOW_GCP}

Supervisor rules:
- Read the handoff JSON first; it is the carry-over state from the previous cycle.
- Trust the external scorer, not prior self-reported scores.
- If the contract is already satisfied, stop and write a clean closeout instead of reopening search.
- If the controller says needs diagnosis, diagnose only; do not run a new batch in this cycle.
EOF
  printf '%s\n' "${cycle_prompt}"
}

ensure_prereqs() {
  test -f "${LEDGER_PATH}" || { echo "Missing ledger: ${LEDGER_PATH}" >&2; exit 1; }
  test -f "${SCORE_SCRIPT}" || { echo "Missing scorer script: ${SCORE_SCRIPT}" >&2; exit 1; }
  command -v claude >/dev/null 2>&1 || { echo "Missing claude command" >&2; exit 1; }
  command -v python3 >/dev/null 2>&1 || { echo "Missing python3" >&2; exit 1; }
  test -f "${CONDA_SH}" || { echo "Missing conda activation script: ${CONDA_SH}" >&2; exit 1; }
}

ensure_prereqs

start_epoch="$(date +%s)"
deadline_epoch="$((start_epoch + MAX_HOURS * 3600))"
cycle=0
stall_count=0
best_score=""

refresh_controller_and_plan
score_path="$(run_score "${cycle}")"
last_score="$(read_json_field "${score_path}" score)"
best_score="${last_score}"
write_state "${cycle}" "${stall_count}" "scored" "${score_path}" "${best_score}" "${last_score}"
write_handoff "${cycle}" "${score_path}"

campaign_type="$(read_json_field "${CONTROLLER_JSON}" next_campaign.campaign_type)"
contract_satisfied="$(read_json_field "${score_path}" contract_satisfied)"
printf '[watchdog] %s initial score=%s contract_satisfied=%s campaign_type=%s\n' \
  "$(timestamp_utc)" "${last_score}" "${contract_satisfied}" "${campaign_type}" | tee -a "${STATUS_LOG}"

if [[ "${contract_satisfied}" == "True" && "${last_score}" == "${TARGET_SCORE}" ]]; then
  write_stop "completed" "score_target_reached" "${cycle}" "${stall_count}" "${score_path}"
  printf '[watchdog] %s stop completed: score target reached\n' "$(timestamp_utc)" | tee -a "${STATUS_LOG}"
  exit 0
fi

if [[ "${campaign_type}" == "no_action" ]]; then
  if [[ "${ALLOW_NO_ACTION_CLOSURE}" != "1" ]]; then
    write_stop "needs_human_review" "controller_no_action_before_score_target" "${cycle}" "${stall_count}" "${score_path}"
    printf '[watchdog] %s stop needs_human_review: controller reported no_action\n' "$(timestamp_utc)" | tee -a "${STATUS_LOG}"
    exit 0
  fi
fi

while true; do
  now_epoch="$(date +%s)"
  if (( now_epoch >= deadline_epoch )); then
    write_stop "bounded_limit_reached" "max_hours_elapsed" "${cycle}" "${stall_count}" "${score_path}"
    printf '[watchdog] %s stop bounded_limit_reached: max hours\n' "$(timestamp_utc)" | tee -a "${STATUS_LOG}"
    break
  fi
  if (( cycle >= MAX_CYCLES )); then
    write_stop "bounded_limit_reached" "max_cycles_reached" "${cycle}" "${stall_count}" "${score_path}"
    printf '[watchdog] %s stop bounded_limit_reached: max cycles\n' "$(timestamp_utc)" | tee -a "${STATUS_LOG}"
    break
  fi
  if (( stall_count >= MAX_STALL_CYCLES )); then
    write_stop "stalled" "max_stall_cycles_reached" "${cycle}" "${stall_count}" "${score_path}"
    printf '[watchdog] %s stop stalled: max stall cycles\n' "$(timestamp_utc)" | tee -a "${STATUS_LOG}"
    break
  fi

  current_ledger_count="$(count_ledger_runs)"
  prompt_path="$(read_json_field "${PLAN_JSON}" prompt_path)"
  current_mode="controller_prompt"
  if [[ "${campaign_type}" == "no_action" && "${ALLOW_NO_ACTION_CLOSURE}" == "1" && "${contract_satisfied}" != "True" ]]; then
    if [[ "${last_score}" == "${TARGET_SCORE}" ]]; then
      prompt_path="$(build_no_action_override_prompt "${cycle}" "${score_path}" "closure")"
      current_mode="override_closure"
    else
      prompt_path="$(build_no_action_override_prompt "${cycle}" "${score_path}" "boost")"
      current_mode="override_boost"
    fi
  fi
  if [[ -z "${prompt_path}" || ! -f "${prompt_path}" ]]; then
    stall_count=$((stall_count + 1))
    write_state "${cycle}" "${stall_count}" "missing_prompt" "${score_path}" "${best_score}" "${last_score}"
    printf '[watchdog] %s missing prompt_path=%s stall_count=%s\n' "$(timestamp_utc)" "${prompt_path}" "${stall_count}" | tee -a "${STATUS_LOG}"
    sleep 2
    continue
  fi

  cycle=$((cycle + 1))
  cycle_prompt="$(build_cycle_prompt "${cycle}" "${prompt_path}" "${score_path}")"
  cycle_log="${LOG_DIR}/fc_watchdog_cycle_$(printf '%02d' "${cycle}").log"
  controller_signature_before="$(read_json_field "${CONTROLLER_JSON}" next_campaign.campaign_type)|$(read_json_field "${CONTROLLER_JSON}" next_campaign.campaign_name)"

  printf '[watchdog] %s cycle=%s mode=%s starting claude with prompt=%s\n' "$(timestamp_utc)" "${cycle}" "${current_mode}" "${cycle_prompt}" | tee -a "${STATUS_LOG}"
  set +e
  claude --dangerously-skip-permissions -p "$(cat "${cycle_prompt}")" | tee "${cycle_log}"
  claude_status=$?
  set -e

  refresh_controller_and_plan
  score_path="$(run_score "${cycle}")"
  new_score="$(read_json_field "${score_path}" score)"
  contract_satisfied="$(read_json_field "${score_path}" contract_satisfied)"
  campaign_type="$(read_json_field "${CONTROLLER_JSON}" next_campaign.campaign_type)"
  controller_signature_after="$(read_json_field "${CONTROLLER_JSON}" next_campaign.campaign_type)|$(read_json_field "${CONTROLLER_JSON}" next_campaign.campaign_name)"
  new_ledger_count="$(count_ledger_runs)"

  if [[ -z "${best_score}" ]] || score_improved "${new_score}" "${best_score}"; then
    best_score="${new_score}"
  fi
  last_score="${new_score}"

  if (( claude_status != 0 )); then
    stall_count=$((stall_count + 1))
    current_stage="claude_nonzero_exit"
  elif (( new_ledger_count > current_ledger_count )) || [[ "${controller_signature_after}" != "${controller_signature_before}" ]]; then
    stall_count=0
    current_stage="progress"
  else
    stall_count=$((stall_count + 1))
    current_stage="no_progress"
  fi

  write_state "${cycle}" "${stall_count}" "${current_stage}" "${score_path}" "${best_score}" "${last_score}"
  write_handoff "${cycle}" "${score_path}"
  printf '[watchdog] %s cycle=%s claude_status=%s score=%s ledger=%s->%s campaign=%s stall=%s\n' \
    "$(timestamp_utc)" "${cycle}" "${claude_status}" "${new_score}" "${current_ledger_count}" "${new_ledger_count}" "${campaign_type}" "${stall_count}" | tee -a "${STATUS_LOG}"

  if [[ "${contract_satisfied}" == "True" && "${new_score}" == "${TARGET_SCORE}" ]]; then
    write_stop "completed" "score_target_reached" "${cycle}" "${stall_count}" "${score_path}"
    printf '[watchdog] %s stop completed: score target reached\n' "$(timestamp_utc)" | tee -a "${STATUS_LOG}"
    break
  fi
  if [[ "${campaign_type}" == "no_action" ]]; then
    if [[ "${contract_satisfied}" == "True" ]]; then
      write_stop "completed" "controller_no_action_after_progress" "${cycle}" "${stall_count}" "${score_path}"
      printf '[watchdog] %s stop completed: controller no_action\n' "$(timestamp_utc)" | tee -a "${STATUS_LOG}"
    elif [[ "${ALLOW_NO_ACTION_CLOSURE}" == "1" ]]; then
      printf '[watchdog] %s continuing: controller no_action but contract still incomplete\n' "$(timestamp_utc)" | tee -a "${STATUS_LOG}"
      continue
    else
      write_stop "needs_human_review" "controller_no_action_before_score_target" "${cycle}" "${stall_count}" "${score_path}"
      printf '[watchdog] %s stop needs_human_review: controller no_action before score target\n' "$(timestamp_utc)" | tee -a "${STATUS_LOG}"
    fi
    break
  fi
done
