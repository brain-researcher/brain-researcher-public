import json
import tarfile
from pathlib import Path

from brain_researcher.cli.commands.traces_commands import export_traces


def test_export_traces_includes_optional_files(tmp_path: Path, monkeypatch):
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "observation.json").write_text('{"schema_version":"observation-v1"}', encoding="utf-8")
    (run_dir / "trace.jsonl").write_text(
        '{"schema_version":"trace-event-v1","run_id":"run-1","event_type":"tool_completed","timestamp":"2026-01-01T00:00:00Z","payload":{}}\n',
        encoding="utf-8",
    )
    (run_dir / "trajectory.json").write_text('{"schema_version":"ATIF-v1.4"}', encoding="utf-8")
    (run_dir / "analysis.json").write_text('{"schema_version":"analysis-manifest-v1"}', encoding="utf-8")
    (run_dir / "analysis_bundle.json").write_text('{"schema_version":"analysis-bundle-v1"}', encoding="utf-8")
    (run_dir / "artifact_manifest.json").write_text(
        '{"schema_version":"artifact-manifest-v1"}', encoding="utf-8"
    )
    (run_dir / "reward_breakdown.json").write_text('{"schema_version":"reward-v1"}', encoding="utf-8")

    out = tmp_path / "traces_export.tar.gz"
    monkeypatch.chdir(tmp_path)

    export_traces(
        run_dirs=[run_dir],
        from_root=None,
        glob="*",
        sqlite_jobstore=None,
        state=None,
        limit=500,
        output=out,
        version="trace-export-v1",
        deid=False,
    )

    assert out.exists()
    with tarfile.open(out, "r:gz") as tar:
        names = set(tar.getnames())
        assert "traces/run-1/observation.json" in names
        assert "traces/run-1/trace.jsonl" in names
        assert "traces/run-1/trajectory.json" in names
        assert "traces/run-1/analysis.json" in names
        assert "traces/run-1/analysis_bundle.json" in names
        assert "traces/run-1/artifact_manifest.json" in names
        assert "traces/run-1/reward_breakdown.json" in names
        manifest_member = tar.extractfile("traces/manifest.json")
        assert manifest_member is not None
        manifest = json.loads(manifest_member.read().decode("utf-8"))

    assert manifest["runs"][0]["analysis_json"] == "analysis.json"
    assert manifest["runs"][0]["analysis_bundle_json"] == "analysis_bundle.json"
    assert manifest["runs"][0]["artifact_manifest_json"] == "artifact_manifest.json"
    assert manifest["runs"][0]["reward_breakdown_json"] == "reward_breakdown.json"
    assert manifest["runs"][0]["trajectory_json"] == "trajectory.json"
