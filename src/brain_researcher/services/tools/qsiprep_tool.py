"""
QSIPrep Diffusion Processing implementation for the BR-KG LangGraph system.

Implements QSIPrep for diffusion MRI preprocessing, reconstruction,
and quality control with support for multiple acquisition schemes.
"""

import json
import logging
import os
from dataclasses import replace
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.services.tools.pipeline_tools import (
    _build_apptainer_bind_env,
    _find_freesurfer_license,
    _resolve_bids_app_executable,
)
from brain_researcher.services.tools.pipelines import (
    QSIPrepParameters,
    build_qsiprep_command,
    qsiprep_from_payload,
)
from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)
from brain_researcher.services.tools.utils import run_subprocess

logger = logging.getLogger(__name__)


def _env_truthy(name: str) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _collect_qsirecon_outputs(output_dir: str) -> dict[str, Any]:
    root = Path(output_dir)
    outputs: dict[str, Any] = {"recon_dir": str(root)}

    dataset_description = root / "dataset_description.json"
    if dataset_description.exists():
        outputs["dataset_description"] = str(dataset_description)

    subject_reports = sorted(str(p) for p in root.glob("sub-*.html"))
    if subject_reports:
        outputs["subject_reports"] = subject_reports

    tractograms = sorted(str(p) for p in root.rglob("*.tck"))
    tractograms.extend(str(p) for p in root.rglob("*.trk"))
    if tractograms:
        outputs["tractograms"] = tractograms

    connectomes = sorted(str(p) for p in root.rglob("*connect*"))
    if connectomes:
        outputs["connectome_outputs"] = connectomes

    figures = sorted(str(p) for p in root.rglob("figures/*"))
    if figures:
        outputs["figures"] = figures

    return outputs


class DenoisingMethod(str, Enum):
    """Denoising methods for diffusion data."""

    PATCH2SELF = "patch2self"
    DWIDENOISE = "dwidenoise"
    NONE = "none"


class DistortionCorrection(str, Enum):
    """Distortion correction methods."""

    TOPUP = "topup"
    SYNBOLDZ = "syn-bold-z"
    FIELDMAP = "fieldmap"
    NONE = "none"


class ReconWorkflow(str, Enum):
    """Reconstruction workflows available in QSIPrep."""

    MRTRIX_SINGLESHELL_SS3T = "mrtrix_singleshell_ss3t_ACT-hsvs"
    MRTRIX_MULTISHELL_MSMT = "mrtrix_multishell_msmt_ACT-hsvs"
    MRTRIX_MULTISHELL_MSMT_NOACT = "mrtrix_multishell_msmt_noACT"
    DIPY_MAPMRI = "dipy_mapmri"
    DIPY_DTI = "dipy_dti"
    DSI_STUDIO_GQI = "dsi_studio_gqi"
    DSI_STUDIO_AUTOTRACK = "dsi_studio_autotrack"
    AMICO_NODDI = "amico_noddi"
    TORTOISE = "tortoise"


class HeadMotionCorrection(str, Enum):
    """Head motion correction strategies."""

    EDDY = "eddy"
    NONE = "none"


class OutputResolution(str, Enum):
    """Output resolution options."""

    ORIGINAL = "original"
    RES_1MM = "1mm"
    RES_1_25MM = "1.25mm"
    RES_1_5MM = "1.5mm"
    RES_2MM = "2mm"


class QSIPrepConfig(QSIPrepParameters):
    """Backwards-compatible configuration wrapper using shared QSIPrep parameters."""

    def __getattribute__(self, name: str):  # type: ignore[override]
        if name == "participant_label":
            value = super().__getattribute__(name)
            return list(value) if value else []
        return super().__getattribute__(name)

    def to_command_args(self) -> list[str]:
        return build_qsiprep_command(self, include_executable=False)


