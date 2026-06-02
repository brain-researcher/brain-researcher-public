#!/bin/bash
# Submit with an explicit array range, for example:
#   sbatch -p russpold --qos=russpold \
#     --array=1-12%4 \
#     scripts/analysis/cognitive_control/sherlock/dmcc_fmriprep_array.sbatch \
#     outputs/patrick_congnitive_control/dmcc_subject_screening/next_batch.txt \
#     ~/brain_researcher_dmcc
#
# Argument 1: subject list file (one sub-* per line)
# Argument 2: optional project root copied to Sherlock, defaults to ~/brain_researcher_dmcc

#SBATCH -J dmccprep
#SBATCH -n 1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=24:00:00
#SBATCH -o logs/dmccprep.%A_%a.out
#SBATCH -e logs/dmccprep.%A_%a.err

set -euo pipefail

SUBJECT_FILE="${1:?subject list file required}"
PROJECT_ROOT="${2:-$HOME/brain_researcher_dmcc}"
SCRIPT_DIR="${PROJECT_ROOT}/scripts/analysis/cognitive_control/sherlock"

if [[ -z "${SLURM_ARRAY_TASK_ID:-}" ]]; then
  echo "SLURM_ARRAY_TASK_ID is not set. Submit this script as a job array." >&2
  exit 2
fi

SUBJECT_ID="$(sed -n "${SLURM_ARRAY_TASK_ID}p" "${SUBJECT_FILE}")"
if [[ -z "${SUBJECT_ID}" ]]; then
  echo "No subject found at array index ${SLURM_ARRAY_TASK_ID} in ${SUBJECT_FILE}" >&2
  exit 1
fi

module purge
module load apptainer || module load singularity
module load aws-cli || true

RAW_ROOT="${DMCC_RAW_ROOT:-$SCRATCH/brain_researcher_dmcc/raw}"
OUTPUT_ROOT="${DMCC_OUTPUT_ROOT:-$SCRATCH/brain_researcher_dmcc/fmriprep_next12}"
CONTAINER_DIR="${DMCC_CONTAINER_DIR:-$HOME/.apptainer_cache/brain_researcher}"
CONTAINER_SIF="${DMCC_CONTAINER_SIF:-${CONTAINER_DIR}/fmriprep_23.2.3.sif}"
TEMPLATEFLOW_DIR="${DMCC_TEMPLATEFLOW_DIR:-$SCRATCH/brain_researcher_dmcc/templateflow}"
WORK_ROOT_BASE="${DMCC_WORK_ROOT_BASE:-${LOCAL_SCRATCH:-$SCRATCH}/brain_researcher_dmcc_work}"
WORK_ROOT="${WORK_ROOT_BASE}/${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID}_${SUBJECT_ID}"
FS_LICENSE_FILE="${FS_LICENSE_FILE:-${FS_LICENSE:-$HOME/.freesurfer/license.txt}}"
OMP_THREADS="${DMCC_OMP_THREADS:-8}"
MEM_MB="${DMCC_MEM_MB:-64000}"

mkdir -p "${RAW_ROOT}" "${OUTPUT_ROOT}" "${CONTAINER_DIR}" "${TEMPLATEFLOW_DIR}" "${WORK_ROOT}" logs

if [[ ! -f "${FS_LICENSE_FILE}" ]]; then
  echo "FreeSurfer license not found: ${FS_LICENSE_FILE}" >&2
  exit 1
fi

if [[ ! -f "${CONTAINER_SIF}" ]]; then
  apptainer pull "${CONTAINER_SIF}" docker://nipreps/fmriprep:23.2.3
fi

bash "${SCRIPT_DIR}/download_dmcc_subject_s3.sh" "${SUBJECT_ID}" "${RAW_ROOT}"

export APPTAINERENV_TEMPLATEFLOW_HOME=/templateflow
export APPTAINERENV_FS_LICENSE=/opt/freesurfer/license.txt

apptainer run --cleanenv \
  -B "${RAW_ROOT}:/data" \
  -B "${OUTPUT_ROOT}:/out" \
  -B "${WORK_ROOT}:/work" \
  -B "${TEMPLATEFLOW_DIR}:/templateflow" \
  -B "${FS_LICENSE_FILE}:/opt/freesurfer/license.txt:ro" \
  "${CONTAINER_SIF}" \
  /data /out participant \
  --participant-label "${SUBJECT_ID#sub-}" \
  -w /work \
  --fs-license-file /opt/freesurfer/license.txt \
  --output-spaces MNI152NLin2009cAsym:res-2 T1w \
  --skip-bids-validation \
  --n-cpus "${SLURM_CPUS_PER_TASK:-16}" \
  --omp-nthreads "${OMP_THREADS}" \
  --mem-mb "${MEM_MB}" \
  --notrack \
  --skull-strip-t1w auto \
  --bold2t1w-init register \
  --bold2t1w-dof 6 \
  --fd-spike-threshold 0.5 \
  --dvars-spike-threshold 1.5 \
  --fs-no-reconall \
  -vv

rm -rf "${WORK_ROOT}"
