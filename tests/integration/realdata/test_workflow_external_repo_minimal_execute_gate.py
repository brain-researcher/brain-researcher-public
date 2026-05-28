"""On-demand minimal execute gate for external neuroimaging repo workflows."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pandas as pd
import pytest

from brain_researcher.services.tools.pipeline_tools import (
    _find_freesurfer_license,
    _resolve_bids_app_executable,
    _resolve_fastsurfer_image,
)
from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


def _execute_gate_enabled(workflow_id: str) -> None:
    raw_enabled = (
        str(os.environ.get("BR_ENABLE_EXTERNAL_REPO_EXEC_GATE") or "").strip().lower()
    )
    if raw_enabled not in {"1", "true", "yes", "on"}:
        pytest.skip(
            "set BR_ENABLE_EXTERNAL_REPO_EXEC_GATE=1 to run minimal execute gate"
        )
    selected_raw = str(
        os.environ.get("BR_EXTERNAL_REPO_EXEC_GATE_WORKFLOWS") or ""
    ).strip()
    if not selected_raw:
        return
    selected = {
        item.strip()
        for item in selected_raw.replace(";", ",").split(",")
        if item.strip()
    }
    if workflow_id not in selected:
        pytest.skip(
            f"{workflow_id} not selected in BR_EXTERNAL_REPO_EXEC_GATE_WORKFLOWS"
        )


def _default_bids_root() -> Path:
    return Path(
        os.environ.get(
            "BR_DS000114_BIDS_ROOT",
            PROJECT_ROOT / "out" / "openneuro_local" / "ds000114" / "bids",
        )
    )


def _default_fmriprep_root() -> Path:
    return Path(
        os.environ.get(
            "BR_DS000114_FMRIPREP_ROOT",
            PROJECT_ROOT
            / "outputs"
            / "_a4_ds000114_linebisection"
            / "derivatives_local"
            / "ds000114-fmriprep",
        )
    )


def _default_qsiprep_bids_root() -> Path:
    return Path(
        os.environ.get(
            "BR_QSIPREP_EXEC_BIDS_ROOT",
            os.environ.get(
                "BR_EXTERNAL_REPO_EXEC_BIDS_ROOT", str(_default_bids_root())
            ),
        )
    )


def _default_smriprep_bids_root() -> Path:
    return Path(
        os.environ.get(
            "BR_SMRIPREP_EXEC_BIDS_ROOT",
            os.environ.get(
                "BR_EXTERNAL_REPO_EXEC_BIDS_ROOT", str(_default_bids_root())
            ),
        )
    )


def _default_qsiprep_root() -> Path:
    return Path(
        os.environ.get(
            "BR_QSIRECON_INPUT_ROOT",
            os.environ.get(
                "BR_DS000114_QSIPREP_ROOT",
                str(
                    PROJECT_ROOT
                    / "outputs"
                    / "_a4_ds000114_linebisection"
                    / "derivatives_local"
                    / "ds000114-qsiprep"
                ),
            ),
        )
    )


def _require_subject(bids_root: Path) -> tuple[str, Path]:
    subject_dirs = sorted(path for path in bids_root.glob("sub-*") if path.is_dir())
    if not subject_dirs:
        pytest.skip(f"No subject directories found under {bids_root}")
    subject_dir = subject_dirs[0]
    participant_label = subject_dir.name.removeprefix("sub-")
    return participant_label, subject_dir


def _require_subject_with_pattern(
    bids_root: Path, pattern: str, *, label: str
) -> tuple[str, Path]:
    subject_dirs = sorted(path for path in bids_root.glob("sub-*") if path.is_dir())
    if not subject_dirs:
        pytest.skip(f"No subject directories found under {bids_root}")
    for subject_dir in subject_dirs:
        if next(subject_dir.rglob(pattern), None) is not None:
            return subject_dir.name.removeprefix("sub-"), subject_dir
    pytest.skip(f"No {label} found under any subject in {bids_root}")


def _workflow_step_payload(res) -> tuple[dict, dict]:
    payload = (res.data or {}).get("outputs") or {}
    outputs = payload.get("outputs") or {}
    summary = payload.get("summary") or {}
    return outputs, summary


def _mean_fd(confounds_tsv: Path) -> float:
    df = pd.read_csv(confounds_tsv, sep="\t")
    if "framewise_displacement" not in df.columns:
        raise ValueError(f"Missing framewise_displacement in {confounds_tsv}")
    fd = pd.to_numeric(df["framewise_displacement"], errors="coerce").dropna()
    return float(fd.mean()) if not fd.empty else float("nan")


def _build_preprocessing_qc_tsv(tmp_path: Path, fmriprep_root: Path) -> Path:
    confounds = sorted(
        fmriprep_root.glob("sub-*/ses-*/func/*_desc-confounds_timeseries.tsv")
    )
    if not confounds:
        pytest.skip(f"No confounds TSVs found under {fmriprep_root}")

    rows: list[dict[str, object]] = []
    for confounds_tsv in confounds:
        rows.append(
            {
                "run_id": confounds_tsv.stem.removesuffix(
                    "_desc-confounds_timeseries"
                ),
                "fd_mean": _mean_fd(confounds_tsv),
            }
        )

    qc_tsv = tmp_path / "precomputed_qc.tsv"
    pd.DataFrame(rows).to_csv(qc_tsv, sep="\t", index=False)
    return qc_tsv


def _require_qsirecon_subject(qsiprep_root: Path) -> str | None:
    subject_dirs = sorted(path for path in qsiprep_root.glob("sub-*") if path.is_dir())
    if not subject_dirs:
        return None
    return subject_dirs[0].name.removeprefix("sub-")


def _require_executable(binary: str, env_var: str) -> str:
    resolved = _resolve_bids_app_executable(binary, env_var=env_var)
    if os.path.isabs(resolved):
        if not os.path.exists(resolved):
            pytest.skip(f"Resolved executable does not exist: {resolved}")
        return resolved
    if shutil.which(resolved):
        return resolved
    pytest.skip(f"Executable not available for {binary}: {resolved}")


def _require_fs_license() -> str:
    license_file = _find_freesurfer_license()
    if not license_file:
        pytest.skip("FreeSurfer license not found")
    return license_file


def _resolve_fastsurfer_runtime() -> tuple[str, str | None]:
    apptainer_image = _resolve_fastsurfer_image(runtime="apptainer")
    if os.path.exists(apptainer_image) and shutil.which("apptainer"):
        return "apptainer", apptainer_image
    if shutil.which("docker"):
        return "docker", None
    pytest.skip("Neither apptainer+FastSurfer image nor docker is available")


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(21600)
def test_workflow_preprocessing_qc_minimal_execute_gate(tmp_path: Path):
    _execute_gate_enabled("workflow_preprocessing_qc")
    bids_root = _default_bids_root()
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")

    fmriprep_root = _default_fmriprep_root()
    if not fmriprep_root.exists():
        pytest.skip(f"Reference fMRIPrep derivatives not found: {fmriprep_root}")

    _require_executable("fmriprep", "BR_FMRIPREP_BIN")
    _require_executable("mriqc", "BR_MRIQC_BIN")
    fs_license = _require_fs_license()
    participant_label, _ = _require_subject(bids_root)
    qc_tsv = _build_preprocessing_qc_tsv(tmp_path, fmriprep_root)

    res = execute_tool(
        "workflow_preprocessing_qc",
        {
            "bids_dir": str(bids_root),
            "output_dir": str(tmp_path / "preprocessing_qc"),
            "participant_label": [participant_label],
            "work_dir": str(tmp_path / "preprocessing_qc_work"),
            "fs_license_file": fs_license,
            "output_spaces": ["MNI152NLin2009cAsym"],
            "analysis_level": "participant",
            "modalities": ["bold"],
            "qc_tsv": str(qc_tsv),
            "outlier_metric": "fd_mean",
            "outlier_z": 3.0,
            "n_cpus": 4,
            "omp_nthreads": 2,
            "mem_mb": 16000,
            "n_procs": 4,
            "mem_gb": 8,
            "dry_run": False,
            "extra_args": ["--skip-bids-validation"],
        },
    )
    assert res.status == "success", res.error

    steps = (res.data or {}).get("steps") or {}
    fmriprep_payload = (steps.get("fmriprep") or {}).get("data") or {}
    mriqc_payload = (steps.get("mriqc") or {}).get("data") or {}
    qc_table_payload = (steps.get("qc_table") or {}).get("data") or {}
    aggregate_payload = (steps.get("aggregate") or {}).get("data") or {}
    dashboard_payload = (steps.get("dashboard") or {}).get("data") or {}

    assert (fmriprep_payload.get("summary") or {}).get("backend") == (
        "wrapper_executable"
    )
    assert (mriqc_payload.get("summary") or {}).get("backend") == (
        "wrapper_executable"
    )
    assert Path(fmriprep_payload["outputs"]["dataset_description"]).exists()
    assert Path(fmriprep_payload["outputs"]["derivatives_dir"]).exists()
    assert Path(mriqc_payload["outputs"]["mriqc_dir"]).exists()
    assert Path(qc_table_payload["outputs"]["qc_table"]).exists()
    assert Path(aggregate_payload["outputs"]["summary"]).exists()
    assert Path(dashboard_payload["outputs"]["dashboard"]).exists()


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(21600)
def test_workflow_fmriprep_preprocessing_minimal_execute_gate(tmp_path: Path):
    _execute_gate_enabled("workflow_fmriprep_preprocessing")
    bids_root = _default_bids_root()
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")

    _require_executable("fmriprep", "BR_FMRIPREP_BIN")
    fs_license = _require_fs_license()
    participant_label, _ = _require_subject(bids_root)

    res = execute_tool(
        "workflow_fmriprep_preprocessing",
        {
            "bids_dir": str(bids_root),
            "output_dir": str(tmp_path / "fmriprep"),
            "participant_label": [participant_label],
            "work_dir": str(tmp_path / "fmriprep_work"),
            "fs_license_file": fs_license,
            "output_spaces": ["MNI152NLin2009cAsym"],
            "n_cpus": 4,
            "omp_nthreads": 2,
            "mem_mb": 16000,
            "dry_run": False,
            "extra_args": ["--skip-bids-validation"],
        },
    )
    assert res.status == "success", res.error
    outputs, summary = _workflow_step_payload(res)
    assert summary.get("backend") == "wrapper_executable"
    dataset_description = Path(outputs["dataset_description"])
    derivatives_dir = Path(outputs["derivatives_dir"])
    assert dataset_description.exists()
    assert derivatives_dir.exists()


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(21600)
def test_workflow_mriqc_minimal_execute_gate(tmp_path: Path):
    _execute_gate_enabled("workflow_mriqc")
    bids_root = _default_bids_root()
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")

    _require_executable("mriqc", "BR_MRIQC_BIN")
    participant_label, _ = _require_subject(bids_root)

    res = execute_tool(
        "workflow_mriqc",
        {
            "bids_dir": str(bids_root),
            "output_dir": str(tmp_path / "mriqc"),
            "analysis_level": "participant",
            "participant_label": [participant_label],
            "modalities": ["bold"],
            "work_dir": str(tmp_path / "mriqc_work"),
            "n_procs": 4,
            "mem_gb": 8,
            "dry_run": False,
        },
    )
    assert res.status == "success", res.error
    outputs, summary = _workflow_step_payload(res)
    assert summary.get("backend") == "wrapper_executable"
    mriqc_dir = Path(outputs["mriqc_dir"])
    assert mriqc_dir.exists()
    assert any(mriqc_dir.glob("sub-*.html"))


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(21600)
def test_workflow_qsiprep_minimal_execute_gate(tmp_path: Path):
    _execute_gate_enabled("workflow_qsiprep")
    bids_root = _default_qsiprep_bids_root()
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")

    _require_executable("qsiprep", "BR_QSIPREP_BIN")
    fs_license = _require_fs_license()
    participant_label, _ = _require_subject_with_pattern(
        bids_root,
        "*_dwi.nii.gz",
        label="DWI input",
    )

    res = execute_tool(
        "workflow_qsiprep",
        {
            "bids_dir": str(bids_root),
            "output_dir": str(tmp_path / "qsiprep"),
            "participant_label": [participant_label],
            "work_dir": str(tmp_path / "qsiprep_work"),
            "fs_license_file": fs_license,
            "n_cpus": 4,
            "omp_nthreads": 2,
            "mem_mb": 16000,
            "extra_args": ["--skip-bids-validation"],
            "dry_run": False,
        },
    )
    assert res.status == "success", res.error
    outputs, summary = _workflow_step_payload(res)
    assert summary.get("backend") == "wrapper_executable"
    dataset_description = Path(outputs["dataset_description"])
    derivatives_dir = Path(outputs["derivatives_dir"])
    assert dataset_description.exists()
    assert derivatives_dir.exists()


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(21600)
def test_workflow_smriprep_minimal_execute_gate(tmp_path: Path):
    _execute_gate_enabled("workflow_smriprep")
    bids_root = _default_smriprep_bids_root()
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")

    _require_executable("smriprep", "BR_SMRIPREP_BIN")
    fs_license = _require_fs_license()
    participant_label, _ = _require_subject_with_pattern(
        bids_root,
        "*_T1w.nii.gz",
        label="T1w input",
    )

    res = execute_tool(
        "workflow_smriprep",
        {
            "bids_dir": str(bids_root),
            "output_dir": str(tmp_path / "smriprep"),
            "participant_label": [participant_label],
            "work_dir": str(tmp_path / "smriprep_work"),
            "fs_license_file": fs_license,
            "extra_args": ["--skip-bids-validation"],
            "dry_run": False,
        },
    )
    assert res.status == "success", res.error
    outputs, summary = _workflow_step_payload(res)
    assert summary.get("backend") == "wrapper_executable"
    dataset_description = Path(outputs["dataset_description"])
    derivatives_dir = Path(outputs["derivatives_dir"])
    assert dataset_description.exists()
    assert derivatives_dir.exists()


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(21600)
def test_workflow_qsirecon_minimal_execute_gate(monkeypatch, tmp_path: Path):
    _execute_gate_enabled("workflow_qsirecon")
    qsiprep_root = _default_qsiprep_root()
    if not qsiprep_root.exists():
        pytest.skip(f"QSIPrep derivatives not found: {qsiprep_root}")

    _require_executable("qsirecon", "BR_QSIRECON_BIN")
    participant_label = _require_qsirecon_subject(qsiprep_root)
    monkeypatch.setenv("BR_QSIRECON_EXECUTE", "1")

    params = {
        "qsiprep_dir": str(qsiprep_root),
        "output_dir": str(tmp_path / "qsirecon"),
        "recon_spec": "mrtrix_multishell_msmt_ACT-hsvs",
    }
    if participant_label:
        params["participant_label"] = [participant_label]

    res = execute_tool("workflow_qsirecon", params)
    assert res.status == "success", res.error
    outputs, summary = _workflow_step_payload(res)
    assert summary.get("backend") == "wrapper_executable"
    assert Path(outputs["qsirecon_dir"]).exists()


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(21600)
def test_workflow_fastsurfer_minimal_execute_gate(tmp_path: Path):
    _execute_gate_enabled("workflow_fastsurfer")
    bids_root = _default_bids_root()
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")

    fs_license = _require_fs_license()
    subject_id, subject_dir = _require_subject(bids_root)
    runtime, container_image = _resolve_fastsurfer_runtime()

    t1w = next(subject_dir.rglob("*_T1w.nii.gz"), None)
    if t1w is None:
        pytest.skip(f"No T1w image found under {subject_dir}")

    res = execute_tool(
        "workflow_fastsurfer",
        {
            "t1w_image": str(t1w),
            "subject_id": f"sub-{subject_id}",
            "output_dir": str(tmp_path / "fastsurfer_out"),
            "fs_license_file": fs_license,
            "n_threads": 1,
            "use_gpu": False,
            "runtime": runtime,
            "container_image": container_image,
            "dry_run": False,
        },
    )
    assert res.status == "success", res.error
    outputs, summary = _workflow_step_payload(res)
    assert summary.get("backend") == "fastsurfer_container"
    assert summary.get("runtime") == runtime
    assert Path(outputs["subject_dir"]).exists()
    assert Path(outputs["surfaces_dir"]).exists()
    assert Path(outputs["aseg_volume"]).exists()
    assert Path(outputs["aparcaseg_volume"]).exists()
