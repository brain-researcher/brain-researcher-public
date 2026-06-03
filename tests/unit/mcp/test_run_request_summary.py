from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from brain_researcher.services.mcp import runstore

UTC = timezone.utc


def _write_run(
    root: Path,
    run_id: str,
    *,
    created_at: str,
    status: str,
    route: str,
    request: dict,
    steps: list[dict],
) -> Path:
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "created_at": created_at,
                "status": status,
                "dry_run": False,
                "steps": steps,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "provenance.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "mode": "mcp",
                "route": route,
                "request": request,
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def test_run_request_summary_aggregates_pipeline_and_tool_requests(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)
    monkeypatch.delenv("BR_MCP_RUN_ROOT_ALIASES", raising=False)
    monkeypatch.setattr(srv, "_run_roots_for_read", lambda: [tmp_path])

    _write_run(
        tmp_path,
        "br_20260314_071038_tool",
        created_at="2026-03-14T07:10:38Z",
        status="succeeded",
        route="tool_execute",
        request={
            "tool_id": "connectivity_matrix",
            "params": {"timeseries": "/tmp/x.npy", "kind": "correlation"},
        },
        steps=[
            {
                "step_id": "s1",
                "tool_id": "connectivity_matrix",
                "status": "succeeded",
                "params": {"timeseries": "/tmp/x.npy", "kind": "correlation"},
            }
        ],
    )
    _write_run(
        tmp_path,
        "br_20260313_020159_pipe_a",
        created_at="2026-03-13T02:02:00Z",
        status="failed",
        route="pipeline_execute",
        request={
            "plan": {
                "steps": [
                    {
                        "tool": "workflow_visual_decoding",
                        "step_id": "s1",
                        "params": {"features": "/tmp/f.npy", "labels": "/tmp/l.npy"},
                    }
                ]
            }
        },
        steps=[
            {
                "step_id": "s1",
                "tool_id": "workflow_visual_decoding",
                "status": "failed",
                "params": {"features": "/tmp/f.npy", "labels": "/tmp/l.npy"},
            }
        ],
    )
    _write_run(
        tmp_path,
        "br_20260313_020200_pipe_b",
        created_at="2026-03-13T02:02:10Z",
        status="succeeded",
        route="pipeline_execute",
        request={
            "plan": {
                "steps": [
                    {
                        "tool": "workflow_visual_decoding",
                        "step_id": "s1",
                        "params": {"features": "/tmp/f2.npy", "labels": "/tmp/l2.npy"},
                    }
                ]
            }
        },
        steps=[
            {
                "step_id": "s1",
                "tool_id": "workflow_visual_decoding",
                "status": "succeeded",
                "params": {"features": "/tmp/f2.npy", "labels": "/tmp/l2.npy"},
            }
        ],
    )

    resp = srv.run_request_summary(top_k=5)

    assert resp["ok"] is True
    assert resp["total_runs"] == 3
    assert resp["runs_without_request_type"] == 0
    assert resp["route_counts"] == [
        {"route": "pipeline_execute", "count": 2},
        {"route": "tool_execute", "count": 1},
    ]
    assert resp["status_counts"] == [
        {"status": "succeeded", "count": 2},
        {"status": "failed", "count": 1},
    ]

    rows = {row["request_type"]: row for row in resp["request_type_counts"]}
    assert rows["workflow_visual_decoding"]["count"] == 2
    assert rows["workflow_visual_decoding"]["routes"] == ["pipeline_execute"]
    assert rows["connectivity_matrix"]["count"] == 1
    assert rows["connectivity_matrix"]["routes"] == ["tool_execute"]
    assert rows["workflow_visual_decoding"]["examples"][0]["param_keys"] == [
        "features",
        "labels",
    ]


def test_run_request_summary_reads_alias_roots_and_applies_since_days_filter(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    recent_created_at = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    old_created_at = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    primary_root = tmp_path / "primary"
    alias_root = tmp_path / "alias"
    monkeypatch.setattr(runstore, "RUN_ROOT", primary_root)
    monkeypatch.setattr(srv, "_run_roots_for_read", lambda: [primary_root, alias_root])

    _write_run(
        alias_root,
        "br_20260314_010000_alias",
        created_at=recent_created_at,
        status="succeeded",
        route="tool_execute",
        request={
            "tool_id": "task_to_concept_mapping",
            "params": {"task_name": "n-back"},
        },
        steps=[
            {
                "step_id": "s1",
                "tool_id": "task_to_concept_mapping",
                "status": "succeeded",
                "params": {"task_name": "n-back"},
            }
        ],
    )
    _write_run(
        primary_root,
        "br_20250101_010000_old",
        created_at=old_created_at,
        status="failed",
        route="pipeline_execute",
        request={
            "plan": {
                "steps": [
                    {
                        "tool": "workflow_visual_decoding",
                        "step_id": "s1",
                        "params": {"features": "/tmp/f.npy"},
                    }
                ]
            }
        },
        steps=[
            {
                "step_id": "s1",
                "tool_id": "workflow_visual_decoding",
                "status": "failed",
                "params": {"features": "/tmp/f.npy"},
            }
        ],
    )

    resp = srv.run_request_summary(top_k=5, since_days=30)

    assert resp["ok"] is True
    assert resp["since_days"] == 30
    assert resp["total_runs"] == 1
    assert str(primary_root) in resp["roots_scanned"]
    assert str(alias_root) in resp["roots_scanned"]
    assert resp["route_counts"] == [{"route": "tool_execute", "count": 1}]
    assert resp["request_type_counts"][0]["request_type"] == "task_to_concept_mapping"
    assert resp["request_type_counts"][0]["count"] == 1
