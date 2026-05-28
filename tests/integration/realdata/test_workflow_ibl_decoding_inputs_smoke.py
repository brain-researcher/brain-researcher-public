from __future__ import annotations

from pathlib import Path

import pytest

from brain_researcher.services.tools.executor import execute_tool

_IBL_PUBLIC_ROOT = Path(
    "/app/data/public_s3/ibl-brain-wide-map-public"
)


@pytest.mark.realdata
@pytest.mark.slow
def test_workflow_ibl_decoding_inputs_smoke(tmp_path: Path):
    if not _IBL_PUBLIC_ROOT.exists():
        pytest.skip("Mounted IBL public dataset is unavailable")

    builder_out = tmp_path / "workflow_ibl_decoding_inputs"
    result = execute_tool(
        "workflow_ibl_decoding_inputs",
        {
            "dataset_ref": "ds:manual:ibl_brainwide",
            "session_id": "CSHL049/2020-01-08/001",
            "probe_label": "probe00",
            "label_field": "choice",
            "feature_level": "region",
            "group_by": "session",
            "output_dir": str(builder_out),
            "dry_run": False,
        },
    )
    assert result.status == "success", result.error

    assert (builder_out / "X.npy").exists()
    assert (builder_out / "y.npy").exists()
    assert (builder_out / "groups.npy").exists()
    assert (builder_out / "sample_metadata.parquet").exists()
    assert (builder_out / "feature_metadata.parquet").exists()
    assert (builder_out / "metadata.json").exists()

    ml_out = tmp_path / "ibl_ml_decoding"
    ml_result = execute_tool(
        "workflow_ml_decoding_pipeline",
        {
            "data_file": str(builder_out / "X.npy"),
            "labels_file": str(builder_out / "y.npy"),
            "groups_file": str(builder_out / "groups.npy"),
            "cv_type": "kfold",
            "n_splits": 2,
            "task_type": "classification",
            "output_dir": str(ml_out),
        },
    )
    assert ml_result.status == "success", ml_result.error
    assert (ml_out / "cv" / "cv_summary.json").exists()
    assert (ml_out / "decoder" / "mvpa_summary.json").exists()
