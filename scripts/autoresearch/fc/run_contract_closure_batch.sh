#!/usr/bin/env bash
set -euo pipefail

# Fill the remaining weak-target contract-closure backlog for an FC project.
#
# Inputs:
# - FC_PROJECT_ROOT: FC project root with experiments.jsonl and scripts/
# - CONDA_SH / CONDA_ENV: runtime environment that can run FC scripts
# - PHASE / STATUS / PROPOSAL_SOURCE: ledger metadata for appended runs
# - PICSEQ_* / LISTSORT_*: incumbent term + alpha-grid settings
# - NULL_SEEDS / *_REPLICATES: controls to materialize
#
# Outputs:
# - Appends missing replicate/null runs to experiments.jsonl
# - Writes before/after scorer payloads under LOG_DIR
# - Writes execution log under LOG_DIR
#
# Usage:
#   FC_PROJECT_ROOT=/path/to/project bash scripts/autoresearch/fc/run_contract_closure_batch.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${FC_PROJECT_ROOT:=$(pwd)}"
: "${CONDA_SH:=/home/ubuntu/miniconda3/etc/profile.d/conda.sh}"
: "${CONDA_ENV:=brain_researcher}"
: "${PHASE:=phase9_weak_target_term_discovery}"
: "${STATUS:=interesting_but_unconfirmed}"
: "${PROPOSAL_SOURCE:=followup}"
: "${LOG_DIR:=${FC_PROJECT_ROOT}/artifacts/autoresearch/fc_contract_closure_batch}"
: "${PICSEQ_TERM_INDEX:=20}"
: "${PICSEQ_ALPHA_GRID:=1000,5000,10000,50000,100000}"
: "${LISTSORT_TERM_INDEX:=16}"
: "${LISTSORT_ALPHA_GRID:=500,1000,2000,3000,5000,8000}"
: "${PICSEQ_REPLICATES:=rep02,rep03,rep04}"
: "${LISTSORT_REPLICATES:=rep03,rep04}"
: "${NULL_SEEDS:=2,3,4}"

LEDGER_PATH="${FC_PROJECT_ROOT}/experiments.jsonl"
RUN_SCRIPT="${FC_PROJECT_ROOT}/scripts/analysis/fc_benchmarking/run_raw_target_experiment.py"
SCORE_SCRIPT="${SCRIPT_DIR}/score_explicit.py"
RUN_LOG="${LOG_DIR}/closure_batch.log"
BEFORE_SCORE="${LOG_DIR}/score_before.json"
AFTER_SCORE="${LOG_DIR}/score_after.json"

mkdir -p "${LOG_DIR}"

timestamp_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

activate_runtime() {
  # shellcheck disable=SC1090
  source "${CONDA_SH}"
  conda activate "${CONDA_ENV}"
}

ensure_prereqs() {
  test -f "${LEDGER_PATH}" || { echo "Missing ledger: ${LEDGER_PATH}" >&2; exit 1; }
  test -f "${RUN_SCRIPT}" || { echo "Missing FC run script: ${RUN_SCRIPT}" >&2; exit 1; }
  test -f "${SCORE_SCRIPT}" || { echo "Missing scorer script: ${SCORE_SCRIPT}" >&2; exit 1; }
  test -f "${CONDA_SH}" || { echo "Missing conda activation script: ${CONDA_SH}" >&2; exit 1; }
}

ledger_has_control() {
  local target="$1"
  local term_index="$2"
  local replicate_id="$3"
  local shuffle_seed="$4"
  python3 - "$LEDGER_PATH" "$target" "$term_index" "$replicate_id" "$shuffle_seed" <<'PY'
import json
import sys
from pathlib import Path

ledger_path = Path(sys.argv[1])
target = sys.argv[2]
term_index = int(sys.argv[3])
replicate_id = sys.argv[4] or None
shuffle_seed = int(sys.argv[5]) if sys.argv[5] else None

if not ledger_path.exists():
    raise SystemExit(1)

for raw_line in ledger_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line:
        continue
    row = json.loads(line)
    if row.get("phase") != "phase9_weak_target_term_discovery":
        continue
    config = row.get("config", {})
    if config.get("target") != target:
        continue
    hp = config.get("hyperparameters", {})
    if hp.get("term_index") != term_index:
        continue
    if replicate_id is not None:
        if hp.get("replicate_id") == replicate_id:
            raise SystemExit(0)
    elif shuffle_seed is not None:
        if hp.get("label_shuffle_seed") == shuffle_seed:
            raise SystemExit(0)

raise SystemExit(1)
PY
}