class QSIPrepArgs(BaseModel):
    """Arguments for QSIPrep diffusion preprocessing."""

    bids_dir: str = Field(
        description="Path to BIDS dataset directory with diffusion data"
    )
    output_dir: str = Field(description="Output directory for QSIPrep results")
    participant_label: list[str] | None = Field(
        default=None,
        description="Participant labels to process (without 'sub-' prefix)",
    )
    work_dir: str | None = Field(
        default=None, description="Working directory for intermediate files"
    )
    fs_license_file: str | None = Field(
        default=None, description="Path to FreeSurfer license file"
    )
    denoise_method: DenoisingMethod = Field(
        default=DenoisingMethod.PATCH2SELF, description="Denoising method to use"
    )
    distortion_correction: DistortionCorrection = Field(
        default=DistortionCorrection.TOPUP, description="Distortion correction method"
    )
    eddy_config: str | None = Field(
        default=None, description="Path to eddy configuration file"
    )
    b0_threshold: float = Field(
        default=100.0, description="B-value threshold for b0 volumes"
    )
    output_resolution: str = Field(
        default="1.25mm", description="Output resolution for preprocessed data"
    )
    skip_bids_validation: bool = Field(
        default=False, description="Skip BIDS dataset validation"
    )
    hmc_model: str = Field(
        default="3dSHORE", description="Head motion correction model"
    )
    impute_slice_threshold: float = Field(
        default=0.0, description="Threshold for slice imputation (0 = disabled)"
    )
    n_cpus: int | None = Field(default=None, description="Number of CPUs to use")
    mem_mb: int | None = Field(default=None, description="Memory limit in MB")
    low_mem: bool = Field(default=False, description="Use low-memory settings")
    container_type: str = Field(
        default="singularity",
        description="Container type to use (singularity or docker)",
    )
    container_image: str | None = Field(
        default=None, description="Path to container image or docker tag"
    )


