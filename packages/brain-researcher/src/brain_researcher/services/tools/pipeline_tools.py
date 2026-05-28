"""Preprocessing pipeline tools for neuroimaging data."""

import glob
import logging
import os
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.executors import (
    BindMount,
    ContainerRequest,
    run_container,
)
from brain_researcher.services.tools.pipelines import (
    build_fmriprep_command,
    build_mriqc_command,
    build_qsiprep_command,
    fmriprep_from_payload,
    mriqc_from_payload,
    qsiprep_from_payload,
    run_fitlins_from_dict,
)
from brain_researcher.services.tools.runtime_profiles import (
    get_container_image,
    get_neurodesk_package_profile,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult
from brain_researcher.services.tools.utils import run_subprocess

logger = logging.getLogger(__name__)


_CVMFS_CONTAINERS = os.environ.get(
    "BR_NEURODESK_CVMFS_CONTAINERS",
    "/cvmfs/neurodesk.ardc.edu.au/containers",
)
_LOCAL_NEUROCOMMAND_CONTAINERS = os.environ.get(
    "BR_NEUROCOMMAND_CONTAINERS_DIR",
    str(
        Path(__file__).resolve().parents[4]
        / "external"
        / "neurocommand"
        / "neurocommand-repo"
        / "local"
        / "containers"
    ),
)

# Neurodesk wrappers invoke Apptainer with `--pwd "$PWD"`.
# Running from /app shadows container-internal /app (where newer pixi installs live),
# so execute BIDS app wrappers from /tmp to avoid that bind collision.
_BIDS_APP_CWD = "/tmp"


def _build_apptainer_bind_env(*paths: str) -> dict[str, str]:
    """Ensure host dataset/output paths are visible inside Apptainer containers."""
    bind_paths: list[str] = []
    for raw in paths:
        if not raw:
            continue
        abspath = os.path.abspath(raw)
        if abspath not in bind_paths:
            bind_paths.append(abspath)

    env = dict(os.environ)
    for var in ("APPTAINER_BINDPATH", "SINGULARITY_BINDPATH"):
        existing = [p for p in env.get(var, "").split(",") if p]
        for path in bind_paths:
            if path not in existing:
                existing.append(path)
        if existing:
            env[var] = ",".join(existing)
    return env


def _resolve_bids_app_executable(binary: str, *, env_var: str | None = None) -> str:
    """Resolve executable for BIDS Apps from PATH or Neurodesk container dirs.

    Resolution order:
    1. Explicit env override (e.g., BR_FMRIPREP_BIN)
    2. PATH (`shutil.which`)
    3. CVMFS Neurodesk containers
    4. Repo-local neurocommand containers
    5. Fallback to bare binary name
    """
    override = os.environ.get(env_var, "").strip() if env_var else ""
    if override:
        if os.path.isabs(override):
            if os.path.isfile(override) and os.access(override, os.X_OK):
                return override
            logger.warning(
                "Override %s=%s is not an executable file; falling back to discovery",
                env_var,
                override,
            )
        else:
            resolved_override = shutil.which(override)
            if resolved_override:
                return resolved_override

    resolved = shutil.which(binary)
    if resolved:
        return resolved

    # Prefer local neurocommand containers (faster/high-frequency), then CVMFS.
    patterns = [
        os.path.join(_LOCAL_NEUROCOMMAND_CONTAINERS, f"{binary}_*", binary),
        os.path.join(_CVMFS_CONTAINERS, f"{binary}_*", binary),
    ]
    for pattern in patterns:
        candidates = sorted(
            p for p in glob.glob(pattern) if os.path.isfile(p) and os.access(p, os.X_OK)
        )
        if candidates:
            chosen = candidates[-1]
            logger.info("Resolved %s executable to %s", binary, chosen)
            return chosen

    return binary


def _find_freesurfer_license(explicit_path: str | None = None) -> str | None:
    """Locate a FreeSurfer license file if available."""
    if explicit_path:
        resolved = os.path.abspath(explicit_path)
        if os.path.exists(resolved):
            return resolved
        logger.warning("FreeSurfer license override not found: %s", explicit_path)

    possible_locations = [
        os.path.expanduser("~/.freesurfer/license.txt"),
        os.path.expanduser("~/.freesurfer_license.txt"),
        "/opt/freesurfer/license.txt",
        os.path.join(os.environ.get("FREESURFER_HOME", ""), "license.txt"),
        "/usr/local/freesurfer/license.txt",
    ]

    for location in possible_locations:
        if location and os.path.exists(location):
            return location

    return None


def _collect_fmriprep_outputs(output_dir: str) -> dict[str, Any]:
    root = Path(output_dir)
    outputs: dict[str, Any] = {"derivatives_dir": str(root)}

    dataset_description = root / "dataset_description.json"
    if dataset_description.exists():
        outputs["dataset_description"] = str(dataset_description)

    logs_dir = root / "logs"
    if logs_dir.exists():
        outputs["logs_dir"] = str(logs_dir)

    figures_dir = root / "figures"
    if figures_dir.exists():
        outputs["figures_dir"] = str(figures_dir)

    subject_reports = sorted(str(p) for p in root.glob("sub-*.html"))
    if subject_reports:
        outputs["subject_reports"] = subject_reports

    confounds = sorted(str(p) for p in root.rglob("*desc-confounds_timeseries.tsv"))
    if confounds:
        outputs["confounds"] = confounds

    return outputs


def _collect_mriqc_outputs(output_dir: str) -> dict[str, Any]:
    root = Path(output_dir)
    outputs: dict[str, Any] = {"mriqc_dir": str(root)}

    dataset_description = root / "dataset_description.json"
    if dataset_description.exists():
        outputs["dataset_description"] = str(dataset_description)

    subject_reports = sorted(str(p) for p in root.glob("sub-*.html"))
    if subject_reports:
        outputs["subject_reports"] = subject_reports

    group_reports = [
        str(path)
        for path in (root / "group_bold.html", root / "group_T1w.html")
        if path.exists()
    ]
    if group_reports:
        outputs["group_reports"] = group_reports

    group_tables = [
        str(path)
        for path in (root / "group_bold.tsv", root / "group_T1w.tsv")
        if path.exists()
    ]
    if group_tables:
        outputs["group_tables"] = group_tables

    return outputs


def _collect_smriprep_outputs(output_dir: str) -> dict[str, Any]:
    root = Path(output_dir)
    outputs: dict[str, Any] = {"derivatives_dir": str(root)}

    dataset_description = root / "dataset_description.json"
    if dataset_description.exists():
        outputs["dataset_description"] = str(dataset_description)

    logs_dir = root / "logs"
    if logs_dir.exists():
        outputs["logs_dir"] = str(logs_dir)

    figures_dir = root / "figures"
    if figures_dir.exists():
        outputs["figures_dir"] = str(figures_dir)

    subject_reports = sorted(str(p) for p in root.glob("sub-*.html"))
    if subject_reports:
        outputs["subject_reports"] = subject_reports

    preprocessed_t1w = sorted(str(p) for p in root.rglob("*desc-preproc_T1w.nii.gz"))
    if preprocessed_t1w:
        outputs["preprocessed_t1w"] = preprocessed_t1w

    surfaces = sorted(str(p) for p in root.rglob("surf/*"))
    if surfaces:
        outputs["surfaces"] = surfaces

    transforms = sorted(str(p) for p in root.rglob("*from-*_to-*_xfm.*"))
    if transforms:
        outputs["transforms"] = transforms

    return outputs


def _collect_qsiprep_outputs(output_dir: str) -> dict[str, Any]:
    root = Path(output_dir)
    outputs: dict[str, Any] = {"derivatives_dir": str(root)}

    dataset_description = root / "dataset_description.json"
    if dataset_description.exists():
        outputs["dataset_description"] = str(dataset_description)

    logs_dir = root / "logs"
    if logs_dir.exists():
        outputs["logs_dir"] = str(logs_dir)

    figures_dir = root / "figures"
    if figures_dir.exists():
        outputs["figures_dir"] = str(figures_dir)

    subject_reports = sorted(str(p) for p in root.glob("sub-*.html"))
    if subject_reports:
        outputs["subject_reports"] = subject_reports

    preprocessed_dwi = sorted(str(p) for p in root.rglob("*desc-preproc_dwi.nii.gz"))
    if preprocessed_dwi:
        outputs["preprocessed_dwi"] = preprocessed_dwi

    figures = sorted(str(p) for p in root.rglob("figures/*"))
    if figures:
        outputs["figures"] = figures

    qc_reports = sorted(str(p) for p in root.rglob("*_qc.json"))
    if qc_reports:
        outputs["qc_reports"] = qc_reports

    gradient_files = sorted(
        str(p)
        for p in root.rglob("*")
        if p.suffix in {".bval", ".bvec"} or p.name.endswith(".b")
    )
    if gradient_files:
        outputs["gradient_files"] = gradient_files

    return outputs


def _build_smriprep_command(
    *,
    executable: str,
    bids_dir: str,
    output_dir: str,
    participant_label: list[str] | None = None,
    work_dir: str | None = None,
    fs_license_file: str | None = None,
    output_spaces: list[str] | None = None,
    skip_bids_validation: bool = False,
    bids_filter_file: str | None = None,
    n_cpus: int | None = None,
    omp_nthreads: int | None = None,
    mem_mb: int | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    cmd = [executable, bids_dir, output_dir, "participant"]
    if participant_label:
        cmd.extend(["--participant-label", *participant_label])
    if work_dir:
        cmd.extend(["-w", work_dir])
    if fs_license_file:
        cmd.extend(["--fs-license-file", fs_license_file])
    if output_spaces:
        cmd.extend(["--output-spaces", *output_spaces])
    if skip_bids_validation:
        cmd.append("--skip-bids-validation")
    if bids_filter_file:
        cmd.extend(["--bids-filter-file", bids_filter_file])
    if n_cpus is not None:
        cmd.extend(["--n-cpus", str(n_cpus)])
    if omp_nthreads is not None:
        cmd.extend(["--omp-nthreads", str(omp_nthreads)])
    if mem_mb is not None:
        cmd.extend(["--mem-mb", str(mem_mb)])
    if extra_args:
        cmd.extend(extra_args)
    return cmd


def _resolve_fastsurfer_image(
    runtime: str = "apptainer",
    container_image: str | None = None,
) -> str:
    if container_image:
        return container_image

    if runtime != "docker":
        profile = get_neurodesk_package_profile("fastsurfer") or {}
        configured = str(profile.get("container_path") or "").strip()
        if configured and os.path.exists(configured):
            return configured

        pattern = os.path.join(_CVMFS_CONTAINERS, "fastsurfer_*")
        for container_dir in sorted(glob.glob(pattern), reverse=True):
            base = os.path.basename(container_dir)
            candidate = os.path.join(container_dir, f"{base}.simg")
            if os.path.exists(candidate):
                return candidate

    return get_container_image("fastsurfer") or "deepmi/fastsurfer:latest"


def _fastsurfer_output_paths(output_dir: str, subject_id: str) -> dict[str, str]:
    subject_dir = Path(output_dir) / subject_id
    mri_dir = subject_dir / "mri"

    aparc_candidates = [
        mri_dir / "aparc+aseg.mgz",
        mri_dir / "aparc.DKTatlas+aseg.deep.mgz",
    ]
    aseg_candidates = [
        mri_dir / "aseg.mgz",
        mri_dir / "aseg.auto_noCCseg.mgz",
    ]

    aparc = next(
        (path for path in aparc_candidates if path.exists()), aparc_candidates[0]
    )
    aseg = next((path for path in aseg_candidates if path.exists()), aseg_candidates[0])

    return {
        "subject_dir": str(subject_dir),
        "surfaces_dir": str(subject_dir / "surf"),
        "aseg_volume": str(aseg),
        "aparcaseg_volume": str(aparc),
    }


class FMRIPrepArgs(BaseModel):
    """Arguments for fMRIPrep."""

    bids_dir: str = Field(description="Input BIDS directory")
    output_dir: str = Field(description="Output derivatives directory")
    participant_label: list[str] | None = Field(
        default=None, description="Optional participant labels to include"
    )
    work_dir: str | None = Field(default=None, description="Optional work directory")
    fs_license_file: str | None = Field(
        default=None, description="Optional FreeSurfer license file"
    )
    output_spaces: list[str] | None = Field(
        default=None, description="Optional output spaces"
    )
    skip_bids_validation: bool = Field(
        default=False, description="Skip BIDS validation before execution"
    )
    n_cpus: int | None = Field(default=None, description="CPU threads")
    omp_nthreads: int | None = Field(default=None, description="OpenMP thread count")
    mem_mb: int | None = Field(default=None, description="Requested memory in MB")
    bids_filter_file: str | None = Field(
        default=None, description="Optional BIDS filter JSON"
    )
    extra_args: list[str] | None = Field(
        default=None, description="Additional command arguments"
    )


class RunFMRIPrepTool(NeuroToolWrapper):
    """Tool for running fMRIPrep preprocessing pipeline."""

    def get_tool_name(self) -> str:
        return "run_fmriprep"

    def get_tool_description(self) -> str:
        return "Execute the fMRIPrep preprocessing workflow on BIDS data"

    def get_args_schema(self):
        return FMRIPrepArgs

    def _run(
        self,
        bids_dir: str,
        output_dir: str,
        participant_label: list[str] | None = None,
        work_dir: str | None = None,
        fs_license_file: str | None = None,
        output_spaces: list[str] | None = None,
        skip_bids_validation: bool = False,
        n_cpus: int | None = None,
        omp_nthreads: int | None = None,
        mem_mb: int | None = None,
        bids_filter_file: str | None = None,
        extra_args: list[str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            os.makedirs(output_dir, exist_ok=True)
            if work_dir:
                os.makedirs(work_dir, exist_ok=True)

            license_file = _find_freesurfer_license(fs_license_file)
            payload: dict[str, Any] = {
                "bids_dir": bids_dir,
                "output_dir": output_dir,
                "participant_label": participant_label or [],
                "work_dir": work_dir,
                "fs_license_file": license_file,
                "output_spaces": output_spaces or [],
                "skip_bids_validation": skip_bids_validation,
                "n_cpus": n_cpus,
                "omp_nthreads": omp_nthreads,
                "mem_mb": mem_mb,
                "bids_filter_file": bids_filter_file,
                "extra_args": extra_args or [],
            }
            for key in (
                "use_aroma",
                "cifti_output",
                "low_mem",
                "stop_on_first_crash",
                "notrack",
                "longitudinal",
                "verbose",
                "skull_strip_t1w",
                "skull_strip_fixed_seed",
                "bold2t1w_init",
                "bold2t1w_dof",
                "fd_spike_threshold",
                "dvars_spike_threshold",
                "me_output_echos",
                "medial_surface_nan",
                "dummy_scans",
                "use_syn_sdc",
                "force_syn",
            ):
                if key in kwargs and kwargs[key] is not None:
                    payload[key] = kwargs[key]

            params = fmriprep_from_payload(payload)
            executable = _resolve_bids_app_executable(
                "fmriprep", env_var="BR_FMRIPREP_BIN"
            )
            command = build_fmriprep_command(params)
            if command:
                command[0] = executable

            proc = run_subprocess(
                command,
                cwd=_BIDS_APP_CWD,
                env=_build_apptainer_bind_env(
                    bids_dir,
                    output_dir,
                    work_dir or "",
                    bids_filter_file or "",
                    license_file or "",
                ),
            )
            return ToolResult(
                status="success",
                data={
                    "command": command,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "outputs": _collect_fmriprep_outputs(output_dir),
                    "summary": {
                        "backend": "wrapper_executable",
                        "executable": executable,
                        "participant_label": list(params.participant_label),
                        "work_dir": work_dir,
                        "has_fs_license": bool(license_file),
                    },
                },
            )
        except Exception as e:
            logger.error(f"fMRIPrep failed: {e}")
            return ToolResult(status="error", error=str(e))


class FitLinsRecipeArgs(BaseModel):
    """Arguments for the FitLins BIDS App wrapper."""

    bids_dir: str = Field(description="Input BIDS directory")
    output_dir: str = Field(description="Output derivatives directory")
    analysis_level: str = Field(
        default="dataset", description="Analysis level (run/session/subject/dataset)"
    )
    model: str | None = Field(
        default=None, description="StatsModel JSON path or name registered in dataset"
    )
    derivatives_dir: str | None = Field(
        default=None, description="Optional derivatives root (e.g., fMRIPrep outputs)"
    )
    participant_label: list[str] | None = Field(
        default=None, description="Participants to include"
    )
    work_dir: str | None = Field(default=None, description="Optional working directory")
    reports_only: bool = Field(
        default=False, description="Generate reports only (if supported)"
    )
    dry_run: bool = Field(
        default=False,
        description="If True, validate inputs and return the command without executing.",
    )
    extra_args: list[str] | None = Field(
        default=None, description="Additional CLI arguments passed through to FitLins"
    )
    runtime: str = Field(
        default="apptainer",
        description="Execution runtime: apptainer|docker|wrapper",
    )
    container_image: str | None = Field(
        default=None,
        description="Optional container image (apptainer/docker). Ignored for wrapper runtime.",
    )


class RunFitLinsRecipeTool(NeuroToolWrapper):
    """Tool wrapper that delegates to ToolHub's FitLins implementation."""

    def get_tool_name(self) -> str:
        return "run_fitlins_recipe"

    def get_tool_description(self) -> str:
        return "Execute the FitLins GLM pipeline via local Neurodesk modules"

    def get_args_schema(self):
        return FitLinsRecipeArgs

    def _run(
        self,
        bids_dir: str,
        output_dir: str,
        analysis_level: str = "dataset",
        model: str | None = None,
        derivatives_dir: str | None = None,
        participant_label: list[str] | None = None,
        work_dir: str | None = None,
        reports_only: bool = False,
        dry_run: bool = False,
        extra_args: list[str] | None = None,
        runtime: str = "apptainer",
        container_image: str | None = None,
    ) -> ToolResult:
        try:
            payload = {
                "bids_dir": bids_dir,
                "output_dir": output_dir,
                "analysis_level": analysis_level,
                "model": model,
                "derivatives_dir": derivatives_dir,
                "participant_label": participant_label or [],
                "work_dir": work_dir,
                "reports_only": reports_only,
                "dry_run": dry_run,
                "extra_args": extra_args or [],
                "container_image": container_image,
            }
            result = run_fitlins_from_dict(payload, runtime=runtime)
            exit_code = result.get("exit_code", 1)
            if exit_code == 0:
                return ToolResult(status="success", data=result)
            error_msg = result.get("stderr") or f"FitLins exited with code {exit_code}"
            return ToolResult(status="error", error=error_msg, data=result)
        except Exception as e:
            logger.error(f"FitLins failed: {e}")
            return ToolResult(status="error", error=str(e))


class MRIQCArgs(BaseModel):
    """Arguments for MRIQC."""

    bids_dir: str = Field(description="Input BIDS directory")
    output_dir: str = Field(description="Output directory")
    analysis_level: str = Field(
        default="participant", description="Analysis level (participant/group)"
    )
    participant_label: list[str] | None = Field(
        default=None, description="Optional participant labels to include"
    )
    modalities: list[str] | None = Field(
        default=None, description="Optional modalities to process"
    )
    work_dir: str | None = Field(default=None, description="Optional work directory")
    bids_filter_file: str | None = Field(
        default=None, description="Optional BIDS filter JSON"
    )
    n_procs: int | None = Field(default=None, description="Process count")
    mem_gb: float | None = Field(default=None, description="Requested memory in GB")
    extra_args: list[str] | None = Field(
        default=None, description="Additional arguments"
    )


class RunMRIQCTool(NeuroToolWrapper):
    """Tool for running MRIQC quality assessment."""

    def get_tool_name(self) -> str:
        return "run_mriqc"

    def get_tool_description(self) -> str:
        return "Run MRIQC quality assessment on MRI data"

    def get_args_schema(self):
        return MRIQCArgs

    def _run(
        self,
        bids_dir: str,
        output_dir: str,
        analysis_level: str = "participant",
        participant_label: list[str] | None = None,
        modalities: list[str] | None = None,
        work_dir: str | None = None,
        bids_filter_file: str | None = None,
        n_procs: int | None = None,
        mem_gb: float | None = None,
        extra_args: list[str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            os.makedirs(output_dir, exist_ok=True)
            if work_dir:
                os.makedirs(work_dir, exist_ok=True)

            payload = {
                "bids_dir": bids_dir,
                "output_dir": output_dir,
                "analysis_level": analysis_level,
                "participant_label": participant_label or [],
                "modalities": modalities or [],
                "work_dir": work_dir,
                "bids_filter_file": bids_filter_file,
                "n_procs": n_procs,
                "mem_gb": mem_gb,
                "extra_args": extra_args or [],
            }
            for key in (
                "session_id",
                "run_id",
                "dsname",
                "float32",
                "clean_workdir",
                "verbose_reports",
                "no_sub",
                "random_seed",
            ):
                if key in kwargs and kwargs[key] is not None:
                    payload[key] = kwargs[key]
            params = mriqc_from_payload(payload)
            command = build_mriqc_command(params)
            if command:
                command[0] = _resolve_bids_app_executable(
                    "mriqc", env_var="BR_MRIQC_BIN"
                )
            proc = run_subprocess(
                command,
                cwd=_BIDS_APP_CWD,
                env=_build_apptainer_bind_env(
                    bids_dir,
                    output_dir,
                    work_dir or "",
                    bids_filter_file or "",
                ),
            )
            return ToolResult(
                status="success",
                data={
                    "command": command,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "outputs": _collect_mriqc_outputs(output_dir),
                    "summary": {
                        "backend": "wrapper_executable",
                        "analysis_level": analysis_level,
                        "participant_label": list(params.participant_label),
                        "modalities": list(params.modalities),
                        "work_dir": work_dir,
                    },
                },
            )
        except Exception as e:
            logger.error(f"MRIQC failed: {e}")
            return ToolResult(status="error", error=str(e))


class SMRIPrepArgs(BaseModel):
    """Arguments for sMRIPrep."""

    bids_dir: str = Field(description="Input BIDS directory")
    output_dir: str = Field(description="Output directory")
    participant_label: list[str] | None = Field(
        default=None, description="Optional participant labels to include"
    )
    work_dir: str | None = Field(default=None, description="Optional work directory")
    fs_license_file: str | None = Field(
        default=None, description="Optional FreeSurfer license file"
    )
    output_spaces: list[str] | None = Field(
        default=None, description="Optional output spaces"
    )
    skip_bids_validation: bool = Field(
        default=False, description="Skip BIDS validation before execution"
    )
    bids_filter_file: str | None = Field(
        default=None, description="Optional BIDS filter JSON"
    )
    n_cpus: int | None = Field(default=None, description="CPU thread count")
    omp_nthreads: int | None = Field(default=None, description="OpenMP thread count")
    mem_mb: int | None = Field(default=None, description="Requested memory in MB")
    extra_args: list[str] | None = Field(
        default=None, description="Additional arguments"
    )


class RunSMRIPrepTool(NeuroToolWrapper):
    """Tool for running sMRIPrep structural preprocessing."""

    def get_tool_name(self) -> str:
        return "run_smriprep"

    def get_tool_description(self) -> str:
        return "Run sMRIPrep structural MRI preprocessing pipeline"

    def get_args_schema(self):
        return SMRIPrepArgs

    def _run(
        self,
        bids_dir: str,
        output_dir: str,
        participant_label: list[str] | None = None,
        work_dir: str | None = None,
        fs_license_file: str | None = None,
        output_spaces: list[str] | None = None,
        skip_bids_validation: bool = False,
        bids_filter_file: str | None = None,
        n_cpus: int | None = None,
        omp_nthreads: int | None = None,
        mem_mb: int | None = None,
        extra_args: list[str] | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            os.makedirs(output_dir, exist_ok=True)
            if work_dir:
                os.makedirs(work_dir, exist_ok=True)
            executable = _resolve_bids_app_executable(
                "smriprep", env_var="BR_SMRIPREP_BIN"
            )
            license_file = _find_freesurfer_license(fs_license_file)
            cmd = _build_smriprep_command(
                executable=executable,
                bids_dir=bids_dir,
                output_dir=output_dir,
                participant_label=participant_label,
                work_dir=work_dir,
                fs_license_file=license_file,
                output_spaces=output_spaces,
                skip_bids_validation=skip_bids_validation,
                bids_filter_file=bids_filter_file,
                n_cpus=n_cpus,
                omp_nthreads=omp_nthreads,
                mem_mb=mem_mb,
                extra_args=extra_args,
            )
            proc = run_subprocess(
                cmd,
                cwd=_BIDS_APP_CWD,
                env=_build_apptainer_bind_env(
                    bids_dir,
                    output_dir,
                    work_dir or "",
                    bids_filter_file or "",
                    license_file or "",
                ),
            )
            return ToolResult(
                status="success",
                data={
                    "command": cmd,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "outputs": _collect_smriprep_outputs(output_dir),
                    "summary": {
                        "backend": "wrapper_executable",
                        "executable": executable,
                        "participant_label": participant_label or [],
                        "work_dir": work_dir,
                        "has_fs_license": bool(license_file),
                    },
                },
            )
        except Exception as e:
            logger.error(f"sMRIPrep failed: {e}")
            return ToolResult(status="error", error=str(e))


class QSIPrepArgs(BaseModel):
    """Arguments for QSIPrep."""

    bids_dir: str = Field(description="Input BIDS directory")
    output_dir: str = Field(description="Output directory")
    participant_label: list[str] | None = Field(
        default=None, description="Optional participant labels to include"
    )
    work_dir: str | None = Field(default=None, description="Optional work directory")
    fs_license_file: str | None = Field(
        default=None, description="Optional FreeSurfer license file"
    )
    bids_filter_file: str | None = Field(
        default=None, description="Optional BIDS filter JSON"
    )
    denoise_method: str | None = Field(
        default="patch2self", description="Optional denoising method"
    )
    distortion_correction: str | None = Field(
        default=None, description="Optional distortion correction mode"
    )
    hmc_model: str | None = Field(
        default="3dSHORE", description="Optional head motion correction model"
    )
    eddy_config: str | None = Field(
        default=None, description="Optional eddy configuration file"
    )
    b0_threshold: float | None = Field(default=100.0, description="B0 threshold")
    output_resolution: str | None = Field(
        default=None, description="Optional output resolution"
    )
    skip_bids_validation: bool = Field(
        default=False, description="Skip BIDS validation before execution"
    )
    n_cpus: int | None = Field(default=None, description="CPU thread count")
    omp_nthreads: int | None = Field(default=None, description="OpenMP thread count")
    mem_mb: int | None = Field(default=None, description="Requested memory in MB")
    extra_args: list[str] | None = Field(
        default=None, description="Additional arguments"
    )


class RunQSIPrepTool(NeuroToolWrapper):
    """Tool for running QSIPrep diffusion preprocessing."""

    def get_tool_name(self) -> str:
        return "run_qsiprep"

    def get_tool_description(self) -> str:
        return "Run QSIPrep diffusion MRI preprocessing pipeline"

    def get_args_schema(self):
        return QSIPrepArgs

    def _run(
        self,
        bids_dir: str,
        output_dir: str,
        participant_label: list[str] | None = None,
        work_dir: str | None = None,
        fs_license_file: str | None = None,
        bids_filter_file: str | None = None,
        denoise_method: str | None = "patch2self",
        distortion_correction: str | None = None,
        hmc_model: str | None = "3dSHORE",
        eddy_config: str | None = None,
        b0_threshold: float | None = 100.0,
        output_resolution: str | None = None,
        skip_bids_validation: bool = False,
        n_cpus: int | None = None,
        omp_nthreads: int | None = None,
        mem_mb: int | None = None,
        extra_args: list[str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            os.makedirs(output_dir, exist_ok=True)
            if work_dir:
                os.makedirs(work_dir, exist_ok=True)
            license_file = _find_freesurfer_license(fs_license_file)
            payload = {
                "bids_dir": bids_dir,
                "output_dir": output_dir,
                "analysis_level": "participant",
                "participant_label": participant_label or [],
                "work_dir": work_dir,
                "fs_license_file": license_file,
                "bids_filter_file": bids_filter_file,
                "denoise_method": denoise_method,
                "distortion_correction": distortion_correction,
                "hmc_model": hmc_model,
                "eddy_config": eddy_config,
                "b0_threshold": b0_threshold,
                "output_resolution": output_resolution,
                "skip_bids_validation": skip_bids_validation,
                "n_cpus": n_cpus,
                "omp_nthreads": omp_nthreads,
                "mem_mb": mem_mb,
                "extra_args": extra_args or [],
            }
            for key in (
                "use_syn_sdc",
                "impute_slice_threshold",
                "skull_strip_template",
                "skull_strip_fixed_seed",
                "force_spatial_normalization",
                "shoreline_iters",
                "write_graph",
                "low_mem",
                "notrack",
                "resource_monitor",
                "verbose",
            ):
                if key in kwargs and kwargs[key] is not None:
                    payload[key] = kwargs[key]
            params = qsiprep_from_payload(payload)
            executable = _resolve_bids_app_executable(
                "qsiprep", env_var="BR_QSIPREP_BIN"
            )
            cmd = build_qsiprep_command(params)
            if cmd:
                cmd[0] = executable
            proc = run_subprocess(
                cmd,
                cwd=_BIDS_APP_CWD,
                env=_build_apptainer_bind_env(
                    bids_dir,
                    output_dir,
                    work_dir or "",
                    bids_filter_file or "",
                    license_file or "",
                ),
            )
            return ToolResult(
                status="success",
                data={
                    "command": cmd,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "outputs": _collect_qsiprep_outputs(output_dir),
                    "summary": {
                        "backend": "wrapper_executable",
                        "executable": executable,
                        "participant_label": list(params.participant_label),
                        "work_dir": work_dir,
                        "has_fs_license": bool(license_file),
                    },
                },
            )
        except Exception as e:
            logger.error(f"QSIPrep failed: {e}")
            return ToolResult(status="error", error=str(e))


class FastSurferArgs(BaseModel):
    """Arguments for FastSurfer structural reconstruction."""

    t1w_image: str = Field(description="Absolute path to the T1-weighted image")
    subject_id: str = Field(description="Subject identifier")
    output_dir: str = Field(description="Output subjects directory root")
    fs_license_file: str | None = Field(
        default=None, description="Optional FreeSurfer license file"
    )
    n_threads: int = Field(default=1, description="Thread count")
    use_gpu: bool = Field(default=False, description="Enable GPU execution")
    runtime: str = Field(
        default="apptainer", description="Execution runtime: apptainer or docker"
    )
    container_image: str | None = Field(
        default=None, description="Optional FastSurfer container image override"
    )
    dry_run: bool = Field(
        default=False, description="Return the resolved container command only"
    )
    extra_args: list[str] | None = Field(
        default=None, description="Additional FastSurfer CLI arguments"
    )


class RunFastSurferTool(NeuroToolWrapper):
    """Tool for running FastSurfer structural reconstruction."""

    def get_tool_name(self) -> str:
        return "run_fastsurfer"

    def get_tool_description(self) -> str:
        return "Run FastSurfer using the configured container backend"

    def get_args_schema(self):
        return FastSurferArgs

    def _run(
        self,
        t1w_image: str,
        subject_id: str,
        output_dir: str,
        fs_license_file: str | None = None,
        n_threads: int = 1,
        use_gpu: bool = False,
        runtime: str = "apptainer",
        container_image: str | None = None,
        dry_run: bool = False,
        extra_args: list[str] | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            input_path = Path(t1w_image).resolve(strict=True)
            output_root = Path(output_dir).resolve()
            output_root.mkdir(parents=True, exist_ok=True)

            license_file = _find_freesurfer_license(fs_license_file)
            if not dry_run and not license_file:
                return ToolResult(
                    status="error",
                    error="FastSurfer requires a FreeSurfer license file",
                    data={"subject_id": subject_id, "t1w_image": str(input_path)},
                )

            resolved_runtime = (
                "docker" if str(runtime).strip().lower() == "docker" else "apptainer"
            )
            image = _resolve_fastsurfer_image(
                runtime=resolved_runtime, container_image=container_image
            )

            mounted_t1 = f"/input/{input_path.name}"
            mounted_license = "/opt/freesurfer/license.txt"
            command = [
                "run_fastsurfer.sh",
                "--sid",
                subject_id,
                "--sd",
                "/out",
                "--t1",
                mounted_t1,
                "--threads",
                str(max(1, int(n_threads))),
                "--device",
                "cuda" if use_gpu else "cpu",
            ]
            if license_file:
                command.extend(["--fs_license", mounted_license])
            if extra_args:
                command.extend(extra_args)

            outputs = _fastsurfer_output_paths(str(output_root), subject_id)
            summary = {
                "backend": "fastsurfer_container",
                "subject_id": subject_id,
                "input_t1w": str(input_path),
                "runtime": resolved_runtime,
                "container_image": image,
                "has_fs_license": bool(license_file),
                "use_gpu": bool(use_gpu),
                "n_threads": max(1, int(n_threads)),
            }
            if dry_run:
                return ToolResult(
                    status="success",
                    data={
                        "dry_run": True,
                        "command": command,
                        "outputs": outputs,
                        "summary": summary,
                    },
                )

            mounts = [
                BindMount(
                    host_path=str(input_path),
                    container_path=mounted_t1,
                    read_only=True,
                ),
                BindMount(host_path=str(output_root), container_path="/out"),
            ]
            if license_file:
                mounts.append(
                    BindMount(
                        host_path=str(Path(license_file).resolve()),
                        container_path=mounted_license,
                        read_only=True,
                    )
                )

            request = ContainerRequest(
                runtime=resolved_runtime,
                image=image,
                command=command,
                workdir="/tmp" if resolved_runtime == "apptainer" else None,
                mounts=mounts,
                gpu_enabled=bool(use_gpu),
            )
            result = run_container(request)
            return ToolResult(
                status="success",
                data={
                    "command": result.get("command", command),
                    "stdout": result.get("stdout", ""),
                    "stderr": result.get("stderr", ""),
                    "runtime": {
                        "mode": result.get("mode", "local"),
                        "request": asdict(request),
                    },
                    "outputs": outputs,
                    "summary": summary,
                },
            )
        except Exception as e:
            logger.error(f"FastSurfer failed: {e}")
            return ToolResult(status="error", error=str(e))


class Suite2PArgs(BaseModel):
    """Arguments for Suite2p."""

    data_dir: str = Field(description="Input data directory")
    extra_args: list[str] | None = Field(
        default=None, description="Additional arguments"
    )


class RunSuite2PTool(NeuroToolWrapper):
    """Tool for running Suite2p calcium imaging pipeline."""

    def get_tool_name(self) -> str:
        return "run_suite2p"

    def get_tool_description(self) -> str:
        return "Run Suite2p calcium imaging analysis pipeline"

    def get_args_schema(self):
        return Suite2PArgs

    def _run(self, data_dir: str, extra_args: list[str] | None = None) -> ToolResult:
        try:
            cmd = ["suite2p", "--data", data_dir]
            if extra_args:
                cmd.extend(extra_args)
            run_subprocess(cmd)
            return ToolResult(status="success", data={"command": cmd})
        except Exception as e:
            logger.error(f"Suite2p failed: {e}")
            return ToolResult(status="error", error=str(e))


class SpikeSortArgs(BaseModel):
    """Arguments for spike sorting."""

    data_dir: str = Field(description="Input data directory")
    extra_args: list[str] | None = Field(
        default=None, description="Additional arguments"
    )


class RunSpikeSortingTool(NeuroToolWrapper):
    """Tool for running spike sorting pipeline."""

    def get_tool_name(self) -> str:
        return "run_spike_sorting"

    def get_tool_description(self) -> str:
        return "Run spike sorting pipeline for electrophysiology data"

    def get_args_schema(self):
        return SpikeSortArgs

    def _run(self, data_dir: str, extra_args: list[str] | None = None) -> ToolResult:
        try:
            cmd = ["spike_sort", data_dir]
            if extra_args:
                cmd.extend(extra_args)
            run_subprocess(cmd)
            return ToolResult(status="success", data={"command": cmd})
        except Exception as e:
            logger.error(f"Spike sorting failed: {e}")
            return ToolResult(status="error", error=str(e))


class PipelineTools:
    """Collection of preprocessing pipeline tools."""

    def __init__(self):
        self.run_fmriprep = RunFMRIPrepTool()
        self.run_fitlins_recipe = RunFitLinsRecipeTool()
        self.run_mriqc = RunMRIQCTool()
        self.run_smriprep = RunSMRIPrepTool()
        self.run_qsiprep = RunQSIPrepTool()
        self.run_fastsurfer = RunFastSurferTool()
        self.run_suite2p = RunSuite2PTool()
        self.run_spike_sorting = RunSpikeSortingTool()

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        return [
            self.run_fmriprep,
            self.run_fitlins_recipe,
            self.run_mriqc,
            self.run_smriprep,
            self.run_qsiprep,
            self.run_fastsurfer,
            self.run_suite2p,
            self.run_spike_sorting,
        ]

    def get_tool_by_name(self, name: str) -> NeuroToolWrapper | None:
        tool_map = {
            "run_fmriprep": self.run_fmriprep,
            "run_fitlins_recipe": self.run_fitlins_recipe,
            "run_mriqc": self.run_mriqc,
            "run_smriprep": self.run_smriprep,
            "run_qsiprep": self.run_qsiprep,
            "run_fastsurfer": self.run_fastsurfer,
            "run_suite2p": self.run_suite2p,
            "run_spike_sorting": self.run_spike_sorting,
        }
        return tool_map.get(name)
