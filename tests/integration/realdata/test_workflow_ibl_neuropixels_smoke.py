from __future__ import annotations

from pathlib import Path

import pytest

from brain_researcher.services.tools.ibl_tools import IBLNeuropixelsWorkflowTool

_IBL_PUBLIC_ROOT = Path(
    "/app/data/public_s3/ibl-brain-wide-map-public"
)


@pytest.mark.slow
def test_workflow_ibl_neuropixels_smoke(tmp_path: Path):
    if not _IBL_PUBLIC_ROOT.exists():
        pytest.skip("Mounted IBL public dataset is unavailable")

    result = IBLNeuropixelsWorkflowTool()._run(
        dataset_ref="ds:manual:ibl_brainwide",
        session_id="CSHL049/2020-01-08/001",
        probe_label="probe00",
        output_dir=str(tmp_path / "workflow_ibl_neuropixels"),
        max_duration_s=60,
        spike_limit=5000,
        pose_backend="lightning_pose",
        include_pose=True,
        dry_run=False,
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    assert Path(outputs["workflow_summary_file"]["path"]).exists()
    assert Path(outputs["aligned_timeseries_path"]).exists()
    assert Path(outputs["features_table_path"]).exists()
