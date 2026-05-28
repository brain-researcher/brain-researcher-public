from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema

from brain_researcher.services.mcp import server as srv


def _write_run_dir(
    root: Path,
    run_id: str,
    *,
    created_at: str,
    status: str,
    extra_files: dict[str, object] | None = None,
) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "created_at": created_at,
                "status": status,
                "dry_run": False,
                "steps": [],
            }
        ),
        encoding="utf-8",
    )
    for relpath, payload in (extra_files or {}).items():
        path = run_dir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, dict | list):
            path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            path.write_text(str(payload), encoding="utf-8")
    return run_dir


def _record(
    run_id: str,
    *,
    created_at: str,
    status: str = "succeeded",
    tool_id: str = "extract_timeseries",
) -> srv.RunRecord:
    return srv.RunRecord(
        run_id=run_id,
        created_at=created_at,
        status=status,
        steps=[
            srv.StepRecord(
                step_id="s1",
                tool_id=tool_id,
                status="succeeded" if status == "succeeded" else "failed",
            )
        ],
    )


def test_run_find_latest_reviewable_prefers_latest_supported_run(
    tmp_path, monkeypatch
):
    review_root = tmp_path / "runs"
    report_dir = _write_run_dir(
        review_root,
        "br_20260424_100300_report",
        created_at="2026-04-24T10:03:00Z",
        status="succeeded",
    )
    failed_dir = _write_run_dir(
        review_root,
        "br_20260424_100200_failed",
        created_at="2026-04-24T10:02:00Z",
        status="failed",
        extra_files={"analysis_bundle.json": {"schema_version": "analysis-bundle-v1"}},
    )
    supported_dir = _write_run_dir(
        review_root,
        "br_20260424_100100_supported",
        created_at="2026-04-24T10:01:00Z",
        status="succeeded",
        extra_files={"analysis_bundle.json": {"schema_version": "analysis-bundle-v1"}},
    )
    external_dir = _write_run_dir(
        review_root,
        "br_20260424_100000_external",
        created_at="2026-04-24T10:00:00Z",
        status="succeeded",
        extra_files={"source_summary.json": {"review_context": {"task": "nback"}}},
    )

    monkeypatch.setattr(
        srv,
        "_iter_run_records_for_summary",
        lambda: [
            (
                _record(
                    "br_20260424_100300_report",
                    created_at="2026-04-24T10:03:00Z",
                    tool_id="latex_report_render",
                ),
                report_dir,
                {},
            ),
            (
                _record(
                    "br_20260424_100200_failed",
                    created_at="2026-04-24T10:02:00Z",
                    status="failed",
                ),
                failed_dir,
                {},
            ),
            (
                _record(
                    "br_20260424_100100_supported",
                    created_at="2026-04-24T10:01:00Z",
                ),
                supported_dir,
                {},
            ),
            (
                _record(
                    "br_20260424_100000_external",
                    created_at="2026-04-24T10:00:00Z",
                    tool_id="import_external_run",
                ),
                external_dir,
                {"route": "external_import"},
            ),
        ],
    )

    from brain_researcher.services.review import bundle_builder
    from brain_researcher.services.review.checks import completeness

    def fake_build_artifact_review_bundle(run_id: str, *, run_dir=None, workflow_id=None):
        if run_id.endswith("supported") or run_id.endswith("failed"):
            return SimpleNamespace(
                observed_artifacts={
                    "analysis_bundle": {"schema_version": "analysis-bundle-v1"},
                    "review_contract": {
                        "contract_mode": "native_review_bundle",
                        "scientific_review_profile": "predictive_model_review",
                    },
                },
                review_context={"target": "memory_score"},
                stats_metrics={},
            )
        if run_id.endswith("external"):
            return SimpleNamespace(
                observed_artifacts={
                    "source_summary": {"review_context": {"task": "nback"}},
                    "review_contract": {
                        "contract_mode": "external_review_bundle",
                    },
                },
                review_context={"task": "nback"},
                stats_metrics={},
            )
        return SimpleNamespace(observed_artifacts={}, review_context={}, stats_metrics={})

    def fake_build_completeness_checklist(bundle):
        context = getattr(bundle, "review_context", {}) or {}
        if context.get("target") == "memory_score":
            return {"random_seed_pinned": True, "target_declared": True}
        if context.get("task") == "nback":
            return {"target_declared": True, "evaluation_protocol_declared": False}
        return {}

    monkeypatch.setattr(
        bundle_builder, "build_artifact_review_bundle", fake_build_artifact_review_bundle
    )
    monkeypatch.setattr(
        completeness, "build_completeness_checklist", fake_build_completeness_checklist
    )

    resp = srv.run_find_latest_reviewable(limit=10, max_candidates=3)

    assert resp["ok"] is True
    assert resp["selected_run_id"] == "br_20260424_100100_supported"
    assert [item["run_id"] for item in resp["candidates"]] == [
        "br_20260424_100100_supported",
        "br_20260424_100000_external",
    ]
    assert resp["selected"]["scientific_review_profile"] == "predictive_model_review"
    assert "analysis_bundle.json" in resp["selected"]["signal_files"]
    assert any(
        "declared completeness checks: 2/2" == reason
        for reason in resp["selected"]["selection_reasons"]
    )
    assert resp["candidates"][1]["review_contract_mode"] == "external_review_bundle"
    assert resp["candidates"][1]["route"] == "external_import"
    assert resp["skipped_preview"][:2] == [
        {
            "run_id": "br_20260424_100300_report",
            "status": "succeeded",
            "reason": "housekeeping_only",
        },
        {
            "run_id": "br_20260424_100200_failed",
            "status": "failed",
            "reason": "status_not_succeeded",
        },
    ]


