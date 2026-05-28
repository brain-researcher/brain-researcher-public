from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.research._bundle_emitter import emit_native_bundle


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_emit_native_bundle_writes_observation_analysis_and_execution_contracts(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "trajectory.json").write_text(
        '{"schema_version":"ATIF-v1.4"}',
        encoding="utf-8",
    )
    _write_json(
        run_dir / "inputs_manifest.json",
        {
            "schema_version": "inputs-manifest-v1",
            "inputs": [
                {
                    "key": "payload.plan.steps[0].params.dataset",
                    "path": "/tmp/data.csv",
                    "resolved_path": "/tmp/data.csv",
                    "checksum_status": "missing",
                }
            ],
        },
    )
    _write_json(
        run_dir / "qc_summary.json",
        {"schema_version": "qc-summary-v1", "status": "pass"},
    )
    (run_dir / "scores.csv").write_text("score\n0.91\n", encoding="utf-8")

    result = emit_native_bundle(
        run_dir,
        job_id="job-1",
        run_id="run-1",
        state="succeeded",
        round_id="round-7",
        run_card={
            "id": "run-1",
            "description": "Predictive sweep round.",
            "parameters": {
                "target_column": "story_score",
                "split_unit": "story",
                "grouped_split_keys": ["story", "subject"],
                "required_group_keys": ["story", "subject"],
                "best_model": "llm-large",
                "model_candidates": ["llm-small", "llm-large"],
                "selection_accounting": "nested_cv",
            },
        },
        provenance={
            "schema_version": "provenance-v1",
            "command": ["python", "analysis.py", "--dataset", "data.csv"],
            "packages": {"numpy": "1.26.4"},
            "environment": {"python_version": "3.11.9"},
            "parameters": {"alpha": 0.1},
        },
        artifacts=[
            {
                "name": "scores.csv",
                "type": "csv",
                "path": "scores.csv",
                "size": (run_dir / "scores.csv").stat().st_size,
            }
        ],
        inputs_manifest_ref="inputs_manifest.json",
        qc_summary_ref="qc_summary.json",
        source_manifests=["inputs_manifest.json"],
        failure_summary="no failure",
    )

    assert result["observation"].exists()
    assert result["analysis_bundle"].exists()
    assert result["execution_manifest"].exists()

    observation = json.loads(result["observation"].read_text(encoding="utf-8"))
    assert observation["round_id"] == "round-7"
    assert observation["inputs_manifest_ref"] == "inputs_manifest.json"
    assert observation["failure_summary"] == "no failure"
    assert (
        observation["run_card"]["review_context"]["selection"]["best_model"]
        == "llm-large"
    )

    bundle = json.loads(result["analysis_bundle"].read_text(encoding="utf-8"))
    assert bundle["files"]["observation_json"] == "observation.json"
    assert bundle["files"]["execution_manifest_json"] == "execution_manifest.json"
    assert bundle["qc_summary_ref"] == "qc_summary.json"
    assert bundle["source_manifests"] == ["inputs_manifest.json"]
    assert "qc_summary.json" in bundle["evidence_index"]
    assert "inputs_manifest.json" in bundle["evidence_index"]
    assert bundle["inputs_manifest"]["schema_version"] == "inputs-manifest-v1"
    assert bundle["review_context"]["split"]["required_group_keys"] == [
        "story",
        "subject",
    ]
    assert bundle["review_context"]["selection"]["best_model"] == "llm-large"
    assert bundle["review_context"]["selection"]["model_candidates"] == [
        "llm-small",
        "llm-large",
    ]
    assert (
        bundle["observation"]["run_card"]["review_context"]["selection"]["best_model"]
        == "llm-large"
    )

    manifest_roles = {entry["role"] for entry in bundle["file_manifest"]}
    assert "qc_summary" in manifest_roles
    assert "source_manifest" in manifest_roles
