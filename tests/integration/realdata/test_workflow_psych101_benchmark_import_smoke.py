"""Synthetic smoke test for workflow_psych101_benchmark_import."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from brain_researcher.services.mcp import server as mcp_server
from brain_researcher.services.tools.runner import execute_tool


def _workflow_present() -> bool:
    resp = mcp_server.workflow_search("psych101", limit=50)
    if not resp.get("ok"):
        return False
    return any(
        str(row.get("id") or "") == "workflow_psych101_benchmark_import"
        for row in (resp.get("workflows") or [])
    )


@pytest.mark.timeout(120)
def test_workflow_psych101_benchmark_import_smoke(tmp_path: Path):
    if not _workflow_present():
        pytest.skip("workflow_psych101_benchmark_import is not registered yet")

    manifest_path = tmp_path / "psych101_eval_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "psych101-eval-manifest-v1",
                "dataset_id": "psych101-demo",
                "benchmark_tasks": [
                    {
                        "schema_version": "task-spec-v1",
                        "task_id": "psych101-demo:exp-001",
                        "name": "two-step task",
                        "description": "Synthetic Psych-101 benchmark case",
                        "inputs": {
                            "dataset_id": "psych101-demo",
                            "experiment_id": "exp-001",
                        },
                        "scoring": {
                            "method": "heldout_prediction_scaffold",
                            "primary_metric": "negative_log_likelihood",
                        },
                        "tags": ["psych101", "behavioral", "non_gpu"],
                        "metadata": {"n_trials": 3, "n_participants": 2},
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "psych101_benchmark_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "benchmarks.sqlite"
    res = execute_tool(
        "workflow_psych101_benchmark_import",
        {
            "eval_manifest_json": str(manifest_path),
            "output_dir": str(out_dir),
            "benchmark_db_path": str(db_path),
        },
    )

    assert res.status == "success", res.error
    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_psych101_benchmark_import"

    summary_path = out_dir / "psych101_benchmark_import.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["dataset_id"] == "psych101-demo"
    assert payload["import_summary"]["added"] == 1

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT task_id FROM benchmark_tasks WHERE dataset_id = ?",
            ("psych101-demo",),
        ).fetchall()
        assert [row[0] for row in rows] == ["psych101-demo:exp-001"]
    finally:
        conn.close()
