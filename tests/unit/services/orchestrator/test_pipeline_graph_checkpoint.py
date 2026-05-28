from brain_researcher.services.orchestrator.pipeline_graph import (
    build_job_graph_snapshot,
)


def test_pipeline_graph_snapshot_uses_canonical_checkpoint_id():
    snapshot = build_job_graph_snapshot(None, job_id="job-123")

    assert snapshot["checkpoint_id"] == 0
    assert "last_checkpoint_id" not in snapshot