class QSIPrepTool(NeuroToolWrapper):
    """QSIPrep diffusion preprocessing tool."""

    def __init__(self):
        """Initialize QSIPrep tool."""
        super().__init__()
        self.neurodesk_path = "/cvmfs/neurodesk.ardc.edu.au/containers"
        self.default_image = "pennbbl/qsiprep:latest"

    def get_tool_name(self) -> str:
        return "qsiprep_preprocessing"

    def get_tool_description(self) -> str:
        return (
            "Run QSIPrep for comprehensive diffusion MRI preprocessing including "
            "denoising, distortion correction, head motion correction, and eddy current "
            "correction. Supports single-shell and multi-shell acquisitions."
        )

    def get_args_schema(self):
        return QSIPrepArgs

    def _find_freesurfer_license(self) -> str | None:
        """Try to locate FreeSurfer license file."""
        possible_locations = [
            os.path.expanduser("~/.freesurfer/license.txt"),
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

    def _find_container_image(self, container_type: str) -> str | None:
        """Find available QSIPrep container image."""
        if container_type == "singularity":
            # Check Neurodesk/CVMFS
            if os.path.exists(self.neurodesk_path):
                # Look for QSIPrep containers
                qsiprep_pattern = os.path.join(self.neurodesk_path, "qsiprep_*")
                import glob

                containers = glob.glob(qsiprep_pattern)
                if containers:
                    # Use the latest version
                    latest = sorted(containers)[-1]
                    sif_file = os.path.join(latest, "qsiprep.sif")
                    if os.path.exists(sif_file):
                        logger.info(f"Found QSIPrep container: {sif_file}")
                        return sif_file

        # Default to Docker Hub image
        return self.default_image

    def _validate_bids_dataset(self, bids_dir: str) -> dict[str, Any]:
        """Basic BIDS dataset validation for diffusion data."""
        validation = {
            "is_valid": False,
            "has_dwi": False,
            "has_dataset_description": False,
            "participants": [],
            "dwi_files": [],
            "issues": [],
        }

        if not os.path.exists(bids_dir):
            validation["issues"].append(f"BIDS directory not found: {bids_dir}")
            return validation

        # Check for dataset description
        description_file = os.path.join(bids_dir, "dataset_description.json")
        if os.path.exists(description_file):
            validation["has_dataset_description"] = True
        else:
            validation["issues"].append("Missing dataset_description.json")

        # Find participant directories and DWI files
        for item in os.listdir(bids_dir):
            if item.startswith("sub-"):
                validation["participants"].append(item.replace("sub-", ""))

                # Check for DWI data
                dwi_dir = os.path.join(bids_dir, item, "dwi")
                if os.path.exists(dwi_dir):
                    for file in os.listdir(dwi_dir):
                        if file.endswith("_dwi.nii.gz"):
                            validation["dwi_files"].append(os.path.join(dwi_dir, file))
                            validation["has_dwi"] = True

        if not validation["participants"]:
            validation["issues"].append("No participant directories found")

        if not validation["has_dwi"]:
            validation["issues"].append("No DWI files found")

        validation["is_valid"] = (
            validation["has_dataset_description"]
            and validation["has_dwi"]
            and len(validation["participants"]) > 0
        )

        return validation

    def _extract_outputs(self, output_dir: str) -> dict[str, Any]:
        """Extract key outputs from QSIPrep results."""
        outputs = {
            "output_dir": output_dir,
            "html_reports": [],
            "derivatives": {},
            "qc_metrics": {},
            "dwi_files": [],
        }

        if not os.path.exists(output_dir):
            return outputs

        # Find HTML reports
        for root, _dirs, files in os.walk(output_dir):
            for file in files:
                if file.endswith(".html"):
                    outputs["html_reports"].append(os.path.join(root, file))

        # Find derivatives by participant
        qsiprep_dir = os.path.join(output_dir, "qsiprep")
        if os.path.exists(qsiprep_dir):
            for participant in os.listdir(qsiprep_dir):
                if participant.startswith("sub-"):
                    part_dir = os.path.join(qsiprep_dir, participant)
                    outputs["derivatives"][participant] = {
                        "anat": [],
                        "dwi": [],
                        "figures": [],
                    }

                    # Anatomical outputs
                    anat_dir = os.path.join(part_dir, "anat")
                    if os.path.exists(anat_dir):
                        for file in os.listdir(anat_dir):
                            if file.endswith(".nii.gz"):
                                outputs["derivatives"][participant]["anat"].append(
                                    os.path.join(anat_dir, file)
                                )

                    # DWI outputs
                    dwi_dir = os.path.join(part_dir, "dwi")
                    if os.path.exists(dwi_dir):
                        for file in os.listdir(dwi_dir):
                            if file.endswith(".nii.gz"):
                                outputs["derivatives"][participant]["dwi"].append(
                                    os.path.join(dwi_dir, file)
                                )
                                if "_dwi.nii.gz" in file:
                                    outputs["dwi_files"].append(
                                        os.path.join(dwi_dir, file)
                                    )

                    # Figures
                    figures_dir = os.path.join(part_dir, "figures")
                    if os.path.exists(figures_dir):
                        outputs["derivatives"][participant]["figures"] = [
                            os.path.join(figures_dir, f)
                            for f in os.listdir(figures_dir)
                        ]

        # QC metrics
        qc_file = os.path.join(output_dir, "qsiprep", "dwiqc.json")
        if os.path.exists(qc_file):
            try:
                with open(qc_file) as f:
                    outputs["qc_metrics"] = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load QC metrics: {e}")

        return outputs

    def _generate_command(
        self, params: QSIPrepParameters, container_type: str, container_image: str
    ) -> str:
        """Generate QSIPrep execution command."""
        if container_type == "singularity":
            cmd: list[str] = ["singularity", "run", "--cleanenv"]

            binds: list[tuple[str, str, bool]] = [
                (params.bids_dir, params.bids_dir, True),
                (params.output_dir, params.output_dir, False),
            ]
            if params.work_dir:
                binds.append((params.work_dir, params.work_dir, False))
            if params.fs_license_file:
                binds.append(
                    (params.fs_license_file, "/opt/freesurfer/license.txt", True)
                )

            for src, dest, readonly in binds:
                if not src:
                    continue
                mount = f"{src}:{dest}"
                if readonly:
                    mount += ":ro"
                cmd.extend(["-B", mount])

            cmd.append(container_image)
            command_params = params
            if params.fs_license_file:
                command_params = replace(
                    params, fs_license_file="/opt/freesurfer/license.txt"
                )
            cmd.extend(build_qsiprep_command(command_params, include_executable=False))

        elif container_type == "docker":
            cmd = ["docker", "run", "--rm", "-it"]
            cmd.extend(["-v", f"{params.bids_dir}:/data:ro"])
            cmd.extend(["-v", f"{params.output_dir}:/out"])
            if params.work_dir:
                cmd.extend(["-v", f"{params.work_dir}:/work"])
            if params.fs_license_file:
                cmd.extend(
                    ["-v", f"{params.fs_license_file}:/opt/freesurfer/license.txt:ro"]
                )

            cmd.append(container_image)
            docker_params = replace(
                params,
                bids_dir="/data",
                output_dir="/out",
                work_dir="/work" if params.work_dir else None,
                fs_license_file=(
                    "/opt/freesurfer/license.txt" if params.fs_license_file else None
                ),
            )
            cmd.extend(build_qsiprep_command(docker_params, include_executable=False))

        else:
            cmd = build_qsiprep_command(params)

        return " ".join(cmd)

    def _run(
        self,
        bids_dir: str,
        output_dir: str,
        participant_label: list[str] | None = None,
        work_dir: str | None = None,
        fs_license_file: str | None = None,
        denoise_method: DenoisingMethod = DenoisingMethod.PATCH2SELF,
        distortion_correction: DistortionCorrection = DistortionCorrection.TOPUP,
        eddy_config: str | None = None,
        b0_threshold: float = 100.0,
        output_resolution: str = "1.25mm",
        skip_bids_validation: bool = False,
        n_cpus: int | None = None,
        mem_mb: int | None = None,
        low_mem: bool = False,
        container_type: str = "singularity",
        container_image: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Execute QSIPrep preprocessing."""
        try:
            # Validate BIDS dataset
            if not skip_bids_validation:
                validation = self._validate_bids_dataset(bids_dir)
                if not validation["is_valid"]:
                    return ToolResult(
                        status="error",
                        error=f"Invalid BIDS dataset: {', '.join(validation['issues'])}",
                        data={"validation": validation},
                    )

                # If no participants specified, use all found
                if not participant_label and validation["participants"]:
                    logger.info(
                        f"Processing all participants: {validation['participants']}"
                    )
                    participant_label = validation["participants"]

            # Find or validate FreeSurfer license
            if not fs_license_file:
                fs_license_file = self._find_freesurfer_license()
                if not fs_license_file:
                    logger.warning(
                        "No FreeSurfer license found - anatomical processing may be limited"
                    )

            # Find container image
            if not container_image:
                container_image = self._find_container_image(container_type)
                if not container_image:
                    return ToolResult(
                        status="error",
                        error="No QSIPrep container image found",
                        data={},
                    )

            # Create output directory
            os.makedirs(output_dir, exist_ok=True)

            # Create work directory if not specified
            if not work_dir:
                work_dir = os.path.join(output_dir, "work")
                os.makedirs(work_dir, exist_ok=True)

            payload: dict[str, Any] = {
                "bids_dir": bids_dir,
                "output_dir": output_dir,
                "analysis_level": "participant",
                "participant_label": participant_label or [],
                "work_dir": work_dir,
                "fs_license_file": fs_license_file,
                "denoise_method": (
                    denoise_method.value
                    if isinstance(denoise_method, DenoisingMethod)
                    else str(denoise_method)
                ),
                "distortion_correction": distortion_correction.value,
                "eddy_config": eddy_config,
                "b0_threshold": b0_threshold,
                "output_resolution": output_resolution,
                "skip_bids_validation": skip_bids_validation,
                "n_cpus": n_cpus,
                "mem_mb": mem_mb,
                "low_mem": low_mem,
                "omp_nthreads": kwargs.get("omp_nthreads"),
                "impute_slice_threshold": kwargs.get("impute_slice_threshold"),
                "skull_strip_template": kwargs.get("skull_strip_template"),
                "skull_strip_fixed_seed": kwargs.get("skull_strip_fixed_seed"),
                "force_spatial_normalization": kwargs.get(
                    "force_spatial_normalization"
                ),
                "shoreline_iters": kwargs.get("shoreline_iters"),
                "write_graph": kwargs.get("write_graph", False),
                "resource_monitor": kwargs.get("resource_monitor", False),
                "notrack": kwargs.get("notrack", True),
                "bids_filter_file": kwargs.get("bids_filter_file"),
                "hmc_model": kwargs.get("hmc_model", "3dSHORE"),
                "extra_args": kwargs.get("extra_args", []),
            }

            params = qsiprep_from_payload(payload)

            command = self._generate_command(params, container_type, container_image)

            # Log command
            logger.info(f"Generated QSIPrep command: {command}")

            # Extract any existing outputs
            outputs = self._extract_outputs(output_dir)

            # Prepare result
            result_data = {
                "command": command,
                "config": {
                    "bids_dir": bids_dir,
                    "output_dir": output_dir,
                    "work_dir": work_dir,
                    "participant_label": participant_label,
                    "denoise_method": (
                        denoise_method.value
                        if isinstance(denoise_method, DenoisingMethod)
                        else str(denoise_method)
                    ),
                    "distortion_correction": distortion_correction.value,
                    "output_resolution": output_resolution,
                    "container_type": container_type,
                    "container_image": container_image,
                },
                "outputs": outputs,
                "message": "QSIPrep command generated successfully. Execute the command to run preprocessing.",
            }

            # Add execution notes
            notes = []
            if not fs_license_file:
                notes.append(
                    "No FreeSurfer license - anatomical processing will be limited"
                )
            if denoise_method == DenoisingMethod.PATCH2SELF:
                notes.append("Using patch2self denoising for improved SNR")
            if distortion_correction == DistortionCorrection.TOPUP:
                notes.append(
                    "TOPUP distortion correction will be applied if reverse PE data available"
                )
            if low_mem:
                notes.append("Low memory mode enabled - processing may be slower")

            if notes:
                result_data["notes"] = notes

            return ToolResult(status="success", data=result_data)

        except Exception as e:
            logger.error(f"QSIPrep setup failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


class QSIPrepReconArgs(BaseModel):
    """Arguments for QSIPrep reconstruction workflows."""

    qsiprep_dir: str = Field(description="Path to QSIPrep output directory")
    output_dir: str = Field(description="Output directory for reconstruction results")
    recon_spec: str | ReconWorkflow = Field(
        description="Reconstruction specification or workflow name"
    )
    participant_label: list[str] | None = Field(
        default=None, description="Participant labels to reconstruct"
    )
    work_dir: str | None = Field(default=None, description="Optional working directory")
    fs_license_file: str | None = Field(
        default=None, description="Optional FreeSurfer license file"
    )
    n_cpus: int | None = Field(default=None, description="Number of CPUs to use")
    omp_nthreads: int | None = Field(
        default=None, description="Number of OpenMP threads"
    )
    extra_args: list[str] | None = Field(
        default=None, description="Additional CLI arguments"
    )
    dry_run: bool = Field(
        default=True,
        description="Return the resolved command preview without executing it",
    )


class QSIPrepReconTool(NeuroToolWrapper):
    """QSIPrep reconstruction tool."""

    def __init__(self):
        """Initialize QSIPrep reconstruction tool."""
        super().__init__()
        self.default_image = "pennbbl/qsiprep:latest"

    def get_tool_name(self) -> str:
        return "qsiprep_reconstruction"

    def get_tool_description(self) -> str:
        return (
            "Run QSIPrep reconstruction workflows on preprocessed diffusion data. "
            "Supports various reconstruction methods including DTI, DKI, MAPMRI, "
            "NODDI, and tractography."
        )

    def get_args_schema(self):
        return QSIPrepReconArgs

    def _get_recon_spec_path(self, recon_spec: str | ReconWorkflow) -> str:
        """Get the path to reconstruction specification file."""
        if isinstance(recon_spec, ReconWorkflow):
            # Use built-in workflow
            return recon_spec.value
        else:
            # Custom spec file
            return recon_spec

    def _collect_outputs(self, output_dir: str) -> dict[str, Any]:
        outputs: dict[str, Any] = {"qsirecon_dir": output_dir}
        root = Path(output_dir)
        if not root.exists():
            return outputs

        dataset_description = root / "dataset_description.json"
        if dataset_description.exists():
            outputs["dataset_description"] = str(dataset_description)

        subject_dirs = sorted(str(path) for path in root.glob("sub-*") if path.is_dir())
        if subject_dirs:
            outputs["subject_dirs"] = subject_dirs

        subject_reports = sorted(str(path) for path in root.glob("sub-*.html"))
        if subject_reports:
            outputs["subject_reports"] = subject_reports

        tractograms = sorted(str(path) for path in root.rglob("*.tck"))
        tractograms.extend(str(path) for path in root.rglob("*.trk"))
        if tractograms:
            outputs["tractograms"] = tractograms

        recon_outputs = sorted(
            str(path)
            for path in root.rglob("*")
            if path.is_file() and "connect" in path.name
        )
        if recon_outputs:
            outputs["recon_outputs"] = recon_outputs

        return outputs

    def _build_command(
        self,
        executable: str,
        qsiprep_dir: str,
        output_dir: str,
        recon_spec: str,
        participant_label: list[str] | None = None,
        work_dir: str | None = None,
        fs_license_file: str | None = None,
        n_cpus: int | None = None,
        omp_nthreads: int | None = None,
        extra_args: list[str] | None = None,
    ) -> list[str]:
        cmd: list[str] = [
            executable,
            qsiprep_dir,
            output_dir,
            "participant",
            "--recon-spec",
            recon_spec,
        ]
        if participant_label:
            cmd.extend(["--participant-label", *participant_label])
        if work_dir:
            cmd.extend(["-w", work_dir])
        if fs_license_file:
            cmd.extend(["--fs-license-file", fs_license_file])
        if n_cpus is not None:
            cmd.extend(["--nthreads", str(n_cpus)])
        if omp_nthreads is not None:
            cmd.extend(["--omp-nthreads", str(omp_nthreads)])
        if extra_args:
            cmd.extend(extra_args)
        return cmd

    def _run(
        self,
        qsiprep_dir: str,
        output_dir: str,
        recon_spec: str | ReconWorkflow,
        participant_label: list[str] | None = None,
        work_dir: str | None = None,
        fs_license_file: str | None = None,
        n_cpus: int | None = None,
        omp_nthreads: int | None = None,
        extra_args: list[str] | None = None,
        dry_run: bool = True,
        **kwargs,
    ) -> ToolResult:
        """Execute QSIPrep reconstruction."""
        try:
            # Validate input directory
            if not os.path.exists(qsiprep_dir):
                return ToolResult(
                    status="error",
                    error=f"QSIPrep directory not found: {qsiprep_dir}",
                    data={},
                )

            # Create output directory
            os.makedirs(output_dir, exist_ok=True)
            if work_dir:
                os.makedirs(work_dir, exist_ok=True)

            # Get reconstruction spec
            spec_path = self._get_recon_spec_path(recon_spec)
            license_file = _find_freesurfer_license(fs_license_file)
            executable = _resolve_bids_app_executable(
                "qsirecon", env_var="BR_QSIRECON_BIN"
            )
            effective_dry_run = (
                False if _env_truthy("BR_QSIRECON_EXECUTE") else bool(dry_run)
            )
            cmd_list = self._build_command(
                executable=executable,
                qsiprep_dir=qsiprep_dir,
                output_dir=output_dir,
                recon_spec=spec_path,
                participant_label=participant_label,
                work_dir=work_dir,
                fs_license_file=license_file,
                n_cpus=n_cpus,
                omp_nthreads=omp_nthreads,
                extra_args=extra_args,
            )
            logger.info("Generated QSIRecon command: %s", " ".join(cmd_list))

            data = {
                "command": cmd_list,
                "outputs": self._collect_outputs(output_dir),
                "summary": {
                    "backend": "wrapper_executable",
                    "executable": executable,
                    "participant_label": participant_label or [],
                    "work_dir": work_dir,
                    "has_fs_license": bool(license_file),
                    "dry_run": bool(effective_dry_run),
                },
                "recon_spec": (
                    spec_path if isinstance(recon_spec, str) else recon_spec.value
                ),
                "output_dir": output_dir,
            }

            if effective_dry_run:
                data["dry_run"] = True
                data["message"] = "QSIRecon command generated successfully"
                return ToolResult(status="success", data=data)

            proc = run_subprocess(
                cmd_list,
                cwd="/tmp",
                env=_build_apptainer_bind_env(
                    qsiprep_dir,
                    output_dir,
                    work_dir or "",
                    license_file or "",
                ),
            )
            data["stdout"] = proc.stdout
            data["stderr"] = proc.stderr
            data["outputs"] = self._collect_outputs(output_dir)
            data["message"] = "QSIRecon completed successfully"
            return ToolResult(status="success", data=data)

        except Exception as e:
            logger.error(f"QSIPrep reconstruction failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


class QSIPrepQCArgs(BaseModel):
    """Arguments for QSIPrep quality control."""

    qsiprep_dir: str = Field(description="Path to QSIPrep output directory")
    output_file: str | None = Field(default=None, description="Path to save QC report")


class QSIPrepQCTool(NeuroToolWrapper):
    """QSIPrep quality control tool."""

    def get_tool_name(self) -> str:
        return "qsiprep_qc"

    def get_tool_description(self) -> str:
        return (
            "Extract and analyze quality control metrics from QSIPrep outputs including "
            "motion parameters, SNR, CNR, and preprocessing quality measures."
        )

    def get_args_schema(self):
        return QSIPrepQCArgs

    def _parse_qc_file(self, qc_file: str) -> dict[str, Any]:
        """Parse QSIPrep QC JSON file."""
        metrics = {}

        try:
            with open(qc_file) as f:
                qc_data = json.load(f)

                # Extract key metrics
                if "summary" in qc_data:
                    metrics.update(qc_data["summary"])

                # Motion metrics
                if "fd_mean" in qc_data:
                    metrics["mean_fd"] = qc_data["fd_mean"]
                if "fd_max" in qc_data:
                    metrics["max_fd"] = qc_data["fd_max"]

                # SNR metrics
                if "snr_b0" in qc_data:
                    metrics["snr_b0"] = qc_data["snr_b0"]
                if "snr_dwi" in qc_data:
                    metrics["snr_dwi"] = qc_data["snr_dwi"]

                # Other quality metrics
                if "outliers_percent" in qc_data:
                    metrics["outliers_percent"] = qc_data["outliers_percent"]

        except Exception as e:
            logger.warning(f"Failed to parse QC file: {e}")

        return metrics

    def _run(
        self, qsiprep_dir: str, output_file: str | None = None, **kwargs
    ) -> ToolResult:
        """Extract QC metrics from QSIPrep outputs."""
        try:
            if not os.path.exists(qsiprep_dir):
                return ToolResult(
                    status="error",
                    error=f"QSIPrep directory not found: {qsiprep_dir}",
                    data={},
                )

            qc_report = {
                "qsiprep_dir": qsiprep_dir,
                "participants": {},
                "summary": {
                    "n_participants": 0,
                    "mean_fd_across_participants": [],
                    "mean_snr_b0": [],
                    "mean_snr_dwi": [],
                    "high_motion_scans": [],
                },
            }

            # Process each participant
            qsiprep_output = os.path.join(qsiprep_dir, "qsiprep")
            if os.path.exists(qsiprep_output):
                for participant in os.listdir(qsiprep_output):
                    if not participant.startswith("sub-"):
                        continue

                    part_data = {
                        "qc_metrics": {},
                        "reports": [],
                        "outputs": {"dwi": [], "anat": []},
                    }

                    part_dir = os.path.join(qsiprep_output, participant)

                    # Find QC files
                    dwi_dir = os.path.join(part_dir, "dwi")
                    if os.path.exists(dwi_dir):
                        for file in os.listdir(dwi_dir):
                            if file.endswith("_qc.json"):
                                qc_path = os.path.join(dwi_dir, file)
                                metrics = self._parse_qc_file(qc_path)
                                part_data["qc_metrics"].update(metrics)

                                # Track high motion scans
                                if metrics.get("mean_fd", 0) > 0.5:
                                    qc_report["summary"]["high_motion_scans"].append(
                                        f"{participant}"
                                    )

                            # Track outputs
                            if file.endswith(".nii.gz"):
                                part_data["outputs"]["dwi"].append(file)

                    # Track anatomical outputs
                    anat_dir = os.path.join(part_dir, "anat")
                    if os.path.exists(anat_dir):
                        part_data["outputs"]["anat"] = [
                            f for f in os.listdir(anat_dir) if f.endswith(".nii.gz")
                        ]

                    # Find HTML reports
                    html_report = os.path.join(qsiprep_dir, f"{participant}.html")
                    if os.path.exists(html_report):
                        part_data["reports"].append(html_report)

                    qc_report["participants"][participant] = part_data
                    qc_report["summary"]["n_participants"] += 1

                    # Aggregate metrics
                    if "mean_fd" in part_data["qc_metrics"]:
                        qc_report["summary"]["mean_fd_across_participants"].append(
                            part_data["qc_metrics"]["mean_fd"]
                        )
                    if "snr_b0" in part_data["qc_metrics"]:
                        qc_report["summary"]["mean_snr_b0"].append(
                            part_data["qc_metrics"]["snr_b0"]
                        )
                    if "snr_dwi" in part_data["qc_metrics"]:
                        qc_report["summary"]["mean_snr_dwi"].append(
                            part_data["qc_metrics"]["snr_dwi"]
                        )

            # Calculate summary statistics
            if qc_report["summary"]["mean_fd_across_participants"]:
                import statistics

                qc_report["summary"]["overall_mean_fd"] = statistics.mean(
                    qc_report["summary"]["mean_fd_across_participants"]
                )
            if qc_report["summary"]["mean_snr_b0"]:
                qc_report["summary"]["overall_mean_snr_b0"] = statistics.mean(
                    qc_report["summary"]["mean_snr_b0"]
                )
            if qc_report["summary"]["mean_snr_dwi"]:
                qc_report["summary"]["overall_mean_snr_dwi"] = statistics.mean(
                    qc_report["summary"]["mean_snr_dwi"]
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
class QSIPrepTools:
    """Collection of QSIPrep tools."""

    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        """Get all QSIPrep tools."""
        return [QSIPrepTool(), QSIPrepReconTool(), QSIPrepQCTool()]
