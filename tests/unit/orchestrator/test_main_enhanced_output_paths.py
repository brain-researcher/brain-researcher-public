from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from brain_researcher.services.orchestrator.main_enhanced import (
    _attach_plan_execution_artifacts,
    _attach_tool_output_artifacts,
    _derive_cross_pod_tool_run_dir,
    _normalize_generic_tool_output_args,
    _normalize_plan_output_dirs_for_job,
    _sync_mirrored_tool_outputs,
)
from brain_researcher.services.shared.planner.models import Plan, PlanDAG, StepSpec


def test_normalize_generic_tool_output_args_anchors_relative_paths(tmp_path: Path):
    args = {
        "output_dir": "outputs/nilearn_connectivity",
        "output_file": "reports/connectivity_matrix.npy",
        "report_file": "reports/summary.html",
        "img": "/data/sub-01_bold.nii.gz",
    }

    normalized = _normalize_generic_tool_output_args(
        args,
        run_dir=str(tmp_path),
        pipeline_hint="connectivity",
        tool_hint="workflow_rest_connectome_e2e",
    )

    assert normalized["output_dir"] == str(
        (tmp_path / "outputs" / "nilearn_connectivity").resolve()
    )
    assert normalized["output_file"] == str(
        (tmp_path / "reports" / "connectivity_matrix.npy").resolve()
    )
    assert normalized["report_file"] == str(
        (tmp_path / "reports" / "summary.html").resolve()
    )
    assert normalized["img"] == "/data/sub-01_bold.nii.gz"


def test_normalize_generic_tool_output_args_sets_default_output_dir(tmp_path: Path):
    args = {
        "output_file": "connectivity.npy",
    }

    normalized = _normalize_generic_tool_output_args(
        args,
        run_dir=str(tmp_path),
        pipeline_hint="nilearn connectivity",
        tool_hint="workflow_rest_connectome_e2e",
    )

    assert normalized["output_dir"] == str(
        (tmp_path / "outputs" / "nilearn_connectivity").resolve()
    )
    assert normalized["output_file"] == str((tmp_path / "connectivity.npy").resolve())


def test_normalize_generic_tool_output_args_can_force_job_output_dir(tmp_path: Path):
    old_output_dir = "/app/jobstore/runs/ds000114/workflow_rest_connectome_e2e"
    args = {
        "output_dir": old_output_dir,
        "output_file": f"{old_output_dir}/connectivity.npy",
        "report_file": f"{old_output_dir}/reports/summary.html",
    }

    normalized = _normalize_generic_tool_output_args(
        args,
        run_dir=str(tmp_path),
        pipeline_hint="connectivity",
        tool_hint="workflow_rest_connectome_e2e",
        force_job_output_dir=True,
    )

    assert normalized["output_dir"] == str(tmp_path.resolve())
    assert normalized["output_file"] == str((tmp_path / "connectivity.npy").resolve())
    assert normalized["report_file"] == str(
        (tmp_path / "reports" / "summary.html").resolve()
    )


def test_normalize_generic_tool_output_args_no_run_dir_is_noop():
    args = {
        "output_dir": "outputs/nilearn_connectivity",
        "output_file": "connectivity.npy",
    }

    normalized = _normalize_generic_tool_output_args(
        args,
        run_dir=None,
        pipeline_hint="connectivity",
        tool_hint="workflow_rest_connectome_e2e",
    )

    assert normalized == args