run_one() {
  local target="$1"
  local term_index="$2"
  local alpha_grid="$3"
  local replicate_id="$4"
  local shuffle_seed="$5"
  local note_suffix="$6"
  local -a cmd

  local mode_label
  if [[ -n "${replicate_id}" ]]; then
    mode_label="replicate:${replicate_id}"
  else
    mode_label="label_shuffle:${shuffle_seed}"
  fi

  printf '[closure] %s target=%s term=%s mode=%s\n' \
    "$(timestamp_utc)" "${target}" "${term_index}" "${mode_label}" | tee -a "${RUN_LOG}"

  activate_runtime
  (
    cd "${FC_PROJECT_ROOT}"
    cmd=(
      python "${RUN_SCRIPT}"
      --lane B
      --feature-mode benchmark_exact
      --confound-strategy none
      --phase "${PHASE}"
      --status "${STATUS}"
      --proposal-source "${PROPOSAL_SOURCE}"
      --target-column "${target}"
      --clf-name ridge
      --term-index "${term_index}"
      --alpha-grid "${alpha_grid}"
      --notes-suffix "${note_suffix}"
    )
    if [[ -n "${replicate_id}" ]]; then
      cmd+=(--replicate-id "${replicate_id}")
    fi
    if [[ -n "${shuffle_seed}" ]]; then
      cmd+=(--label-shuffle-seed "${shuffle_seed}")
    fi
    "${cmd[@]}"
  ) | tee -a "${RUN_LOG}"
}

run_missing_replicates() {
  local target="$1"
  local term_index="$2"
  local alpha_grid="$3"
  local replicate_csv="$4"

  IFS=',' read -r -a replicate_ids <<< "${replicate_csv}"
  for replicate_id in "${replicate_ids[@]}"; do
    if ledger_has_control "${target}" "${term_index}" "${replicate_id}" ""; then
      printf '[closure] %s skip existing replicate target=%s term=%s replicate_id=%s\n' \
        "$(timestamp_utc)" "${target}" "${term_index}" "${replicate_id}" | tee -a "${RUN_LOG}"
      continue
    fi
    run_one \
      "${target}" \
      "${term_index}" \
      "${alpha_grid}" \
      "${replicate_id}" \
      "" \
      "Phase 9 contract-closure: ${target%%_*} replicate ${replicate_id}"
  done
}

run_missing_nulls() {
  local target="$1"
  local term_index="$2"
  local alpha_grid="$3"
  local seed_csv="$4"

  IFS=',' read -r -a seeds <<< "${seed_csv}"
  for seed in "${seeds[@]}"; do
    if ledger_has_control "${target}" "${term_index}" "" "${seed}"; then
      printf '[closure] %s skip existing null target=%s term=%s seed=%s\n' \
        "$(timestamp_utc)" "${target}" "${term_index}" "${seed}" | tee -a "${RUN_LOG}"
      continue
    fi
    run_one \
      "${target}" \
      "${term_index}" \
      "${alpha_grid}" \
      "" \
      "${seed}" \
      "Phase 9 contract-closure: ${target%%_*} null control seed=${seed}"
  done
}

ensure_prereqs

printf '[closure] %s project=%s\n' "$(timestamp_utc)" "${FC_PROJECT_ROOT}" | tee -a "${RUN_LOG}"
python3 "${SCORE_SCRIPT}" --ledger "${LEDGER_PATH}" --output "${BEFORE_SCORE}" | tee -a "${RUN_LOG}"

run_missing_replicates "PicSeq_Unadj" "${PICSEQ_TERM_INDEX}" "${PICSEQ_ALPHA_GRID}" "${PICSEQ_REPLICATES}"
run_missing_replicates "ListSort_Unadj" "${LISTSORT_TERM_INDEX}" "${LISTSORT_ALPHA_GRID}" "${LISTSORT_REPLICATES}"
run_missing_nulls "PicSeq_Unadj" "${PICSEQ_TERM_INDEX}" "${PICSEQ_ALPHA_GRID}" "${NULL_SEEDS}"
run_missing_nulls "ListSort_Unadj" "${LISTSORT_TERM_INDEX}" "${LISTSORT_ALPHA_GRID}" "${NULL_SEEDS}"

printf '[closure] %s final_score\n' "$(timestamp_utc)" | tee -a "${RUN_LOG}"
python3 "${SCORE_SCRIPT}" --ledger "${LEDGER_PATH}" --output "${AFTER_SCORE}" | tee -a "${RUN_LOG}"
