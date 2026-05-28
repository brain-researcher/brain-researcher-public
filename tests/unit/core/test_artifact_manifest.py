import json
from pathlib import Path

from brain_researcher.core.artifact_manifest import save_artifact_manifest


class DummyJob:
    def __init__(self, run_dir: Path, payload_json: str):
        self.run_dir = str(run_dir)
        self.payload_json = payload_json


def test_save_artifact_manifest_includes_qc_reports(tmp_path: Path):
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "output.txt").write_text("ok", encoding="utf-8")
    (run_dir / "qc_report.json").write_text('{"ok": true}', encoding="utf-8")

    observation = {
        "schema_version": "observation-v1",
        "artifacts": [
            {"name": "output.txt", "type": "text", "path": "output.txt", "size": 2}
        ],
    }
    (run_dir / "observation.json").write_text(
        json.dumps(observation), encoding="utf-8"
    )

    job = DummyJob(run_dir, payload_json=json.dumps({"artifacts": []}))
    save_artifact_manifest(job, run_dir)

    manifest_path = run_dir / "artifact_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema_version"] == "artifact-manifest-v1"
    assert manifest["artifacts"]
    artifact = manifest["artifacts"][0]
    assert artifact["checksum_status"] == "ok"
    assert artifact["checksum"].startswith("sha256:")
    assert manifest["qc_reports"][0]["path"] == "qc_report.json"
