import json
from pathlib import Path

from brain_researcher.services.orchestrator.observation import build_observation
from brain_researcher.services.orchestrator.job_store import JobRecord


def test_behavior_policy_surfaces_in_observation(tmp_path: Path):
    # Prepare artifact with behavior policy
    events_path = tmp_path / "events.tsv"
    events_path.write_text("onset\tduration\n0\t1\n", encoding="utf-8")
    artifact = {
        "name": "events.tsv",
        "path": str(events_path),
        "type": "behavior_events",
        "metadata": {
            "policy_id": "behavior_default_v1",
            "sidecar": str(events_path.with_suffix(".json")),
            "sidecar_sha256": "sha256:sidecar123",
        },
        "checksum": "sha256:events123",
    }

    record = JobRecord(
        job_id="job1",
        kind="tool",
        payload_json=json.dumps({"artifacts": [artifact]}),
        state="success",
        run_dir=str(tmp_path),
        run_id="run1",
    )

    spec = build_observation(
        record=record,
        run_dir=tmp_path,
        provenance=None,
        steps=[],
        artifacts=[artifact],
        diagnostics_summary=None,
        violations=None,
    )

    assert spec.diagnostics_summary is not None
    assert spec.diagnostics_summary.get("behavior", {}).get("policies") == [
        "behavior_default_v1"
    ]
    assert spec.diagnostics_summary.get("behavior", {}).get("events_checksum") == "sha256:events123"
    assert spec.diagnostics_summary.get("behavior", {}).get("sidecar_checksum") == "sha256:sidecar123"
    # Artifacts preserved
    assert spec.artifacts and spec.artifacts[0]["metadata"]["policy_id"] == "behavior_default_v1"
