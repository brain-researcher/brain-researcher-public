# Neuroimaging Environment Setup

## Purpose
This separate conda environment contains the optional dependencies identified during testing that enable full functionality of all 108+ neuroimaging tools in Brain Researcher.

## Why a Separate Environment?
- Keeps the main `brain_researcher` environment clean and minimal
- Avoids dependency conflicts between specialized neuroimaging packages
- Allows testing tools with different dependency versions
- Can be activated only when using specific neuroimaging tools

## Required Optional Dependencies

These packages were identified during testing as causing fallback mode when missing:

| Package | Purpose | Tools Affected |
|---------|---------|----------------|
| `fooof` | Spectral parameterization for MEG/EEG | `mne_fooof_tool.py` |
| `autoreject` | Automated artifact rejection | `mne_autoreject_tool.py` |
| `rsatoolbox` | Representational similarity analysis | `rsa_toolbox_tool.py` |
| `bctpy` | Brain connectivity metrics | `graph_theory_tool.py` |
| `pymc` | Bayesian statistical modeling | `statistical_inference_tool.py` |
| `torch-geometric` | Graph neural networks | `gnn_connectivity_tool.py` |
| `tensorly` | Tensor decomposition | `multimodal_integration_tool.py` |
| `antspyx` | ANTs registration | `ants_tool.py` |
| `nimare` | Meta-analysis | `meta_analysis_tool.py` |

## Installation

### 1. Create the Environment
```bash
cd <repo>
conda env create -f neuroimage_env.yaml
```

### 2. Activate the Environment
```bash
conda activate neuroimaging_env
```

### 3. Verify Installation
```bash
python -c "import fooof, autoreject, rsatoolbox, bctpy, pymc, tensorly"
```

## Using with Brain Researcher

### Option 1: Activate for Specific Sessions
```bash
# When you need to use neuroimaging tools
conda activate neuroimaging_env
br agent start  # or any br command
```

### Option 2: Install into Main Environment
If you prefer everything in one environment:
```bash
conda activate brain_researcher
conda install -c conda-forge fooof autoreject pymc tensorly networkx
pip install rsatoolbox bctpy antspyx nimare
```

## Known Issues

### torch-geometric Installation
If `torch-geometric` fails to install, try:
```bash
# Install without geometric first
conda env create -f neuroimage_env.yaml
conda activate neuroimaging_env

# Then try installing geometric separately
pip install torch-geometric --no-deps
pip install torch-scatter torch-sparse -f https://data.pyg.org/whl/torch-2.0.0+cpu.html
```

### FSL Configuration
FSL tools generate commands but don't execute without proper setup:
```bash
export FSLDIR=/usr/local/fsl  # or your FSL installation path
source $FSLDIR/etc/fslconf/fsl.sh
export PATH=$FSLDIR/bin:$PATH
```

### Neurodesk Modules (Recommended Runtime)
If you are using the Neurodesk module tree (CVMFS or local mirror), load the containers you need and export the matching environment variables before launching `br`/`brainr`:

```bash
# Load the modules you need for your workflow
module load fsl/6.0.7.16
module load freesurfer/7.4.1
module load mriqc/24.0.2
module load qsiprep/0.20.0
module load ants/2.5.3
module load mrtrix3/3.0.4
module load connectomeworkbench/1.5.0
# (load additional modules such as xcpd, fmriprep, etc. if available)

# Export tool locations so the agent can find binaries
export FSLDIR="/cvmfs/neurodesk.ardc.edu.au/containers/fsl_6.0.7.16_20250131/fsl_6.0.7.16_20250131.simg/opt/fsl-6.0.7.16"
export PATH="$FSLDIR/bin:$PATH"

export ANTSPATH="/cvmfs/neurodesk.ardc.edu.au/containers/ants_2.5.3_20240925/ants_2.5.3_20240925.simg/opt/ants/bin"
export MRTRIXDIR="/cvmfs/neurodesk.ardc.edu.au/containers/mrtrix3_3.0.4_20240320/mrtrix3_3.0.4_20240320.simg/opt/mrtrix3/bin"
export CONNWBIN="/cvmfs/neurodesk.ardc.edu.au/containers/connectomeworkbench_1.5.0_20220914/connectomeworkbench_1.5.0_20220914.simg/opt/workbench/bin_linux64"
export PATH="$ANTSPATH:$MRTRIXDIR:$CONNWBIN:$PATH"

export FS_LICENSE="$HOME/.freesurfer_license.txt"
export APPTAINERENV_FS_LICENSE="$FS_LICENSE"

export NUMBA_DISABLE_CACHING=1
export NUMBA_CACHE_DIR="$HOME/.cache/numba-cache"
mkdir -p "$NUMBA_CACHE_DIR"

export NEURODESK_PATH="/cvmfs/neurodesk.ardc.edu.au"
export NEURODESK_CONTAINERS="$NEURODESK_PATH/containers"
export NEURODESK_MODULES="$NEURODESK_PATH/neurodesk-modules"

# Optional: control threaded tools
export OMP_NUM_THREADS=4
```

> Note: the module names above reflect the current Neurodesk catalog; use `module avail` to confirm versions (e.g., `qsiprep/0.20.0`) and adjust the paths if you mirror Neurodesk locally.

## Testing the Environment

Run the test suite to verify all tools work:
```bash
conda activate neuroimaging_env
cd <repo>
python tests/integration/real_data/run_all_tests.py
```

Expected output:
- All 108 tools should load without fallback warnings
- Success rate should be 100% (up from 94.1% without optional deps)

## Environment File Location
- Main file: `<repo>/neuroimage_env.yaml`
- This is the ONLY environment file needed for neuroimaging tools
- Previous files (minimal, essential) have been removed to avoid confusion

## Updating the Environment

To add new dependencies:
1. Edit `neuroimage_env.yaml`
2. Update the environment:
   ```bash
   conda env update -f neuroimage_env.yaml
   ```

Or install directly:
```bash
conda activate neuroimaging_env
conda install new_package  # or pip install new_package
```

