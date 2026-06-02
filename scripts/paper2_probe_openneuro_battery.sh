#!/usr/bin/env bash
set -euo pipefail

# Probe the Paper 2 OpenNeuro battery with the dataset-loader-openneuro skill.
# Usage:
#   scripts/paper2_probe_openneuro_battery.sh [mode] [analysis_goal] [out_dir]
# Example:
#   scripts/paper2_probe_openneuro_battery.sh light fmri-glm tmp/paper2_probe_latest

MODE="${1:-light}"
ANALYSIS_GOAL="${2:-fmri-glm}"
OUT_DIR="${3:-tmp/paper2_openneuro_probe_$(date +%Y%m%d_%H%M%S)}"

RESOLVER="${HOME}/.codex/skills/dataset-loader/scripts/resolve_openneuro.sh"
DATASETS=(ds000114 ds004873 ds003999)

if [[ ! -x "${RESOLVER}" ]]; then
  echo "Resolver not found or not executable: ${RESOLVER}" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"
echo "Writing probe outputs to: ${OUT_DIR}"

for ds in "${DATASETS[@]}"; do
  out="${OUT_DIR}/${ds}.json"
  echo ""
  echo "=== Probing ${ds} (mode=${MODE}, goal=${ANALYSIS_GOAL}) ==="
  "${RESOLVER}" --dataset "${ds}" --mode "${MODE}" --analysis-goal "${ANALYSIS_GOAL}" > "${out}" || true

  status="$(rg -n '"status":' "${out}" | head -n 1 | sed -E 's/^[0-9]+:[[:space:]]*"status":[[:space:]]*//; s/[",]//g')"
  resolved_path="$(rg -n '"resolved_path":' "${out}" | head -n 1 | sed -E 's/^[0-9]+:[[:space:]]*"resolved_path":[[:space:]]*//; s/[",]//g')"
  echo "status: ${status}"
  echo "resolved_path: ${resolved_path}"
done

echo ""
echo "Done. JSON outputs:"
ls -1 "${OUT_DIR}"/*.json