def test_run_find_latest_reviewable_can_include_non_succeeded_runs(
    tmp_path, monkeypatch
):
    failed_dir = _write_run_dir(
        tmp_path / "runs",
        "br_20260424_101000_failed",
        created_at="2026-04-24T10:10:00Z",
        status="failed",
        extra_files={"analysis_bundle.json": {"schema_version": "analysis-bundle-v1"}},
    )
    succeeded_dir = _write_run_dir(
        tmp_path / "runs",
        "br_20260424_100900_supported",
        created_at="2026-04-24T10:09:00Z",
        status="succeeded",
        extra_files={"analysis_bundle.json": {"schema_version": "analysis-bundle-v1"}},
    )

    monkeypatch.setattr(
        srv,
        "_iter_run_records_for_summary",
        lambda: [
            (
                _record(
                    "br_20260424_101000_failed",
                    created_at="2026-04-24T10:10:00Z",
                    status="failed",
                ),
                failed_dir,
                {},
            ),
            (
                _record(
                    "br_20260424_100900_supported",
                    created_at="2026-04-24T10:09:00Z",
                ),
                succeeded_dir,
                {},
            ),
        ],
    )

    from brain_researcher.services.review import bundle_builder
    from brain_researcher.services.review.checks import completeness

    monkeypatch.setattr(
        bundle_builder,
        "build_artifact_review_bundle",
        lambda run_id, *, run_dir=None, workflow_id=None: SimpleNamespace(
            observed_artifacts={
                "analysis_bundle": {"schema_version": "analysis-bundle-v1"},
                "review_contract": {"contract_mode": "native_review_bundle"},
            },
            review_context={"target": run_id},
            stats_metrics={},
        ),
    )
    monkeypatch.setattr(
        completeness,
        "build_completeness_checklist",
        lambda bundle: {"target_declared": True},
    )

    resp = srv.run_find_latest_reviewable(
        limit=10,
        max_candidates=2,
        include_non_succeeded=True,
    )

    assert resp["ok"] is True
    assert resp["selected_run_id"] == "br_20260424_101000_failed"
    assert [item["run_id"] for item in resp["candidates"]] == [
        "br_20260424_101000_failed",
        "br_20260424_100900_supported",
    ]


def test_run_find_latest_reviewable_doc_schema_accepts_default_inputs():
    doc_path = Path(__file__).resolve().parents[3] / "docs" / "mcp_tools.schema.json"
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    schema = next(
        tool["input_schema"]
        for tool in doc["tools"]
        if tool["name"] == "run_find_latest_reviewable"
    )

    jsonschema.validate({}, schema)
    jsonschema.validate({"limit": 20}, schema)
    jsonschema.validate({"max_candidates": 3}, schema)
    jsonschema.validate({"include_non_succeeded": True}, schema)
