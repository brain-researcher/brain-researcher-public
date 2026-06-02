#!/bin/bash
# Quick activation script for Brain Researcher environment

eval "$(conda shell.bash hook)"
conda activate brain_researcher
export PYTHONPATH="/home/zijiaochen/projects/brain_researcher:${PYTHONPATH}"
cd "/home/zijiaochen/projects/brain_researcher"

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

echo "Brain Researcher environment activated!"
echo "Run 'br --help' to get started."
