#!/usr/bin/env bash
# Quick activation script for the Brain Researcher scientific runtime.
# Source this file from any directory:
#   source /path/to/brain-researcher-public/activate.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_ENV="${BR_CONDA_ENV:-brain_researcher}"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda is required to activate ${CONDA_ENV}." >&2
  return 1 2>/dev/null || exit 1
fi

if ! CONDA_BASE="$(conda info --base 2>/dev/null)"; then
  echo "Could not determine the Conda installation root." >&2
  return 1 2>/dev/null || exit 1
fi
CONDA_SH="${CONDA_BASE}/etc/profile.d/conda.sh"
if [ ! -r "${CONDA_SH}" ]; then
  echo "Conda activation script is not readable: ${CONDA_SH}" >&2
  return 1 2>/dev/null || exit 1
fi
# shellcheck disable=SC1091
if ! source "${CONDA_SH}"; then
  echo "Failed to initialize Conda from ${CONDA_SH}." >&2
  return 1 2>/dev/null || exit 1
fi
if ! conda activate "${CONDA_ENV}"; then
  echo "Failed to activate Conda environment '${CONDA_ENV}'." >&2
  return 1 2>/dev/null || exit 1
fi
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
if ! cd "${REPO_ROOT}"; then
  echo "Could not enter repository root: ${REPO_ROOT}" >&2
  return 1 2>/dev/null || exit 1
fi

# Ensure MNE/Numba imports work inside the sandboxed environment.
export NUMBA_DISABLE_CACHING="${NUMBA_DISABLE_CACHING:-1}"
export MNE_USE_NATIVE_CODE="${MNE_USE_NATIVE_CODE:-0}"
export NUMBA_CACHE_DIR="${NUMBA_CACHE_DIR:-${HOME}/.cache/numba-cache}"
mkdir -p "${NUMBA_CACHE_DIR}" 2>/dev/null || true

# Optional: preload Neurodesk modules if available (comment out if not using Neurodesk)
if command -v module >/dev/null 2>&1; then
  module load fsl/6.0.7.16 >/dev/null 2>&1 || true
  module load freesurfer/7.4.1 >/dev/null 2>&1 || true
  module load mriqc/24.0.2 >/dev/null 2>&1 || true
  module load qsiprep/0.20.0 >/dev/null 2>&1 || true
  module load ants/2.5.3 >/dev/null 2>&1 || true
  module load mrtrix3/3.0.4 >/dev/null 2>&1 || true
  module load connectomeworkbench/1.5.0 >/dev/null 2>&1 || true
fi

# Export tool locations for Neurodesk-based deployments (adjust paths if mirroring locally)
if [ -d "/cvmfs/neurodesk.ardc.edu.au" ]; then
  export NEURODESK_PATH="${NEURODESK_PATH:-/cvmfs/neurodesk.ardc.edu.au}"
  export NEURODESK_CONTAINERS="${NEURODESK_CONTAINERS:-${NEURODESK_PATH}/containers}"
  export NEURODESK_MODULES="${NEURODESK_MODULES:-${NEURODESK_PATH}/neurodesk-modules}"

  export FSLDIR="${FSLDIR:-${NEURODESK_CONTAINERS}/fsl_6.0.7.16_20250131/fsl_6.0.7.16_20250131.simg/opt/fsl-6.0.7.16}"
  export PATH="${FSLDIR}/bin:${PATH}"

  export ANTSPATH="${ANTSPATH:-${NEURODESK_CONTAINERS}/ants_2.5.3_20240925/ants_2.5.3_20240925.simg/opt/ants/bin}"
  export MRTRIXDIR="${MRTRIXDIR:-${NEURODESK_CONTAINERS}/mrtrix3_3.0.4_20240320/mrtrix3_3.0.4_20240320.simg/opt/mrtrix3/bin}"
  export CONNWBIN="${CONNWBIN:-${NEURODESK_CONTAINERS}/connectomeworkbench_1.5.0_20220914/connectomeworkbench_1.5.0_20220914.simg/opt/workbench/bin_linux64}"
  export PATH="${ANTSPATH}:${MRTRIXDIR}:${CONNWBIN}:${PATH}"

  export FS_LICENSE="${FS_LICENSE:-${HOME}/.freesurfer_license.txt}"
  export APPTAINERENV_FS_LICENSE="${APPTAINERENV_FS_LICENSE:-${FS_LICENSE}}"
fi

# Optional threading control
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"

echo "Brain Researcher environment '${CONDA_ENV}' activated at ${REPO_ROOT}."
echo "Run 'br --help' to get started."
