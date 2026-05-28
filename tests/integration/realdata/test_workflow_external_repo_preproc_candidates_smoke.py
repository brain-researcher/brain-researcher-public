"""Real-data smoke tests for candidate external-repo workflows.

These workflows are preview-first adapters over mature external repositories.
They intentionally avoid heavy container execution in CI and instead verify that
the declarative workflow surface resolves commands or stub outputs correctly on
real dataset paths when available.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


def _default_bids_root() -> Path:
    return Path(
        os.environ.get(
            "BR_DS000114_BIDS_ROOT",
            PROJECT_ROOT / "out" / "openneuro_local" / "ds000114" / "bids",
        )
    )


def _default_qsiprep_root() -> Path:
    return Path(
        os.environ.get(
            "BR_DS000114_QSIPREP_ROOT",
            PROJECT_ROOT
            / "outputs"
            / "_a4_ds000114_linebisection"
            / "derivatives_local"
            / "ds000114-qsiprep",
        )
    )


@pytest.mark.realdata
@pytest.mark.timeout(300)
def test_workflow_fmriprep_preprocessing_ds000114_smoke(tmp_path: Path):
    bids_root = _default_bids_root()
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")

    res = execute_tool(
        "workflow_fmriprep_preprocessing",
        {
            "bids_dir": str(bids_root),
            "output_dir": str(tmp_path / "fmriprep"),
            "dry_run": True,
            "extra_args": ["--skip-bids-validation"],
        },
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("app") == "fmriprep"
    command = outputs.get("command")
    assert isinstance(command, list)
    assert command[1] == str(bids_root)


@pytest.mark.realdata
@pytest.mark.timeout(300)
def test_workflow_mriqc_ds000114_smoke(tmp_path: Path):
    bids_root = _default_bids_root()
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")

    res = execute_tool(
        "workflow_mriqc",
        {
            "bids_dir": str(bids_root),
            "output_dir": str(tmp_path / "mriqc"),
            "dry_run": True,
            "modalities": ["bold"],
        },
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("app") == "mriqc"
    command = outputs.get("command")
    assert isinstance(command, list)
    assert any("participant" == str(arg) for arg in command)


@pytest.mark.realdata
@pytest.mark.timeout(300)
def test_workflow_qsiprep_ds000114_smoke(tmp_path: Path):
    bids_root = _default_bids_root()
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")

    res = execute_tool(
        "workflow_qsiprep",
        {
            "bids_dir": str(bids_root),
            "output_dir": str(tmp_path / "qsiprep"),
            "dry_run": True,
            "extra_args": ["--skip-bids-validation"],
        },
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("app") == "qsiprep"
    command = outputs.get("command")
    assert isinstance(command, list)
    assert command[1] == str(bids_root)


@pytest.mark.realdata
@pytest.mark.timeout(300)
def test_workflow_smriprep_ds000114_smoke(tmp_path: Path):
    bids_root = _default_bids_root()
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")

    res = execute_tool(
        "workflow_smriprep",
        {
            "bids_dir": str(bids_root),
            "output_dir": str(tmp_path / "smriprep"),
            "dry_run": True,
            "extra_args": ["--skip-bids-validation"],
        },
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("app") == "smriprep"
    command = outputs.get("command")
    assert isinstance(command, list)
    assert command[1] == str(bids_root)


@pytest.mark.realdata
@pytest.mark.timeout(300)
def test_workflow_qsirecon_smoke(tmp_path: Path):
    qsiprep_root = _default_qsiprep_root()
    if not qsiprep_root.exists():
        pytest.skip(f"QSIPrep derivatives not found: {qsiprep_root}")

    res = execute_tool(
        "workflow_qsirecon",
        {
            "qsiprep_dir": str(qsiprep_root),
            "output_dir": str(tmp_path / "qsirecon"),
            "recon_spec": "mrtrix_multishell_msmt_ACT-hsvs",
            "dry_run": True,
        },
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    command = outputs.get("command")
    assert isinstance(command, list)
    assert "--recon-spec" in command


@pytest.mark.realdata
@pytest.mark.timeout(300)
def test_workflow_fastsurfer_ds000114_smoke(tmp_path: Path):
    bids_root = _default_bids_root()
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")

    t1w = next(bids_root.rglob("*_T1w.nii.gz"), None)
    if t1w is None:
        pytest.skip(f"No T1w image found under {bids_root}")

    res = execute_tool(
        "workflow_fastsurfer",
        {
            "t1w_image": str(t1w),
            "subject_id": "sub-01",
            "output_dir": str(tmp_path / "fastsurfer"),
            "dry_run": True,
        },
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("dry_run") is True
    command = outputs.get("command")
    assert isinstance(command, list)
    assert command[0] == "run_fastsurfer.sh"
