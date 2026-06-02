#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <subject_id> <target_root>" >&2
  exit 2
fi

SUBJECT_ID="$1"
TARGET_ROOT="$2"
S3_ROOT="s3://openneuro.org/ds003465"
TASKS=(Axcpt Cuedts Stern Stroop)

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI is required to download DMCC data from OpenNeuro S3." >&2
  exit 1
fi

mkdir -p "${TARGET_ROOT}"

include_args=(
  --exclude "*"
  --include "dataset_description.json"
  --include "participants.tsv"
  --include "participants.json"
  --include "README"
  --include "CHANGES"
  --include "task-*_events.json"
  --include "${SUBJECT_ID}/ses-wave1bas/anat/*_T1w.json"
  --include "${SUBJECT_ID}/ses-wave1bas/anat/*_T1w.nii.gz"
)

for task in "${TASKS[@]}"; do
  include_args+=(
    --include "${SUBJECT_ID}/ses-wave1bas/func/*task-${task}_*bold.json"
    --include "${SUBJECT_ID}/ses-wave1bas/func/*task-${task}_*events.tsv"
    --include "${SUBJECT_ID}/ses-wave1bas/func/*task-${task}_*bold.nii.gz"
  )
done

aws s3 cp \
  --no-sign-request \
  --recursive \
  "${S3_ROOT}/" \
  "${TARGET_ROOT}/" \
  "${include_args[@]}"

anat_dir="${TARGET_ROOT}/${SUBJECT_ID}/ses-wave1bas/anat"
func_dir="${TARGET_ROOT}/${SUBJECT_ID}/ses-wave1bas/func"

t1w_count=0
if [[ -d "${anat_dir}" ]]; then
  t1w_count=$(find "${anat_dir}" -maxdepth 1 -name '*_T1w.nii.gz' | wc -l | tr -d ' ')
fi

bold_count=0
if [[ -d "${func_dir}" ]]; then
  bold_count=$(find "${func_dir}" -maxdepth 1 -name '*_bold.nii.gz' | wc -l | tr -d ' ')
fi

if [[ "${t1w_count}" -lt 1 ]]; then
  echo "Missing T1w for ${SUBJECT_ID} under ${anat_dir}" >&2
  exit 1
fi

if [[ "${bold_count}" -lt 8 ]]; then
  echo "Expected 8 BOLD runs for ${SUBJECT_ID}, found ${bold_count} under ${func_dir}" >&2
  exit 1
fi

echo "Downloaded ${SUBJECT_ID}: t1w_count=${t1w_count} bold_count=${bold_count}"
