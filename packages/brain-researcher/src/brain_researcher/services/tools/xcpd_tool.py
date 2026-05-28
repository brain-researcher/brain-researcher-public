"""
XCP-D Post-Processing implementation for the BR-KG LangGraph system.

Implements XCP-D for post-processing fMRIPrep outputs with advanced
denoising strategies and functional connectivity analysis.
"""

import json
import logging
import os
import shlex
import shutil
import subprocess
from dataclasses import replace
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.core.analysis.connectivity_contracts import (
    FeatureContract,
    write_feature_contract,
)
from brain_researcher.services.tools.params import (
    XCPDParameters,
    build_xcpd_command,
    xcpd_from_payload,
)
from brain_researcher.services.tools.spec import ToolSpec
from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


class DenoisingStrategy(str, Enum):
    """Denoising strategies available in XCP-D."""

    MINIMAL = "24P"  # 24 parameter model
    MODERATE = "36P"  # 36 parameter model (recommended)
    AGGRESSIVE = "acompcor"  # Anatomical CompCor
    AROMA = "aroma"  # ICA-AROMA (if available in fMRIPrep)
    CUSTOM = "custom"  # Custom strategy


class Parcellation(str, Enum):
    """Brain parcellation atlases."""

    SCHAEFER_100 = "Schaefer2018_100Parcels_7Networks"
    SCHAEFER_200 = "Schaefer2018_200Parcels_7Networks"
    SCHAEFER_400 = "Schaefer2018_400Parcels_7Networks"
    GLASSER = "Glasser360"
    GORDON = "Gordon333"
    POWER = "Power264"
    AAL = "AAL"
    HARVARD_OXFORD = "HarvardOxford"


class OutputType(str, Enum):
    """Output types for XCP-D."""

    MINIMAL = "minimal"  # Only essential outputs
    FULL = "full"  # All outputs including intermediates
    DEBUG = "debug"  # Debug outputs


class SmoothingKernel(str, Enum):
    """Smoothing kernel sizes."""

    NONE = "0"
    SMALL = "4"
    MEDIUM = "6"
    LARGE = "8"


class XCPDConfig(XCPDParameters):
    """Backwards-compatible configuration wrapper using shared XCP-D parameters."""

    def __getattribute__(self, name: str):  # type: ignore[override]
        if name == "participant_label":
            value = super().__getattribute__(name)
            return list(value) if value else []
        return super().__getattribute__(name)

    def to_command_args(self) -> list[str]:
        return build_xcpd_command(self, include_executable=False)


class XCPDArgs(BaseModel):
    """Arguments for XCP-D post-processing."""

    fmriprep_dir: str = Field(description="Path to fMRIPrep output directory")
    output_dir: str = Field(description="Output directory for XCP-D results")
    participant_label: list[str] | None = Field(
        default=None,
        description="Participant labels to process (without 'sub-' prefix)",
    )
    work_dir: str | None = Field(
        default=None, description="Working directory for intermediate files"
    )
    denoising_strategy: DenoisingStrategy = Field(
        default=DenoisingStrategy.MODERATE,
        description="Denoising strategy (24P, 36P, acompcor, aroma)",
    )
    parcellation: Parcellation | None = Field(
        default=None, description="Brain parcellation for connectivity analysis"
    )
    smoothing: SmoothingKernel = Field(
        default=SmoothingKernel.MEDIUM,
        description="Smoothing kernel size in mm (0, 4, 6, or 8)",
    )
    fd_threshold: float = Field(
        default=0.5, description="Framewise displacement threshold for censoring"
    )
    despike: bool = Field(
        default=True, description="Apply despiking to remove outliers"
    )
    bandpass_filter: tuple[float, float] | None = Field(
        default=(0.01, 0.1),
        description="Bandpass filter range in Hz (set None to disable)",
    )
    cifti: bool = Field(default=False, description="Process CIFTI files if available")
    n_cpus: int | None = Field(default=None, description="Number of CPUs to use")
    mem_gb: int | None = Field(default=None, description="Memory limit in GB")
    container_type: str = Field(
        default="singularity",
        description="Container type to use (singularity or docker)",
    )
    container_image: str | None = Field(
        default=None, description="Path to container image or docker tag"
    )


