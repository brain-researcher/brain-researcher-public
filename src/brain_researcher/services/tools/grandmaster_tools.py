"""Grand Master (intent-based) tool surface.

These tools provide stable, high-level IDs (e.g., ``compute_connectivity``)
while delegating work to existing implementations in this repository.

Design goals:
- Prefer thin wrappers (no wheel reinvention).
- Keep schemas simple and stable for evaluators/benchmarks.
- Return ToolResult consistently so both LangChain + internal executors work.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from brain_researcher.services.tools.dwi_tools import (  # noqa: F401
    BuildStructuralConnectomeArgs,
    BuildStructuralConnectomeTool,
    ExtractBundleStatsArgs,
    ExtractBundleStatsTool,
    ReconstructMicrostructureArgs,
    ReconstructMicrostructureTool,
    RunTractographyArgs,
    RunTractographyTool,
    _normalize_participant_labels,
    _resolve_qsiprep_dwi_inputs,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


def _as_tool_result(obj: Any) -> ToolResult:
    # Accept ToolResult from tool_base
    if isinstance(obj, ToolResult):
        return obj
    # Accept ToolResult-like objects (e.g., brain_researcher.services.tools.result.ToolResult)
    if hasattr(obj, "status") and hasattr(obj, "data"):
        return ToolResult(
            status=getattr(obj, "status", "success"),
            data=getattr(obj, "data", None),
            error=getattr(obj, "error", None),
            metadata=getattr(obj, "metadata", None),
        )
    if isinstance(obj, dict):
        try:
            return ToolResult(**obj)
        except Exception:
            status = obj.get("status", "success") if isinstance(obj, dict) else "error"
            return ToolResult(status=status, data={"raw": obj})
    return ToolResult(
        status="error",
        error="Unexpected tool result type",
        data={"raw": str(obj)},
    )


def _call_wrapper(wrapper: NeuroToolWrapper, params: dict[str, Any]) -> ToolResult:
    result = wrapper._run(**params)
    return _as_tool_result(result)


def _ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


# =============================================================================
# Layer 1: Infrastructure & Data Governance
# =============================================================================


class LoadDatasetArgs(BaseModel):
    bids_root: str | None = Field(default=None, description="Path to BIDS dataset root")
    bids_dir: str | None = Field(default=None, description="Alias for bids_root")
    subjects: list[str] | None = Field(
        default=None, description="Optional subject labels without 'sub-'"
    )
    sessions: list[str] | None = Field(
        default=None, description="Optional session labels without 'ses-'"
    )
    validate_bids: bool = Field(default=False, description="Run BIDS validation first")


class LoadDatasetTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "load_dataset"

    def get_tool_description(self) -> str:
        return "Load and summarize a BIDS dataset (subjects/sessions/tasks/modalities)."

    def get_args_schema(self):
        return LoadDatasetArgs

    def _run(
        self,
        bids_root: str | None = None,
        bids_dir: str | None = None,
        subjects: list[str] | None = None,
        sessions: list[str] | None = None,
        validate_bids: bool = False,
        **_: Any,
    ) -> ToolResult:
        try:
            root = bids_root or bids_dir
            if not root:
                return ToolResult(
                    status="error", error="bids_root/bids_dir is required", data={}
                )

            if validate_bids:
                from brain_researcher.services.tools.bids_tools import ValidateBIDSTool

                v = _call_wrapper(
                    ValidateBIDSTool(), {"bids_dir": root, "strict": True}
                )
                if v.status != "success":
                    return v

            from bids import BIDSLayout

            layout = BIDSLayout(root, validate=False, derivatives=True)
            dataset_subjects = layout.get_subjects() or []
            dataset_sessions = layout.get_sessions() or []
            tasks = sorted({t for t in (layout.get_tasks() or []) if t})
            datatypes = sorted({d for d in (layout.get_datatypes() or []) if d})

            filters: dict[str, Any] = {}
            if subjects:
                filters["subject"] = subjects
            if sessions:
                filters["session"] = sessions
            bold_runs = layout.get(
                return_type="file", datatype="func", suffix="bold", **filters
            )

            return ToolResult(
                status="success",
                data={
                    "bids_root": root,
                    "subjects": dataset_subjects,
                    "sessions": dataset_sessions,
                    "tasks": tasks,
                    "datatypes": datatypes,
                    "filtered": {
                        "subjects": subjects,
                        "sessions": sessions,
                        "n_func_bold_files": len(bold_runs),
                    },
                },
            )
        except Exception as exc:
            return ToolResult(
                status="error",
                error=str(exc),
                data={"bids_root": bids_root or bids_dir},
            )


class ValidateBIDSStructureArgs(BaseModel):
    bids_dir: str = Field(description="Path to BIDS dataset")
    strict: bool = Field(default=True, description="Fail on warnings")


class ValidateBIDSStructureTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "validate_bids_structure"

    def get_tool_description(self) -> str:
        return "Validate BIDS structure and metadata (thin wrapper over validate_bids)."

    def get_args_schema(self):
        return ValidateBIDSStructureArgs

    def _run(self, bids_dir: str, strict: bool = True, **_: Any) -> ToolResult:
        from brain_researcher.services.tools.bids_tools import ValidateBIDSTool

        return _call_wrapper(
            ValidateBIDSTool(), {"bids_dir": bids_dir, "strict": strict}
        )


class InspectDatasetStructureArgs(BaseModel):
    bids_root: str = Field(description="Path to BIDS dataset root")


class InspectDatasetStructureTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "inspect_dataset_structure"

    def get_tool_description(self) -> str:
        return "Inspect dataset structure (tasks, TR where available, file counts)."

    def get_args_schema(self):
        return InspectDatasetStructureArgs

    def _run(self, bids_root: str, **_: Any) -> ToolResult:
        try:
            from bids import BIDSLayout

            layout = BIDSLayout(bids_root, validate=False, derivatives=True)
            subjects = layout.get_subjects() or []
            sessions = layout.get_sessions() or []
            tasks = sorted({t for t in (layout.get_tasks() or []) if t})

            bold_files = layout.get(return_type="file", datatype="func", suffix="bold")
            t_r_values: list[float] = []
            for f in bold_files[:10]:
                try:
                    md = layout.get_metadata(f) or {}
                    tr = md.get("RepetitionTime")
                    if isinstance(tr, int | float):
                        t_r_values.append(float(tr))
                except Exception:
                    continue

            tr_summary = sorted({round(v, 6) for v in t_r_values})
            return ToolResult(
                status="success",
                data={
                    "bids_root": bids_root,
                    "n_subjects": len(subjects),
                    "n_sessions": len(sessions),
                    "tasks": tasks,
                    "n_func_bold_files": len(bold_files),
                    "observed_tr_s": tr_summary,
                },
            )
        except Exception as exc:
            return ToolResult(
                status="error", error=str(exc), data={"bids_root": bids_root}
            )


class RunBIDSAppArgs(BaseModel):
    app: Literal["fmriprep", "mriqc", "qsiprep", "smriprep", "fitlins"] = Field(
        description="BIDS App to run"
    )
    bids_dir: str = Field(description="Input BIDS directory")
    output_dir: str = Field(description="Output derivatives directory")
    analysis_level: str | None = Field(
        default=None, description="Optional analysis level override"
    )
    participant_label: list[str] | None = Field(
        default=None, description="Optional participant labels"
    )
    modalities: list[str] | None = Field(
        default=None, description="Optional MRIQC modalities"
    )
    work_dir: str | None = Field(default=None, description="Optional work directory")
    fs_license_file: str | None = Field(
        default=None, description="Optional FreeSurfer license file"
    )
    bids_filter_file: str | None = Field(
        default=None, description="Optional BIDS filter file"
    )
    output_spaces: list[str] | None = Field(
        default=None, description="Optional fMRIPrep output spaces"
    )
    n_cpus: int | None = Field(default=None, description="Optional CPU count")
    omp_nthreads: int | None = Field(
        default=None, description="Optional OpenMP thread count"
    )
    mem_mb: int | None = Field(default=None, description="Optional memory in MB")
    n_procs: int | None = Field(
        default=None, description="Optional MRIQC process count"
    )
    mem_gb: float | None = Field(
        default=None, description="Optional MRIQC memory in GB"
    )
    extra_args: list[str] | None = Field(default=None, description="Extra CLI args")
    dry_run: bool = Field(
        default=False,
        description="If true, return resolved command preview without executing.",
    )


class RunBIDSAppTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "run_bids_app"

    def get_tool_description(self) -> str:
        return "Run common BIDS Apps (fMRIPrep/MRIQC/QSIPrep/sMRIPrep/FitLins) using existing wrappers."

    def get_args_schema(self):
        return RunBIDSAppArgs

    def _run(
        self,
        app: str,
        bids_dir: str,
        output_dir: str,
        extra_args: list[str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        from brain_researcher.services.tools.params.mriqc import (
            build_mriqc_command,
            mriqc_from_payload,
        )
        from brain_researcher.services.tools.pipeline_tools import (
            RunFitLinsRecipeTool,
            RunFMRIPrepTool,
            RunMRIQCTool,
            RunQSIPrepTool,
            RunSMRIPrepTool,
            _build_smriprep_command,
            _resolve_bids_app_executable,
        )
        from brain_researcher.services.tools.pipelines import (
            build_fmriprep_command,
            build_qsiprep_command,
            fmriprep_from_payload,
            qsiprep_from_payload,
        )

        tool_by_app: dict[str, NeuroToolWrapper] = {
            "fmriprep": RunFMRIPrepTool(),
            "mriqc": RunMRIQCTool(),
            "qsiprep": RunQSIPrepTool(),
            "smriprep": RunSMRIPrepTool(),
            "fitlins": RunFitLinsRecipeTool(),
        }
        tool = tool_by_app.get(app)
        if not tool:
            return ToolResult(
                status="error", error=f"Unsupported app: {app}", data={"app": app}
            )

        dry_run = bool(kwargs.get("dry_run", False))

        if dry_run and app in {"fmriprep", "mriqc", "qsiprep", "smriprep"}:
            if app == "mriqc":
                payload = {
                    "bids_dir": bids_dir,
                    "output_dir": output_dir,
                    "analysis_level": str(kwargs.get("analysis_level", "participant")),
                    "participant_label": kwargs.get("participant_label") or [],
                    "modalities": kwargs.get("modalities") or [],
                    "work_dir": kwargs.get("work_dir"),
                    "bids_filter_file": kwargs.get("bids_filter_file"),
                    "n_procs": kwargs.get("n_procs"),
                    "mem_gb": kwargs.get("mem_gb"),
                    "extra_args": extra_args or kwargs.get("extra_args") or [],
                }
                params = mriqc_from_payload(payload)
                command = build_mriqc_command(params)
                if command:
                    command[0] = _resolve_bids_app_executable(
                        "mriqc", env_var="BR_MRIQC_BIN"
                    )
                return ToolResult(
                    status="success",
                    data={"app": app, "dry_run": True, "command": command},
                )

            if app == "fmriprep":
                payload = {
                    "bids_dir": bids_dir,
                    "output_dir": output_dir,
                    "analysis_level": str(kwargs.get("analysis_level", "participant")),
                    "participant_label": kwargs.get("participant_label") or [],
                    "work_dir": kwargs.get("work_dir"),
                    "fs_license_file": kwargs.get("fs_license_file"),
                    "output_spaces": kwargs.get("output_spaces") or [],
                    "n_cpus": kwargs.get("n_cpus"),
                    "omp_nthreads": kwargs.get("omp_nthreads"),
                    "mem_mb": kwargs.get("mem_mb"),
                    "bids_filter_file": kwargs.get("bids_filter_file"),
                    "extra_args": extra_args or kwargs.get("extra_args") or [],
                }
                params = fmriprep_from_payload(payload)
                command = build_fmriprep_command(params)
                if command:
                    command[0] = _resolve_bids_app_executable(
                        "fmriprep", env_var="BR_FMRIPREP_BIN"
                    )
                return ToolResult(
                    status="success",
                    data={"app": app, "dry_run": True, "command": command},
                )

            if app == "qsiprep":
                payload = {
                    "bids_dir": bids_dir,
                    "output_dir": output_dir,
                    "analysis_level": str(kwargs.get("analysis_level", "participant")),
                    "participant_label": kwargs.get("participant_label") or [],
                    "work_dir": kwargs.get("work_dir"),
                    "fs_license_file": kwargs.get("fs_license_file"),
                    "bids_filter_file": kwargs.get("bids_filter_file"),
                    "denoise_method": kwargs.get("denoise_method"),
                    "distortion_correction": kwargs.get("distortion_correction"),
                    "hmc_model": kwargs.get("hmc_model"),
                    "eddy_config": kwargs.get("eddy_config"),
                    "b0_threshold": kwargs.get("b0_threshold"),
                    "output_resolution": kwargs.get("output_resolution"),
                    "skip_bids_validation": bool(
                        kwargs.get("skip_bids_validation", False)
                    ),
                    "n_cpus": kwargs.get("n_cpus"),
                    "omp_nthreads": kwargs.get("omp_nthreads"),
                    "mem_mb": kwargs.get("mem_mb"),
                    "extra_args": extra_args or kwargs.get("extra_args") or [],
                }
                params = qsiprep_from_payload(payload)
                command = build_qsiprep_command(params)
                if command:
                    command[0] = _resolve_bids_app_executable(
                        "qsiprep", env_var="BR_QSIPREP_BIN"
                    )
                return ToolResult(
                    status="success",
                    data={"app": app, "dry_run": True, "command": command},
                )

            if app == "smriprep":
                executable = _resolve_bids_app_executable(
                    "smriprep", env_var="BR_SMRIPREP_BIN"
                )
                command = _build_smriprep_command(
                    executable=executable,
                    bids_dir=bids_dir,
                    output_dir=output_dir,
                    participant_label=kwargs.get("participant_label"),
                    work_dir=kwargs.get("work_dir"),
                    fs_license_file=kwargs.get("fs_license_file"),
                    output_spaces=kwargs.get("output_spaces"),
                    skip_bids_validation=bool(
                        kwargs.get("skip_bids_validation", False)
                    ),
                    bids_filter_file=kwargs.get("bids_filter_file"),
                    n_cpus=kwargs.get("n_cpus"),
                    omp_nthreads=kwargs.get("omp_nthreads"),
                    mem_mb=kwargs.get("mem_mb"),
                    extra_args=extra_args or kwargs.get("extra_args"),
                )
                return ToolResult(
                    status="success",
                    data={"app": app, "dry_run": True, "command": command},
                )

            executable_name = {
                "fmriprep": "fmriprep",
                "qsiprep": "qsiprep",
                "smriprep": "smriprep",
            }.get(app, app)
            executable = _resolve_bids_app_executable(
                executable_name,
                env_var={
                    "fmriprep": "BR_FMRIPREP_BIN",
                    "qsiprep": "BR_QSIPREP_BIN",
                    "smriprep": "BR_SMRIPREP_BIN",
                }.get(app),
            )
            command = [executable, bids_dir, output_dir, "participant"]
            if extra_args:
                command.extend(extra_args)
            return ToolResult(
                status="success",
                data={"app": app, "dry_run": True, "command": command},
            )

        # FitLins needs additional context (model/derivatives/runtime). Keep the
        # wrapper permissive so workflows can pass these through without
        # depending on a separate tool id.
        if app == "fitlins":
            params = {
                "bids_dir": bids_dir,
                "output_dir": output_dir,
                "analysis_level": kwargs.get("analysis_level", "dataset"),
                "model": kwargs.get("model"),
                "participant_label": kwargs.get("participant_label"),
                "derivatives_dir": (
                    kwargs.get("derivatives_dir")
                    or kwargs.get("derivatives")
                    or kwargs.get("fmriprep_dir")
                ),
                "work_dir": kwargs.get("work_dir"),
                "reports_only": bool(kwargs.get("reports_only", False)),
                "dry_run": dry_run,
                "extra_args": extra_args or kwargs.get("extra_args") or [],
                "runtime": kwargs.get("runtime")
                or kwargs.get("container_type")
                or "apptainer",
                "container_image": kwargs.get("container_image") or kwargs.get("image"),
            }
        elif app in {"fmriprep", "mriqc"}:
            params = {
                "bids_dir": bids_dir,
                "output_dir": output_dir,
                "extra_args": extra_args or [],
            }
            for key in (
                "analysis_level",
                "participant_label",
                "modalities",
                "work_dir",
                "fs_license_file",
                "bids_filter_file",
                "output_spaces",
                "n_cpus",
                "omp_nthreads",
                "mem_mb",
                "n_procs",
                "mem_gb",
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
                "session_id",
                "run_id",
                "dsname",
                "float32",
                "clean_workdir",
                "verbose_reports",
                "no_sub",
                "random_seed",
            ):
                value = kwargs.get(key)
                if value is not None:
                    params[key] = value
        elif app in {"qsiprep", "smriprep"}:
            params = {
                "bids_dir": bids_dir,
                "output_dir": output_dir,
                "extra_args": extra_args or [],
            }
            for key in (
                "analysis_level",
                "participant_label",
                "work_dir",
                "fs_license_file",
                "output_spaces",
                "skip_bids_validation",
                "bids_filter_file",
                "denoise_method",
                "distortion_correction",
                "hmc_model",
                "eddy_config",
                "b0_threshold",
                "output_resolution",
                "n_cpus",
                "omp_nthreads",
                "mem_mb",
            ):
                value = kwargs.get(key)
                if value is not None:
                    params[key] = value
        else:
            params = {
                "bids_dir": bids_dir,
                "output_dir": output_dir,
                "extra_args": extra_args or [],
            }

        return _call_wrapper(tool, params)


class ConvertDicomToBIDSArgs(BaseModel):
    dicom_dir: str = Field(description="Path to DICOM directory")
    bids_dir: str = Field(description="Output BIDS directory")
    heuristic: str = Field(description="Heuristic Python file for HeuDiConv")


class ConvertDicomToBIDSTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "convert_dicom_to_bids"

    def get_tool_description(self) -> str:
        return "Convert DICOMs to BIDS (wrapper over heudiconv_convert)."

    def get_args_schema(self):
        return ConvertDicomToBIDSArgs

    def _run(
        self, dicom_dir: str, bids_dir: str, heuristic: str, **_: Any
    ) -> ToolResult:
        from brain_researcher.services.tools.bids_tools import HeudiconvConvertTool

        return _call_wrapper(
            HeudiconvConvertTool(),
            {"dicom_dir": dicom_dir, "bids_dir": bids_dir, "heuristic": heuristic},
        )


class RunMRIQCWorkflowArgs(BaseModel):
    bids_dir: str = Field(description="Input BIDS directory")
    output_dir: str = Field(description="Output directory")
    analysis_level: str = Field(
        default="participant",
        description="Analysis level (participant/group). Note: this tool currently previews the command.",
    )
    participant_label: list[str] | None = Field(
        default=None, description="Optional participant labels to include"
    )
    modalities: list[str] | None = Field(
        default=None, description="Optional modalities (e.g., ['bold','T1w'])"
    )
    extra_args: list[str] | None = Field(default=None, description="Extra CLI args")


class RunMRIQCWorkflowTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "run_mriqc_workflow"

    def get_tool_description(self) -> str:
        return "Run MRIQC (wrapper over run_mriqc)."

    def get_args_schema(self):
        return RunMRIQCWorkflowArgs

    def _run(
        self,
        bids_dir: str,
        output_dir: str,
        analysis_level: str = "participant",
        participant_label: list[str] | None = None,
        modalities: list[str] | None = None,
        extra_args: list[str] | None = None,
        **_: Any,
    ) -> ToolResult:
        # Intentionally a preview: we avoid hard runtime/container deps in the
        # Grandmaster workflow layer. Full MRIQC execution can still be done via
        # pipeline tools when an environment provides the `mriqc` binary.
        from brain_researcher.services.tools.grandmaster.runtime_functions import (
            mriqc_command_preview,
        )

        return mriqc_command_preview(
            bids_dir=bids_dir,
            output_dir=output_dir,
            analysis_level=analysis_level,
            participant_label=participant_label,
            modalities=modalities,
            extra_args=extra_args,
        )


class GetQCTableArgs(BaseModel):
    qc_tsv: str | None = Field(
        default=None,
        description="Path to an existing QC TSV (MRIQC/XCP-D/custom) to normalize into a CSV.",
    )
    mriqc_dir: str | None = Field(
        default=None,
        description="MRIQC output directory (derivatives/mriqc). If provided, the tool will look for group TSVs inside.",
    )
    modality: Literal["bold", "T1w"] = Field(
        default="bold", description="MRIQC group table type"
    )
    output_file: str | None = Field(
        default=None, description="Optional output CSV/TSV path"
    )


class GetQCTableTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "get_qc_table"

    def get_tool_description(self) -> str:
        return "Load MRIQC group TSV into a table for downstream filtering."

    def get_args_schema(self):
        return GetQCTableArgs

    def _run(
        self,
        qc_tsv: str | None = None,
        mriqc_dir: str | None = None,
        modality: str = "bold",
        output_file: str | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            import pandas as pd

            if qc_tsv:
                path = Path(qc_tsv)
                if not path.exists():
                    return ToolResult(
                        status="error", error=f"qc_tsv not found: {qc_tsv}", data={}
                    )
                df = pd.read_csv(path, sep="\t")
                out_path = (
                    Path(output_file) if output_file else path.with_suffix(".csv")
                )
                out_path.parent.mkdir(parents=True, exist_ok=True)
                df.to_csv(out_path, index=False)
                return ToolResult(
                    status="success",
                    data={
                        "outputs": {"qc_table": str(out_path), "source": str(path)},
                        "summary": {"rows": int(df.shape[0]), "cols": int(df.shape[1])},
                        "columns": list(df.columns),
                    },
                )

            if not mriqc_dir:
                return ToolResult(
                    status="error",
                    error="Provide either qc_tsv or mriqc_dir",
                    data={},
                )

            root = Path(mriqc_dir)
            candidates = [
                root / f"group_{modality}.tsv",
                root / f"group_{modality}.csv",
                root / "group_bold.tsv",
                root / "group_T1w.tsv",
            ]
            table_path = next((p for p in candidates if p.exists()), None)
            if not table_path:
                return ToolResult(
                    status="error",
                    error="MRIQC group table not found",
                    data={
                        "mriqc_dir": mriqc_dir,
                        "checked": [str(p) for p in candidates],
                    },
                )

            df = pd.read_csv(
                table_path, sep="\t" if table_path.suffix == ".tsv" else ","
            )
            out_path = (
                Path(output_file) if output_file else root / f"qc_table_{modality}.csv"
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(out_path, index=False)
            return ToolResult(
                status="success",
                data={
                    "outputs": {"qc_table": str(out_path), "source": str(table_path)},
                    "summary": {"rows": int(df.shape[0]), "cols": int(df.shape[1])},
                    "columns": list(df.columns),
                },
            )
        except Exception as exc:
            return ToolResult(
                status="error", error=str(exc), data={"mriqc_dir": mriqc_dir}
            )


class DetectOutliersArgs(BaseModel):
    qc_table: str = Field(description="Path to QC table (CSV/TSV) from get_qc_table")
    metric: str = Field(
        default="fd_mean", description="Column name to use for outlier detection"
    )
    z_threshold: float = Field(
        default=3.0, description="Z-score threshold for outlier flagging"
    )
    output_file: str | None = Field(default=None, description="Output CSV of outliers")


class DetectOutliersTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "detect_outliers"

    def get_tool_description(self) -> str:
        return "Detect outlier subjects/runs from QC metrics (MRIQC-style tables)."

    def get_args_schema(self):
        return DetectOutliersArgs

    def _run(
        self,
        qc_table: str,
        metric: str = "fd_mean",
        z_threshold: float = 3.0,
        output_file: str | None = None,
        **_: Any,
    ) -> ToolResult:
        from brain_researcher.services.tools.grandmaster.runtime_functions import (
            detect_outliers_from_qc_table,
        )

        return detect_outliers_from_qc_table(
            qc_table=qc_table,
            metric=metric,
            z_threshold=z_threshold,
            output_file=output_file,
        )


class StandardizeConfoundsArgs(BaseModel):
    confounds_file: str = Field(description="fMRIPrep confounds TSV/CSV path")
    strategy: Literal["minimal", "motion", "compcor", "custom"] = Field(
        default="minimal", description="Confound selection preset"
    )
    custom_patterns: list[str] | None = Field(
        default=None, description="Column name substrings to keep (strategy=custom)"
    )
    output_file: str | None = Field(default=None, description="Output TSV path")


class StandardizeConfoundsTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "standardize_confounds"

    def get_tool_description(self) -> str:
        return "Select and export a standardized confounds table for denoising."

    def get_args_schema(self):
        return StandardizeConfoundsArgs

    def _run(
        self,
        confounds_file: str,
        strategy: str = "minimal",
        custom_patterns: list[str] | None = None,
        output_file: str | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            import pandas as pd

            path = Path(confounds_file)
            df = pd.read_csv(path, sep="\t" if path.suffix == ".tsv" else ",")
            cols = list(df.columns)
            keep: list[str] = []

            def _match_any(col: str, patterns: list[str]) -> bool:
                cl = col.lower()
                return any(p.lower() in cl for p in patterns)

            if strategy == "minimal":
                patterns = ["trans_", "rot_"]
                keep = [c for c in cols if _match_any(c, patterns)][:6]
            elif strategy == "motion":
                patterns = ["trans_", "rot_", "framewise_displacement", "dvars"]
                keep = [c for c in cols if _match_any(c, patterns)]
            elif strategy == "compcor":
                patterns = ["a_comp_cor", "t_comp_cor", "cosine", "trans_", "rot_"]
                keep = [c for c in cols if _match_any(c, patterns)]
            elif strategy == "custom":
                patterns = custom_patterns or []
                if not patterns:
                    return ToolResult(
                        status="error",
                        error="custom_patterns required for strategy=custom",
                    )
                keep = [c for c in cols if _match_any(c, patterns)]
            else:
                return ToolResult(status="error", error=f"Unknown strategy: {strategy}")

            kept_df = df[keep].copy() if keep else df.iloc[:, :0].copy()
            out_path = (
                Path(output_file)
                if output_file
                else path.with_name("confounds_standardized.tsv")
            )
            kept_df.to_csv(out_path, sep="\t", index=False)
            return ToolResult(
                status="success",
                data={
                    "outputs": {"confounds_standardized": str(out_path)},
                    "summary": {"n_cols": int(kept_df.shape[1]), "strategy": strategy},
                    "columns": keep,
                },
            )
        except Exception as exc:
            return ToolResult(
                status="error", error=str(exc), data={"confounds_file": confounds_file}
            )


class ResampleImageArgs(BaseModel):
    input_image: str = Field(description="Input NIfTI image")
    reference_image: str = Field(
        description="Reference NIfTI image (target space/shape/affine)"
    )
    interpolation: Literal["continuous", "linear", "nearest"] = Field(
        default="continuous", description="Interpolation mode"
    )
    output_file: str | None = Field(default=None, description="Output NIfTI path")


class ResampleImageTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "resample_image"

    def get_tool_description(self) -> str:
        return "Resample an image into the space of a reference image (nilearn)."

    def get_args_schema(self):
        return ResampleImageArgs

    def _run(
        self,
        input_image: str,
        reference_image: str,
        interpolation: str = "continuous",
        output_file: str | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            import nibabel as nib
            from nilearn.image import resample_to_img

            out_path = (
                Path(output_file) if output_file else Path.cwd() / "resampled.nii.gz"
            )
            img = resample_to_img(
                source_img=input_image,
                target_img=reference_image,
                interpolation=interpolation,
            )
            nib.save(img, str(out_path))
            return ToolResult(
                status="success", data={"outputs": {"resampled_image": str(out_path)}}
            )
        except Exception as exc:
            return ToolResult(
                status="error", error=str(exc), data={"input_image": input_image}
            )


# =============================================================================
# Layer 2: Core fMRI Analysis
# =============================================================================


class ComputeConnectivityArgs(BaseModel):
    timeseries: str = Field(description="Path to ROI timeseries (.npy) or CSV")
    kind: Literal[
        "correlation", "partial correlation", "tangent", "covariance", "precision"
    ] = Field(default="correlation", description="Connectivity estimator")
    fisher_z: bool = Field(
        default=True, description="Apply Fisher z-transform (correlations)"
    )
    output_file: str | None = Field(
        default=None, description="Output .npy path for connectivity matrix"
    )


class ComputeConnectivityTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "compute_connectivity"

    def get_tool_description(self) -> str:
        return "Compute functional connectivity matrix from ROI time series."

    def get_args_schema(self):
        return ComputeConnectivityArgs

    def _run(
        self,
        timeseries: str,
        kind: str = "correlation",
        fisher_z: bool = True,
        output_file: str | None = None,
        **_: Any,
    ) -> ToolResult:
        from brain_researcher.services.tools.nilearn_connectivity import (
            ConnectivityMatrixTool,
        )

        payload = {
            "timeseries": timeseries,
            "kind": kind,
            "fisher_z": fisher_z,
            "output_file": output_file or str(Path.cwd() / "connectivity.npy"),
        }
        return _call_wrapper(ConnectivityMatrixTool(), payload)


class AnalyzeGraphTopologyArgs(BaseModel):
    connectivity_file: str = Field(description="Connectivity matrix .npy/.csv file")
    output_dir: str | None = Field(default=None, description="Output directory")


class AnalyzeGraphTopologyTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "analyze_graph_topology"

    def get_tool_description(self) -> str:
        return "Compute graph metrics from a connectivity matrix (wrapper over graph_theory)."

    def get_args_schema(self):
        return AnalyzeGraphTopologyArgs

    def _run(
        self, connectivity_file: str, output_dir: str | None = None, **_: Any
    ) -> ToolResult:
        from brain_researcher.services.tools.graph_theory_tool import GraphTheoryTool

        return _call_wrapper(
            GraphTheoryTool(),
            {"connectivity_file": connectivity_file, "output_dir": output_dir},
        )


class RunGLMFirstLevelArgs(BaseModel):
    img: str = Field(description="Path to 4D BOLD NIfTI")
    events: str | None = Field(default=None, description="Path to events.tsv or 'auto'")
    t_r: float | None = Field(default=None, description="TR in seconds")
    contrasts: dict[str, list[float]] | None = Field(
        default=None, description="Contrast definitions"
    )
    output_dir: str | None = Field(default=None, description="Output directory")


class RunGLMFirstLevelTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "run_glm_first_level"

    def get_tool_description(self) -> str:
        return "First-level GLM (wrapper over glm_first_level)."

    def get_args_schema(self):
        return RunGLMFirstLevelArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        from brain_researcher.services.tools.nilearn_glm import GLMFirstLevelTool

        return _call_wrapper(GLMFirstLevelTool(), kwargs)


class RunGLMSecondLevelArgs(BaseModel):
    contrast_maps: list[str] = Field(description="List of first-level contrast maps")
    design_matrix: str | dict | None = Field(
        default=None, description="Design matrix or path"
    )
    contrast: str | list[float] | None = Field(
        default=None, description="Second-level contrast"
    )
    output_dir: str | None = Field(default=None, description="Output directory")


class RunGLMSecondLevelTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "run_glm_second_level"

    def get_tool_description(self) -> str:
        return "Second-level GLM (wrapper over glm_second_level)."

    def get_args_schema(self):
        return RunGLMSecondLevelArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        from brain_researcher.services.tools.nilearn_glm import SecondLevelGLMTool

        return _call_wrapper(SecondLevelGLMTool(), kwargs)


class FilterEventsArgs(BaseModel):
    events_tsv: str = Field(description="Path to events.tsv")
    query: str = Field(description="pandas.DataFrame.query() expression")
    output_file: str | None = Field(default=None, description="Output TSV path")


class FilterEventsTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "filter_events"

    def get_tool_description(self) -> str:
        return "Filter a BIDS events.tsv file using a pandas query expression."

    def get_args_schema(self):
        return FilterEventsArgs

    def _run(
        self, events_tsv: str, query: str, output_file: str | None = None, **_: Any
    ) -> ToolResult:
        try:
            import pandas as pd

            path = Path(events_tsv)
            df = pd.read_csv(path, sep="\t")
            filtered = df.query(query)
            out_path = (
                Path(output_file)
                if output_file
                else path.with_name(path.stem + "_filtered.tsv")
            )
            filtered.to_csv(out_path, sep="\t", index=False)
            return ToolResult(
                status="success",
                data={
                    "outputs": {"events_filtered": str(out_path)},
                    "summary": {
                        "rows_in": int(df.shape[0]),
                        "rows_out": int(filtered.shape[0]),
                    },
                },
            )
        except Exception as exc:
            return ToolResult(
                status="error",
                error=str(exc),
                data={"events_tsv": events_tsv, "query": query},
            )


class ExtractRoiValuesArgs(BaseModel):
    stat_map: str = Field(description="Path to 3D stat/contrast map")
    atlas_name: str = Field(
        default="Schaefer2018_200", description="Atlas identifier (or local path)"
    )
    output_dir: str | None = Field(default=None, description="Output directory")


class ExtractRoiValuesTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "extract_roi_values"

    def get_tool_description(self) -> str:
        return "Extract mean ROI values from a 3D stat map using an atlas."

    def get_args_schema(self):
        return ExtractRoiValuesArgs

    def _run(
        self,
        stat_map: str,
        atlas_name: str = "Schaefer2018_200",
        output_dir: str | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            out_root = _ensure_dir(output_dir or (Path.cwd() / "extract_roi_values"))
            atlas_path = atlas_name
            labels_tsv: str | None = None
            if not Path(atlas_name).exists():
                from brain_researcher.services.tools.fetch_atlas_tool import (
                    FetchAtlasTool,
                )

                atlas_res = _call_wrapper(
                    FetchAtlasTool(),
                    {"atlas_name": atlas_name, "output_dir": str(out_root)},
                )
                if atlas_res.status != "success":
                    return atlas_res
                atlas_path = atlas_res.data["outputs"]["atlas_path"]  # type: ignore[index]
                labels_tsv = atlas_res.data["outputs"].get("labels_tsv")  # type: ignore[index]

            import numpy as np
            import pandas as pd
            from nilearn.maskers import NiftiLabelsMasker

            masker = NiftiLabelsMasker(
                labels_img=atlas_path, standardize=False, detrend=False
            )
            values = masker.fit_transform(stat_map)
            vec = np.asarray(values).reshape(-1)

            labels: list[str] = []
            if labels_tsv and Path(labels_tsv).exists():
                labels = Path(labels_tsv).read_text(encoding="utf-8").splitlines()
            else:
                labels = [f"roi_{i:04d}" for i in range(vec.shape[0])]

            df = pd.DataFrame({"roi": labels[: vec.shape[0]], "value": vec.tolist()})
            out_tsv = out_root / "roi_values.tsv"
            df.to_csv(out_tsv, sep="\t", index=False)
            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "roi_values_tsv": str(out_tsv),
                        "atlas_path": str(atlas_path),
                    },
                    "summary": {"n_rois": int(df.shape[0])},
                },
            )
        except Exception as exc:
            return ToolResult(
                status="error", error=str(exc), data={"stat_map": stat_map}
            )


class PPIAnalyzerArgs(BaseModel):
    img: str | list[str] = Field(description="4D BOLD NIfTI (or list of runs)")
    events: str | list[str] = Field(description="Events TSV (or list aligned to img)")
    t_r: float = Field(description="Repetition time (seconds)")
    seed_coords: list[float] | None = Field(
        default=None, description="Seed coordinates (x, y, z)"
    )
    seed_mask: str | None = Field(default=None, description="Seed mask NIfTI")
    confounds: str | list[str] | None = Field(
        default=None, description="Confounds TSV (optional)"
    )
    output_dir: str | None = Field(default=None, description="Output directory")


class PPIAnalyzerTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "ppi_analyzer"

    def get_tool_description(self) -> str:
        return "Compute a basic PPI model using nilearn GLM."

    def get_args_schema(self):
        return PPIAnalyzerArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        try:
            import nibabel as nib
            import numpy as np
            import pandas as pd
            from nilearn.glm.first_level import (
                FirstLevelModel,
                make_first_level_design_matrix,
            )
            from nilearn.maskers import NiftiMasker, NiftiSpheresMasker
        except ImportError as exc:
            return ToolResult(
                status="error", error=f"nilearn not available: {exc}", data={}
            )

        args = PPIAnalyzerArgs(**kwargs)
        out_dir = _ensure_dir(args.output_dir or (Path.cwd() / "ppi"))

        imgs = args.img if isinstance(args.img, list) else [args.img]
        events_list = (
            args.events if isinstance(args.events, list) else [args.events] * len(imgs)
        )
        conf_list = (
            args.confounds
            if isinstance(args.confounds, list)
            else (
                [args.confounds] * len(imgs)
                if args.confounds is not None
                else [None] * len(imgs)
            )
        )

        if len(events_list) != len(imgs):
            return ToolResult(
                status="error", error="events list must match img list", data={}
            )
        if len(conf_list) != len(imgs):
            return ToolResult(
                status="error", error="confounds list must match img list", data={}
            )

        zmap_paths: list[str] = []
        summaries: list[dict[str, Any]] = []

        ref_img = None
        for idx, (img_path, events_path, conf_path) in enumerate(
            zip(imgs, events_list, conf_list, strict=False)
        ):
            events = pd.read_csv(events_path, sep="\t")
            if "trial_type" in events.columns:
                cond = str(events["trial_type"].dropna().unique()[0])
                events = events[events["trial_type"] == cond]
            else:
                cond = "stim"

            img = nib.load(img_path)
            n_scans = img.shape[-1]
            frame_times = np.arange(n_scans) * float(args.t_r)

            try:
                design = make_first_level_design_matrix(
                    frame_times,
                    events,
                    hrf_model="spm",
                    drift_model="cosine",
                    high_pass=0.01,
                )
                psych = design[cond].values
            except Exception:
                psych = np.zeros(n_scans)

            if args.seed_mask:
                masker = NiftiMasker(
                    mask_img=args.seed_mask,
                    standardize="zscore_sample",
                )
            else:
                if not args.seed_coords:
                    return ToolResult(
                        status="error",
                        error="seed_coords or seed_mask required",
                        data={},
                    )
                masker = NiftiSpheresMasker(
                    [args.seed_coords],
                    radius=6.0,
                    standardize="zscore_sample",
                )
            # Fit per-run to avoid affine mismatch between sessions
            phys = masker.fit_transform(img_path).ravel()

            psych = psych[: len(phys)]
            phys = phys[: len(psych)]
            psych = psych - psych.mean()
            phys = phys - phys.mean()
            ppi = psych * phys

            conf_df = None
            if conf_path:
                try:
                    conf_df = pd.read_csv(conf_path, sep="\t")
                    conf_df = conf_df.select_dtypes(include=[np.number]).fillna(0.0)
                    conf_df = conf_df.iloc[: len(psych)]
                except Exception:
                    conf_df = None

            design_mat = pd.DataFrame(
                {"psych": psych, "phys": phys, "ppi": ppi},
                index=frame_times[: len(ppi)],
            )
            if conf_df is not None and not conf_df.empty:
                design_mat = pd.concat(
                    [design_mat, conf_df.reset_index(drop=True)], axis=1
                )

            model = FirstLevelModel(t_r=args.t_r, noise_model="ar1", standardize=False)
            model = model.fit(img_path, design_matrices=design_mat)

            contrast = np.zeros(design_mat.shape[1])
            ppi_idx = list(design_mat.columns).index("ppi")
            contrast[ppi_idx] = 1.0
            zmap = model.compute_contrast(contrast, output_type="z_score")
            if ref_img is None:
                ref_img = zmap
            else:
                try:
                    from nilearn import image as nl_image

                    zmap = nl_image.resample_to_img(
                        zmap, ref_img, interpolation="linear"
                    )
                except Exception:
                    pass

            zmap_path = out_dir / f"ppi_zmap_{idx:02d}.nii.gz"
            zmap.to_filename(str(zmap_path))
            zmap_paths.append(str(zmap_path))

            design_path = out_dir / f"ppi_design_matrix_{idx:02d}.tsv"
            design_mat.to_csv(design_path, sep="\t", index=False)

            summaries.append(
                {
                    "condition": cond,
                    "n_scans": int(n_scans),
                    "seed": args.seed_coords or args.seed_mask,
                }
            )

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "contrast_maps": zmap_paths,
                    "design_matrices": [
                        str(out_dir / f"ppi_design_matrix_{i:02d}.tsv")
                        for i in range(len(zmap_paths))
                    ],
                },
                "summary": {"n_runs": len(zmap_paths), "runs": summaries},
            },
        )


class GetAtlasArgs(BaseModel):
    atlas_name: str = Field(default="Schaefer2018_200", description="Atlas identifier")
    output_dir: str | None = Field(default=None, description="Output directory")


class GetAtlasTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "get_atlas"

    def get_tool_description(self) -> str:
        return "Fetch an atlas (wrapper over fetch_atlas)."

    def get_args_schema(self):
        return GetAtlasArgs

    def _run(
        self,
        atlas_name: str = "Schaefer2018_200",
        output_dir: str | None = None,
        **_: Any,
    ) -> ToolResult:
        from brain_researcher.services.tools.fetch_atlas_tool import FetchAtlasTool

        return _call_wrapper(
            FetchAtlasTool(), {"atlas_name": atlas_name, "output_dir": output_dir}
        )


# =============================================================================
# Layer 3: Modalities (thin wrappers / delegations)
# =============================================================================


class PreprocessEEGArgs(BaseModel):
    raw_eeg: str = Field(description="Raw EEG recording path (.fif/.edf/.bdf)")
    montage_def: str = Field(description="Montage name or montage file path")
    highpass_hz: float = Field(default=1.0, description="High-pass cutoff (Hz)")
    lowpass_hz: float = Field(default=40.0, description="Low-pass cutoff (Hz)")
    reference: str = Field(default="average", description="EEG reference")
    output_dir: str | None = Field(default=None, description="Output directory")


class PreprocessEEGTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "preprocess_eeg"

    def get_tool_description(self) -> str:
        return "Preprocess EEG (wrapper over eeg_preprocess)."

    def get_args_schema(self):
        return PreprocessEEGArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        from brain_researcher.services.tools.eeg_preprocess_tool import (
            EEGPreprocessTool,
        )

        return _call_wrapper(EEGPreprocessTool(), kwargs)


class SegmentLesionArgs(BaseModel):
    t1: str = Field(description="T1w image path")
    output_dir: str | None = Field(default=None, description="Output directory")


class SegmentLesionTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "segment_lesion"

    def get_tool_description(self) -> str:
        return "Segment lesion (wrapper over lesion_detection)."

    def get_args_schema(self):
        return SegmentLesionArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        from brain_researcher.services.tools.lesion_detection_tool import (
            LesionDetectionTool,
        )

        params = dict(kwargs)
        # Normalize argument naming to match lesion_detection_tool
        if "t1" in params and "t1_image" not in params:
            params["t1_image"] = params.pop("t1")
        return _call_wrapper(LesionDetectionTool(), params)


# =============================================================================
# Layer 4/5: Statistics, ML, Knowledge
# =============================================================================


class HarmonizeDataArgs(BaseModel):
    features: str = Field(
        description="CSV/TSV/NPY features file (rows=samples, cols=features)"
    )
    batch: list[int] | str = Field(
        description="Batch labels or path to 1D labels file (.npy/.csv/.tsv)"
    )
    covars: str | None = Field(
        default=None, description="Optional covariates table (rows=samples)"
    )
    output_file: str = Field(description="Output CSV path for harmonized features")
    method: str = Field(default="combat", description="Harmonization method (combat)")
    report_file: str | None = Field(
        default=None, description="Optional JSON report path"
    )
    provenance_file: str | None = Field(
        default=None, description="Optional provenance JSON path"
    )


class HarmonizeDataTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "harmonize_data"

    def get_tool_description(self) -> str:
        return "Harmonize data across sites/scanners (wrapper over data_harmonization)."

    def get_args_schema(self):
        return HarmonizeDataArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        try:
            import numpy as np
            import pandas as pd
        except Exception as exc:  # pragma: no cover
            return ToolResult(
                status="error", error=f"Missing dependency: {exc}", data={}
            )

        params = dict(kwargs)
        if "backend" in params and "method" not in params:
            params["method"] = params.pop("backend")
        args = HarmonizeDataArgs(**params)
        features_path = Path(args.features).expanduser().resolve()
        if not features_path.exists():
            return ToolResult(
                status="error", error=f"features not found: {features_path}", data={}
            )
        method = str(args.method or "combat").strip().lower()
        method_aliases = {
            "combat_like": "combat",
            "combat": "combat",
            "deepresbat": "deepresbat_external",
            "deepresbat_external": "deepresbat_external",
        }
        method = method_aliases.get(method, method)

        out_path = Path(args.output_file).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report_path = (
            Path(args.report_file).expanduser().resolve()
            if args.report_file
            else out_path.with_name("harmonization_report.json")
        )
        provenance_path = (
            Path(args.provenance_file).expanduser().resolve()
            if args.provenance_file
            else out_path.with_name("provenance.json")
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        provenance_path.parent.mkdir(parents=True, exist_ok=True)

        def _load_batch(value: list[int] | str) -> np.ndarray:
            if isinstance(value, list):
                return np.asarray(value, dtype=int)
            p = Path(value).expanduser().resolve()
            if not p.exists():
                raise FileNotFoundError(f"batch file not found: {p}")
            if p.suffix.lower() in {".npy", ".npz"}:
                arr = np.load(p)
                if hasattr(arr, "files"):
                    arr = arr[arr.files[0]]
                return np.asarray(arr, dtype=int).ravel()
            sep = "\t" if p.suffix.lower() == ".tsv" else ","
            df = pd.read_csv(p, sep=sep)
            if "batch" in df.columns:
                return np.asarray(df["batch"], dtype=int).ravel()
            return np.asarray(df.iloc[:, 0], dtype=int).ravel()

        def _load_covars(path: str | None, n: int) -> np.ndarray | None:
            if not path:
                return None
            p = Path(path).expanduser().resolve()
            if not p.exists():
                raise FileNotFoundError(f"covars not found: {p}")
            sep = "\t" if p.suffix.lower() == ".tsv" else ","
            df = pd.read_csv(p, sep=sep)
            cov = df.select_dtypes(include=[np.number]).to_numpy(dtype=float)
            if cov.shape[0] != n:
                raise ValueError(f"covars rows={cov.shape[0]} must match samples={n}")
            return cov

        def _write_json(path: Path, payload: dict[str, Any]) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )

        def _materialize_external_batch(value: list[int] | str, work_dir: Path) -> Path:
            if isinstance(value, str):
                return Path(value).expanduser().resolve()
            batch_path = work_dir / "batch_labels.csv"
            batch_path.write_text(
                "batch\n" + "\n".join(str(int(v)) for v in value), encoding="utf-8"
            )
            return batch_path

        def _site_effect_score(data: np.ndarray, batch_labels: np.ndarray) -> float:
            codes = np.unique(batch_labels)
            if codes.size <= 1:
                return 0.0
            grand = data.mean(axis=0, keepdims=True)
            score = 0.0
            for code in codes:
                batch_data = data[batch_labels == code]
                if batch_data.size == 0:
                    continue
                score += float(
                    np.mean(np.abs(batch_data.mean(axis=0, keepdims=True) - grand))
                )
            return score / float(codes.size)

        def _combat_like(
            data: np.ndarray, batch_labels: np.ndarray, cov: np.ndarray | None
        ) -> np.ndarray:
            """ComBat-like batch harmonization (parametric EB, simplified)."""

            n_samples, n_features = data.shape
            batch_codes, batch_inv = np.unique(batch_labels, return_inverse=True)
            n_batches = int(batch_codes.size)

            # 1) Residualize covariates (incl intercept), preserving fitted signal.
            if cov is not None and cov.size:
                Z = np.concatenate([np.ones((n_samples, 1), dtype=float), cov], axis=1)
                beta, *_ = np.linalg.lstsq(Z, data, rcond=None)
                fitted = Z @ beta
                resid = data - fitted
            else:
                fitted = data.mean(axis=0, keepdims=True)
                resid = data - fitted

            # 2) Standardize residuals
            grand_mean = resid.mean(axis=0)
            ddof = 1 if n_samples > 1 else 0
            var_pooled = resid.var(axis=0, ddof=ddof)
            eps = np.finfo(float).eps
            var_pooled = np.where(var_pooled < eps, eps, var_pooled)
            sdata = (resid - grand_mean) / np.sqrt(var_pooled)

            # 3) Batch estimates
            gamma_hat = np.zeros((n_batches, n_features), dtype=float)
            delta_hat = np.zeros((n_batches, n_features), dtype=float)
            n_per_batch = np.zeros((n_batches,), dtype=int)
            for b in range(n_batches):
                idx = batch_inv == b
                n_b = int(idx.sum())
                n_per_batch[b] = n_b
                if n_b == 0:
                    continue
                gamma_hat[b] = sdata[idx].mean(axis=0)
                ddof_b = 1 if n_b > 1 else 0
                delta_hat[b] = sdata[idx].var(axis=0, ddof=ddof_b)

            # 4) Hyperpriors per batch (method-of-moments across features)
            gamma_bar = gamma_hat.mean(axis=1)
            t2 = (
                gamma_hat.var(axis=1, ddof=1)
                if n_features > 1
                else np.ones(n_batches, dtype=float)
            )
            t2 = np.where(t2 < eps, eps, t2)

            delta_bar = delta_hat.mean(axis=1)
            s2 = (
                delta_hat.var(axis=1, ddof=1)
                if n_features > 1
                else np.ones(n_batches, dtype=float)
            )
            s2 = np.where(s2 < eps, eps, s2)
            a_prior = 2.0 + (delta_bar**2) / s2
            b_prior = delta_bar * (a_prior - 1.0)

            # 5) Posterior estimates (closed-form approximation)
            gamma_star = np.zeros_like(gamma_hat)
            delta_star = np.zeros_like(delta_hat)
            for b in range(n_batches):
                n_b = max(int(n_per_batch[b]), 1)
                denom = t2[b] * n_b + delta_hat[b]
                denom = np.where(denom < eps, eps, denom)
                gamma_star[b] = (
                    t2[b] * n_b * gamma_hat[b] + delta_hat[b] * gamma_bar[b]
                ) / denom

                denom_delta = a_prior[b] + n_b / 2.0 - 1.0
                if denom_delta <= 0:
                    denom_delta = 1.0
                delta_star[b] = (b_prior[b] + 0.5 * n_b * delta_hat[b]) / denom_delta
                delta_star[b] = np.where(delta_star[b] < eps, eps, delta_star[b])

            # 6) Adjust
            sdata_adj = np.empty_like(sdata)
            for b in range(n_batches):
                idx = batch_inv == b
                if not idx.any():
                    continue
                sdata_adj[idx] = (sdata[idx] - gamma_star[b]) / np.sqrt(delta_star[b])

            resid_adj = sdata_adj * np.sqrt(var_pooled) + grand_mean
            return resid_adj + fitted

        try:
            # Load features (keep original DF if possible to preserve non-numeric cols)
            if features_path.suffix.lower() in {".npy", ".npz"}:
                arr = np.load(features_path)
                if hasattr(arr, "files"):
                    arr = arr[arr.files[0]]
                X = np.asarray(arr, dtype=float)
                if X.ndim != 2:
                    raise ValueError("features must be 2D (samples x features)")
                df_in = None
            else:
                sep = "\t" if features_path.suffix.lower() == ".tsv" else ","
                df_in = pd.read_csv(features_path, sep=sep)
                X = df_in.select_dtypes(include=[np.number]).to_numpy(dtype=float)
                if X.shape[1] == 0:
                    raise ValueError("features file contains no numeric columns")

            batch = _load_batch(args.batch)
            if batch.shape[0] != X.shape[0]:
                raise ValueError(
                    f"batch length={batch.shape[0]} must match samples={X.shape[0]}"
                )

            covars = _load_covars(args.covars, X.shape[0])
            batch_counts = {
                str(int(code)): int((batch == code).sum()) for code in np.unique(batch)
            }

            external_backend_info: dict[str, Any] = {}
            if method == "deepresbat_external":
                entrypoint = str(os.getenv("BR_DEEPRESBAT_ENTRYPOINT") or "").strip()
                if not entrypoint:
                    raise RuntimeError(
                        "deepresbat_external requested but BR_DEEPRESBAT_ENTRYPOINT is not configured"
                    )
                batch_file = _materialize_external_batch(args.batch, out_path.parent)
                cmd = [
                    entrypoint,
                    "--features",
                    str(features_path),
                    "--batch",
                    str(batch_file),
                    "--output",
                    str(out_path),
                    "--report",
                    str(report_path),
                    "--provenance",
                    str(provenance_path),
                ]
                if args.covars:
                    cmd.extend(
                        ["--covars", str(Path(args.covars).expanduser().resolve())]
                    )
                proc = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    raise RuntimeError(
                        "deepresbat_external backend failed: "
                        + (
                            proc.stderr.strip()
                            or proc.stdout.strip()
                            or f"exit={proc.returncode}"
                        )
                    )
                if not out_path.exists():
                    raise RuntimeError(
                        "deepresbat_external backend completed without writing output_file"
                    )
                df_out = pd.read_csv(out_path)
                X_h = df_out.select_dtypes(include=[np.number]).to_numpy(dtype=float)
                if X_h.shape != X.shape:
                    raise RuntimeError(
                        "deepresbat_external output shape mismatch: "
                        f"expected {X.shape}, got {X_h.shape}"
                    )
                external_backend_info = {
                    "entrypoint": entrypoint,
                    "stdout": proc.stdout.strip(),
                    "stderr": proc.stderr.strip(),
                }
            elif method == "combat":
                X_h = _combat_like(X, batch, covars)
            else:
                raise ValueError(
                    f"Unsupported harmonization method/backend: {args.method}"
                )

            if df_in is None:
                df_out = pd.DataFrame(
                    X_h, columns=[f"f{i}" for i in range(X_h.shape[1])]
                )
            else:
                df_out = df_in.copy()
                numeric_cols = df_in.select_dtypes(include=[np.number]).columns
                df_out.loc[:, numeric_cols] = X_h

            df_out.to_csv(out_path, index=False)

            report_payload = {
                "tool": "harmonize_data",
                "method": method,
                "n_samples": int(X.shape[0]),
                "n_features": int(X.shape[1]),
                "n_batches": int(np.unique(batch).size),
                "batch_counts": batch_counts,
                "site_effect_before": _site_effect_score(X, batch),
                "site_effect_after": _site_effect_score(X_h, batch),
                "covariates_used": bool(covars is not None and covars.size),
                "external_backend": external_backend_info or None,
            }
            _write_json(report_path, report_payload)

            provenance_payload = {
                "workflow_family": "data_harmonization",
                "tool": "harmonize_data",
                "method": method,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "inputs": {
                    "features": str(features_path),
                    "batch": (
                        args.batch
                        if isinstance(args.batch, list)
                        else str(Path(args.batch).expanduser().resolve())
                    ),
                    "covars": (
                        str(Path(args.covars).expanduser().resolve())
                        if args.covars
                        else None
                    ),
                },
                "outputs": {
                    "harmonized_file": str(out_path),
                    "report_json": str(report_path),
                    "provenance_json": str(provenance_path),
                },
                "source_repo": (
                    "https://github.com/ThomasYeoLab/Standalone_An2024_DeepResBat"
                    if method == "deepresbat_external"
                    else "brain_researcher local ComBat-like backend"
                ),
                "tested_release": "brain_researcher stable-pack baseline 2026-03-09",
            }
            _write_json(provenance_path, provenance_payload)

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "harmonized_file": str(out_path),
                        "report_json": str(report_path),
                        "provenance_json": str(provenance_path),
                    },
                    "summary": {
                        "n_samples": int(X.shape[0]),
                        "n_features": int(X.shape[1]),
                        "n_batches": int(np.unique(batch).size),
                        "method": method,
                    },
                },
            )
        except Exception as exc:
            return ToolResult(
                status="error", error=str(exc), data={"features": str(features_path)}
            )


class SearchToolsArgs(BaseModel):
    query: str = Field(description="Search query")
    limit: int = Field(default=20, ge=1, le=100, description="Max results")


class SearchToolsTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "search_tools"

    def get_tool_description(self) -> str:
        return "Search available tools by keywords (wrapper over MCP tool_search)."

    def get_args_schema(self):
        return SearchToolsArgs

    def _run(self, query: str, limit: int = 20, **_: Any) -> ToolResult:
        try:
            from brain_researcher.services.shared.mcp_runtime_bridge import (
                call_mcp_tool,
            )

            return ToolResult(
                status="success",
                data=call_mcp_tool("tool_search", query=query, limit=limit),
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


class SearchDatasetsArgs(BaseModel):
    query: str | None = Field(default=None, description="Free-text query")
    modality: str | None = Field(
        default=None, description="Modality filter (e.g., fMRI)"
    )
    task: str | None = Field(default=None, description="Task filter")
    min_subjects: int | None = Field(default=None, description="Minimum subject count")
    limit: int = Field(default=20, ge=1, le=100, description="Max results")


class SearchDatasetsTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "search_datasets"

    def get_tool_description(self) -> str:
        return "Search public datasets (OpenNeuro wrapper)."

    def get_args_schema(self):
        return SearchDatasetsArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        from brain_researcher.services.tools.openneuro_tool import OpenNeuroSearchTool

        return _call_wrapper(OpenNeuroSearchTool(), kwargs)


class SearchLiteratureArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description=(
            "Free-text query. If `concepts` is not provided, this will be used as a "
            "single concept term."
        ),
    )
    concepts: list[str] | None = Field(
        default=None,
        description="Concept terms to search (preferred).",
    )
    max_results: int = Field(default=20, ge=1, le=200, description="Max results")
    output_file: str | None = Field(
        default=None, description="Optional path to write JSON search results"
    )


class SearchLiteratureTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "search_literature"

    def get_tool_description(self) -> str:
        return "Search literature by concepts (wrapper over concept_literature_search)."

    def get_args_schema(self):
        return SearchLiteratureArgs

    def _run(
        self,
        query: str | None = None,
        concepts: list[str] | None = None,
        max_results: int = 20,
        output_file: str | None = None,
        **_: Any,
    ) -> ToolResult:
        from brain_researcher.services.tools.br_kg_tools import LiteratureSearchTool

        concept_list = (concepts or [])[:]
        if not concept_list and query:
            concept_list = [query]
        if not concept_list:
            return ToolResult(
                status="error",
                error="Either `concepts` or `query` is required.",
            )

        result = _call_wrapper(
            LiteratureSearchTool(),
            {"concepts": concept_list, "max_results": max_results},
        )
        if output_file and isinstance(result.data, dict):
            out_path = Path(output_file).expanduser().resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result.data, indent=2), encoding="utf-8")
            payload = dict(result.data)
            payload.setdefault("outputs", {})
            payload["outputs"]["literature_json"] = str(out_path)
            return ToolResult(
                status=result.status,
                data=payload,
                error=result.error,
                metadata=result.metadata,
            )
        return result


class PerformMetaAnalysisArgs(BaseModel):
    coordinates: list[list[float]] | None = Field(
        default=None, description="List of MNI coordinates"
    )
    method: str = Field(default="ale", description="Meta-analysis method")
    term: str | None = Field(
        default=None,
        description="Neurosynth keyword/term for term-based meta-analysis (e.g., 'memory')",
    )
    keyword: str | None = Field(
        default=None,
        description="Alias of term (kept for compatibility with other callers)",
    )
    roi_mask: str | None = Field(
        default=None,
        description="Optional ROI mask NIfTI (MNI space) for summarizing term map within ROI",
    )
    threshold: float = Field(
        default=3.0,
        description="Threshold passed to Neurosynth map builder (interpreted as a minimum hit-count)",
    )
    output_dir: str | None = Field(default=None, description="Output directory")


class PerformMetaAnalysisTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "perform_meta_analysis"

    def get_tool_description(self) -> str:
        return "Run coordinate-based meta-analysis (wrapper over coordinate_meta_analysis)."

    def get_args_schema(self):
        return PerformMetaAnalysisArgs

    def _run(
        self,
        coordinates: list[list[float]] | None = None,
        method: str = "ale",
        term: str | None = None,
        keyword: str | None = None,
        roi_mask: str | None = None,
        threshold: float = 3.0,
        output_dir: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        # Term-based Neurosynth path (preferred for Grandmaster workflow_neurosynth_roi_analysis).
        selected_term = (term or keyword or "").strip()
        if selected_term:
            try:
                import json
                import re

                import nibabel as nib
                import numpy as np
                from nilearn import image as nl_image

                from brain_researcher.core.analysis.neurosynth_integration import (
                    get_neurosynth_mapping,
                )

                out_root = _ensure_dir(output_dir or (Path.cwd() / "meta_analysis"))
                slug = (
                    re.sub(r"[^a-zA-Z0-9_-]+", "_", selected_term).strip("_") or "term"
                )

                stat_map_path = out_root / f"neurosynth_{slug}.nii.gz"
                meta_json_path = out_root / f"neurosynth_{slug}_meta.json"
                roi_summary_path = out_root / f"neurosynth_{slug}_roi_summary.json"

                mapping = get_neurosynth_mapping(
                    selected_term, threshold=float(threshold)
                )
                err = mapping.get("error")
                if err:
                    return ToolResult(
                        status="error",
                        error=str(err),
                        data={"term": selected_term, "output_dir": str(out_root)},
                    )

                activation_maps = mapping.get("activation_maps") or []
                if not activation_maps:
                    return ToolResult(
                        status="error",
                        error="No activation map returned from neurosynth mapping",
                        data={"term": selected_term, "output_dir": str(out_root)},
                    )

                img = activation_maps[0]
                nib.save(img, str(stat_map_path))

                serializable = {
                    k: v for k, v in mapping.items() if k != "activation_maps"
                }
                serializable["outputs"] = {"stat_map": str(stat_map_path)}
                meta_json_path.write_text(
                    json.dumps(serializable, indent=2), encoding="utf-8"
                )

                outputs: dict[str, Any] = {
                    "stat_map": str(stat_map_path),
                    "meta_json": str(meta_json_path),
                }
                summary: dict[str, Any] = {
                    "term": serializable.get("term_used", selected_term),
                    "n_studies": int(
                        serializable.get("n_studies")
                        or len(serializable.get("studies") or [])
                    ),
                    "n_coords": int(
                        serializable.get("n_coords")
                        or len(serializable.get("coordinates") or [])
                    ),
                }

                if roi_mask:
                    stat_img = nib.load(str(stat_map_path))
                    mask_img = nib.load(str(roi_mask))
                    if mask_img.ndim == 4:
                        mask_img = nl_image.index_img(mask_img, 0)
                    if mask_img.shape != stat_img.shape[:3] or not np.allclose(
                        mask_img.affine, stat_img.affine
                    ):
                        mask_img = nl_image.resample_to_img(
                            mask_img, stat_img, interpolation="nearest"
                        )
                    mask = np.asanyarray(mask_img.dataobj) > 0
                    stat = np.asanyarray(stat_img.dataobj)
                    vals = stat[mask]
                    if vals.size == 0:
                        roi_payload = {
                            "roi_mask": str(roi_mask),
                            "n_voxels": 0,
                            "mean": None,
                            "max": None,
                        }
                    else:
                        roi_payload = {
                            "roi_mask": str(roi_mask),
                            "n_voxels": int(vals.size),
                            "mean": float(np.nanmean(vals)),
                            "max": float(np.nanmax(vals)),
                        }
                    roi_summary_path.write_text(
                        json.dumps(roi_payload, indent=2), encoding="utf-8"
                    )
                    outputs["roi_summary_json"] = str(roi_summary_path)
                    summary["roi_n_voxels"] = int(roi_payload.get("n_voxels") or 0)

                return ToolResult(
                    status="success", data={"outputs": outputs, "summary": summary}
                )
            except Exception as exc:
                return ToolResult(
                    status="error",
                    error=str(exc),
                    data={"term": selected_term, "output_dir": output_dir},
                )

        # Coordinate-based meta-analysis fallback.
        try:
            from brain_researcher.services.tools.enhanced_meta_analysis import (
                CoordinateMetaAnalysisTool,
            )

            payload = {
                "coordinates": coordinates,
                "method": method,
                "output_dir": output_dir,
                **kwargs,
            }
            return _call_wrapper(CoordinateMetaAnalysisTool(), payload)
        except Exception as exc:
            return ToolResult(
                status="error",
                error=str(exc),
                data={"coordinates": coordinates, "method": method},
            )


class ConsultKnowledgeGraphArgs(BaseModel):
    query_type: str = Field(description="Query type (neighbors/path/subgraph/...)")
    start_node: str = Field(description="Start node id/name")
    end_node: str | None = Field(default=None, description="Optional end node")
    filters: dict[str, Any] | None = Field(default=None, description="Optional filters")


class ConsultKnowledgeGraphTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "consult_knowledge_graph"

    def get_tool_description(self) -> str:
        return "Query BR-KG (wrapper over graph_query)."

    def get_args_schema(self):
        return ConsultKnowledgeGraphArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        from brain_researcher.services.tools.br_kg_tools import GraphQueryTool

        return _call_wrapper(GraphQueryTool(), kwargs)


class DecodeBrainMapArgs(BaseModel):
    stat_map: str | None = Field(default=None, description="Path to stat map")
    coordinates: list[list[float]] | None = Field(
        default=None, description="Peak coordinates in MNI space"
    )
    top_k: int = Field(default=5, ge=1, le=50, description="Top concepts to return")


class DecodeBrainMapTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "decode_brain_map"

    def get_tool_description(self) -> str:
        return "Decode a brain map to cognitive concepts (NeuroVLM-first, coordinate fallback)."

    def get_args_schema(self):
        return DecodeBrainMapArgs

    def _run(
        self,
        stat_map: str | None = None,
        coordinates: list[list[float]] | None = None,
        top_k: int = 5,
        **_: Any,
    ) -> ToolResult:
        try:
            coords = coordinates
            peak_error: str | None = None
            if coords is None and stat_map:
                try:
                    import nibabel as nib
                    import numpy as np

                    img = nib.load(stat_map)
                    data = np.asanyarray(img.dataobj)
                    idx = np.unravel_index(int(np.nanargmax(np.abs(data))), data.shape)
                    xyz = nib.affines.apply_affine(img.affine, idx).tolist()
                    coords = [xyz]
                except Exception as exc:
                    peak_error = str(exc)

            neurovlm_error: str | None = None
            if stat_map:
                try:
                    from brain_researcher.services.tools.neurovlm_tool import (
                        decode_brain_map_with_neurovlm,
                    )

                    neurovlm_result = decode_brain_map_with_neurovlm(
                        stat_map=stat_map,
                        top_k=top_k,
                        peak_coordinate=coords[0] if coords else None,
                    )
                    if neurovlm_result.status == "success":
                        return neurovlm_result
                    neurovlm_error = neurovlm_result.error or "NeuroVLM decode failed"
                except Exception as exc:
                    neurovlm_error = str(exc)
            if not coords:
                if neurovlm_error or peak_error:
                    details = [msg for msg in [neurovlm_error, peak_error] if msg]
                    return ToolResult(
                        status="error",
                        error=(
                            "; ".join(details)
                            if details
                            else "Provide stat_map or coordinates"
                        ),
                        data={"stat_map": stat_map},
                    )
                return ToolResult(
                    status="error", error="Provide stat_map or coordinates"
                )
            from brain_researcher.services.tools.br_kg_tools import (
                CoordinateToConceptTool,
            )

            result = _call_wrapper(
                CoordinateToConceptTool(), {"coordinates": coords, "top_k": top_k}
            )
            if neurovlm_error and result.status == "success":
                data = dict(result.data or {})
                fallbacks = list(data.get("fallbacks") or [])
                fallbacks.append({"tool": "neurovlm", "error": neurovlm_error})
                data["fallbacks"] = fallbacks
                result.data = data
            return result
        except Exception as exc:
            return ToolResult(
                status="error", error=str(exc), data={"stat_map": stat_map}
            )


from brain_researcher.services.tools.ml_decoding_tools import (  # noqa: F401,E402
    EvaluateModelArgs,
    EvaluateModelTool,
    MLCrossValidationArgs,
    MLCrossValidationTool,
    RunSearchlightArgs,
    RunSearchlightTool,
    TrainDecoderArgs,
    TrainDecoderTool,
)

# =============================================================================
# Layer 2b: Surface & CIFTI tools  (moved to surface_cifti_tools.py)
# =============================================================================
from brain_researcher.services.tools.surface_cifti_tools import (  # noqa: F401,E402
    CompareSurfaceMapsArgs,
    CompareSurfaceMapsTool,
    MapVolumeToSurfaceArgs,
    MapVolumeToSurfaceTool,
    ParcellateCiftiArgs,
    ParcellateCiftiTool,
    ProcessCiftiArgs,
    ProcessCiftiTool,
)


class NBSEngineArgs(BaseModel):
    connectivity_matrices: str = Field(
        description="Path to npy/npz (n_subj, n_roi, n_roi)"
    )
    labels: str | list[int] = Field(description="Group labels (two-group, 0/1)")
    threshold: float = Field(default=3.1, description="Edgewise |t| threshold")
    n_permutations: int = Field(default=100, description="Permutation count")
    tail: Literal["two", "pos", "neg"] = Field(
        default="two", description="Tail for thresholding"
    )
    output_file: str | None = Field(
        default=None, description="Optional base path for outputs"
    )


class NBSEngineTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "nbs_engine"

    def get_tool_description(self) -> str:
        return "Lightweight network-based statistic (permutation on connectivity matrices)."

    def get_args_schema(self):
        return NBSEngineArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        from brain_researcher.services.tools.grandmaster.runtime_tools import (
            nbs_engine_tool,
        )

        result = nbs_engine_tool(**kwargs)
        if isinstance(result, ToolResult):
            return result
        return ToolResult(
            status=result.get("status", "success"), data=result.get("outputs", result)
        )


class AnalyzeFrequencyPowerArgs(BaseModel):
    raw_or_epochs: str = Field(description="Path to raw/epochs file")
    output_dir: str | None = Field(default=None, description="Output directory")


class AnalyzeFrequencyPowerTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "analyze_frequency_power"

    def get_tool_description(self) -> str:
        return (
            "Frequency-domain power analysis (TODO: wire to MNE time-frequency tools)."
        )

    def get_args_schema(self):
        return AnalyzeFrequencyPowerArgs

    def _run(self, **_: Any) -> ToolResult:
        return ToolResult(
            status="error",
            error="analyze_frequency_power not implemented yet",
            data={"suggestions": ["timefreq_tfr", "mne_timefreq"]},
        )


class ComputeERPArgs(BaseModel):
    epochs_file: str = Field(description="Epochs file path")
    output_dir: str | None = Field(default=None, description="Output directory")


class ComputeERPTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "compute_erp"

    def get_tool_description(self) -> str:
        return (
            "Compute event-related potentials (TODO: wire to MNE epochs/evoked tools)."
        )

    def get_args_schema(self):
        return ComputeERPArgs

    def _run(self, **_: Any) -> ToolResult:
        return ToolResult(
            status="error",
            error="compute_erp not implemented yet",
            data={"suggestions": ["epoch_events", "ieeg_epoch_features"]},
        )


class LocalizeSourceArgs(BaseModel):
    evoked_file: str = Field(description="Evoked/ERP file path")
    output_dir: str | None = Field(default=None, description="Output directory")


class LocalizeSourceTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "localize_source"

    def get_tool_description(self) -> str:
        return "Source localization (TODO: wire to MNE source tools)."

    def get_args_schema(self):
        return LocalizeSourceArgs

    def _run(self, **_: Any) -> ToolResult:
        from brain_researcher.core.utils import configure_mne_environment

        try:
            import mne
        except ImportError as exc:
            return ToolResult(
                status="error", error=f"MNE not available: {exc}", data={}
            )

        args = LocalizeSourceArgs(**_)
        input_path = Path(args.evoked_file).expanduser().resolve()
        if not input_path.exists():
            return ToolResult(status="error", error="evoked_file not found", data={})

        output_dir = (
            Path(args.output_dir).expanduser().resolve()
            if args.output_dir
            else input_path.parent / "source_localization"
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        configure_mne_environment()

        evoked = None
        raw = None
        epochs = None

        # Try evoked first, then raw/epochs fallbacks
        if input_path.suffix == ".fif":
            try:
                evoked = mne.read_evokeds(str(input_path), condition=0, verbose=False)
            except Exception:
                try:
                    raw = mne.io.read_raw_fif(
                        str(input_path), preload=True, verbose=False
                    )
                except Exception:
                    raw = None
        elif input_path.suffix in {".edf", ".bdf"}:
            try:
                raw = mne.io.read_raw_edf(str(input_path), preload=True, verbose=False)
            except Exception:
                raw = None

        if evoked is None:
            if raw is None:
                return ToolResult(
                    status="error",
                    error="Unsupported evoked_file format or failed to read data",
                    data={},
                )
            try:
                epochs = mne.make_fixed_length_epochs(
                    raw, duration=2.0, preload=True, verbose=False
                )
                evoked = epochs.average()
            except Exception as exc:
                return ToolResult(status="error", error=str(exc), data={})

        try:
            import numpy as np

            if epochs is None and raw is not None:
                epochs = mne.make_fixed_length_epochs(
                    raw, duration=2.0, preload=True, verbose=False
                )
            if epochs is not None:
                noise_cov = mne.compute_covariance(
                    epochs, method="shrunk", verbose=False
                )
            else:
                noise_cov = mne.make_ad_hoc_cov(evoked.info)

            src = mne.setup_volume_source_space(
                subject=None, pos=20.0, sphere=(0.0, 0.0, 0.0, 0.09), verbose=False
            )
            try:
                sphere = mne.make_sphere_model(
                    r0="auto", head_radius="auto", info=evoked.info, verbose=False
                )
            except Exception:
                # Some datasets (especially MEG-only recordings) may not include
                # digitization points required for auto-fitting. Use a fixed
                # sphere to keep the workflow runnable for smoke tests.
                sphere = mne.make_sphere_model(
                    r0=(0.0, 0.0, 0.0),
                    head_radius=0.09,
                    info=evoked.info,
                    verbose=False,
                )
            eeg_picks = mne.pick_types(evoked.info, eeg=True, meg=False)
            meg_picks = mne.pick_types(evoked.info, meg=True, eeg=False)

            use_eeg = bool(eeg_picks.size)
            if use_eeg:
                # Some datasets include EEG channels without sensor locations.
                # If locations are missing, disable EEG forward computation.
                has_loc = False
                for idx in eeg_picks:
                    loc = np.asarray(
                        evoked.info["chs"][int(idx)]["loc"][:3], dtype=float
                    )
                    if np.linalg.norm(loc) > 1e-6:
                        has_loc = True
                        break
                use_eeg = has_loc

            use_meg = bool(meg_picks.size)

            fwd = mne.make_forward_solution(
                evoked.info,
                trans=None,
                src=src,
                bem=sphere,
                eeg=use_eeg,
                meg=use_meg,
                mindist=5.0,
                verbose=False,
            )
            inv = mne.minimum_norm.make_inverse_operator(
                evoked.info, fwd, noise_cov, loose=0.2, depth=0.8, verbose=False
            )
            stc = mne.minimum_norm.apply_inverse(
                evoked, inv, lambda2=1.0 / 9.0, method="dSPM", verbose=False
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc), data={})

        stc_prefix = output_dir / f"{input_path.stem}_stc"
        stc.save(str(stc_prefix))
        stc_files = sorted(str(p) for p in output_dir.glob(f"{stc_prefix.name}*"))

        return ToolResult(
            status="success",
            data={
                "outputs": {"source_estimate": stc_files},
                "summary": {
                    "input": str(input_path),
                    "n_vertices": int(stc.data.shape[0]),
                    "n_times": int(stc.data.shape[1]),
                    "method": "dSPM",
                },
            },
        )


class NormalizeWithLesionArgs(BaseModel):
    t1: str = Field(description="T1w image")
    lesion_mask: str = Field(description="Lesion mask")
    output_dir: str | None = Field(default=None, description="Output directory")


class NormalizeWithLesionTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "normalize_with_lesion"

    def get_tool_description(self) -> str:
        return "Lesion-aware normalization (TODO: wire to ANTs with mask constraints)."

    def get_args_schema(self):
        return NormalizeWithLesionArgs

    def _run(self, **_: Any) -> ToolResult:
        try:
            import nibabel as nib
            import numpy as np
        except ImportError as exc:
            return ToolResult(
                status="error", error=f"nibabel not available: {exc}", data={}
            )

        args = NormalizeWithLesionArgs(**_)
        t1_path = Path(args.t1).expanduser().resolve()
        mask_path = Path(args.lesion_mask).expanduser().resolve()
        if not t1_path.exists():
            return ToolResult(status="error", error="t1 not found", data={})
        if not mask_path.exists():
            return ToolResult(status="error", error="lesion_mask not found", data={})

        output_dir = (
            Path(args.output_dir).expanduser().resolve()
            if args.output_dir
            else t1_path.parent / "lesion_normalized"
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        t1_img = nib.load(str(t1_path))
        t1_img = nib.as_closest_canonical(t1_img)

        if mask_path.suffix == ".npy":
            mask_data = np.load(mask_path)
            mask_img = nib.Nifti1Image(mask_data.astype(float), t1_img.affine)
        else:
            mask_img = nib.load(str(mask_path))
            mask_img = nib.as_closest_canonical(mask_img)

        resampled = False
        if mask_img.shape != t1_img.shape:
            resampled = True
            try:
                from nilearn.image import resample_to_img

                mask_img = resample_to_img(mask_img, t1_img, interpolation="nearest")
            except Exception:
                from nibabel.processing import resample_from_to

                mask_img = resample_from_to(mask_img, t1_img, order=0)

        def _strip_all_suffixes(path: Path) -> str:
            name = path.name
            for suf in reversed(path.suffixes):
                if name.endswith(suf):
                    name = name[: -len(suf)]
            return name

        t1_base = _strip_all_suffixes(t1_path)
        mask_base = _strip_all_suffixes(mask_path)

        t1_out = output_dir / f"{t1_base}_norm.nii.gz"
        mask_out = output_dir / f"{mask_base}_norm.nii.gz"
        nib.save(t1_img, str(t1_out))
        nib.save(mask_img, str(mask_out))

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "normalized_t1": str(t1_out),
                    "normalized_lesion_mask": str(mask_out),
                },
                "summary": {
                    "t1": str(t1_path),
                    "lesion_mask": str(mask_path),
                    "method": "canonical_reorient",
                    "resampled_mask": resampled,
                },
            },
        )


class CompareToNormativeModelArgs(BaseModel):
    features: str = Field(
        description=(
            "Cohort feature table (CSV/TSV) with `participant_id` + numeric feature columns, "
            "or a .npy array (n_samples x n_features)."
        )
    )
    model: str | None = Field(
        default=None,
        description=(
            "Model selector. If unset or 'cohort', compute mean/std from the provided cohort. "
            "If set to 'leave_one_out', compute per-subject z-scores against the rest of the cohort."
        ),
    )
    id_col: str = Field(
        default="participant_id", description="Subject id column for tabular inputs"
    )
    output_file: str = Field(
        default="normative_deviation.tsv",
        description="Output TSV/CSV path for per-subject deviation summary",
    )


class CompareToNormativeModelTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "compare_to_normative_model"

    def get_tool_description(self) -> str:
        return "Compare a cohort to a normative model (simple z-score deviations)."

    def get_args_schema(self):
        return CompareToNormativeModelArgs

    def _run(
        self,
        features: str,
        model: str | None = None,
        id_col: str = "participant_id",
        output_file: str = "normative_deviation.tsv",
        **_: Any,
    ) -> ToolResult:
        """Compute per-subject deviation summary via cohort mean/std (or LOO)."""
        try:
            import numpy as np
            import pandas as pd

            feats_path = Path(features).expanduser().resolve()
            if not feats_path.exists():
                return ToolResult(
                    status="error", error=f"features not found: {feats_path}"
                )

            participant_ids: list[str]
            X: np.ndarray

            if feats_path.suffix.lower() == ".npy":
                X = np.load(feats_path)
                if X.ndim == 1:
                    X = X[:, None]
                if X.ndim != 2:
                    return ToolResult(
                        status="error", error="features .npy must be 1D or 2D array"
                    )
                participant_ids = [f"sample-{i:04d}" for i in range(X.shape[0])]
                feature_names = [f"f{i}" for i in range(X.shape[1])]
            else:
                df = pd.read_csv(
                    feats_path, sep="\t" if feats_path.suffix.lower() == ".tsv" else ","
                )
                if id_col not in df.columns:
                    return ToolResult(
                        status="error",
                        error=f"features table missing id_col={id_col!r}; columns={df.columns.tolist()}",
                    )
                participant_ids = df[id_col].astype(str).tolist()
                feature_names = [c for c in df.columns if c != id_col]
                if not feature_names:
                    return ToolResult(
                        status="error", error="features table has no feature columns"
                    )
                X = (
                    df[feature_names]
                    .apply(pd.to_numeric, errors="coerce")
                    .to_numpy(dtype=float)
                )

            if X.shape[0] < 3:
                return ToolResult(
                    status="error",
                    error="Need at least 3 samples for normative modeling",
                )

            model_key = (model or "cohort").strip().lower()
            loo = model_key in {
                "leave_one_out",
                "loo",
                "cohort_loo",
                "cohort_leave_one_out",
            }

            if not loo:
                mean = np.nanmean(X, axis=0)
                std = np.nanstd(X, axis=0) + 1e-6
                Z = (X - mean) / std
            else:
                Z = np.zeros_like(X, dtype=float)
                for i in range(X.shape[0]):
                    mask = np.ones(X.shape[0], dtype=bool)
                    mask[i] = False
                    mean = np.nanmean(X[mask], axis=0)
                    std = np.nanstd(X[mask], axis=0) + 1e-6
                    Z[i] = (X[i] - mean) / std

            z_abs = np.abs(Z)
            summary = pd.DataFrame(
                {
                    "participant_id": participant_ids,
                    "z_mean_abs": np.nanmean(z_abs, axis=1),
                    "z_max_abs": np.nanmax(z_abs, axis=1),
                    "n_features": int(Z.shape[1]),
                }
            )

            out_path = Path(output_file).expanduser().resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            sep = "\t" if out_path.suffix.lower() == ".tsv" else ","
            summary.to_csv(out_path, sep=sep, index=False)

            z_path = out_path.with_suffix(".npy")
            np.save(z_path, Z.astype("float32"))

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "deviation_table": str(out_path),
                        "zscores_npy": str(z_path),
                    },
                    "summary": {
                        "n_samples": int(Z.shape[0]),
                        "n_features": int(Z.shape[1]),
                        "method": "leave_one_out" if loo else "cohort",
                    },
                },
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


class AnalyzeClinicalCorrelationArgs(BaseModel):
    table_file: str = Field(description="CSV/TSV with feature + clinical columns")
    feature_col: str = Field(description="Feature column name")
    clinical_col: str = Field(description="Clinical column name")
    method: Literal["pearson", "spearman"] = Field(
        default="pearson", description="Correlation type"
    )


class AnalyzeClinicalCorrelationTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "analyze_clinical_correlation"

    def get_tool_description(self) -> str:
        return "Compute correlation between a brain feature and a clinical score."

    def get_args_schema(self):
        return AnalyzeClinicalCorrelationArgs

    def _run(
        self,
        table_file: str,
        feature_col: str,
        clinical_col: str,
        method: str = "pearson",
        **_: Any,
    ) -> ToolResult:
        try:
            import pandas as pd
            from scipy import stats

            path = Path(table_file)
            df = pd.read_csv(path, sep="\t" if path.suffix == ".tsv" else ",")
            x = df[feature_col].astype(float)
            y = df[clinical_col].astype(float)
            mask = x.notna() & y.notna()
            if method == "spearman":
                r, p = stats.spearmanr(x[mask], y[mask])
            else:
                r, p = stats.pearsonr(x[mask], y[mask])
            return ToolResult(
                status="success",
                data={"r": float(r), "p": float(p), "n": int(mask.sum())},
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


class AnalyzeLongitudinalLMEArgs(BaseModel):
    data_file: str = Field(description="CSV/TSV with longitudinal data")
    subject_col: str = Field(default="participant_id", description="Subject id column")
    time_col: str = Field(default="session", description="Time/session column")
    dv_col: str = Field(default="score", description="Dependent variable column")
    covariates: list[str] | None = Field(
        default=None, description="Optional covariates"
    )
    output_file: str | None = Field(default=None, description="Output summary path")

    # Advanced interface (optional): fall back to MixedEffectsTool when provided.
    formula: str | None = Field(
        default=None, description="Mixed model formula (e.g., 'y ~ time + (1|subject)')"
    )
    output_dir: str | None = Field(
        default=None, description="Output directory for advanced backend"
    )


class AnalyzeLongitudinalLMETool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "analyze_longitudinal_lme"

    def get_tool_description(self) -> str:
        return "Longitudinal linear mixed effects model (wrapper over mixed_effects)."

    def get_args_schema(self):
        return AnalyzeLongitudinalLMEArgs

    def _run(
        self,
        data_file: str,
        subject_col: str = "participant_id",
        time_col: str = "session",
        dv_col: str = "score",
        covariates: list[str] | None = None,
        output_file: str | None = None,
        formula: str | None = None,
        output_dir: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        # Prefer the simple, dependency-light statsmodels implementation unless the
        # caller explicitly provides the advanced (formula/output_dir) interface.
        if formula or output_dir:
            from brain_researcher.services.tools.mixed_effects_tool import (
                MixedEffectsTool,
            )

            out_dir = (
                Path(output_dir).expanduser().resolve()
                if output_dir
                else (
                    Path(output_file).expanduser().resolve().parent
                    if output_file
                    else Path.cwd() / "lme_output"
                )
            )
            payload = {
                "data_file": data_file,
                "formula": formula or f"{dv_col} ~ {time_col}",
                "output_dir": str(out_dir),
                **kwargs,
            }
            return _call_wrapper(MixedEffectsTool(), payload)

        try:
            from brain_researcher.services.tools.grandmaster.clinical_stats_tools import (
                analyze_longitudinal_lme_tool,
            )

            out_path = (
                str(Path(output_file).expanduser().resolve())
                if output_file
                else str(Path.cwd() / "longitudinal_lme.tsv")
            )
            result = analyze_longitudinal_lme_tool(
                features_file=data_file,
                subject_col=subject_col,
                time_col=time_col,
                dv_col=dv_col,
                covariates=covariates,
                output_file=out_path,
            )
            status = result.get("status", "success")
            if status != "success":
                return ToolResult(
                    status="error", error=result.get("error"), data=result
                )
            return ToolResult(status="success", data=result)
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


class ComputeTrajectorySimilarityArgs(BaseModel):
    data_file: str = Field(description="Longitudinal trajectory table")
    output_dir: str | None = Field(default=None, description="Output directory")


class ComputeTrajectorySimilarityTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "compute_trajectory_similarity"

    def get_tool_description(self) -> str:
        return "Trajectory similarity / deviation (TODO: define contract + backend)."

    def get_args_schema(self):
        return ComputeTrajectorySimilarityArgs

    def _run(self, **_: Any) -> ToolResult:
        return ToolResult(
            status="error", error="compute_trajectory_similarity not implemented yet"
        )


class TrainGNNClassifierArgs(BaseModel):
    adjacency: str = Field(description="Connectivity/adjacency matrix (.npy)")
    labels: str = Field(description="Labels vector (.npy)")
    output_dir: str | None = Field(default=None, description="Output directory")
    model: Literal["logreg", "linear_svc"] = Field(
        default="logreg", description="Lightweight backend (fallback for smoke tests)"
    )
    random_state: int = Field(default=42, description="Random seed")
    max_iter: int = Field(default=1000, description="Max iterations for optimizer")


class TrainGNNClassifierTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "train_gnn_classifier"

    def get_tool_description(self) -> str:
        return (
            "Train a graph-based classifier on connectivity matrices.\n\n"
            "Note: This repository currently provides a lightweight fallback "
            "implementation (LogisticRegression/LinearSVC on flattened adjacency) "
            "to keep workflows runnable without heavy GNN deps."
        )

    def get_args_schema(self):
        return TrainGNNClassifierArgs

    def _run(
        self,
        adjacency: str,
        labels: str,
        output_dir: str | None = None,
        model: str = "logreg",
        random_state: int = 42,
        max_iter: int = 1000,
        **_: Any,
    ) -> ToolResult:
        try:
            import numpy as np

            adj = np.load(adjacency)
            y = np.load(labels)
            if y.ndim != 1:
                y = np.asarray(y).reshape(-1)
            if adj.shape[0] != y.shape[0]:
                return ToolResult(
                    status="error",
                    error="adjacency and labels must have matching n_samples",
                    data={
                        "adjacency_shape": list(adj.shape),
                        "labels_shape": list(y.shape),
                    },
                )

            x = adj.reshape(adj.shape[0], -1)
            out_dir = (
                Path(output_dir or (Path.cwd() / "gnn_classifier"))
                .expanduser()
                .resolve()
            )
            out_dir.mkdir(parents=True, exist_ok=True)

            preds: np.ndarray
            proba: np.ndarray | None = None
            unique = np.unique(y)
            if unique.size < 2:
                preds = np.full_like(y, unique[0])
            else:
                if model == "linear_svc":
                    from sklearn.svm import LinearSVC

                    clf = LinearSVC(random_state=random_state, max_iter=max_iter)
                    clf.fit(x, y)
                    preds = clf.predict(x)
                else:
                    from sklearn.linear_model import LogisticRegression

                    clf = LogisticRegression(
                        random_state=random_state,
                        max_iter=max_iter,
                        solver="liblinear",
                    )
                    clf.fit(x, y)
                    preds = clf.predict(x)
                    try:
                        proba = clf.predict_proba(x)
                    except Exception:
                        proba = None

            pred_file = out_dir / "predictions.npy"
            np.save(pred_file, preds.astype(int))
            if proba is not None:
                proba_file = out_dir / "probabilities.npy"
                np.save(proba_file, proba)
            else:
                proba_file = None

            acc = float(np.mean(preds == y)) if y.size else 0.0
            summary = {"n_samples": int(y.size), "accuracy_train": acc, "model": model}
            summary_file = out_dir / "summary.json"
            summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "predictions": str(pred_file),
                        "probabilities": str(proba_file) if proba_file else None,
                        "summary": str(summary_file),
                    },
                    "summary": summary,
                },
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


class ApplyFoundationModelArgs(BaseModel):
    input_file: str = Field(description="Input file (image/features)")
    model_id: str | None = Field(
        default=None, description="Foundation model identifier"
    )
    output_dir: str | None = Field(default=None, description="Output directory")


class ApplyFoundationModelTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "apply_foundation_model"

    def get_tool_description(self) -> str:
        return "Apply a pretrained foundation model (TODO: pick concrete backend + artifacts)."

    def get_args_schema(self):
        return ApplyFoundationModelArgs

    def _run(self, **_: Any) -> ToolResult:
        return ToolResult(
            status="error", error="apply_foundation_model not implemented yet"
        )


class GenerateSyntheticDataArgs(BaseModel):
    tool_hint: str | None = Field(default=None, description="Optional backend hint")


class GenerateSyntheticDataTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "generate_synthetic_data"

    def get_tool_description(self) -> str:
        return (
            "Generate synthetic/augmented data (TODO: pick modality-specific backend)."
        )

    def get_args_schema(self):
        return GenerateSyntheticDataArgs

    def _run(self, **_: Any) -> ToolResult:
        return ToolResult(
            status="error", error="generate_synthetic_data not implemented yet"
        )


# =============================================================================
# Layer 6: Visualization & Ops  (moved to vizops_tools.py)
# =============================================================================
from brain_researcher.services.tools.vizops_tools import (  # noqa: F401,E402
    CreateArchiveArgs,
    CreateArchiveTool,
    GenerateStudyReportArgs,
    GenerateStudyReportTool,
    PlotBrainMapArgs,
    PlotBrainMapTool,
    PlotMatrixArgs,
    PlotMatrixTool,
    RequestUserReviewArgs,
    RequestUserReviewTool,
    VisualizeInteractiveArgs,
    VisualizeInteractiveTool,
)


class GrandMasterTools:
    """Factory to register Grand Master tool wrappers."""

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        # Ensure direct FitLins recipe execution is available in both light/full registry modes.
        from brain_researcher.services.tools.pipeline_tools import (
            RunFitLinsRecipeTool as PipelineRunFitLinsRecipeTool,
        )

        return [
            # Infra
            LoadDatasetTool(),
            ValidateBIDSStructureTool(),
            InspectDatasetStructureTool(),
            RunBIDSAppTool(),
            PipelineRunFitLinsRecipeTool(),
            ConvertDicomToBIDSTool(),
            RunMRIQCWorkflowTool(),
            GetQCTableTool(),
            DetectOutliersTool(),
            StandardizeConfoundsTool(),
            ResampleImageTool(),
            # Core fMRI
            ComputeConnectivityTool(),
            AnalyzeGraphTopologyTool(),
            NBSEngineTool(),
            RunGLMFirstLevelTool(),
            RunGLMSecondLevelTool(),
            FilterEventsTool(),
            ExtractRoiValuesTool(),
            PPIAnalyzerTool(),
            GetAtlasTool(),
            # Modalities (selected)
            RunTractographyTool(),
            ReconstructMicrostructureTool(),
            BuildStructuralConnectomeTool(),
            ExtractBundleStatsTool(),
            PreprocessEEGTool(),
            SegmentLesionTool(),
            # Stats/Knowledge
            HarmonizeDataTool(),
            SearchToolsTool(),
            SearchDatasetsTool(),
            SearchLiteratureTool(),
            PerformMetaAnalysisTool(),
            ConsultKnowledgeGraphTool(),
            DecodeBrainMapTool(),
            MLCrossValidationTool(),
            TrainDecoderTool(),
            RunSearchlightTool(),
            EvaluateModelTool(),
            MapVolumeToSurfaceTool(),
            ProcessCiftiTool(),
            ParcellateCiftiTool(),
            CompareSurfaceMapsTool(),
            AnalyzeFrequencyPowerTool(),
            ComputeERPTool(),
            LocalizeSourceTool(),
            NormalizeWithLesionTool(),
            CompareToNormativeModelTool(),
            AnalyzeClinicalCorrelationTool(),
            AnalyzeLongitudinalLMETool(),
            ComputeTrajectorySimilarityTool(),
            TrainGNNClassifierTool(),
            ApplyFoundationModelTool(),
            GenerateSyntheticDataTool(),
            # Vis/Ops
            PlotBrainMapTool(),
            PlotMatrixTool(),
            VisualizeInteractiveTool(),
            GenerateStudyReportTool(),
            RequestUserReviewTool(),
            CreateArchiveTool(),
        ]


__all__ = ["GrandMasterTools"]
