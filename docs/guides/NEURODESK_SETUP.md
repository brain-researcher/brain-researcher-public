# Neurodesk Module Setup Guide

Complete setup guide for the **official Neurodesk approach**: module system with local preinstalls for high-frequency tools + CVMFS for everything else.

## Quick Start

```bash
# Environment loads automatically via .bashrc
# Or manually: source ~/projects/brain_researcher/scripts/setup/setup_neurocommand_modules.sh

# List available tools
module avail                    # All modules
module avail fsl                # All FSL versions

# Load high-frequency tools (local, fast)
module load fsl/6.0.3           # Local version (priority)
module load fmriprep/23.2.1     # Local version
module load dcm2niix            # Local version
module load mriqc               # Local version
module load ants                # Local version

# Load long-tail tools (CVMFS, auto-cached)
module load afni               # CVMFS (first load may be slow)
module load spm12              # CVMFS
module load conn               # CVMFS

# Check loaded modules
module list

# Use tools directly (no errors!)
bet structural.nii brain.nii
fmriprep --version
dcm2niix -h
```

## Architecture

### Local Tools (High-Frequency, Fast Access)
Preinstalled locally for immediate access:
- **FSL 6.0.3** - FMRIB Software Library
- **fMRIPrep 23.2.1** - fMRI preprocessing pipeline
- **FreeSurfer 7.4.1** - Cortical reconstruction
- **ANTs 2.5.3** - Advanced Normalization Tools
- **dcm2niix v1.0.20240202** - DICOM to NIfTI conversion
- **MRIQC 24.0.2** - MRI quality control
- **ConnectomeWorkbench 1.5.0** - Surface analysis (wb_command)
- **MRtrix3 3.0.4** - Diffusion MRI analysis

### CVMFS Tools (Long-Tail, Auto-Cached)
Accessed on-demand via network filesystem:
- SPM12, AFNI, CONN, QSIPrep, etc.
- First load may be slow (downloading), subsequent loads are fast (cached)
- Requires CVMFS mount at `/cvmfs/neurodesk.ardc.edu.au`

## Key Fixes Applied

### 1. **Unified Bind Paths**
Prevents "different values" warnings:
```bash
export APPTAINER_BINDPATH="${PROJECT_ROOT}:${PROJECT_ROOT},${HOME}:${HOME},/tmp:/tmp"
export SINGULARITY_BINDPATH="${APPTAINER_BINDPATH}"  # Identical!
```

### 2. **Working Directory Fix**
Project directory bound at same path inside containers:
- ✅ FSL works from `/home/user/projects/brain_researcher/`
- ✅ No more "failed to set working directory" errors

### 3. **Modules.sh Silencer**
Creates override to suppress login shell errors:
```bash
# Override file: ~/nd_overrides/modules.sh
[ -r /usr/share/modules/init/sh ] && . /usr/share/modules/init/sh || :
```

### 4. **Essential Environment Variables**
```bash
export FS_LICENSE="${HOME}/.freesurfer_license.txt"
export TEMPLATEFLOW_HOME="${HOME}/.cache/templateflow"
export APPTAINERENV_FS_LICENSE="${FS_LICENSE}"
export APPTAINERENV_TEMPLATEFLOW_HOME="${TEMPLATEFLOW_HOME}"
export APPTAINERENV_ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=8
```

### 5. **SCRATCH Cache Support**
Uses `/scratch` if available to prevent HOME quota issues:
```bash
[ -n "$SCRATCH" ] && \
export APPTAINER_CACHEDIR="${SCRATCH}/.apptainer-cache" \
       APPTAINER_TMPDIR="${SCRATCH}/.apptainer-tmp"
```

### 6. **Standard Module System**
Official Neurodesk approach using native module commands:
```bash
module avail fmriprep      # Shows: fmriprep/23.2.1
module avail ants          # Shows: ants/2.5.3
module avail freesurfer    # Shows: freesurfer/7.4.1
```