def _model_required(model_cls) -> list[str]:
    try:
        schema = model_cls.model_json_schema()
    except AttributeError:  # pragma: no cover
        schema = model_cls.schema()
    return schema.get("required", [])


def _model_defaults(model_cls) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    if hasattr(model_cls, "model_fields"):
        for name, field in model_cls.model_fields.items():
            if field.default is not None:
                defaults[name] = field.default
    elif hasattr(model_cls, "__fields__"):
        for name, field in model_cls.__fields__.items():
            if field.default is not None:
                defaults[name] = field.default
    return defaults


try:
    _XCPD_SCHEMA = XCPDArgs.model_json_schema()
except AttributeError:  # pragma: no cover
    _XCPD_SCHEMA = XCPDArgs.schema()


TOOL_SPEC = ToolSpec(
    name="xcpd_postprocessing",
    description="Run XCP-D post-processing on fMRIPrep derivatives via shared neurocore builder.",
    json_schema=_XCPD_SCHEMA,
    required=_model_required(XCPDArgs),
    defaults=_model_defaults(XCPDArgs),
    category="xcpd",
)


class XCPDTool(NeuroToolWrapper):
    """XCP-D post-processing tool."""

    def __init__(self):
        """Initialize XCP-D tool."""
        super().__init__()
        self.neurodesk_path = "/cvmfs/neurodesk.ardc.edu.au/containers"
        self.default_image = "pennlinc/xcp_d:latest"
        # Prefer unstable tag to avoid known 0.14.0 metadata serialization bug
        self.preferred_images = [
            "pennlinc/xcp_d:unstable",
            "pennlinc/xcp_d:latest",
        ]

    def get_tool_name(self) -> str:
        return "xcpd_postprocessing"

    def get_tool_description(self) -> str:
        return (
            "Post-process fMRIPrep outputs using XCP-D for functional connectivity analysis. "
            "Applies advanced denoising strategies, motion censoring, and generates "
            "connectivity matrices with various parcellation schemes."
        )

    def get_args_schema(self):
        return XCPDArgs

    def _find_container_image(self, container_type: str) -> str | None:
        """Find available XCP-D container image."""
        if container_type == "singularity":
            # Check Neurodesk/CVMFS
            if os.path.exists(self.neurodesk_path):
                # Look for XCP-D containers
                xcp_pattern = os.path.join(self.neurodesk_path, "xcp*")
                import glob

                containers = glob.glob(xcp_pattern)
                if containers:
                    # Use the latest version
                    latest = sorted(containers)[-1]
                    sif_file = os.path.join(latest, "xcp_d.sif")
                    if os.path.exists(sif_file):
                        logger.info(f"Found XCP-D container: {sif_file}")
                        return sif_file

        # Default to Docker Hub image (prefer unstable to dodge known 0.14.0 JSON bug)
        for image in getattr(self, "preferred_images", [self.default_image]):
            if image:
                return image
        return self.default_image

    def _validate_fmriprep_outputs(self, fmriprep_dir: str) -> dict[str, Any]:
        """Validate fMRIPrep outputs for XCP-D processing."""
        validation = {
            "is_valid": False,
            "has_func": False,
            "has_anat": False,
            "participants": [],
            "func_files": [],
            "issues": [],
        }

        if not os.path.exists(fmriprep_dir):
            validation["issues"].append(f"fMRIPrep directory not found: {fmriprep_dir}")
            return validation

        # Check for dataset description
        description_file = os.path.join(fmriprep_dir, "dataset_description.json")
        if not os.path.exists(description_file):
            validation["issues"].append(
                "Missing dataset_description.json - may not be fMRIPrep output"
            )

        # Find participant directories and functional files
        for item in os.listdir(fmriprep_dir):
            if item.startswith("sub-"):
                validation["participants"].append(item.replace("sub-", ""))

                # Check for functional data
                func_dir = os.path.join(fmriprep_dir, item, "func")
                if os.path.exists(func_dir):
                    for file in os.listdir(func_dir):
                        if file.endswith("_desc-preproc_bold.nii.gz"):
                            validation["func_files"].append(
                                os.path.join(func_dir, file)
                            )
                            validation["has_func"] = True

                # Check for anatomical data
                anat_dir = os.path.join(fmriprep_dir, item, "anat")
                if os.path.exists(anat_dir):
                    validation["has_anat"] = True

        if not validation["participants"]:
            validation["issues"].append("No participant directories found")

        if not validation["has_func"]:
            validation["issues"].append("No preprocessed functional files found")

        validation["is_valid"] = (
            validation["has_func"] and len(validation["participants"]) > 0
        )

        return validation

    def _extract_outputs(self, output_dir: str) -> dict[str, Any]:
        """Extract key outputs from XCP-D results."""
        outputs = {
            "output_dir": output_dir,
            "connectivity": {},
            "denoised": {},
            "qc_files": [],
            "reports": [],
        }

        if not os.path.exists(output_dir):
            return outputs

        # Find XCP-D outputs by participant
        xcp_dir = os.path.join(output_dir, "xcp_d")
        if os.path.exists(xcp_dir):
            for participant in os.listdir(xcp_dir):
                if not participant.startswith("sub-"):
                    continue

                part_dir = os.path.join(xcp_dir, participant)
                outputs["connectivity"][participant] = {
                    "matrices": [],
                    "timeseries": [],
                    "networks": [],
                }
                outputs["denoised"][participant] = []

                # Functional outputs
                func_dir = os.path.join(part_dir, "func")
                if os.path.exists(func_dir):
                    for file in os.listdir(func_dir):
                        if "_connectivity.tsv" in file:
                            outputs["connectivity"][participant]["matrices"].append(
                                os.path.join(func_dir, file)
                            )
                        elif "_timeseries.tsv" in file:
                            outputs["connectivity"][participant]["timeseries"].append(
                                os.path.join(func_dir, file)
                            )
                        elif "_desc-denoised_bold.nii.gz" in file:
                            outputs["denoised"][participant].append(
                                os.path.join(func_dir, file)
                            )

        # Find QC files
        for root, _dirs, files in os.walk(output_dir):
            for file in files:
                if file.endswith("_qc.json") or file.endswith("_qc.tsv"):
                    outputs["qc_files"].append(os.path.join(root, file))
                elif file.endswith(".html"):
                    outputs["reports"].append(os.path.join(root, file))

        return outputs

    def _generate_command(
        self, config: XCPDConfig, container_type: str, container_image: str
    ) -> str:
        """Generate XCP-D execution command."""
        if container_type == "singularity":
            cmd: list[str] = ["singularity", "run", "--cleanenv"]

            binds: list[tuple[str, str, bool]] = [
                (config.fmriprep_dir, config.fmriprep_dir, True),
                (config.output_dir, config.output_dir, False),
            ]
            if config.work_dir:
                binds.append((config.work_dir, config.work_dir, False))

            fs_license = os.path.expanduser("~/.freesurfer/license.txt")
            if os.path.exists(fs_license):
                binds.append((fs_license, "/opt/freesurfer/license.txt", True))

            for src, dest, readonly in binds:
                if not src:
                    continue
                mount = f"{src}:{dest}"
                if readonly:
                    mount += ":ro"
                cmd.extend(["-B", mount])

            cmd.append(container_image)
            command_params = config
            command_list = build_xcpd_command(command_params, include_executable=False)
            cmd.extend(command_list)

        elif container_type == "docker":
            cmd = ["docker", "run", "--rm", "-it"]
            cmd.extend(["-v", f"{config.fmriprep_dir}:/data:ro"])
            cmd.extend(["-v", f"{config.output_dir}:/out"])
            if config.work_dir:
                cmd.extend(["-v", f"{config.work_dir}:/work"])

            fs_license = os.path.expanduser("~/.freesurfer/license.txt")
            if os.path.exists(fs_license):
                cmd.extend(["-v", f"{fs_license}:/opt/freesurfer/license.txt:ro"])

            cmd.append(container_image)

            docker_config = replace(
                config,
                fmriprep_dir="/data",
                output_dir="/out",
                work_dir="/work" if config.work_dir else None,
            )
            cmd.extend(build_xcpd_command(docker_config, include_executable=False))

        else:
            cmd_list = build_xcpd_command(config)
            return " ".join(cmd_list)

        return " ".join(cmd)

    def _run(
        self,
        fmriprep_dir: str,
        output_dir: str,
        participant_label: list[str] | None = None,
        work_dir: str | None = None,
        denoising_strategy: DenoisingStrategy = DenoisingStrategy.MODERATE,
        parcellation: Parcellation | None = None,
        smoothing: SmoothingKernel = SmoothingKernel.MEDIUM,
        fd_threshold: float = 0.5,
        despike: bool = True,
        bandpass_filter: tuple[float, float] | None = (0.01, 0.1),
        cifti: bool = False,
        n_cpus: int | None = None,
        mem_gb: int | None = None,
        container_type: str = "singularity",
        container_image: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Execute XCP-D post-processing."""
        try:
            # Coerce string inputs into Enum instances for safer .value access downstream
            if isinstance(denoising_strategy, str):
                try:
                    denoising_strategy = DenoisingStrategy(denoising_strategy)
                except Exception:
                    pass
            if isinstance(parcellation, str):
                try:
                    parcellation = Parcellation(parcellation)
                except Exception:
                    pass
            if isinstance(smoothing, str):
                try:
                    smoothing = SmoothingKernel(smoothing)
                except Exception:
                    pass

            # XCP-D requires a mode and several flags; provide robust defaults for fMRIPrep NIfTI
            mode = kwargs.get("mode", "abcd")
            input_type = kwargs.get("input_type", "fmriprep")
            file_format = kwargs.get("file_format", "nifti")
            output_type = kwargs.get("output_type", "auto")
            motion_filter_type = kwargs.get("motion_filter_type", "none")
            min_coverage = kwargs.get("min_coverage", "auto")
            output_run_wise_corr = kwargs.get("output_run_wise_correlations", "n")
            warp_surfaces_native2std = kwargs.get("warp_surfaces_native2std", "n")
            linc_qc = kwargs.get("linc_qc", "n")
            abcc_qc = kwargs.get("abcc_qc", "n")
            combine_runs = kwargs.get("combine_runs", "n")
            # Validate fMRIPrep outputs
            validation = self._validate_fmriprep_outputs(fmriprep_dir)
            if not validation["is_valid"]:
                return ToolResult(
                    status="error",
                    error=f"Invalid fMRIPrep directory: {', '.join(validation['issues'])}",
                    data={"validation": validation},
                )

            # If no participants specified, use all found
            if not participant_label and validation["participants"]:
                logger.info(
                    f"Processing all participants: {validation['participants']}"
                )
                participant_label = validation["participants"]

            # Find container image
            if not container_image:
                container_image = self._find_container_image(container_type)
                if not container_image:
                    return ToolResult(
                        status="error", error="No XCP-D container image found", data={}
                    )

            # Create output directory
            os.makedirs(output_dir, exist_ok=True)

            # Create work directory if not specified
            if not work_dir:
                work_dir = os.path.join(output_dir, "work")
                os.makedirs(work_dir, exist_ok=True)

            payload: dict[str, Any] = {
                "fmriprep_dir": fmriprep_dir,
                "output_dir": output_dir,
                "analysis_level": kwargs.get("analysis_level", "participant"),
                "participant_label": participant_label or [],
                "work_dir": work_dir,
                "denoising_strategy": (
                    denoising_strategy.value
                    if isinstance(denoising_strategy, DenoisingStrategy)
                    else str(denoising_strategy)
                ),
                "parcellation": (
                    parcellation.value
                    if isinstance(parcellation, Parcellation)
                    else (parcellation if parcellation else None)
                ),
                "smoothing": (
                    smoothing.value
                    if isinstance(smoothing, SmoothingKernel)
                    else str(smoothing)
                ),
                "fd_threshold": fd_threshold,
                "despike": despike,
                "bandpass_filter": bandpass_filter,
                "cifti": cifti,
                "n_cpus": n_cpus,
                "mem_gb": mem_gb,
                "extra_args": kwargs.get("extra_args", []),
                "mode": mode,
                "input_type": input_type,
                "file_format": file_format,
                "output_type": output_type,
                "motion_filter_type": motion_filter_type,
                "min_coverage": min_coverage,
                "output_run_wise_correlations": output_run_wise_corr,
                "warp_surfaces_native2std": warp_surfaces_native2std,
                "linc_qc": linc_qc,
                "abcc_qc": abcc_qc,
                "combine_runs": combine_runs,
            }

            params = xcpd_from_payload(payload)
            config = XCPDConfig(**params.__dict__)
            command_tokens = build_xcpd_command(config, include_executable=True)

            # Generate command
            command = self._generate_command(config, container_type, container_image)

            logger.info(f"Generated XCP-D command: {command}")

            run_stdout = ""
            run_stderr = ""
            returncode: int | None = None
            log_file: str | None = None

            # Execute only when explicitly allowed AND the container runtime exists.
            # Default to dry-run in hermetic/unit-test contexts; callers can opt in with execute=True.
            execute_requested: bool = bool(kwargs.get("execute", False))
            runtime = (
                "singularity"
                if container_type == "singularity"
                else "docker" if container_type == "docker" else None
            )
            runtime_available = shutil.which(runtime) is not None if runtime else True

            if execute_requested and not runtime_available:
                # Gracefully degrade to dry-run when runtime is absent (keeps unit tests hermetic).
                logger.warning(
                    "Container runtime '%s' not found; running XCP-D as dry-run",
                    runtime,
                )
                execute_requested = False

            if execute_requested:
                log_file = os.path.join(output_dir, "xcpd_command.log")
                try:
                    completed = subprocess.run(
                        shlex.split(command),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    returncode = completed.returncode
                    run_stdout = completed.stdout
                    run_stderr = completed.stderr
                    with open(log_file, "w") as lf:
                        lf.write("# Command\n")
                        lf.write(command + "\n\n# STDOUT\n")
                        lf.write(run_stdout or "")
                        lf.write("\n# STDERR\n")
                        lf.write(run_stderr or "")
                except FileNotFoundError as e:
                    return ToolResult(
                        status="error",
                        error=f"Failed to execute XCP-D command: {e}",
                        data={"command": command},
                    )

            # Extract outputs (post-run if executed)
            outputs = self._extract_outputs(output_dir)

            result_data = {
                "command": command,
                "command_tokens": command_tokens,
                "config": {
                    "fmriprep_dir": fmriprep_dir,
                    "output_dir": output_dir,
                    "work_dir": work_dir,
                    "participant_label": list(config.participant_label),
                    "denoising_strategy": denoising_strategy.value,
                    "parcellation": parcellation.value if parcellation else None,
                    "smoothing": f"{smoothing.value}mm",
                    "fd_threshold": fd_threshold,
                    "despike": despike,
                    "bandpass_filter": bandpass_filter,
                    "container_type": container_type,
                    "container_image": container_image,
                },
                "execution": {
                    "executed": execute_requested,
                    "returncode": returncode,
                    "stdout": run_stdout,
                    "stderr": run_stderr,
                    "log_file": log_file,
                },
                "outputs": outputs,
                "message": (
                    "XCP-D command executed successfully."
                    if execute_requested and returncode == 0
                    else (
                        "XCP-D command prepared (dry run)."
                        if not execute_requested
                        else "XCP-D command finished with errors."
                    )
                ),
            }

            # Add execution notes
            notes = []
            if denoising_strategy == DenoisingStrategy.MODERATE:
                notes.append("Using 36P denoising (recommended for most studies)")
            if parcellation:
                notes.append(
                    f"Will generate connectivity matrices using {parcellation.value}"
                )
            if fd_threshold < 0.5:
                notes.append(
                    f"Strict motion threshold ({fd_threshold}mm) - more data may be censored"
                )
            if not bandpass_filter:
                notes.append("Bandpass filtering disabled")

            if notes:
                result_data["notes"] = notes

            if execute_requested and returncode not in (0, None):
                return ToolResult(
                    status="error",
                    error=f"XCP-D exited with code {returncode}",
                    data=result_data,
                )

            return ToolResult(status="success", data=result_data)

        except Exception as e:
            logger.error(f"XCP-D setup failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


class XCPDConnectivityArgs(BaseModel):
    """Arguments for connectivity analysis."""

    xcpd_dir: str = Field(description="Path to XCP-D output directory")
    parcellation: Parcellation = Field(
        description="Parcellation scheme for connectivity"
    )
    metric: str = Field(
        default="correlation",
        description="Connectivity metric (correlation, partial_correlation, covariance)",
    )
    output_file: str | None = Field(
        default=None, description="Path to save connectivity report"
    )


class XCPDConnectivityTool(NeuroToolWrapper):
    """Tool for analyzing XCP-D connectivity outputs."""

    def get_tool_name(self) -> str:
        return "xcpd_connectivity_analysis"

    def get_tool_description(self) -> str:
        return (
            "Analyze functional connectivity matrices generated by XCP-D. "
            "Extract network metrics, identify hubs, and generate connectivity reports."
        )

    def get_args_schema(self):
        return XCPDConnectivityArgs

    def _load_connectivity_matrix(self, matrix_file: str) -> dict[str, Any]:
        """Load and analyze connectivity matrix."""
        import numpy as np
        import pandas as pd

        try:
            # Load matrix (assuming TSV format)
            matrix = pd.read_csv(matrix_file, sep="\t", index_col=0)

            # Calculate network metrics
            metrics = {
                "n_nodes": matrix.shape[0],
                "mean_connectivity": np.mean(
                    matrix.values[np.triu_indices_from(matrix.values, k=1)]
                ),
                "std_connectivity": np.std(
                    matrix.values[np.triu_indices_from(matrix.values, k=1)]
                ),
                "sparsity": np.sum(np.abs(matrix.values) > 0.2)
                / (matrix.shape[0] * (matrix.shape[0] - 1) / 2),
            }

            # Identify hubs (nodes with high mean connectivity)
            node_strength = np.mean(np.abs(matrix.values), axis=1)
            hub_threshold = np.percentile(node_strength, 90)
            hubs = matrix.index[node_strength > hub_threshold].tolist()
            metrics["hubs"] = hubs
            metrics["n_hubs"] = len(hubs)

            return {
                "file": matrix_file,
                "matrix": matrix.values.tolist(),
                "labels": matrix.index.tolist(),
                "metrics": metrics,
            }

        except Exception as e:
            logger.error(f"Failed to load connectivity matrix: {e}")
            return {"error": str(e)}

    def _run(
        self,
        xcpd_dir: str,
        parcellation: Parcellation,
        metric: str = "correlation",
        output_file: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Analyze connectivity outputs."""
        try:
            if not os.path.exists(xcpd_dir):
                return ToolResult(
                    status="error",
                    error=f"XCP-D directory not found: {xcpd_dir}",
                    data={},
                )

            connectivity_report = {
                "xcpd_dir": xcpd_dir,
                "parcellation": parcellation.value,
                "metric": metric,
                "participants": {},
                "summary": {
                    "n_participants": 0,
                    "mean_connectivity_across_participants": [],
                    "network_metrics": {},
                },
            }
            feature_contract_root = (
                Path(output_file).expanduser().resolve().parent / "feature_contracts"
                if output_file
                else None
            )

            # Find connectivity matrices
            xcp_output = os.path.join(xcpd_dir, "xcp_d")
            if os.path.exists(xcp_output):
                for participant in os.listdir(xcp_output):
                    if not participant.startswith("sub-"):
                        continue

                    func_dir = os.path.join(xcp_output, participant, "func")
                    if not os.path.exists(func_dir):
                        continue

                    # Look for connectivity matrices
                    for file in os.listdir(func_dir):
                        if (
                            f"{parcellation.value}" in file
                            and "_connectivity.tsv" in file
                        ):
                            matrix_file = os.path.join(func_dir, file)
                            matrix_data = self._load_connectivity_matrix(matrix_file)

                            if "error" not in matrix_data:
                                if feature_contract_root is not None:
                                    try:
                                        contract = FeatureContract(
                                            matrix_kind=f"xcpd_{metric}",
                                            source_level="xcpd_connectivity_tsv",
                                            n_rois=int(
                                                matrix_data["metrics"]["n_nodes"]
                                            ),
                                            covariance_estimator="XCPD",
                                            transform_state="raw_connectivity",
                                            extras={
                                                "participant": participant,
                                                "parcellation": parcellation.value,
                                                "matrix_file": matrix_file,
                                            },
                                        )
                                        contract_path = write_feature_contract(
                                            contract,
                                            feature_contract_root
                                            / participant
                                            / Path(file).stem,
                                        )
                                        matrix_data["feature_contract"] = str(
                                            contract_path
                                        )
                                    except Exception:
                                        matrix_data["feature_contract"] = None
                                connectivity_report["participants"][
                                    participant
                                ] = matrix_data
                                connectivity_report["summary"]["n_participants"] += 1

                                if "metrics" in matrix_data:
                                    connectivity_report["summary"][
                                        "mean_connectivity_across_participants"
                                    ].append(
                                        matrix_data["metrics"]["mean_connectivity"]
                                    )

            # Calculate summary statistics
            if connectivity_report["summary"]["mean_connectivity_across_participants"]:
                import statistics

                connectivity_report["summary"]["overall_mean_connectivity"] = (
                    statistics.mean(
                        connectivity_report["summary"][
                            "mean_connectivity_across_participants"
                        ]
                    )
                )

            # Save report if requested
            if output_file:
                with open(output_file, "w") as f:
                    json.dump(connectivity_report, f, indent=2)
                logger.info(f"Connectivity report saved to: {output_file}")

            return ToolResult(
                status="success",
                data={
                    "connectivity_report": connectivity_report,
                    "message": f"Analyzed connectivity for {connectivity_report['summary']['n_participants']} participants",
                },
            )

        except Exception as e:
            logger.error(f"Connectivity analysis failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


class XCPDQCArgs(BaseModel):
    """Arguments for XCP-D quality control."""

    xcpd_dir: str = Field(description="Path to XCP-D output directory")
    output_file: str | None = Field(default=None, description="Path to save QC report")


class XCPDQCTool(NeuroToolWrapper):
    """Tool for XCP-D quality control analysis."""

    def get_tool_name(self) -> str:
        return "xcpd_qc"

    def get_tool_description(self) -> str:
        return (
            "Extract and analyze quality control metrics from XCP-D outputs including "
            "motion parameters, censoring statistics, and denoising effectiveness."
        )

    def get_args_schema(self):
        return XCPDQCArgs

    def _parse_qc_file(self, qc_file: str) -> dict[str, Any]:
        """Parse XCP-D QC file."""
        metrics = {}

        try:
            if qc_file.endswith(".json"):
                with open(qc_file) as f:
                    qc_data = json.load(f)
                    metrics.update(qc_data)
            elif qc_file.endswith(".tsv"):
                import pandas as pd

                qc_data = pd.read_csv(qc_file, sep="\t")
                metrics = qc_data.to_dict("records")[0] if len(qc_data) > 0 else {}
        except Exception as e:
            logger.warning(f"Failed to parse QC file {qc_file}: {e}")

        return metrics

    def _run(
        self, xcpd_dir: str, output_file: str | None = None, **kwargs
    ) -> ToolResult:
        """Extract QC metrics from XCP-D outputs."""
        try:
            if not os.path.exists(xcpd_dir):
                return ToolResult(
                    status="error",
                    error=f"XCP-D directory not found: {xcpd_dir}",
                    data={},
                )

            qc_report = {
                "xcpd_dir": xcpd_dir,
                "participants": {},
                "summary": {
                    "n_participants": 0,
                    "mean_fd": [],
                    "mean_censored_volumes": [],
                    "mean_dvars": [],
                },
            }

            # Process each participant
            xcp_output = os.path.join(xcpd_dir, "xcp_d")
            if os.path.exists(xcp_output):
                for participant in os.listdir(xcp_output):
                    if not participant.startswith("sub-"):
                        continue

                    part_data = {"qc_metrics": {}, "motion": {}, "censoring": {}}

                    # Look for QC files
                    part_dir = os.path.join(xcp_output, participant)
                    for root, _dirs, files in os.walk(part_dir):
                        for file in files:
                            if file.endswith("_qc.json") or file.endswith("_qc.tsv"):
                                qc_path = os.path.join(root, file)
                                metrics = self._parse_qc_file(qc_path)
                                part_data["qc_metrics"].update(metrics)

                                # Extract key metrics for summary
                                if "mean_fd" in metrics:
                                    qc_report["summary"]["mean_fd"].append(
                                        metrics["mean_fd"]
                                    )
                                if "n_censored" in metrics:
                                    qc_report["summary"][
                                        "mean_censored_volumes"
                                    ].append(metrics["n_censored"])
                                if "mean_dvars" in metrics:
                                    qc_report["summary"]["mean_dvars"].append(
                                        metrics["mean_dvars"]
                                    )

                    if part_data["qc_metrics"]:
                        qc_report["participants"][participant] = part_data
                        qc_report["summary"]["n_participants"] += 1

            # Calculate summary statistics
            if qc_report["summary"]["mean_fd"]:
                import statistics

                qc_report["summary"]["overall_mean_fd"] = statistics.mean(
                    qc_report["summary"]["mean_fd"]
                )
                qc_report["summary"]["overall_mean_censored"] = (
                    statistics.mean(qc_report["summary"]["mean_censored_volumes"])
                    if qc_report["summary"]["mean_censored_volumes"]
                    else 0
                )

            # Save report if requested
            if output_file:
                with open(output_file, "w") as f:
                    json.dump(qc_report, f, indent=2)
                logger.info(f"QC report saved to: {output_file}")

            return ToolResult(
                status="success",
                data={
                    "qc_report": qc_report,
                    "message": f"QC analysis completed for {qc_report['summary']['n_participants']} participants",
                },
            )

        except Exception as e:
            logger.error(f"QC analysis failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


# Tool collection for registration
class XCPDTools:
    """Collection of XCP-D tools."""

    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        """Get all XCP-D tools."""
        return [XCPDTool(), XCPDConnectivityTool(), XCPDQCTool()]
