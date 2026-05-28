from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.tools.params.reproducibility_bundle import (
    ReproducibilityBundleParameters,
    build_reproducibility_bundle_payload,
    reproducibility_bundle_from_payload,
)


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_reproducibility_bundle_from_payload():
    params = reproducibility_bundle_from_payload(
        {"run_id": "run-123", "run_dir": "/tmp/run"}
    )
    assert isinstance(params, ReproducibilityBundleParameters)
    assert params.run_id == "run-123"
    assert params.run_dir == "/tmp/run"


def test_build_reproducibility_bundle_payload_uses_native_manifests(tmp_path):
    run_dir = tmp_path / "run-123"
    run_dir.mkdir()

    _write_json(
        run_dir / "analysis_bundle.json",
        {
            "schema_version": "analysis-bundle-v1",
            "versions": {"git_commit": "abc123", "brain_researcher_version": "1.0"},
            "policy": {"policy_id": "policy-1"},
        },
    )
    _write_json(
        run_dir / "inputs_manifest.json",
        {
            "datasets": [{"id": "ds000001"}],
            "inputs": [{"path": "bold.nii.gz", "checksum": "sha256:" + "a" * 64}],
        },
    )
    _write_json(
        run_dir / "artifact_manifest.json",
        {
            "artifacts": [
                {"path": "report.json", "checksum": "sha256:" + "b" * 64}
            ]
        },
    )
    _write_json(run_dir / "execution_manifest.json", {"parameters": {"tr": 2.0}})
    _write_json(run_dir / "observation.json", {"steps": [{"tool_id": "demo"}]})
    _write_json(
        run_dir / "run.json",
        {"status": "succeeded", "steps": [{"tool_id": "demo", "status": "succeeded"}]},
    )

    payload = build_reproducibility_bundle_payload("run-123", run_dir=run_dir)

    assert payload["run_id"] == "run-123"
    assert payload["analysis_bundle"]["schema_version"] == "analysis-bundle-v1"
    assert payload["component_status"]["analysis_bundle"] is True
    assert payload["component_status"]["execution_manifest"] is True
    assert payload["reproducibility_score"] is not None
    assert 0.0 <= payload["reproducibility_score"] <= 1.0
    assert payload["warnings"] == []