def test_normalize_plan_output_dirs_for_job_reanchors_existing_output_dir(
    monkeypatch, tmp_path: Path
):
    run_root = tmp_path / "runs"
    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(run_root))
    monkeypatch.setattr("brain_researcher.config.run_artifacts._config", None)

    original_output_dir = "/app/jobstore/runs/ds000114/workflow_rest_connectome_e2e"
    plan = Plan(
        plan_id="plan_connectome",
        domain="neuroimaging",
        modality=["fmri"],
        dag=PlanDAG(
            steps=[
                StepSpec(
                    id="connectome",
                    tool="workflow_rest_connectome_e2e",
                    params={
                        "bids_dir": "/app/data/OpenNeuro/ds000114",
                        "output_dir": original_output_dir,
                        "output_file": f"{original_output_dir}/connectivity_matrix.npy",
                        "report_file": f"{original_output_dir}/reports/connectivity.html",
                    },
                    runtime_kind="python",
                )
            ]
        ),
    )
    job = SimpleNamespace(
        id="job_isolated_outputs",
        run_dir=None,
        run_id=None,
        metadata={"pipeline": "connectivity"},
    )

    normalized = _normalize_plan_output_dirs_for_job(job, plan)

    assert Path(job.run_dir).name == "job_isolated_outputs"
    assert normalized.dag.steps[0].params["output_dir"] == job.run_dir
    assert normalized.dag.steps[0].params["output_file"] == str(
        Path(job.run_dir) / "connectivity_matrix.npy"
    )
    assert normalized.dag.steps[0].params["report_file"] == str(
        Path(job.run_dir) / "reports" / "connectivity.html"
    )
    assert normalized.dag.steps[0].params["bids_dir"] == "/app/data/OpenNeuro/ds000114"
    assert plan.dag.steps[0].params["output_dir"] == original_output_dir
    assert plan.dag.steps[0].params["output_file"] == (
        f"{original_output_dir}/connectivity_matrix.npy"
    )
    assert job.metadata["plan_execution_run_dir"] == job.run_dir
    assert job.metadata["plan_execution_tool_run_dir"] == job.run_dir


def test_normalize_plan_output_dirs_for_job_adds_output_dir_for_workflow_step(
    monkeypatch, tmp_path: Path
):
    run_root = tmp_path / "runs"
    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(run_root))
    monkeypatch.setattr("brain_researcher.config.run_artifacts._config", None)

    plan = Plan(
        plan_id="plan_connectome",
        domain="neuroimaging",
        modality=["fmri"],
        dag=PlanDAG(
            steps=[
                StepSpec(
                    id="connectome",
                    tool="workflow_rest_connectome_e2e",
                    params={"bids_dir": "/app/data/OpenNeuro/ds000114"},
                    runtime_kind="python",
                ),
                StepSpec(
                    id="search",
                    tool="literature_search",
                    params={"query": "connectome"},
                    runtime_kind="python",
                ),
            ]
        ),
    )
    job = SimpleNamespace(
        id="job_workflow_default_output",
        run_dir=None,
        run_id=None,
        metadata={"pipeline": "connectivity"},
    )

    normalized = _normalize_plan_output_dirs_for_job(job, plan)

    assert normalized.dag.steps[0].params["output_dir"] == job.run_dir
    assert "output_dir" not in normalized.dag.steps[1].params


def test_derive_cross_pod_tool_run_dir_maps_shared_root(monkeypatch, tmp_path: Path):
    source_root = tmp_path / "source-runs"
    shared_root = tmp_path / "shared-runs"
    run_dir = source_root / "20260228" / "job_test"
    run_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("BR_GENERIC_TOOL_SOURCE_ROOT", str(source_root))
    monkeypatch.setenv("BR_GENERIC_TOOL_SHARED_ROOT", str(shared_root))

    mapped = _derive_cross_pod_tool_run_dir(str(run_dir))

    assert mapped == str((shared_root / "20260228" / "job_test").resolve())


def test_sync_mirrored_tool_outputs_copies_files(tmp_path: Path):
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    (source_root / "outputs").mkdir(parents=True, exist_ok=True)
    source_file = source_root / "outputs" / "connectivity_matrix.npy"
    source_file.write_bytes(b"matrix-bytes")

    _sync_mirrored_tool_outputs(
        source_run_dir=str(source_root),
        target_run_dir=str(target_root),
    )

    copied = target_root / "outputs" / "connectivity_matrix.npy"
    assert copied.exists()
    assert copied.read_bytes() == b"matrix-bytes"