## Module Commands

### List Available Tools
```bash
module avail                    # All available modules
module avail fsl                # All FSL versions
module avail | grep fmri        # Search for fMRI tools
```

### Load/Unload Modules
```bash
module load fsl/6.0.3           # Load specific version
module load fmriprep            # Load default version
module list                     # Show loaded modules
module unload fsl               # Unload specific module
module purge                    # Unload all modules
```

### Module Information
```bash
module whatis fsl/6.0.3         # Brief description
module help fsl                 # Detailed help
module show fsl/6.0.3           # Show module file contents
```

### Priority System
- **Local modules** take precedence (high-frequency tools)
- **CVMFS modules** provide fallback (long-tail tools)
- Module path order: Local → CVMFS (first match wins)

### Verified Working Modules
```bash
# Local modules (installed and tested)
module load fsl/6.0.3           ✓ Working
module load fmriprep/23.2.1     ✓ Working
module load freesurfer/7.4.1    ✓ Working
module load ants/2.5.3          ✓ Working
module load dcm2niix            ✓ Working
module load mriqc/24.0.2        ✓ Working
module load connectomeworkbench ✓ Working (wb_command)
module load mrtrix3/3.0.4       ✓ Working

# CVMFS modules (available, auto-cached)
module load afni               ✓ Available
module load spm12              ✓ Available
module load conn               ✓ Available
```

## Prerequisites

### FreeSurfer License (Required)
```bash
# Download license from: https://surfer.nmr.mgh.harvard.edu/registration.html
# Save as: ~/.freesurfer_license.txt
```

### TemplateFlow Cache (Recommended)
```bash
# Will be created automatically at: ~/.cache/templateflow
# Or set custom location: export TEMPLATEFLOW_HOME="/path/to/templates"
```

## Troubleshooting

### Module System Issues

**Problem**: `MODULEPATH is not set` or `module avail` fails
**Solution**: Reload the environment
```bash
source ~/projects/brain_researcher/scripts/setup/setup_neurocommand_modules.sh
module avail  # Should now work
```

**Problem**: `module load fsl` fails with "module unknown"
**Solution**: Check available versions and use specific version
```bash
module avail fsl              # See available versions
module load fsl/6.0.3         # Use specific version
```

### Container Error Messages (FIXED!)

**Problem**: ❌ `/etc/profile.d/modules.sh: No such file or directory`
**Solution**: ✅ Already fixed with silent modules.sh override
- Containers now use silent override that doesn't show errors
- Host manages modules, containers run quietly

**Problem**: Working directory errors
**Solution**: ✅ Already fixed with proper bind paths
- Project directory bound at same path in containers
- FSL and other tools work from any project subdirectory

### Working Directory Errors
**Problem**: `failed to set working directory: chdir /path: no such file or directory`
**Solution**: Verify bind paths include project directory at same location

```bash
echo $APPTAINER_BINDPATH
# Should show: /home/user/projects/brain_researcher:/home/user/projects/brain_researcher
```

### Module System Errors
**Problem**: `/usr/share/modules/init/sh: No such file or directory`
**Solution**: Already fixed by modules.sh override (safe to ignore)

### Cache/Quota Issues
**Problem**: HOME directory quota exceeded
**Solution**: Use SCRATCH for cache:
```bash
export SCRATCH="/scratch/username"
source scripts/neurodesk-hybrid.sh
```

### Commands Not in PATH
**Problem**: `fmriprep: command not found`
**Solution**: Check installation and reload environment:
```bash
neurodesk_status  # Check if tool is installed
source scripts/neurodesk-hybrid.sh  # Reload environment
```

## Environment Integration

### .bashrc Setup
The environment is automatically loaded via .bashrc:
```bash
# Neurodesk/Neurocommand Hybrid Setup
if [ -f "$HOME/projects/brain_researcher/scripts/neurodesk-hybrid.sh" ]; then
    source "$HOME/projects/brain_researcher/scripts/neurodesk-hybrid.sh"
fi
```

