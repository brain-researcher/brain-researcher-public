"""
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
friprep --version
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
export APPTAINER_BINDPATH="${PROJECT_ROOT}:${PROJECT_ROOT},/app:/app,/tmp:/tmp"
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
export FS_LICENSE="/app/.freesurfer_license.txt"
export TEMPLATEFLOW_HOME="/app/.cache/templateflow"
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
module show fsl/6.0.3         # Show module file contents
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
friprep bids_dataset/ output/ participant --participant-label 01

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

Neurodesk tool wrappers for the Brain Researcher Agent.

Provides command generation for 100+ neuroimaging tools available through
Neurodesk/CVMFS, including FSL, SPM, MRtrix3, ANTs, FreeSurfer, and more.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.services.tools.runtime_profiles import (
    get_neurodesk_package_profile,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


# Base path for CVMFS neurodesk containers
CVMFS_BASE = "/cvmfs/neurodesk.ardc.edu.au"
CONTAINERS_PATH = f"{CVMFS_BASE}/containers"


@dataclass
class NeurodeskTool:
    """Metadata for a Neurodesk tool."""

    name: str
    module_name: str
    version: str
    container_path: str
    category: str
    description: str
    common_commands: dict[str, str]
    requires_gpu: bool = False
    requires_license: bool = False


def _neurodesk_profile_defaults(
    package: str,
    *,
    module_name: str,
    version: str,
    container_path: str,
) -> tuple[str, str, str]:
    profile = get_neurodesk_package_profile(package)
    if not isinstance(profile, dict):
        return module_name, version, container_path

    resolved_module = (
        str(profile.get("module_name") or module_name).strip() or module_name
    )
    resolved_version = str(profile.get("version") or version).strip() or version
    resolved_container = (
        str(profile.get("container_path") or container_path).strip() or container_path
    )
    return resolved_module, resolved_version, resolved_container


_FSL_MODULE, _FSL_VERSION, _FSL_CONTAINER = _neurodesk_profile_defaults(
    "fsl",
    module_name="fsl",
    version="6.0.7.16",
    container_path=f"{CONTAINERS_PATH}/fsl_6.0.7.16_20250131",
)
_MRTRIX3_MODULE, _MRTRIX3_VERSION, _MRTRIX3_CONTAINER = _neurodesk_profile_defaults(
    "mrtrix3",
    module_name="mrtrix3",
    version="3.0.7",
    container_path=f"{CONTAINERS_PATH}/mrtrix3_3.0.7_20250805",
)
_ANTS_MODULE, _ANTS_VERSION, _ANTS_CONTAINER = _neurodesk_profile_defaults(
    "ants",
    module_name="ants",
    version="2.5.3",
    container_path=f"{CONTAINERS_PATH}/ants_2.5.3_20240915",
)
_FREESURFER_MODULE, _FREESURFER_VERSION, _FREESURFER_CONTAINER = (
    _neurodesk_profile_defaults(
        "freesurfer",
        module_name="freesurfer",
        version="7.4.1",
        container_path=f"{CONTAINERS_PATH}/freesurfer_7.4.1_20240507",
    )
)
_AFNI_MODULE, _AFNI_VERSION, _AFNI_CONTAINER = _neurodesk_profile_defaults(
    "afni",
    module_name="afni",
    version="24.3.10",
    container_path=f"{CONTAINERS_PATH}/afni_24.3.10_20241108",
)
_FMRIPREP_MODULE, _FMRIPREP_VERSION, _FMRIPREP_CONTAINER = _neurodesk_profile_defaults(
    "fmriprep",
    module_name="fmriprep",
    version="23.2.3",
    container_path=f"{CONTAINERS_PATH}/fmriprep_23.2.3_20240916",
)
_MRIQC_MODULE, _MRIQC_VERSION, _MRIQC_CONTAINER = _neurodesk_profile_defaults(
    "mriqc",
    module_name="mriqc",
    version="24.0.2",
    container_path=f"{CONTAINERS_PATH}/mriqc_24.0.2_20241113",
)
_DCM2NIIX_MODULE, _DCM2NIIX_VERSION, _DCM2NIIX_CONTAINER = _neurodesk_profile_defaults(
    "dcm2niix",
    module_name="dcm2niix",
    version="v1.0.20240202",
    container_path=f"{CONTAINERS_PATH}/dcm2niix_1.0.20240202_20240202",
)


# Registry of available Neurodesk tools
NEURODESK_TOOLS = {
    "fsl": NeurodeskTool(
        name="FSL",
        module_name=_FSL_MODULE,
        version=_FSL_VERSION,
        container_path=_FSL_CONTAINER,
        category="structural_functional",
        description="FMRIB Software Library for brain imaging analysis",
        common_commands={
            "bet": "bet",  # Brain extraction
            "flirt": "flirt",  # Linear registration
            "fnirt": "fnirt",  # Non-linear registration
            "feat": "feat",  # fMRI analysis
            "melodic": "melodic",  # ICA analysis
            "pnm_stage1": "pnm_stage1",  # Physiological preprocessing
            "pnm_evs": "pnm_evs",  # Slice-aware physiological EVs
            "fslmaths": "fslmaths",  # Image calculator
            "fslstats": "fslstats",  # Image statistics
        },
    ),
    "mrtrix3": NeurodeskTool(
        name="MRtrix3",
        module_name=_MRTRIX3_MODULE,
        version=_MRTRIX3_VERSION,
        container_path=_MRTRIX3_CONTAINER,
        category="diffusion",
        description="Advanced diffusion MRI analysis and tractography",
        common_commands={
            "mrinfo": "mrinfo",  # Display image header info
            "mrconvert": "mrconvert",  # Convert between formats
            "dwi2tensor": "dwi2tensor",  # Tensor estimation
            "tckgen": "tckgen",  # Tractography
            "mrview": "mrview",  # Image viewer
        },
    ),
    "spm12": NeurodeskTool(
        name="SPM12",
        module_name="physio",
        version="r7771",
        container_path=f"{CONTAINERS_PATH}/physio_r7771_20211206",
        category="statistical",
        description="Statistical Parametric Mapping for neuroimaging",
        common_commands={
            "spm12": "spm12",  # Main SPM interface
        },
        requires_license=True,  # Requires MATLAB runtime
    ),
    "ants": NeurodeskTool(
        name="ANTs",
        module_name=_ANTS_MODULE,
        version=_ANTS_VERSION,
        container_path=_ANTS_CONTAINER,
        category="registration",
        description="Advanced Normalization Tools for image registration",
        common_commands={
            "antsRegistration": "antsRegistration",
            "antsApplyTransforms": "antsApplyTransforms",
            "N4BiasFieldCorrection": "N4BiasFieldCorrection",
            "antsCorticalThickness": "antsCorticalThickness.sh",
        },
    ),
    "freesurfer": NeurodeskTool(
        name="FreeSurfer",
        module_name=_FREESURFER_MODULE,
        version=_FREESURFER_VERSION,
        container_path=_FREESURFER_CONTAINER,
        category="structural",
        description="Cortical surface reconstruction and analysis",
        common_commands={
            "recon-all": "recon-all",
            "mri_convert": "mri_convert",
            "mris_info": "mris_info",
            "tkmedit": "tkmedit",
            "tksurfer": "tksurfer",
        },
        requires_license=True,
    ),
    "afni": NeurodeskTool(
        name="AFNI",
        module_name=_AFNI_MODULE,
        version=_AFNI_VERSION,
        container_path=_AFNI_CONTAINER,
        category="functional",
        description="Analysis of Functional NeuroImages",
        common_commands={
            "3dSkullStrip": "3dSkullStrip",
            "3dvolreg": "3dvolreg",
            "3dDeconvolve": "3dDeconvolve",
            "3dClustSim": "3dClustSim",
            "afni": "afni",  # GUI
        },
    ),
    "fmriprep": NeurodeskTool(
        name="fMRIPrep",
        module_name=_FMRIPREP_MODULE,
        version=_FMRIPREP_VERSION,
        container_path=_FMRIPREP_CONTAINER,
        category="preprocessing",
        description="Robust preprocessing pipeline for fMRI data",
        common_commands={
            "fmriprep": "fmriprep",
        },
        requires_license=True,  # FreeSurfer license
    ),
    "mriqc": NeurodeskTool(
        name="MRIQC",
        module_name=_MRIQC_MODULE,
        version=_MRIQC_VERSION,
        container_path=_MRIQC_CONTAINER,
        category="quality_control",
        description="MRI quality control tool",
        common_commands={
            "mriqc": "mriqc",
        },
    ),
    "dcm2niix": NeurodeskTool(
        name="dcm2niix",
        module_name=_DCM2NIIX_MODULE,
        # version from module avail (local neurocommand container list)
        version=_DCM2NIIX_VERSION,
        # container path is optional for module-based execution; keep a sensible default
        container_path=_DCM2NIIX_CONTAINER,
        category="conversion",
        description="DICOM to NIfTI converter with BIDS sidecar support",
        common_commands={
            "dcm2niix": "dcm2niix",
        },
    ),
}


class NeurodeskCommandArgs(BaseModel):
    """Arguments for Neurodesk tool command generation."""

    tool_name: str = Field(
        description="Name of the neuroimaging tool (e.g., 'fsl', 'mrtrix3')"
    )
    command: str = Field(description="Specific command to run (e.g., 'bet', 'flirt')")
    input_files: list[str] = Field(description="Input file paths")
    output_path: str | None = Field(
        default=None, description="Output file or directory path"
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Tool-specific parameters as key-value pairs"
    )
    execute: bool = Field(
        default=False,
        description="If true, return a command intended for execution and set preview to False. This tool only generates commands and does not execute them.",
    )
    use_module: bool = Field(
        default=True,
        description="Use module system (True) or direct CVMFS path (False)",
    )
    bind_paths: list[str] | None = Field(
        default=None, description="Additional paths to bind for container access"
    )


class NeurodeskCommandGenerator(NeuroToolWrapper):
    """
    Generates commands for Neurodesk neuroimaging tools.

    Returns executable commands that users can run in their environment
    where Neurodesk/CVMFS is properly configured.
    """

    def get_tool_name(self) -> str:
        return "neurodesk_command"

    def get_tool_description(self) -> str:
        return (
            "Generate executable commands for Neurodesk neuroimaging tools. "
            "Supports FSL, SPM, MRtrix3, ANTs, FreeSurfer, AFNI, and 100+ other tools. "
            "Returns commands that can be executed in a Neurodesk-enabled environment."
        )

    def get_args_schema(self):
        return NeurodeskCommandArgs

    def _run(
        self,
        tool_name: str,
        command: str,
        input_files: list[str],
        output_path: str | None = None,
        parameters: dict[str, Any] | None = None,
        use_module: bool = True,
        bind_paths: list[str] | None = None,
        execute: bool = False,
    ) -> ToolResult:
        """Generate Neurodesk tool command."""
        try:
            # Validate tool exists
            tool_info = NEURODESK_TOOLS.get(tool_name.lower())
            if not tool_info:
                available = ", ".join(NEURODESK_TOOLS.keys())
                return ToolResult(
                    status="error",
                    error=f"Unknown tool '{tool_name}'. Available tools: {available}",
                )

            # Validate command exists for tool
            if command not in tool_info.common_commands:
                available_cmds = ", ".join(tool_info.common_commands.keys())
                logger.warning(
                    f"Command '{command}' not in common commands for {tool_name}. "
                    f"Common commands: {available_cmds}"
                )

            # Generate command based on mode (command-only; this tool never executes)
            if use_module:
                generated_cmd = self._generate_module_command(
                    tool_info, command, input_files, output_path, parameters
                )
            else:
                generated_cmd = self._generate_cvmfs_command(
                    tool_info, command, input_files, output_path, parameters, bind_paths
                )

            # Add usage instructions
            instructions = self._get_usage_instructions(tool_info, use_module)

            return ToolResult(
                status="success",
                data={
                    "command": generated_cmd,
                    "tool": tool_name,
                    "tool_version": tool_info.version,
                    "execution_mode": "module" if use_module else "cvmfs_direct",
                    "instructions": instructions,
                    "requires_gpu": tool_info.requires_gpu,
                    "requires_license": tool_info.requires_license,
                    "preview": not execute,
                    "execute": execute,
                    "notes": "Command-only generator; tool not executed by this agent",
                },
                metadata={"tool": "neurodesk_command", "category": tool_info.category},
            )

        except Exception as e:
            logger.error(f"Command generation failed: {str(e)}")
            return ToolResult(
                status="error",
                error=f"Failed to generate command: {str(e)}",
                metadata={"tool": "neurodesk_command"},
            )

    def _generate_module_command(
        self,
        tool_info: NeurodeskTool,
        command: str,
        input_files: list[str],
        output_path: str | None,
        parameters: dict[str, Any] | None,
    ) -> str:
        """Generate command using module system."""
        cmd_parts = []

        # Module load command
        cmd_parts.append(f"module load {tool_info.module_name}/{tool_info.version}")
        cmd_parts.append("&&")

        # Tool command
        tool_cmd = tool_info.common_commands.get(command, command)
        cmd_parts.append(tool_cmd)

        # Add input files
        for input_file in input_files:
            cmd_parts.append(input_file)

        # Add output path if specified
        if output_path:
            cmd_parts.append(output_path)

        # Add parameters
        if parameters:
            for key, value in parameters.items():
                # Handle different parameter formats
                if key.startswith("--"):
                    param_flag = key
                elif key.startswith("-"):
                    param_flag = key
                else:
                    param_flag = f"-{key}" if len(key) == 1 else f"--{key}"

                if isinstance(value, bool):
                    if value:
                        cmd_parts.append(param_flag)
                elif value is not None:
                    cmd_parts.append(param_flag)
                    cmd_parts.append(str(value))

        return " ".join(cmd_parts)

    def _generate_cvmfs_command(
        self,
        tool_info: NeurodeskTool,
        command: str,
        input_files: list[str],
        output_path: str | None,
        parameters: dict[str, Any] | None,
        bind_paths: list[str] | None,
    ) -> str:
        """Generate command using direct CVMFS path."""
        cmd_parts = []

        # Use apptainer/singularity to run container
        cmd_parts.append("apptainer exec")

        # Add bind paths
        if bind_paths:
            for path in bind_paths:
                cmd_parts.append(f"-B {path}")

        # Add default binds for input/output
        for input_file in input_files:
            input_dir = os.path.dirname(input_file)
            if input_dir:
                cmd_parts.append(f"-B {input_dir}")

        if output_path:
            output_dir = (
                os.path.dirname(output_path)
                if not os.path.isdir(output_path)
                else output_path
            )
            if output_dir:
                cmd_parts.append(f"-B {output_dir}")

        # Container path
        cmd_parts.append(f"{tool_info.container_path}")

        # Tool command
        tool_cmd = tool_info.common_commands.get(command, command)
        cmd_parts.append(tool_cmd)

        # Add input files
        for input_file in input_files:
            cmd_parts.append(input_file)

        # Add output
        if output_path:
            cmd_parts.append(output_path)

        # Add parameters
        if parameters:
            for key, value in parameters.items():
                if key.startswith("--") or key.startswith("-"):
                    param_flag = key
                else:
                    param_flag = f"-{key}" if len(key) == 1 else f"--{key}"

                if isinstance(value, bool):
                    if value:
                        cmd_parts.append(param_flag)
                elif value is not None:
                    cmd_parts.append(param_flag)
                    cmd_parts.append(str(value))

        return " ".join(cmd_parts)

    def _get_usage_instructions(
        self, tool_info: NeurodeskTool, use_module: bool
    ) -> str:
        """Get usage instructions for the tool."""
        instructions = []

        if use_module:
            instructions.append("1. Ensure Neurodesk module system is configured")
            instructions.append(f"2. Run: module avail {tool_info.module_name}")
            instructions.append("3. Execute the generated command")
        else:
            instructions.append(f"1. Ensure CVMFS is mounted at {CVMFS_BASE}")
            instructions.append("2. Ensure apptainer/singularity is installed")
            instructions.append("3. Execute the generated command")

        if tool_info.requires_license:
            instructions.append(
                "4. License required: Ensure proper license is configured"
            )

        if tool_info.requires_gpu:
            instructions.append("5. GPU required: Add --nv flag for GPU support")

        return "\n".join(instructions)


class FSLCommandGenerator(NeurodeskCommandGenerator):
    """Specialized generator for FSL commands."""

    def get_tool_name(self) -> str:
        return "fsl_command"

    def get_tool_description(self) -> str:
        return (
            "Generate FSL (FMRIB Software Library) commands for brain extraction, "
            "registration, statistical analysis, and more."
        )

    def _run(self, **kwargs) -> ToolResult:
        # Force tool_name to be FSL
        kwargs["tool_name"] = "fsl"
        return super()._run(**kwargs)


class MRtrix3CommandGenerator(NeurodeskCommandGenerator):
    """Specialized generator for MRtrix3 commands."""

    def get_tool_name(self) -> str:
        return "mrtrix3_command"

    def get_tool_description(self) -> str:
        return (
            "Generate MRtrix3 commands for diffusion MRI processing, "
            "tractography, and connectome analysis."
        )

    def _run(self, **kwargs) -> ToolResult:
        kwargs["tool_name"] = "mrtrix3"
        return super()._run(**kwargs)


class BatchNeurodeskArgs(BaseModel):
    """Arguments for batch command generation."""

    commands: list[dict[str, Any]] = Field(
        description="List of command specifications, each containing tool_name, command, input_files, etc."
    )
    pipeline_name: str | None = Field(
        default=None, description="Name for the processing pipeline"
    )
    parallel: bool = Field(
        default=False, description="Generate commands for parallel execution"
    )


class BatchNeurodeskGenerator(NeuroToolWrapper):
    """Generate batch processing scripts for multiple Neurodesk tools."""

    def get_tool_name(self) -> str:
        return "neurodesk_batch"

    def get_tool_description(self) -> str:
        return (
            "Generate batch processing scripts that chain multiple Neurodesk tools "
            "for complex neuroimaging pipelines."
        )

    def get_args_schema(self):
        return BatchNeurodeskArgs

    def _run(
        self,
        commands: list[dict[str, Any]],
        pipeline_name: str | None = None,
        parallel: bool = False,
    ) -> ToolResult:
        """Generate batch script."""
        try:
            script_lines = ["#!/bin/bash", ""]

            if pipeline_name:
                script_lines.append(f"# Pipeline: {pipeline_name}")
                script_lines.append("")

            # Add error handling
            script_lines.append("set -e  # Exit on error")
            script_lines.append("")

            # Generate commands
            generator = NeurodeskCommandGenerator()
            generated_commands = []

            for i, cmd_spec in enumerate(commands, 1):
                script_lines.append(
                    f"# Step {i}: {cmd_spec.get('tool_name', 'Unknown')} - {cmd_spec.get('command', 'Unknown')}"
                )

                result = generator._run(**cmd_spec)
                if result.status == "success":
                    command = result.data["command"]
                    generated_commands.append(command)

                    if parallel and i < len(commands):
                        script_lines.append(f"{command} &")
                    else:
                        script_lines.append(command)

                    script_lines.append("")
                else:
                    return ToolResult(
                        status="error",
                        error=f"Failed to generate command {i}: {result.error}",
                    )

            if parallel:
                script_lines.append("wait  # Wait for parallel jobs to complete")
                script_lines.append("")

            script_lines.append("echo 'Pipeline completed successfully!'")

            script_content = "\n".join(script_lines)

            return ToolResult(
                status="success",
                data={
                    "script": script_content,
                    "commands": generated_commands,
                    "pipeline_name": pipeline_name or "neurodesk_pipeline",
                    "num_steps": len(commands),
                    "execution_mode": "parallel" if parallel else "sequential",
                },
                metadata={"tool": "neurodesk_batch"},
            )

        except Exception as e:
            logger.error(f"Batch script generation failed: {str(e)}")
            return ToolResult(
                status="error",
                error=f"Failed to generate batch script: {str(e)}",
                metadata={"tool": "neurodesk_batch"},
            )


class NeurodeskTools:
    """Collection of all Neurodesk tool generators."""

    def __init__(self):
        self.general = NeurodeskCommandGenerator()
        self.fsl = FSLCommandGenerator()
        self.mrtrix3 = MRtrix3CommandGenerator()
        self.batch = BatchNeurodeskGenerator()

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        """Get all Neurodesk tool generators."""
        return [self.general, self.fsl, self.mrtrix3, self.batch]

    def get_tool_by_name(self, name: str) -> NeuroToolWrapper | None:
        """Get a specific tool generator by name."""
        tool_map = {
            "neurodesk_command": self.general,
            "fsl_command": self.fsl,
            "mrtrix3_command": self.mrtrix3,
            "neurodesk_batch": self.batch,
        }
        return tool_map.get(name)

    def list_available_tools(self) -> dict[str, dict[str, Any]]:
        """List all available Neurodesk tools with metadata."""
        tools_info = {}
        for tool_name, tool_info in NEURODESK_TOOLS.items():
            tools_info[tool_name] = {
                "name": tool_info.name,
                "version": tool_info.version,
                "module": f"{tool_info.module_name}/{tool_info.version}",
                "category": tool_info.category,
                "description": tool_info.description,
                "commands": list(tool_info.common_commands.keys()),
                "requires_gpu": tool_info.requires_gpu,
                "requires_license": tool_info.requires_license,
            }
        return tools_info