def test_attach_tool_output_artifacts_discovers_outputs(tmp_path: Path):
    outputs_dir = tmp_path / "outputs" / "nilearn_connectivity"
    probe_dir = outputs_dir / "review_probes"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    probe_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = outputs_dir / "connectivity_matrix.npy"
    feature_contract_path = outputs_dir / "feature_contract.json"
    label_permutation_path = probe_dir / "label_permutation_null.json"
    matrix_path.write_bytes(b"matrix")
    feature_contract_path.write_text('{"matrix_kind":"correlation"}', encoding="utf-8")
    label_permutation_path.write_text(
        '{"pipeline_scope":"full_pipeline"}', encoding="utf-8"
    )

    job = SimpleNamespace(run_dir=str(tmp_path), artifacts=[])
    raw_payload = {
        "status": "success",
        "result": {
            "data": {
                "outputs": {
                    "matrix": str(matrix_path),
                    "feature_contract": str(feature_contract_path),
                    "label_permutation_null": str(label_permutation_path),
                }
            }
        },
    }

    _attach_tool_output_artifacts(
        job=job, job_id="job_demo123", raw_payload=raw_payload
    )

    artifact_paths = {artifact.meta.get("path"): artifact for artifact in job.artifacts}
    assert {
        "outputs/nilearn_connectivity/connectivity_matrix.npy",
        "outputs/nilearn_connectivity/feature_contract.json",
        "outputs/nilearn_connectivity/review_probes/label_permutation_null.json",
    } <= set(artifact_paths)
    artifact = artifact_paths["outputs/nilearn_connectivity/connectivity_matrix.npy"]
    assert artifact.name == "connectivity_matrix.npy"
    assert (
        "/api/jobs/job_demo123/artifacts/files/outputs/nilearn_connectivity/connectivity_matrix.npy"
        in artifact.url
    )


def test_attach_plan_execution_artifacts_mirrors_step_outputs(
    monkeypatch, tmp_path: Path
):
    source_root = tmp_path / "shared" / "ds000114" / "workflow_rest_connectome_e2e"
    (source_root / "timeseries").mkdir(parents=True, exist_ok=True)
    matrix_path = source_root / "connectivity_matrix.npy"
    timeseries_path = source_root / "timeseries" / "timeseries.npy"
    csv_path = source_root / "timeseries" / "timeseries.csv"
    feature_contract_path = source_root / "feature_contract.json"
    matrix_path.write_bytes(b"matrix")
    timeseries_path.write_bytes(b"timeseries")
    csv_path.write_text("roi,value\n", encoding="utf-8")
    feature_contract_path.write_text('{"matrix_kind":"correlation"}', encoding="utf-8")

    run_root = tmp_path / "runs"
    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(run_root))
    monkeypatch.setattr("brain_researcher.config.run_artifacts._config", None)
    job = SimpleNamespace(
        run_dir=None,
        run_id=None,
        metadata={"parameters": {"output_dir": str(source_root)}},
        artifacts=[],
    )
    events = [
        {
            "event": "step_completed",
            "data": {
                "produces": {
                    "data": {
                        "outputs": {
                            "matrix": str(matrix_path),
                            "timeseries": str(timeseries_path),
                            "timeseries_csv": str(csv_path),
                            "feature_contract": str(feature_contract_path),
                        }
                    }
                }
            },
        }
    ]

    _attach_plan_execution_artifacts(job, "job_plan_outputs", events)

    assert job.run_id == "job_plan_outputs"
    assert Path(job.run_dir).name == "job_plan_outputs"
    assert (Path(job.run_dir) / "connectivity_matrix.npy").exists()
    assert (Path(job.run_dir) / "timeseries" / "timeseries.npy").exists()
    assert (Path(job.run_dir) / "feature_contract.json").exists()
    artifact_names = {artifact.name for artifact in job.artifacts}
    assert {
        "connectivity_matrix.npy",
        "timeseries.npy",
        "timeseries.csv",
        "feature_contract.json",
    } <= artifact_names


def test_attach_plan_execution_artifacts_uses_source_dir_when_run_dir_unavailable(
    monkeypatch, tmp_path: Path
):
    source_root = tmp_path / "shared" / "workflow_rest_connectome_e2e"
    source_root.mkdir(parents=True, exist_ok=True)
    matrix_path = source_root / "connectivity_matrix.npy"
    matrix_path.write_bytes(b"matrix")

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.main_enhanced._ensure_job_run_dir",
        lambda job, job_id: None,
    )
    job = SimpleNamespace(
        run_dir=None,
        run_id=None,
        metadata={"parameters": {"output_dir": str(source_root)}},
        artifacts=[],
    )
    events = [
        {
            "event": "step_completed",
            "data": {"produces": {"data": {"outputs": {"matrix": str(matrix_path)}}}},
        }
    ]

    _attach_plan_execution_artifacts(job, "job_plan_outputs", events)

    assert job.run_id == "job_plan_outputs"
    assert job.run_dir == str(source_root.resolve())
    assert [artifact.name for artifact in job.artifacts] == ["connectivity_matrix.npy"]
