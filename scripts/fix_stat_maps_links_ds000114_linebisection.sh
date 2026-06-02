#!/usr/bin/env bash
# Replace broken symlinks with real files for ds000114/task-linebisection stat maps.
# Usage:
#   bash scripts/fix_stat_maps_links_ds000114_linebisection.sh [SRC_ROOT] [DST_ROOT]
# Defaults:
#   SRC_ROOT=${BR_OAK_MOUNT:-/oak}/data/openneuro_fitlins/analyses
#   DST_ROOT=${BR_HOME:-/app/brain_researcher}/data/openneuro_glmfitlins/stat_maps

set -euo pipefail

SRC_ROOT="${1:-${BR_OAK_MOUNT:-/oak}/data/openneuro_fitlins/analyses}"
DST_ROOT="${2:-${BR_HOME:-/app/brain_researcher}/data/openneuro_glmfitlins/stat_maps}"

DATASET="ds000114"
TASK_DIR="task-linebisection"

SRC_PATH="${SRC_ROOT}/${DATASET}/${TASK_DIR}"
DST_PATH="${DST_ROOT}/${DATASET}/${TASK_DIR}"

if [[ ! -d "${SRC_PATH}" ]]; then
  echo "Source path not found: ${SRC_PATH}"
  echo "Mount OAK first (bash mount_oak.sh) or pass a different SRC_ROOT."
  exit 1
fi

mkdir -p "${DST_PATH}"

echo "Removing existing symlinks under ${DST_PATH}..."
SYMLINKS_REMOVED=$(find "${DST_PATH}" -type l -print -delete | wc -l | tr -d ' ')
echo "  Removed ${SYMLINKS_REMOVED} symlinks"

echo "Copying real stat maps from ${SRC_PATH} -> ${DST_PATH}..."
rsync -aL --info=progress2 "${SRC_PATH}/" "${DST_PATH}/"

REMAINING=$(find "${DST_PATH}" -type l | wc -l | tr -d ' ')
echo "Remaining symlinks: ${REMAINING}"
if [[ "${REMAINING}" != "0" ]]; then
  echo "Warning: some symlinks remain; source may contain symlinks or copy incomplete."
fi

echo "Done."
