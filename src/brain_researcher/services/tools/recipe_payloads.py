"""Minimal per-workflow recipe payloads for public MCP tools.

Carved out of ``mcp/execution_recipes.py``: the ``_minimal_*_payload`` builders
that produce the compact per-workflow recipe payloads (fMRIPrep, MRIQC, QSIPrep,
sMRIPrep, QSIRecon, FastSurfer, task-GLM-group, dwi-connectome, preprocessing
-QC). They are consumed by the recipe builders (``recipe_builders``); the few
coercion helpers they need (``_coerce_float_value`` / ``_coerce_int_value`` /
``_normalize_sequence_value``) stay in ``execution_recipes`` and are imported
back lazily, so this module imports nothing from ``execution_recipes`` at load
(cycle-free). ``execution_recipes`` re-exports these so existing importers keep
resolving.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from brain_researcher.services.tools.runtime_profiles import get_container_image


def _minimal_task_glm_group_payload(params: dict[str, Any]) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _coerce_float_value,
        _normalize_sequence_value,
    )

    payload: dict[str, Any] = {
        "output_dir": str(
            params.get("output_dir") or "./outputs/out/task_glm_group_minimal_execute"
        ),
        "bids_dir": str(params.get("bids_dir") or "/data/openneuro/ds000114/bids"),
        "fmriprep_dir": str(
            params.get("fmriprep_dir")
            or "/data/openneuro/ds000114/derivatives/fmriprep"
        ),
        "task": str(params.get("task") or "linebisection"),
        "participant_label": _normalize_sequence_value(params.get("participant_label"))
        or ["01", "02"],
        "session": str(params.get("session") or ""),
        "space": str(params.get("space") or "MNI152NLin2009cAsym"),
        "contrast_name": str(params.get("contrast_name") or ""),
        "dry_run": bool(params.get("dry_run", False)),
    }
    direct_imgs = _normalize_sequence_value(params.get("img"))
    direct_events = _normalize_sequence_value(params.get("events"))
    if direct_imgs:
        payload["img"] = direct_imgs
    if direct_events:
        payload["events"] = direct_events
    if params.get("t_r") is not None:
        payload["t_r"] = _coerce_float_value(params.get("t_r"), 0.0)
    if params.get("smoothing_fwhm") is not None:
        payload["smoothing_fwhm"] = _coerce_float_value(
            params.get("smoothing_fwhm"), 0.0
        )
    if params.get("mask_img"):
        payload["mask_img"] = str(params.get("mask_img"))
    return payload


def _minimal_dwi_connectome_payload(params: dict[str, Any]) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _normalize_sequence_value,
    )

    participant_labels = _normalize_sequence_value(params.get("participant_label"))
    extra_args = _normalize_sequence_value(
        params.get("qsirecon_extra_args", params.get("extra_args"))
    )
    return {
        "qsiprep_dir": str(
            params.get("qsiprep_dir") or "/data/openneuro/ds000117/derivatives/qsiprep"
        ),
        "qsirecon_dir": str(params.get("qsirecon_dir") or ""),
        "output_dir": str(
            params.get("output_dir")
            or "./outputs/out/dwi_connectome_single_subject_minimal"
        ),
        "atlas": str(
            params.get("atlas")
            or "/data/reference/Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
        ),
        "recon_spec": str(
            params.get("recon_spec") or "mrtrix_multishell_msmt_ACT-hsvs"
        ),
        "participant_label": participant_labels or ["01"],
        "work_dir": str(
            params.get("work_dir")
            or "./outputs/out/dwi_connectome_single_subject_minimal_work"
        ),
        "fs_license_file": str(
            params.get("fs_license_file") or "/path/to/freesurfer/license.txt"
        ),
        "extra_args": extra_args,
        "dry_run": False,
    }


def _minimal_fmriprep_payload(params: dict[str, Any]) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _coerce_int_value,
        _normalize_sequence_value,
    )

    participant_labels = _normalize_sequence_value(params.get("participant_label"))
    output_spaces = _normalize_sequence_value(params.get("output_spaces"))
    extra_args = _normalize_sequence_value(params.get("extra_args"))
    if "--skip-bids-validation" not in extra_args:
        extra_args.append("--skip-bids-validation")
    if "--fs-no-reconall" not in extra_args:
        extra_args.append("--fs-no-reconall")
    return {
        "bids_dir": str(params.get("bids_dir") or "/data/openneuro/ds000114/bids"),
        "output_dir": str(
            params.get("output_dir") or "./outputs/out/fmriprep_single_subject_minimal"
        ),
        "participant_label": participant_labels or ["01"],
        "work_dir": str(
            params.get("work_dir")
            or "./outputs/out/fmriprep_single_subject_minimal_work"
        ),
        "fs_license_file": str(
            params.get("fs_license_file") or "/path/to/freesurfer/license.txt"
        ),
        "output_spaces": output_spaces or ["MNI152NLin2009cAsym"],
        "n_cpus": _coerce_int_value(params.get("n_cpus"), 4),
        "omp_nthreads": _coerce_int_value(params.get("omp_nthreads"), 2),
        "mem_mb": _coerce_int_value(params.get("mem_mb"), 16000),
        "extra_args": extra_args,
        "dry_run": False,
    }


def _minimal_preprocessing_qc_payload(params: dict[str, Any]) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _coerce_float_value,
        _coerce_int_value,
        _normalize_sequence_value,
    )

    participant_labels = _normalize_sequence_value(params.get("participant_label"))
    output_spaces = _normalize_sequence_value(params.get("output_spaces"))
    modalities = _normalize_sequence_value(params.get("modalities"))
    common_extra_args = _normalize_sequence_value(params.get("extra_args"))
    fmriprep_extra_args = _normalize_sequence_value(params.get("fmriprep_extra_args"))
    mriqc_extra_args = _normalize_sequence_value(params.get("mriqc_extra_args"))

    fmriprep_args = [*common_extra_args, *fmriprep_extra_args]
    mriqc_args = [*common_extra_args, *mriqc_extra_args]
    if "--skip-bids-validation" not in fmriprep_args:
        fmriprep_args.append("--skip-bids-validation")
    if "--fs-no-reconall" not in fmriprep_args:
        fmriprep_args.append("--fs-no-reconall")
    if "--no-sub" not in mriqc_args:
        mriqc_args.append("--no-sub")

    output_dir = str(
        params.get("output_dir")
        or "./outputs/out/preprocessing_qc_single_subject_minimal"
    )
    work_dir = str(
        params.get("work_dir")
        or "./outputs/out/preprocessing_qc_single_subject_minimal_work"
    )
    qc_tsv = str(params.get("qc_tsv") or "").strip()
    bids_filter_file = str(params.get("bids_filter_file") or "").strip()
    return {
        "bids_dir": str(params.get("bids_dir") or "/data/openneuro/ds000114/bids"),
        "output_dir": output_dir,
        "participant_label": participant_labels or ["01"],
        "analysis_level": str(params.get("analysis_level") or "participant"),
        "fs_license_file": str(
            params.get("fs_license_file") or "/path/to/freesurfer/license.txt"
        ),
        "output_spaces": output_spaces or ["MNI152NLin2009cAsym"],
        "modalities": modalities or ["bold"],
        "modality": str(params.get("modality") or "bold"),
        "bids_filter_file": bids_filter_file,
        "qc_tsv": qc_tsv,
        "outlier_metric": str(params.get("outlier_metric") or "fd_mean"),
        "outlier_z": _coerce_float_value(params.get("outlier_z"), 3.0),
        "n_cpus": _coerce_int_value(params.get("n_cpus"), 4),
        "omp_nthreads": _coerce_int_value(params.get("omp_nthreads"), 2),
        "mem_mb": _coerce_int_value(params.get("mem_mb"), 16000),
        "n_procs": _coerce_int_value(params.get("n_procs"), 4),
        "mem_gb": _coerce_float_value(params.get("mem_gb"), 8.0),
        "fmriprep_output_dir": str(Path(output_dir) / "fmriprep"),
        "mriqc_output_dir": str(Path(output_dir) / "mriqc"),
        "fmriprep_work_dir": str(Path(work_dir) / "fmriprep"),
        "mriqc_work_dir": str(Path(work_dir) / "mriqc"),
        "fmriprep_extra_args": fmriprep_args,
        "mriqc_extra_args": mriqc_args,
        "dry_run": False,
    }


def _minimal_mriqc_payload(params: dict[str, Any]) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _coerce_float_value,
        _coerce_int_value,
        _normalize_sequence_value,
    )

    participant_labels = _normalize_sequence_value(params.get("participant_label"))
    modalities = _normalize_sequence_value(params.get("modalities"))
    extra_args = _normalize_sequence_value(params.get("extra_args"))
    if "--no-sub" not in extra_args:
        extra_args.append("--no-sub")
    return {
        "bids_dir": str(params.get("bids_dir") or "/data/openneuro/ds000114/bids"),
        "output_dir": str(
            params.get("output_dir") or "./outputs/out/mriqc_single_subject_minimal"
        ),
        "analysis_level": str(params.get("analysis_level") or "participant"),
        "participant_label": participant_labels or ["01"],
        "modalities": modalities or ["bold"],
        "work_dir": str(
            params.get("work_dir") or "./outputs/out/mriqc_single_subject_minimal_work"
        ),
        "bids_filter_file": str(params.get("bids_filter_file") or ""),
        "n_procs": _coerce_int_value(params.get("n_procs"), 4),
        "mem_gb": _coerce_float_value(params.get("mem_gb"), 8.0),
        "extra_args": extra_args,
        "dry_run": False,
    }


def _minimal_qsiprep_payload(params: dict[str, Any]) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _coerce_int_value,
        _normalize_sequence_value,
    )

    participant_labels = _normalize_sequence_value(params.get("participant_label"))
    extra_args = _normalize_sequence_value(params.get("extra_args"))
    if "--skip-bids-validation" not in extra_args:
        extra_args.append("--skip-bids-validation")
    return {
        "bids_dir": str(params.get("bids_dir") or "/data/openneuro/ds000114/bids"),
        "output_dir": str(
            params.get("output_dir") or "./outputs/out/qsiprep_single_subject_minimal"
        ),
        "analysis_level": str(params.get("analysis_level") or "participant"),
        "participant_label": participant_labels or ["01"],
        "work_dir": str(
            params.get("work_dir")
            or "./outputs/out/qsiprep_single_subject_minimal_work"
        ),
        "fs_license_file": str(
            params.get("fs_license_file") or "/path/to/freesurfer/license.txt"
        ),
        "bids_filter_file": str(params.get("bids_filter_file") or ""),
        "n_cpus": _coerce_int_value(params.get("n_cpus"), 4),
        "omp_nthreads": _coerce_int_value(params.get("omp_nthreads"), 2),
        "mem_mb": _coerce_int_value(params.get("mem_mb"), 16000),
        "extra_args": extra_args,
        "dry_run": False,
    }


def _minimal_smriprep_payload(params: dict[str, Any]) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _coerce_int_value,
        _normalize_sequence_value,
    )

    participant_labels = _normalize_sequence_value(params.get("participant_label"))
    extra_args = _normalize_sequence_value(params.get("extra_args"))
    if "--skip-bids-validation" not in extra_args:
        extra_args.append("--skip-bids-validation")
    return {
        "bids_dir": str(params.get("bids_dir") or "/data/openneuro/ds000114/bids"),
        "output_dir": str(
            params.get("output_dir") or "./outputs/out/smriprep_single_subject_minimal"
        ),
        "participant_label": participant_labels or ["01"],
        "work_dir": str(
            params.get("work_dir")
            or "./outputs/out/smriprep_single_subject_minimal_work"
        ),
        "fs_license_file": str(
            params.get("fs_license_file") or "/path/to/freesurfer/license.txt"
        ),
        "bids_filter_file": str(params.get("bids_filter_file") or ""),
        "n_cpus": _coerce_int_value(params.get("n_cpus"), 4),
        "omp_nthreads": _coerce_int_value(params.get("omp_nthreads"), 2),
        "mem_mb": _coerce_int_value(params.get("mem_mb"), 16000),
        "extra_args": extra_args,
        "dry_run": False,
    }


def _minimal_qsirecon_payload(params: dict[str, Any]) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _coerce_int_value,
        _normalize_sequence_value,
    )

    participant_labels = _normalize_sequence_value(params.get("participant_label"))
    extra_args = _normalize_sequence_value(params.get("extra_args"))
    return {
        "qsiprep_dir": str(
            params.get("qsiprep_dir") or "/data/openneuro/ds000114/derivatives/qsiprep"
        ),
        "output_dir": str(
            params.get("output_dir") or "./outputs/out/qsirecon_single_subject_minimal"
        ),
        "recon_spec": str(
            params.get("recon_spec") or "mrtrix_multishell_msmt_ACT-hsvs"
        ),
        "participant_label": participant_labels or ["01"],
        "work_dir": str(
            params.get("work_dir")
            or "./outputs/out/qsirecon_single_subject_minimal_work"
        ),
        "fs_license_file": str(
            params.get("fs_license_file") or "/path/to/freesurfer/license.txt"
        ),
        "n_cpus": _coerce_int_value(params.get("n_cpus"), 4),
        "omp_nthreads": _coerce_int_value(params.get("omp_nthreads"), 2),
        "mem_mb": _coerce_int_value(params.get("mem_mb"), 16000),
        "extra_args": extra_args,
        "dry_run": False,
    }


def _minimal_fastsurfer_payload(params: dict[str, Any]) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _coerce_int_value,
        _normalize_sequence_value,
    )

    extra_args = _normalize_sequence_value(params.get("extra_args"))
    runtime = str(params.get("runtime") or "docker").strip().lower()
    if runtime not in {"docker", "apptainer"}:
        runtime = "docker"
    return {
        "t1w_image": str(
            params.get("t1w_image")
            or "/data/openneuro/ds000114/bids/sub-01/anat/sub-01_T1w.nii.gz"
        ),
        "subject_id": str(params.get("subject_id") or "sub-01"),
        "output_dir": str(
            params.get("output_dir")
            or "./outputs/out/fastsurfer_single_subject_minimal"
        ),
        "fs_license_file": str(
            params.get("fs_license_file") or "/path/to/freesurfer/license.txt"
        ),
        "n_threads": _coerce_int_value(params.get("n_threads"), 1),
        "use_gpu": bool(params.get("use_gpu", False)),
        "runtime": runtime,
        "container_image": str(
            params.get("container_image")
            or get_container_image("fastsurfer")
            or "deepmi/fastsurfer:latest"
        ),
        "extra_args": extra_args,
        "dry_run": False,
    }