### HPC Integration
Automatically detects and binds common HPC paths:
- `/oak` - Research storage
- `/scratch` - Fast temporary storage
- `/data` - Shared data directories

### CVMFS Integration
When CVMFS is available:
```bash
module avail                    # List all available tools
module load <tool>              # Load CVMFS-based tool
module list                     # Show loaded modules
```

## Example Workflows

### Daily Neuroimaging Workflow
```bash
# Load all daily tools at once
module load fsl/6.0.3 fmriprep/23.2.1 dcm2niix mriqc

# Convert DICOM to BIDS
dcm2niix -f %p_%s dicom_folder/

# Run fMRIPrep
fmriprep bids_dataset/ output/ participant --participant-label 01

# Basic FSL analysis
bet structural.nii brain.nii
flirt -in functional.nii -ref structural.nii -out aligned.nii

# Quality control
mriqc bids_dataset/ output/mriqc/ participant --participant-label 01
```

### Advanced Analysis (CVMFS Tools)
```bash
# Load specialized tools (first time may be slow due to CVMFS download)
module load afni spm12 conn

# AFNI analysis
3dSkullStrip -input anat.nii -prefix brain.nii
3dTstat -mean -prefix mean.nii input.nii

# Connectivity analysis with CONN
# (launches GUI or batch processing)
```

### Development/Testing Workflow
```bash
# Quick tool switching
module list                    # See what's loaded
module unload fsl             # Remove specific module
module purge                  # Clear all modules
module load fsl/6.0.7.16     # Load different version (CVMFS)

# Check module information
module show fsl/6.0.3         # See what the module does
module whatis fmriprep        # Brief description
```

## File Structure

```
~/projects/brain_researcher/
├── docs/
│   ├── NEURODESK_SETUP.md            # This guide (updated)
│   └── archive/                      # Old documentation
├── scripts/
│   └── setup_neurocommand_modules.sh # Clean module setup script
├── external/neurocommand/
│   └── neurocommand-repo/
│       └── local/containers/
│           ├── fsl_6.0.3_20200905/           # FSL (5.5GB)
│           ├── fmriprep_23.2.1_20240402/     # fMRIPrep (~4GB)
│           ├── freesurfer_7.4.1_20231214/    # FreeSurfer (~3GB)
│           ├── ants_2.5.3_20240925/          # ANTs (~500MB)
│           ├── dcm2niix_v1.0.20240202_20241125/    # DICOM converter
│           ├── mriqc_24.0.2_20241108/        # Quality control
│           ├── connectomeworkbench_1.5.0_20220919/ # Surface analysis
│           ├── mrtrix3_3.0.4_20240320/       # Diffusion MRI
│           └── modules/                      # Local module files
└── ~/nd_overrides/
    └── modules.sh                    # Silent modules override for containers
```

## Version History

### v2.0 (Current)
- ✅ All 6 critical fixes applied
- ✅ Dynamic version lookup
- ✅ Unified bind paths
- ✅ modules.sh silencer
- ✅ Essential environment variables
- ✅ SCRATCH cache support
- ✅ Absolute paths everywhere

### v1.0 (Previous)
- ❌ Hardcoded dates causing pull failures
- ❌ Inconsistent bind paths
- ❌ modules.sh errors
- ❌ Working directory failures

## References

- [Neurodesk Official Documentation](https://neurodesk.org/getting-started/neurocommand/linux-and-hpc/)
- [fMRIPrep 23.2.1 Documentation](https://fmriprep.org/en/23.2.1/)
- [FreeSurfer License Registration](https://surfer.nmr.mgh.harvard.edu/registration.html)
- [Container Versions List](https://raw.githubusercontent.com/NeuroDesk/neurocommand/master/cvmfs/log.txt)