from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from brain_researcher.services.mcp import runstore


def _tool_schema(tool_name: str) -> dict[str, Any]:
    doc_path = Path(__file__).resolve().parents[3] / "docs" / "mcp_tools.schema.json"
    payload = json.loads(doc_path.read_text(encoding="utf-8"))
    return next(tool for tool in payload["tools"] if tool["name"] == tool_name)


def _configure_run_root(monkeypatch, tmp_path: Path):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "_run_roots_for_read", lambda: [tmp_path])
    srv._ensure_dirs()
    return srv


def test_refuted_landscape_reports_all_missing_required_item_keys():
    from brain_researcher.services.mcp import server as srv

    resp = srv.refuted_landscape_summary(
        findings=[
            {"claim": "A", "status": "refuted"},
            {"direction": "B", "status": "supported"},
            {"claim": "C", "direction": "D", "reason": "missing status"},
        ]
    )

    assert resp["ok"] is False
    assert resp["error"] == "invalid_arguments"
    assert resp["missing_required_keys"] == [
        "findings[0].direction",
        "findings[0].reason",
        "findings[1].claim",
        "findings[1].reason",
        "findings[2].status",
    ]
    assert resp["required_item_fields"] == ["claim", "direction", "status", "reason"]
    assert all(key in resp["message"] for key in resp["missing_required_keys"])

    schema = _tool_schema("refuted_landscape_summary")
    finding_item = schema["input_schema"]["properties"]["findings"]["items"]
    assert finding_item["required"] == ["claim", "direction", "status", "reason"]


def test_kg_probe_schema_exposes_enum_and_handler_rejects_unknown_type():
    from brain_researcher.services.mcp import server as srv

    expected = {
        "structural_leverage",
        "contradiction_motifs",
        "contradiction_frontiers",
        "assumption_cracks",
        "analogy_transfers",
    }
    schema = _tool_schema("kg_probe")
    assert set(schema["input_schema"]["properties"]["probe_type"]["enum"]) == expected

    accepted = srv.kg_probe(probe_type="assumption_cracks")
    assert accepted["ok"] is False
    assert "unsupported probe_type" not in accepted["error"]

    rejected = srv.kg_probe(probe_type="mystery_probe")  # type: ignore[arg-type]
    assert rejected["ok"] is False
    assert "unsupported probe_type" in rejected["error"]


def test_memory_write_unsupported_card_type_lists_supported_types(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.memory_write("not_a_card_type", {})

    assert resp["ok"] is False
    assert resp["error"] == "memory_write_failed"
    assert resp["supported_card_types"] == sorted(srv.MEMORY_CARD_TYPES)


def test_tool_execute_worker_policy_violation_returns_policy_reasons(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    _configure_run_root(monkeypatch, tmp_path)
    monkeypatch.setattr(srv, "ENABLE_TOOL_EXECUTE", True)
    monkeypatch.setattr(srv, "TOOL_EXECUTE_ALLOWLIST", {"*"})
    monkeypatch.setattr(srv, "AGENT_DELEGATED_EXECUTION_ENABLED", False)
    monkeypatch.setattr(srv, "is_workflow_tool_id", lambda _tool_id: False)
    monkeypatch.setattr(
        srv,
        "_preflight_tool_call",
        lambda tool_id, params, **_kwargs: (
            ToolSpec(
                name=tool_id,
                description="stub",
                backend="python",
                timeout_s=1,
            ),
            [],
        ),
    )

    class DummyProc:
        def join(self, timeout=None):
            return None

        def is_alive(self):
            return False

    issues = [
        {
            "level": "error",
            "code": "path_not_allowed",
            "message": "input_path is outside allowed roots",
        }
    ]
    monkeypatch.setattr(
        srv,
        "_spawn_timeout_worker",
        lambda **_kwargs: (DummyProc(), object()),
    )
    monkeypatch.setattr(
        srv,
        "_receive_timeout_worker_payload",
        lambda _channel, *, timeout_s: {
            "ok": False,
            "error": "execution_policy_violation",
            "policy_issues": issues,
        },
    )

    resp = srv.tool_execute("python.policy_worker", params={"input_path": "/outside"})

    assert resp["ok"] is False
    assert resp["error"] == "execution_policy_violation"
    assert resp["policy_issues"][0]["code"] == "path_not_allowed"
    assert resp["policy_issues"][0]["message"] == "input_path is outside allowed roots"
    assert resp["policy_issues"][0]["step_id"] == "s1"


def test_slurm_wrappers_report_all_action_required_params_together():
    from brain_researcher.services.mcp import server as srv

    submit = srv.slurm_submit(action="patch_script")
    assert submit["ok"] is False
    assert submit["error"] == "missing_required_params"
    assert submit["missing_required_params"] == [
        "change_request",
        "script_text_or_script_path",
    ]
    assert "patch_script" in submit["supported_actions"]

    guide = srv.slurm_guide(action="command")
    assert guide["ok"] is False
    assert guide["error"] == "missing_required_params"
    assert guide["missing_required_params"] == ["intent"]
    assert "queue_status" in guide["supported_intents"]


def test_external_review_directive_without_session_includes_round_trip_hint(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.request_external_scientific_review_directive(goal="review external run")

    assert resp["ok"] is True
    assert "logged_event_id" not in resp
    hint = resp["round_trip_hint"]
    assert hint["session_binding_required"] is True
    assert hint["submission_tool"] == "submit_external_scientific_review_verdict"
    assert "session_id" in hint["message"]
    assert any("session_id" in line for line in resp["agent_instructions"])
