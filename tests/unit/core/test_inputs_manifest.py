import json
from pathlib import Path

from brain_researcher.core.analysis_bundle import save_analysis_bundle
from brain_researcher.core.inputs_manifest import save_inputs_manifest


class DummyJob:
    def __init__(
        self,
        run_dir: Path,
        *,
        job_id: str = "job-1",
        run_id: str = "run-1",
        payload: dict | None = None,
    ):
        self.run_dir = str(run_dir)
        self.id = job_id
        self.run_id = run_id
        self.payload_json = json.dumps(payload or {})


def test_save_inputs_manifest_emits_checksums_and_bundle_picks_it_up(tmp_path: Path):
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()

    inp = run_dir / "input.txt"
    inp.write_text("hello", encoding="utf-8")

    payload = {
        "plan": {
            "steps": [
                {"tool": "extract_timeseries", "params": {"img": str(inp)}},
            ]
        }
    }
    job = DummyJob(run_dir, payload=payload)

    save_inputs_manifest(job, run_dir)
    manifest_path = run_dir / "inputs_manifest.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "inputs-manifest-v1"
    assert manifest["inputs"]
    first = manifest["inputs"][0]
    assert first["checksum_status"] == "ok"
    assert first["checksum"].startswith("sha256:")

    # Ensure bundle wires it in (pointer + embedded doc + file manifest role).
    (run_dir / "trajectory.json").write_text('{"schema_version":"ATIF-v1.4"}', encoding="utf-8")
    (run_dir / "observation.json").write_text(
        json.dumps(
            {
                "schema_version": "observation-v1",
                "job_id": "job-1",
                "run_id": "run-1",
                "state": "succeeded",
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )

    save_analysis_bundle(job, run_dir)
    bundle = json.loads((run_dir / "analysis_bundle.json").read_text(encoding="utf-8"))
    assert bundle["files"]["inputs_manifest_json"] == "inputs_manifest.json"
    assert bundle.get("inputs_manifest", {}).get("schema_version") == "inputs-manifest-v1"
    roles = {entry["role"] for entry in bundle.get("file_manifest", [])}
    assert "inputs_manifest" in roles

