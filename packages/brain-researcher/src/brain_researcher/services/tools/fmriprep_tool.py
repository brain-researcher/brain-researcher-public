"""
fMRIPrep Tool Implementation for the BR-KG LangGraph system.

Implements fMRIPrep for comprehensive fMRI preprocessing with 
BIDS validation, quality control, and multiple output options.
"""

import json
import logging
import os
import shlex
import tempfile
import time
from contextlib import nullcontext
from dataclasses import replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from brain_researcher.services.tools.pipelines import (
    FMRIPrepParameters,
    build_fmriprep_command,
    fmriprep_from_payload,
)

from brain_researcher.services.agent.execution import (
    CommandSpec,
    CommandExecutionError,
    JobLogEmitter,
    run_command,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class OutputSpace(str, Enum):
    """Common output spaces for fMRIPrep."""
    MNI152NLin2009cAsym = "MNI152NLin2009cAsym"
    MNI152NLin6Asym = "MNI152NLin6Asym"
    MNI152Lin = "MNI152Lin"
    OASIS30ANTs = "OASIS30ANTs"
    FSAVERAGE = "fsaverage"
    FSNATIVE = "fsnative"
    T1W = "T1w"
    FUNC = "func"


class CiftiOutput(str, Enum):
    """CIFTI output resolutions."""
    NONE = ""
    RES_91K = "91k"
    RES_170K = "170k"


class ErrorMode(str, Enum):
    """Error handling modes."""
    CRASH = "crash"
    CONTINUE = "continue"
    
    
class MemoryProfile(str, Enum):
    """Memory profile settings."""
    LOW = "low"  # < 8GB
    MEDIUM = "medium"  # 8-16GB  
    HIGH = "high"  # 16-32GB
    RESAMPLING = "resampling"  # > 32GB


# Backwards compatible alias for tests/importers that still import FMRIPrepConfig.
FMRIPrepConfig = FMRIPrepParameters


class FMRIPrepArgs(BaseModel):
    """Arguments for fMRIPrep preprocessing."""
    
    bids_dir: str = Field(
        description="Path to BIDS dataset directory"
    )
    output_dir: str = Field(
        description="Output directory for fMRIPrep results"
    )
    participant_label: Optional[List[str]] = Field(
        default=None,
        description="Participant labels to process (without 'sub-' prefix)"
    )
    work_dir: Optional[str] = Field(
        default=None,
        description="Working directory for intermediate files"
    )
    fs_license_file: Optional[str] = Field(
        default=None,
        description="Path to FreeSurfer license file"
    )
    output_spaces: Optional[List[str]] = Field(
        default=None,
        description="Output spaces for registration (e.g., ['MNI152NLin2009cAsym', 'fsaverage'])"
    )
    skip_bids_validation: bool = Field(
        default=False,
        description="Skip BIDS dataset validation"
    )
    use_aroma: bool = Field(
        default=False,
        description="Use ICA-AROMA for denoising"
    )
    cifti_output: Optional[str] = Field(
        default=None,
        description="Generate CIFTI outputs at specified resolution (91k or 170k)"
    )
    n_cpus: Optional[int] = Field(
        default=None,
        description="Number of CPUs to use"
    )
    mem_mb: Optional[int] = Field(
        default=None,
        description="Memory limit in MB"
    )
    low_mem: bool = Field(
        default=False,
        description="Use low-memory settings"
    )
    stop_on_first_crash: bool = Field(
        default=False,
        description="Stop on first crash instead of continuing"
    )
    longitudinal: bool = Field(
        default=False,
        description="Enable longitudinal processing"
    )
    skull_strip_t1w: str = Field(
        default="auto",
        description="Skull stripping method (auto, skip, or force)"
    )
    bold2t1w_dof: int = Field(
        default=6,
        description="Degrees of freedom for BOLD to T1w registration (6, 9, or 12)"
    )
    fd_spike_threshold: float = Field(
        default=0.5,
        description="Framewise displacement threshold for motion outliers (mm)"
    )
    dvars_spike_threshold: float = Field(
        default=1.5,
        description="DVARS threshold for motion outliers"
    )
    use_syn_sdc: Optional[str] = Field(
        default=None,
        description="Use fieldmap-less distortion correction (error or warn)"
    )
    force_syn: bool = Field(
        default=False,
        description="Force fieldmap-less correction"
    )
    container_type: str = Field(
        default="singularity",
        description="Container type to use (singularity or docker)"
    )
    container_image: Optional[str] = Field(
        default=None,
        description="Path to container image or docker tag"
    )
    execute: bool = Field(
        default=False,
        description="Execute the generated command instead of returning it only"
    )
    timeout_minutes: Optional[int] = Field(
        default=12 * 60,
        description="Timeout in minutes when executing the container (default 12h)"
    )


class FMRIPrepTool(NeuroToolWrapper):
    """fMRIPrep preprocessing tool."""
    
    def __init__(self):
        """Initialize fMRIPrep tool."""
        super().__init__()
        # Check for Neurodesk/CVMFS installation
        self.neurodesk_path = "/cvmfs/neurodesk.ardc.edu.au/containers"
        self.default_image = "nipreps/fmriprep:latest"
        
    def get_tool_name(self) -> str:
        return "fmriprep_preprocessing"
    
    def get_tool_description(self) -> str:
        return (
            "Run fMRIPrep for comprehensive fMRI preprocessing including motion correction, "
            "distortion correction, registration, and confound extraction. "
            "Supports BIDS datasets and generates standardized outputs."
        )
    
    def get_args_schema(self):
        return FMRIPrepArgs
    
    def _find_freesurfer_license(self) -> Optional[str]:
        """Try to locate FreeSurfer license file."""
        possible_locations = [
            os.path.expanduser("~/.freesurfer/license.txt"),
            os.path.expanduser("~/.freesurfer_license.txt"),
            "/opt/freesurfer/license.txt",
            os.path.join(os.environ.get("FREESURFER_HOME", ""), "license.txt"),
            "/usr/local/freesurfer/license.txt",
        ]
        
        for location in possible_locations:
            if location and os.path.exists(location):
                logger.info(f"Found FreeSurfer license at: {location}")
                return location
        
        logger.warning("No FreeSurfer license found in common locations")
        return None
    
    def _find_container_image(self, container_type: str) -> Optional[str]:
        """Find available fMRIPrep container image."""
        if container_type == "singularity":
            # Check Neurodesk/CVMFS
            if os.path.exists(self.neurodesk_path):
                # Look for fMRIPrep containers
                fmriprep_pattern = os.path.join(self.neurodesk_path, "fmriprep_*")
                import glob
                containers = glob.glob(fmriprep_pattern)
                if containers:
                    # Use the latest version
                    latest = sorted(containers)[-1]
                    sif_file = os.path.join(latest, "fmriprep.sif")
                    if os.path.exists(sif_file):
                        logger.info(f"Found fMRIPrep container: {sif_file}")
                        return sif_file
        
        # Default to Docker Hub image
        return self.default_image
    
    def _validate_bids_dataset(self, bids_dir: str) -> Dict[str, Any]:
        """Basic BIDS dataset validation."""
        validation = {
            "is_valid": False,
            "has_participants": False,
            "has_dataset_description": False,
            "participants": [],
            "issues": []
        }
        
        # Check for required BIDS files
        participants_file = os.path.join(bids_dir, "participants.tsv")
        description_file = os.path.join(bids_dir, "dataset_description.json")
        
        if not os.path.exists(bids_dir):
            validation["issues"].append(f"BIDS directory not found: {bids_dir}")
            return validation
        
        if os.path.exists(participants_file):
            validation["has_participants"] = True
        else:
            validation["issues"].append("Missing participants.tsv")
        
        if os.path.exists(description_file):
            validation["has_dataset_description"] = True
        else:
            validation["issues"].append("Missing dataset_description.json")
        
        # Find participant directories
        for item in os.listdir(bids_dir):
            if item.startswith("sub-"):
                validation["participants"].append(item.replace("sub-", ""))
        
        if not validation["participants"]:
            validation["issues"].append("No participant directories found")
        
        validation["is_valid"] = (
            validation["has_dataset_description"] and 
            len(validation["participants"]) > 0
        )
        
        return validation
    
    def _extract_outputs(self, output_dir: str) -> Dict[str, Any]:
        """Extract key outputs from fMRIPrep results."""
        outputs = {
            "output_dir": output_dir,
            "html_reports": [],
            "derivatives": {},
            "confounds": [],
            "surfaces": [],
            "quality_metrics": {}
        }
        
        if not os.path.exists(output_dir):
            return outputs
        
        # Find HTML reports
        for root, dirs, files in os.walk(output_dir):
            for file in files:
                if file.endswith(".html"):
                    outputs["html_reports"].append(os.path.join(root, file))
        
        # Find derivatives by participant
        fmriprep_dir = os.path.join(output_dir, "fmriprep")
        if os.path.exists(fmriprep_dir):
            for participant in os.listdir(fmriprep_dir):
                if participant.startswith("sub-"):
                    part_dir = os.path.join(fmriprep_dir, participant)
                    outputs["derivatives"][participant] = {
                        "anat": [],
                        "func": [],
                        "figures": []
                    }
                    
                    # Anatomical outputs
                    anat_dir = os.path.join(part_dir, "anat")
                    if os.path.exists(anat_dir):
                        for file in os.listdir(anat_dir):
                            if file.endswith(".nii.gz"):
                                outputs["derivatives"][participant]["anat"].append(
                                    os.path.join(anat_dir, file)
                                )
                    
                    # Functional outputs
                    func_dir = os.path.join(part_dir, "func")
                    if os.path.exists(func_dir):
                        for file in os.listdir(func_dir):
                            if file.endswith(".nii.gz"):
                                outputs["derivatives"][participant]["func"].append(
                                    os.path.join(func_dir, file)
                                )
                            elif "confounds" in file and file.endswith(".tsv"):
                                outputs["confounds"].append(
                                    os.path.join(func_dir, file)
                                )
                    
                    # Figures
                    figures_dir = os.path.join(part_dir, "figures")
                    if os.path.exists(figures_dir):
                        outputs["derivatives"][participant]["figures"] = [
                            os.path.join(figures_dir, f) for f in os.listdir(figures_dir)
                        ]
        
        # Find surface outputs
        freesurfer_dir = os.path.join(output_dir, "freesurfer")
        if os.path.exists(freesurfer_dir):
            for participant in os.listdir(freesurfer_dir):
                if participant.startswith("sub-"):
                    surf_dir = os.path.join(freesurfer_dir, participant, "surf")
                    if os.path.exists(surf_dir):
                        outputs["surfaces"].extend([
                            os.path.join(surf_dir, f) for f in os.listdir(surf_dir)
                            if f.endswith((".white", ".pial", ".inflated"))
                        ])
        
        return outputs
    
    def _generate_command(
        self,
        config: FMRIPrepConfig,
        container_type: str,
        container_image: str
    ) -> str:
        """Generate fMRIPrep execution command."""
        if container_type == "singularity":
            cmd = ["singularity", "run", "--cleanenv"]

            binds: list[tuple[str, str, bool]] = [
                (config.bids_dir, config.bids_dir, True),
                (config.output_dir, config.output_dir, False),
            ]
            if config.work_dir:
                binds.append((config.work_dir, config.work_dir, False))
            if config.fs_license_file:
                binds.append(
                    (config.fs_license_file, "/opt/freesurfer/license.txt", True)
                )

            for src, dest, readonly in binds:
                if not src:
                    continue
                mount = f"{src}:{dest}"
                if readonly:
                    mount += ":ro"
                cmd.extend(["-B", mount])

            cmd.append(container_image)

            command_config = config
            if config.fs_license_file:
                command_config = replace(
                    config,
                    fs_license_file="/opt/freesurfer/license.txt",
                )
            cmd.extend(
                build_fmriprep_command(command_config, include_executable=False)
            )

        elif container_type == "docker":
            cmd = ["docker", "run", "--rm", "-it"]

            # Volume mounts
            cmd.extend(["-v", f"{config.bids_dir}:/data:ro"])
            cmd.extend(["-v", f"{config.output_dir}:/out"])
            if config.work_dir:
                cmd.extend(["-v", f"{config.work_dir}:/work"])
            if config.fs_license_file:
                cmd.extend(
                    ["-v", f"{config.fs_license_file}:/opt/freesurfer/license.txt:ro"]
                )

            cmd.append(container_image)

            # Adjust paths for Docker
            docker_config = replace(
                config,
                bids_dir="/data",
                output_dir="/out",
                work_dir="/work" if config.work_dir else None,
                fs_license_file="/opt/freesurfer/license.txt" if config.fs_license_file else None,
            )
            cmd.extend(
                build_fmriprep_command(docker_config, include_executable=False)
            )
        else:
            # Direct execution (if fMRIPrep is installed locally)
            cmd = build_fmriprep_command(config)

        return " ".join(cmd)
    
    def _run(
        self,
        bids_dir: str,
        output_dir: str,
        participant_label: Optional[List[str]] = None,
        work_dir: Optional[str] = None,
        fs_license_file: Optional[str] = None,
        output_spaces: Optional[List[str]] = None,
        skip_bids_validation: bool = False,
        use_aroma: bool = False,
        cifti_output: Optional[str] = None,
        n_cpus: Optional[int] = None,
        mem_mb: Optional[int] = None,
        low_mem: bool = False,
        container_type: str = "singularity",
        container_image: Optional[str] = None,
        execute: bool = False,
        timeout_minutes: Optional[int] = None,
        **kwargs
    ) -> ToolResult:
        """Execute fMRIPrep preprocessing."""
        try:
            # Validate BIDS dataset
            if not skip_bids_validation:
                validation = self._validate_bids_dataset(bids_dir)
                if not validation["is_valid"]:
                    return ToolResult(
                        status="error",
                        error=f"Invalid BIDS dataset: {', '.join(validation['issues'])}",
                        data={"validation": validation}
                    )
                
                # If no participants specified, use all found
                if not participant_label and validation["participants"]:
                    logger.info(f"Processing all participants: {validation['participants']}")
                    participant_label = validation["participants"]
            
            # Find or validate FreeSurfer license
            if not fs_license_file:
                fs_license_file = self._find_freesurfer_license()
                if not fs_license_file:
                    logger.warning("No FreeSurfer license found - surface reconstruction will be skipped")
            
            # Find container image
            if not container_image:
                container_image = self._find_container_image(container_type)
                if not container_image:
                    return ToolResult(
                        status="error",
                        error="No fMRIPrep container image found",
                        data={}
                    )
            
            # Set default output spaces
            if not output_spaces:
                output_spaces = ["MNI152NLin2009cAsym", "T1w", "fsaverage"]
            
            # Create output directory
            os.makedirs(output_dir, exist_ok=True)
            
            # Create work directory if not specified
            if not work_dir:
                work_dir = os.path.join(output_dir, "work")
                os.makedirs(work_dir, exist_ok=True)
            
            # Create configuration
            payload: Dict[str, Any] = {
                "bids_dir": bids_dir,
                "output_dir": output_dir,
                "participant_label": participant_label or [],
                "work_dir": work_dir,
                "fs_license_file": fs_license_file,
                "output_spaces": output_spaces or [],
                "skip_bids_validation": skip_bids_validation,
                "use_aroma": use_aroma,
                "cifti_output": cifti_output,
                "n_cpus": n_cpus,
                "omp_nthreads": kwargs.get("omp_nthreads"),
                "mem_mb": mem_mb,
                "low_mem": low_mem,
                "stop_on_first_crash": kwargs.get("stop_on_first_crash", False),
                "notrack": kwargs.get("notrack", True),
                "longitudinal": kwargs.get("longitudinal", False),
                "bids_filter_file": kwargs.get("bids_filter_file"),
                "verbose": kwargs.get("verbose", 1),
                "skull_strip_t1w": kwargs.get("skull_strip_t1w", "auto"),
                "skull_strip_fixed_seed": kwargs.get("skull_strip_fixed_seed", False),
                "bold2t1w_init": kwargs.get("bold2t1w_init", "register"),
                "bold2t1w_dof": kwargs.get("bold2t1w_dof", 6),
                "fd_spike_threshold": kwargs.get("fd_spike_threshold", 0.5),
                "dvars_spike_threshold": kwargs.get("dvars_spike_threshold", 1.5),
                "me_output_echos": kwargs.get("me_output_echos", False),
                "medial_surface_nan": kwargs.get("medial_surface_nan", False),
                "dummy_scans": kwargs.get("dummy_scans"),
                "use_syn_sdc": kwargs.get("use_syn_sdc"),
                "force_syn": kwargs.get("force_syn", False),
                "extra_args": kwargs.get("extra_args", []),
            }
            config = fmriprep_from_payload(payload)
            
            # Generate command
            command_args = self._generate_command(config, container_type, container_image)
            if isinstance(command_args, str):
                command = command_args
                command_args_list = shlex.split(command_args)
            else:
                command_args_list = command_args
                command = " ".join(shlex.quote(part) for part in command_args_list)
            
            # Log command
            logger.info(f"Generated fMRIPrep command: {command}")
            
            # Extract any existing outputs
            outputs = self._extract_outputs(output_dir)
            
            # Prepare result
            result_data = {
                "command": command,
                "command_args": command_args_list,
                "config": {
                    "bids_dir": bids_dir,
                    "output_dir": output_dir,
                    "work_dir": work_dir,
                    "participant_label": participant_label,
                    "output_spaces": output_spaces,
                    "container_type": container_type,
                    "container_image": container_image
                },
                "outputs": outputs,
                "message": (
                    "fMRIPrep command generated successfully."
                    if not execute
                    else "fMRIPrep execution completed."
                )
            }
            
            # Add execution notes
            notes = []
            if not fs_license_file:
                notes.append("No FreeSurfer license - surface reconstruction will be skipped")
            if use_aroma:
                notes.append("ICA-AROMA denoising will be performed")
            if cifti_output:
                notes.append(f"CIFTI outputs will be generated at {cifti_output} resolution")
            if low_mem:
                notes.append("Low memory mode enabled - processing may be slower")
            
            if notes:
                result_data["notes"] = notes
            
            if not execute:
                return ToolResult(status="success", data=result_data)

            logs_dir = os.path.join(output_dir, "logs", "fmriprep")
            os.makedirs(logs_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            stdout_path = os.path.join(logs_dir, f"fmriprep_{timestamp}_stdout.log")
            stderr_path = os.path.join(logs_dir, f"fmriprep_{timestamp}_stderr.log")

            env: Dict[str, str] = {}
            if container_type == "singularity" and config.fs_license_file:
                env["SINGULARITYENV_FS_LICENSE"] = "/opt/freesurfer/license.txt"

            timeout_seconds = None
            if timeout_minutes:
                timeout_seconds = max(timeout_minutes, 1) * 60

            spec = CommandSpec(
                cmd=command_args,
                env=env,
                cwd=None,
                timeout=timeout_seconds,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                name="fmriprep",
            )

            log_emitter = JobLogEmitter.from_env(
                kwargs.get("job_id"), step_id=kwargs.get("job_step_id")
            )
            context_manager = log_emitter if log_emitter.enabled else nullcontext()
            if log_emitter.enabled:
                log_emitter.emit("Launching fMRIPrep command...", stream="info")

            def _progress(event: Dict[str, str]) -> None:
                line = event.get("line", "").rstrip()
                if not line:
                    return
                stream = event.get("stream", "stdout")
                logger.debug("[fmriprep][%s] %s", stream, line)
                if log_emitter.enabled:
                    log_emitter.emit(line, stream=stream)

            with context_manager:
                try:
                    run_result = run_command(spec, progress_callback=_progress)
                except CommandExecutionError as exc:
                    logger.error("fMRIPrep execution failed: %s", exc)
                    if log_emitter.enabled:
                        log_emitter.emit(f"fMRIPrep failed: {exc}", stream="error")
                    failure_data = dict(result_data)
                    failure_data["execution"] = {
                        "status": "failed",
                        "stdout_path": stdout_path,
                        "stderr_path": stderr_path,
                        "timeout_minutes": timeout_minutes,
                    }
                    if exc.result:
                        failure_data["execution"].update(
                            {
                                "exit_code": exc.result.exit_code,
                                "duration_s": exc.result.duration_s,
                                "was_timeout": exc.result.was_timeout,
                            }
                        )
                    return ToolResult(status="error", error=str(exc), data=failure_data)
                else:
                    if log_emitter.enabled:
                        log_emitter.emit(
                            "fMRIPrep execution completed successfully.",
                            stream="info",
                        )

            result_data["execution"] = {
                "status": "completed",
                "exit_code": run_result.exit_code,
                "duration_s": run_result.duration_s,
                "stdout_path": run_result.stdout_path,
                "stderr_path": run_result.stderr_path,
                "timeout_minutes": timeout_minutes,
            }
            return ToolResult(status="success", data=result_data)

        except Exception as e:
            logger.error(f"fMRIPrep setup failed: {str(e)}")
            return ToolResult(
                status="error",
                error=str(e),
                data={}
            )


class FMRIPrepQCArgs(BaseModel):
    """Arguments for fMRIPrep quality control."""
    
    fmriprep_dir: str = Field(
        description="Path to fMRIPrep output directory"
    )
    output_file: Optional[str] = Field(
        default=None,
        description="Path to save QC report"
    )


class FMRIPrepQCTool(NeuroToolWrapper):
    """fMRIPrep quality control tool."""
    
    def get_tool_name(self) -> str:
        return "fmriprep_qc"
    
    def get_tool_description(self) -> str:
        return (
            "Extract and analyze quality control metrics from fMRIPrep outputs including "
            "motion parameters, registration quality, and preprocessing summaries."
        )
    
    def get_args_schema(self):
        return FMRIPrepQCArgs
    
    def _parse_confounds(self, confounds_file: str) -> Dict[str, Any]:
        """Parse confounds TSV file."""
        metrics = {}
        
        try:
            import pandas as pd
            df = pd.read_csv(confounds_file, sep='\t')
            
            # Motion parameters
            if 'framewise_displacement' in df.columns:
                fd = df['framewise_displacement'].dropna()
                metrics['mean_fd'] = float(fd.mean())
                metrics['max_fd'] = float(fd.max())
                metrics['percent_fd_above_0.5'] = float((fd > 0.5).mean() * 100)
            
            # DVARS
            if 'std_dvars' in df.columns:
                dvars = df['std_dvars'].dropna()
                metrics['mean_dvars'] = float(dvars.mean())
                metrics['max_dvars'] = float(dvars.max())
            
            # Global signals
            for signal in ['global_signal', 'csf', 'white_matter']:
                if signal in df.columns:
                    metrics[f'mean_{signal}'] = float(df[signal].mean())
                    metrics[f'std_{signal}'] = float(df[signal].std())
            
            # Count motion outliers
            motion_cols = [c for c in df.columns if 'motion_outlier' in c]
            if motion_cols:
                metrics['n_motion_outliers'] = int(df[motion_cols].sum().sum())
                metrics['percent_motion_outliers'] = float(df[motion_cols].mean().mean() * 100)
            
        except Exception as e:
            logger.warning(f"Failed to parse confounds: {e}")
        
        return metrics
    
    def _run(
        self,
        fmriprep_dir: str,
        output_file: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Extract QC metrics from fMRIPrep outputs."""
        try:
            if not os.path.exists(fmriprep_dir):
                return ToolResult(
                    status="error",
                    error=f"fMRIPrep directory not found: {fmriprep_dir}",
                    data={}
                )
            
            qc_report = {
                "fmriprep_dir": fmriprep_dir,
                "participants": {},
                "summary": {
                    "n_participants": 0,
                    "mean_fd_across_participants": [],
                    "high_motion_runs": [],
                    "failed_runs": []
                }
            }
            
            # Process each participant
            fmriprep_output = os.path.join(fmriprep_dir, "fmriprep")
            if os.path.exists(fmriprep_output):
                for participant in os.listdir(fmriprep_output):
                    if not participant.startswith("sub-"):
                        continue
                    
                    part_data = {
                        "confounds": {},
                        "reports": [],
                        "outputs": {
                            "anat": [],
                            "func": []
                        }
                    }
                    
                    part_dir = os.path.join(fmriprep_output, participant)
                    
                    # Find confounds files
                    func_dir = os.path.join(part_dir, "func")
                    if os.path.exists(func_dir):
                        for file in os.listdir(func_dir):
                            if "confounds" in file and file.endswith(".tsv"):
                                confounds_path = os.path.join(func_dir, file)
                                run_name = file.replace("_desc-confounds_timeseries.tsv", "")
                                metrics = self._parse_confounds(confounds_path)
                                part_data["confounds"][run_name] = metrics
                                
                                # Track high motion runs
                                if metrics.get("mean_fd", 0) > 0.5:
                                    qc_report["summary"]["high_motion_runs"].append(
                                        f"{participant}/{run_name}"
                                    )
                            
                            # Track outputs
                            if file.endswith(".nii.gz"):
                                part_data["outputs"]["func"].append(file)
                    
                    # Track anatomical outputs
                    anat_dir = os.path.join(part_dir, "anat")
                    if os.path.exists(anat_dir):
                        part_data["outputs"]["anat"] = [
                            f for f in os.listdir(anat_dir) if f.endswith(".nii.gz")
                        ]
                    
                    # Find HTML reports
                    html_report = os.path.join(
                        fmriprep_dir, f"{participant}.html"
                    )
                    if os.path.exists(html_report):
                        part_data["reports"].append(html_report)
                    
                    qc_report["participants"][participant] = part_data
                    qc_report["summary"]["n_participants"] += 1
                    
                    # Aggregate motion metrics
                    for run_metrics in part_data["confounds"].values():
                        if "mean_fd" in run_metrics:
                            qc_report["summary"]["mean_fd_across_participants"].append(
                                run_metrics["mean_fd"]
                            )
            
            # Calculate summary statistics
            if qc_report["summary"]["mean_fd_across_participants"]:
                import statistics
                qc_report["summary"]["overall_mean_fd"] = statistics.mean(
                    qc_report["summary"]["mean_fd_across_participants"]
                )
                qc_report["summary"]["overall_median_fd"] = statistics.median(
                    qc_report["summary"]["mean_fd_across_participants"]
                )
            
            # Save report if requested
            if output_file:
                with open(output_file, 'w') as f:
                    json.dump(qc_report, f, indent=2)
                logger.info(f"QC report saved to: {output_file}")
            
            return ToolResult(
                status="success",
                data={
                    "qc_report": qc_report,
                    "message": f"QC analysis completed for {qc_report['summary']['n_participants']} participants"
                }
            )
            
        except Exception as e:
            logger.error(f"QC analysis failed: {str(e)}")
            return ToolResult(
                status="error",
                error=str(e),
                data={}
            )


# Tool collection for registration
class FMRIPrepTools:
    """Collection of fMRIPrep tools."""
    
    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all fMRIPrep tools."""
        return [
            FMRIPrepTool(),
            FMRIPrepQCTool()
        ]
