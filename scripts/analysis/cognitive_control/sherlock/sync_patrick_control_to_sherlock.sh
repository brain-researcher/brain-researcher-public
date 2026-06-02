#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${1:-login.sherlock.stanford.edu}"
REMOTE_ROOT="${2:-~/brain_researcher_dmcc}"

ssh "${REMOTE_HOST}" "mkdir -p ${REMOTE_ROOT}/scripts/analysis/cognitive_control/sherlock ${REMOTE_ROOT}/outputs/patrick_congnitive_control/dmcc_subject_screening"

rsync -avP \
  ${BR_HOME:-/app/brain_researcher}/scripts/analysis/cognitive_control/sherlock/ \
  "${REMOTE_HOST}:${REMOTE_ROOT}/scripts/analysis/cognitive_control/sherlock/"

rsync -avP \
  ${BR_HOME:-/app/brain_researcher}/outputs/patrick_congnitive_control/dmcc_subject_screening/ \
  "${REMOTE_HOST}:${REMOTE_ROOT}/outputs/patrick_congnitive_control/dmcc_subject_screening/"
