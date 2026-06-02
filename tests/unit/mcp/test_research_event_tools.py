from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from brain_researcher.services.mcp import runstore


class _FakeToolContext:
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.session = object()


class _TempReviewHandoffResult(TypedDict):
    ok: bool
    client_session_id: str
    source_client: str
    session_id: str | None
    payload: str
    _agent_directive: dict


def _configure_run_root(monkeypatch, tmp_path: Path):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "_run_roots_for_read", lambda: [tmp_path])
    srv._ensure_dirs()
    return srv


def _write_run(
    root: Path,
    run_id: str,
    *,
    status: str = "succeeded",
    route: str = "tool_execute",
    progress: dict | None = None,
    steps: list[dict] | None = None,
) -> Path:
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "created_at": "2026-03-20T00:00:00Z",
                "status": status,
                "dry_run": False,
                "steps": steps or [],
                "progress": progress or {},
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
                "transport": "stdio",
                "request": {"tool_id": "connectivity_matrix"},
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _directive_action(directive: dict, action_type: str) -> dict:
    for action in directive.get("actions", []):
        if action.get("type") == action_type:
            return action
    raise AssertionError(f"missing action: {action_type}")


def test_log_research_event_creates_synthetic_run(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.log_research_event(
        session_id="codex-session-1",
        kind="start",
        content="Starting connectivity review",
    )

    assert resp["ok"] is True
    run_id = resp["run_id"]
    run_dir = tmp_path / "runs" / run_id
    assert run_dir.exists()

    run = srv.run_get(run_id)
    assert run["ok"] is True
    assert run["status"] == "running"
    assert run["run"]["progress"]["research_logging"]["session_id"] == "codex-session-1"
    assert run["run"]["progress"]["research_logging"]["start_count"] == 1

    provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["route"] == "research_logging"
    assert provenance["research_logging"]["managed_run"] is True

    events = _read_jsonl(run_dir / "research_events.jsonl")
    assert events == [
        {
            "event_id": "research_evt_0001",
            "kind": "start",
            "session_id": "codex-session-1",
            "client_session_id": None,
            "source_client": None,
            "run_id": run_id,
            "source": "agent",
            "content": "Starting connectivity review",
            "context": {},
            "tags": [],
            "timestamp": events[0]["timestamp"],
            "managed_run": True,
        }
    ]

    trace_lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    assert trace_lines


def test_log_research_event_accepts_csv_string_tags_via_mcp_tool(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)
    ctx = _FakeToolContext("codex-client-csv-tags")

    resp = srv._run_async_sync(
        srv.mcp._tool_manager.call_tool(
            "log_research_event",
            {
                "session_id": "codex-session-csv-tags",
                "kind": "note",
                "content": "Normalize legacy CSV tags",
                "tags": "validation, connectivity, Validation",
            },
            context=ctx,
        )
    )

    assert resp["ok"] is True
    run_dir = tmp_path / "runs" / resp["run_id"]
    events = _read_jsonl(run_dir / "research_events.jsonl")
    assert events[0]["tags"] == ["validation", "connectivity"]


def test_write_session_snapshot_accepts_csv_string_tags_via_mcp_tool(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)
    ctx = _FakeToolContext("codex-client-csv-snapshot")

    start = srv.log_research_event(
        session_id="codex-session-csv-snapshot",
        kind="start",
        content="Start CSV snapshot session",
    )
    assert start["ok"] is True

    snapshot = srv._run_async_sync(
        srv.mcp._tool_manager.call_tool(
            "write_session_snapshot",
            {
                "session_id": "codex-session-csv-snapshot",
                "goal": "Close CSV snapshot session",
                "done": ["normalized tags"],
                "open": ["none"],
                "next_command": "stop",
                "tags": "rollout, handoff, rollout",
            },
            context=ctx,
        )
    )

    assert snapshot["ok"] is True
    run_dir = tmp_path / "runs" / start["run_id"]
    payload = json.loads(
        (run_dir / "session_snapshot.json").read_text(encoding="utf-8")
    )
    assert payload["tags"] == ["rollout", "handoff"]


def test_log_research_event_attaches_to_existing_run_without_rewriting_route(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)
    run_dir = _write_run(tmp_path, "existing_run", status="succeeded")

    resp = srv.log_research_event(
        session_id="codex-session-2",
        run_id="existing_run",
        kind="note",
        content="Need to verify fisher-z handling",
        source="user",
        tags=["validation", "connectivity"],
    )

    assert resp["ok"] is True
    run = srv.run_get("existing_run")
    assert run["status"] == "succeeded"
    assert run["run"]["progress"]["research_logging"]["note_count"] == 1

    provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["route"] == "tool_execute"
    assert provenance["research_logging"]["session_id"] == "codex-session-2"
    assert provenance["research_logging"]["managed_run"] is False

    events = _read_jsonl(run_dir / "research_events.jsonl")
    assert events[0]["kind"] == "note"
    assert events[0]["source"] == "user"
    assert events[0]["tags"] == ["validation", "connectivity"]


def test_log_research_event_can_derive_canonical_session_id_from_client_session_id(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.log_research_event(
        kind="start",
        content="Start from native client thread",
        source_client="claude-code",
        client_session_id="thread-42",
    )

    assert resp["ok"] is True
    assert resp["session_id"] == "claude_code:thread-42"
    assert resp["client_session_id"] == "thread-42"
    assert resp["source_client"] == "claude_code"

    digest = srv.research_session_digest(session_id="claude_code:thread-42")
    assert digest["ok"] is True
    assert digest["digest"]["client_session_id"] == "thread-42"
    assert digest["digest"]["source_client"] == "claude_code"


def test_write_session_snapshot_persists_structured_snapshot(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.write_session_snapshot(
        session_id="codex-session-3",
        goal="Finish connectivity workflow review",
        done=["checked output paths", "verified atlas coverage"],
        open=["confirm diagonal convention"],
        next_command="resume with rollout checklist",
    )

    assert resp["ok"] is True
    run_id = resp["run_id"]
    run_dir = tmp_path / "runs" / run_id

    run = srv.run_get(run_id)
    assert run["status"] == "succeeded"
    assert run["run"]["progress"]["research_logging"]["start_count"] == 1
    assert run["run"]["progress"]["research_logging"]["snapshot_count"] == 1
    assert run["run"]["progress"]["session_snapshot"]["goal"] == (
        "Finish connectivity workflow review"
    )

    snapshot = json.loads(
        (run_dir / "session_snapshot.json").read_text(encoding="utf-8")
    )
    assert snapshot["goal"] == "Finish connectivity workflow review"
    assert snapshot["done"] == ["checked output paths", "verified atlas coverage"]
    assert snapshot["open"] == ["confirm diagonal convention"]
    assert snapshot["next_command"] == "resume with rollout checklist"

    events = _read_jsonl(run_dir / "research_events.jsonl")
    assert events[0]["kind"] == "start"
    assert (
        events[0]["content"] == "Auto-started research session on first snapshot write."
    )
    assert events[1]["kind"] == "end"
    assert events[1]["event_type"] == "research.snapshot"
    assert events[1]["snapshot"]["goal"] == "Finish connectivity workflow review"
    assert (run_dir / "analysis_bundle.json").exists()
    assert (run_dir / "observation.json").exists()


def test_write_session_snapshot_wrapper_emits_post_close_followup_action(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)
    ctx = _FakeToolContext("codex-client-1")

    start = srv._run_async_sync(
        srv.mcp._tool_manager.call_tool(
            "log_research_event",
            {
                "kind": "start",
                "content": "Start managed tool session",
                "source_client": "codex",
                "client_session_id": "chat-1",
            },
            context=ctx,
        )
    )
    assert start["ok"] is True

    snapshot = srv._run_async_sync(
        srv.mcp._tool_manager.call_tool(
            "write_session_snapshot",
            {
                "session_id": start["session_id"],
                "goal": "Finish connectivity workflow review",
                "done": ["checked output paths"],
                "open": ["confirm diagonal convention"],
                "next_command": "generate durable summary",
            },
            context=ctx,
        )
    )

    assert snapshot["ok"] is True
    directive = snapshot["_agent_directive"]["research_logging"]
    assert directive["state"]["session_id"] == "codex:chat-1"
    assert directive["state"]["snapshot_required_on_close"] is False
    assert directive["state"]["session_closed"] is True
    assert directive["state"]["post_close_actions_available"] is True
    action_types = [action.get("type") for action in directive["actions"]]
    assert "write_snapshot_on_close" not in action_types
    assert "attach_transcript_on_close" not in action_types
    assert "attach_external_trace_on_close" not in action_types

    post_close = _directive_action(directive, "prompt_post_session_actions")
    assert post_close["required"] is False
    assert post_close["payload"]["requires_user_initiation"] is True
    assert post_close["payload"]["run_id"] == snapshot["run_id"]
    suggested = post_close["payload"]["suggested_actions"]
    assert len(suggested) == 1
    assert suggested[0]["tool_name"] == "generate_research_trajectory_and_insights"
    assert suggested[0]["arguments"] == {
        "run_id": snapshot["run_id"],
        "persist": True,
    }


def test_write_session_snapshot_wrapper_emits_hygiene_warning_action(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)
    ctx = _FakeToolContext("codex-client-hygiene-warning")

    snapshot = srv._run_async_sync(
        srv.mcp._tool_manager.call_tool(
            "write_session_snapshot",
            {
                "session_id": "hygiene-warning-session",
                "goal": "Update prompt wording",
                "done": ["Edited the wording."],
                "open": ["None"],
                "next_command": "git diff -- AGENTS.md",
            },
            context=ctx,
        )
    )

    assert snapshot["ok"] is True
    directive = snapshot["_agent_directive"]["research_logging"]
    hygiene = _directive_action(directive, "review_session_snapshot_hygiene")
    assert hygiene["required"] is False
    codes = {issue["code"] for issue in hygiene["payload"]["issues"]}
    assert {
        "missing_source_client",
        "vague_open_none",
        "succeeded_without_validation_evidence",
    } <= codes


def test_write_session_snapshot_wrapper_omits_hygiene_warning_for_clean_closeout(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)
    ctx = _FakeToolContext("codex-client-clean-closeout")

    snapshot = srv._run_async_sync(
        srv.mcp._tool_manager.call_tool(
            "write_session_snapshot",
            {
                "session_id": "clean-closeout-session",
                "source_client": "codex",
                "goal": "Update MCP contract",
                "done": [
                    "Verified pytest -q tests/unit/mcp/test_research_event_tools.py."
                ],
                "open": ["Follow-up: publish after review."],
                "next_command": "pytest -q tests/unit/mcp/test_research_event_tools.py",
            },
            context=ctx,
        )
    )

    assert snapshot["ok"] is True
    directive = snapshot["_agent_directive"]["research_logging"]
    action_types = {action.get("type") for action in directive["actions"]}
    assert "review_session_snapshot_hygiene" not in action_types


def test_call_tool_wrapper_preserves_existing_review_handoff_and_adds_research_logging(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)
    ctx = _FakeToolContext("codex-client-coexistence")
    tool_name = "temp_review_handoff_coexistence_tool"
    review_handoff = {
        "protocol": "br.review_handoff.directive.v1",
        "review_type": "scientific_review",
        "inner_verdict": {"overall_decision": "diagnose"},
        "findings_summary": ["REVIEW_CONDITION_NUMBER_HIGH: condition number 5000"],
        "reviewer_questions": ["Is the confound model sufficient?"],
        "actions": [
            {
                "type": "independent_second_opinion",
                "required": False,
                "reason": "inner_model_flagged_issues",
                "prompt": "Check the flagged issues independently.",
            }
        ],
    }

    def _temp_tool(
        client_session_id: str,
        source_client: str,
        payload: str = "coexistence",
    ) -> _TempReviewHandoffResult:
        return {
            "ok": True,
            "client_session_id": client_session_id,
            "source_client": source_client,
            "session_id": None,
            "payload": payload,
            "_agent_directive": {"review_handoff": review_handoff},
        }

    srv.mcp._tool_manager.add_tool(
        _temp_tool,
        name=tool_name,
        description="Temporary tool used to verify directive coexistence in wrapper tests.",
        structured_output=True,
    )
    try:
        result = srv._run_async_sync(
            srv.mcp._tool_manager.call_tool(
                tool_name,
                {
                    "client_session_id": "thread-merge-1",
                    "source_client": "codex",
                    "payload": "coexistence",
                },
                context=ctx,
            )
        )
    finally:
        srv.mcp._tool_manager.remove_tool(tool_name)

    assert result["ok"] is True
    assert result["payload"] == "coexistence"
    assert result["_agent_directive"]["review_handoff"] == review_handoff

    research_logging = result["_agent_directive"]["research_logging"]
    assert research_logging["protocol"] == "br.research_logging.directive.v1"
    assert research_logging["state"]["session_id"] == "codex:thread-merge-1"
    assert research_logging["state"]["client_session_id"] == "thread-merge-1"
    assert research_logging["state"]["source_client"] == "codex"
    assert (
        _directive_action(research_logging, "bind_session")["payload"]["session_id"]
        == "codex:thread-merge-1"
    )


def test_write_session_snapshot_convert_result_tuple_emits_post_close_followup_action(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)
    ctx = _FakeToolContext("codex-client-1")

    start = srv._run_async_sync(
        srv._call_tool_with_research_telemetry(
            "log_research_event",
            {
                "kind": "start",
                "content": "Start managed tool session",
                "source_client": "codex",
                "client_session_id": "chat-1",
            },
            context=ctx,
            convert_result=True,
        )
    )
    assert isinstance(start, tuple)
    start_payload = start[1]
    assert start_payload["ok"] is True

    snapshot = srv._run_async_sync(
        srv._call_tool_with_research_telemetry(
            "write_session_snapshot",
            {
                "session_id": start_payload["session_id"],
                "goal": "Finish connectivity workflow review",
                "done": ["checked output paths"],
                "open": ["confirm diagonal convention"],
                "next_command": "generate durable summary",
            },
            context=ctx,
            convert_result=True,
        )
    )

    assert isinstance(snapshot, tuple)
    snapshot_payload = snapshot[1]
    assert snapshot_payload["ok"] is True
    directive = snapshot_payload["_agent_directive"]["research_logging"]
    post_close = _directive_action(directive, "prompt_post_session_actions")
    assert post_close["payload"]["run_id"] == snapshot_payload["run_id"]

    content = snapshot[0]
    assert len(content) == 1
    text_payload = json.loads(content[0].text)
    assert (
        text_payload["_agent_directive"]["research_logging"]["state"]["session_closed"]
        is True
    )
    suggested = post_close["payload"]["suggested_actions"]
    assert suggested[0]["tool_name"] == "generate_research_trajectory_and_insights"


def test_write_session_snapshot_convert_result_tuple_includes_hygiene_warning(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)
    ctx = _FakeToolContext("codex-client-hygiene-tuple")

    snapshot = srv._run_async_sync(
        srv._call_tool_with_research_telemetry(
            "write_session_snapshot",
            {
                "session_id": "tuple-hygiene-session",
                "goal": "Update prompt wording",
                "done": ["Edited the wording."],
                "open": ["None"],
                "next_command": "git diff -- AGENTS.md",
            },
            context=ctx,
            convert_result=True,
        )
    )

    assert isinstance(snapshot, tuple)
    payload = snapshot[1]
    directive = payload["_agent_directive"]["research_logging"]
    hygiene = _directive_action(directive, "review_session_snapshot_hygiene")
    assert hygiene["payload"]["session_id"] == "tuple-hygiene-session"

    text_payload = json.loads(snapshot[0][0].text)
    text_directive = text_payload["_agent_directive"]["research_logging"]
    text_hygiene = _directive_action(text_directive, "review_session_snapshot_hygiene")
    assert text_hygiene["payload"]["session_id"] == "tuple-hygiene-session"


def test_write_session_snapshot_is_idempotent_for_matching_payload(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    first = srv.write_session_snapshot(
        session_id="codex-session-idempotent",
        goal="Close session once",
        done=["captured findings"],
        open=["follow up"],
        next_command="resume later",
    )
    second = srv.write_session_snapshot(
        session_id="codex-session-idempotent",
        goal="Close session once",
        done=["captured findings"],
        open=["follow up"],
        next_command="resume later",
    )

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["idempotent"] is True
    assert second["run_id"] == first["run_id"]

    run_dir = tmp_path / "runs" / first["run_id"]
    events = _read_jsonl(run_dir / "research_events.jsonl")
    assert [event["kind"] for event in events] == ["start", "end"]


def test_log_research_event_rejects_closed_session(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    start = srv.log_research_event(
        session_id="closed-session",
        kind="start",
        content="Start closed-session",
    )
    assert start["ok"] is True

    snapshot = srv.write_session_snapshot(
        session_id="closed-session",
        goal="Close the session",
        done=["wrote snapshot"],
        open=["none"],
        next_command="stop",
    )
    assert snapshot["ok"] is True

    note = srv.log_research_event(
        session_id="closed-session",
        kind="note",
        content="Late note after close",
    )
    assert note["ok"] is False
    assert note["error"] == "session_already_closed"

    run_dir = tmp_path / "runs" / start["run_id"]
    events = _read_jsonl(run_dir / "research_events.jsonl")
    assert [event["kind"] for event in events] == ["start", "end"]


def test_write_session_snapshot_rejects_note_only_session_without_start(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    note = srv.log_research_event(
        session_id="note-only-session",
        kind="note",
        content="Logged a note without start",
    )
    assert note["ok"] is True

    snapshot = srv.write_session_snapshot(
        session_id="note-only-session",
        goal="Try to close note-only session",
        done=["logged note"],
        open=["add proper start"],
        next_command="call start first",
    )
    assert snapshot["ok"] is False
    assert snapshot["error"] == "session_not_started"


def test_write_session_snapshot_attaches_to_existing_run_without_changing_status(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)
    run_dir = _write_run(tmp_path, "existing_snapshot_run", status="failed")

    resp = srv.write_session_snapshot(
        session_id="codex-session-4",
        run_id="existing_snapshot_run",
        goal="Triage failed rollout",
        done=["captured failing symptom"],
        open=["find regression source"],
        next_command="inspect failure taxonomy",
        source="user",
    )

    assert resp["ok"] is True
    run = srv.run_get("existing_snapshot_run")
    assert run["status"] == "failed"
    assert run["run"]["progress"]["session_snapshot"]["goal"] == "Triage failed rollout"

    provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["route"] == "tool_execute"
    assert provenance["research_logging"]["managed_run"] is False

    snapshot = json.loads(
        (run_dir / "session_snapshot.json").read_text(encoding="utf-8")
    )
    assert snapshot["source"] == "user"
    assert snapshot["open"] == ["find regression source"]

    events = _read_jsonl(run_dir / "research_events.jsonl")
    assert [event["kind"] for event in events] == ["start", "end"]
    assert (
        events[0]["content"] == "Auto-started research session on first snapshot write."
    )


def test_write_session_snapshot_without_run_id_reuses_indexed_attached_run(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)
    _write_run(tmp_path, "attached_followup_run", status="succeeded")

    event = srv.log_research_event(
        session_id="attached-followup-session",
        run_id="attached_followup_run",
        kind="start",
        content="Start attached follow-up",
    )
    assert event["ok"] is True
    assert event["run_id"] == "attached_followup_run"

    snapshot = srv.write_session_snapshot(
        session_id="attached-followup-session",
        goal="Close attached follow-up",
        done=["captured follow-up findings"],
        open=["ship fix if needed"],
        next_command="resume attached follow-up",
    )

    assert snapshot["ok"] is True
    assert snapshot["run_id"] == "attached_followup_run"

    digest = srv.research_session_digest(session_id="attached-followup-session")
    assert digest["ok"] is True
    assert digest["run_id"] == "attached_followup_run"
    assert digest["digest"]["event_counts"] == {
        "total": 2,
        "start": 1,
        "note": 0,
        "auto": 0,
        "end": 1,
    }


def test_research_session_digest_uses_session_lookup_and_returns_notes(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    start = srv.log_research_event(
        session_id="codex-session-digest",
        kind="start",
        content="Kick off rollout review",
    )
    assert start["ok"] is True
    run_id = start["run_id"]

    note = srv.log_research_event(
        session_id="codex-session-digest",
        kind="note",
        content="Need to confirm failure taxonomy coverage",
        tags=["rollout", "taxonomy"],
    )
    assert note["ok"] is True
    assert note["run_id"] == run_id

    snapshot = srv.write_session_snapshot(
        session_id="codex-session-digest",
        goal="Close rollout review",
        done=["captured open issues"],
        open=["implement weekly digest"],
        next_command="resume with digest pass",
    )
    assert snapshot["ok"] is True
    assert snapshot["run_id"] == run_id

    resp = srv.research_session_digest(session_id="codex-session-digest")

    assert resp["ok"] is True
    assert resp["run_id"] == run_id
    digest = resp["digest"]
    assert digest["session_id"] == "codex-session-digest"
    assert digest["has_snapshot"] is True
    assert digest["event_counts"] == {
        "total": 3,
        "start": 1,
        "note": 1,
        "auto": 0,
        "end": 1,
    }
    assert digest["notes"][0]["content"] == "Need to confirm failure taxonomy coverage"
    assert digest["open_items"] == ["implement weekly digest"]


def test_research_session_digest_and_summary_merge_duplicate_session_runs(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    run_a = _write_run(
        tmp_path,
        "duplicate_session_run_a",
        status="cancelled",
        route="kg_hypothesis_candidate_cards_start",
        progress={
            "research_logging": {
                "session_id": "duplicate-session",
                "event_count": 1,
                "start_count": 1,
                "last_event_at": "2026-03-20T00:00:01Z",
            }
        },
    )
    (run_a / "provenance.json").write_text(
        json.dumps(
            {
                "run_id": "duplicate_session_run_a",
                "mode": "mcp",
                "route": "kg_hypothesis_candidate_cards_start",
                "transport": "stdio",
                "research_logging": {
                    "session_id": "duplicate-session",
                    "managed_run": False,
                },
            }
        ),
        encoding="utf-8",
    )
    (run_a / "research_events.jsonl").write_text(
        json.dumps(
            {
                "event_id": "research_evt_0001",
                "kind": "start",
                "session_id": "duplicate-session",
                "run_id": "duplicate_session_run_a",
                "source": "agent",
                "content": "start duplicate session",
                "context": {},
                "tags": [],
                "timestamp": "2026-03-20T00:00:01Z",
                "managed_run": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    run_b = _write_run(
        tmp_path,
        "duplicate_session_run_b",
        status="succeeded",
        route="research_logging",
        progress={
            "research_logging": {
                "session_id": "duplicate-session",
                "event_count": 1,
                "snapshot_count": 1,
                "last_event_at": "2026-03-20T00:00:02Z",
            },
            "session_snapshot": {
                "goal": "close duplicate session",
                "done": ["merged duplicate"],
                "open": ["verify merged summary"],
                "next_command": "resume duplicate session",
                "session_id": "duplicate-session",
                "run_id": "duplicate_session_run_b",
                "updated_at": "2026-03-20T00:00:02Z",
            },
        },
    )
    (run_b / "provenance.json").write_text(
        json.dumps(
            {
                "run_id": "duplicate_session_run_b",
                "mode": "mcp",
                "route": "research_logging",
                "transport": "stdio",
                "research_logging": {
                    "session_id": "duplicate-session",
                    "managed_run": True,
                    "snapshot_path": "session_snapshot.json",
                },
            }
        ),
        encoding="utf-8",
    )
    (run_b / "session_snapshot.json").write_text(
        json.dumps(
            {
                "goal": "close duplicate session",
                "done": ["merged duplicate"],
                "open": ["verify merged summary"],
                "next_command": "resume duplicate session",
                "session_id": "duplicate-session",
                "run_id": "duplicate_session_run_b",
                "updated_at": "2026-03-20T00:00:02Z",
            }
        ),
        encoding="utf-8",
    )
    (run_b / "research_events.jsonl").write_text(
        json.dumps(
            {
                "event_id": "research_evt_0001",
                "kind": "end",
                "event_type": "research.snapshot",
                "session_id": "duplicate-session",
                "run_id": "duplicate_session_run_b",
                "source": "agent",
                "tags": [],
                "timestamp": "2026-03-20T00:00:02Z",
                "managed_run": True,
                "snapshot": {
                    "goal": "close duplicate session",
                    "done": ["merged duplicate"],
                    "open": ["verify merged summary"],
                    "next_command": "resume duplicate session",
                    "session_id": "duplicate-session",
                    "run_id": "duplicate_session_run_b",
                    "updated_at": "2026-03-20T00:00:02Z",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    digest = srv.research_session_digest(session_id="duplicate-session")
    assert digest["ok"] is True
    assert digest["run_id"] == "duplicate_session_run_b"
    assert digest["digest"]["run_ids"] == [
        "duplicate_session_run_a",
        "duplicate_session_run_b",
    ]
    assert digest["digest"]["event_counts"] == {
        "total": 2,
        "start": 1,
        "note": 0,
        "auto": 0,
        "end": 1,
    }

    summary = srv.research_log_summary(top_k=5)
    assert summary["ok"] is True
    assert summary["total_sessions"] == 1
    assert summary["total_run_rows"] == 2
    assert summary["duplicate_session_ids"] == 1
    assert summary["duplicate_run_rows"] == 2
    assert summary["synthetic_sessions"] == 0
    assert summary["attached_sessions"] == 1
    assert summary["event_counts"] == {
        "total": 2,
        "start": 1,
        "note": 0,
        "auto": 0,
        "end": 1,
    }
    assert summary["recent_sessions"][0]["logging_mode"] == "attached"
    assert summary["recent_sessions"][0]["run_ids"] == [
        "duplicate_session_run_a",
        "duplicate_session_run_b",
    ]

    report = srv.session_learning_report_generate(
        since_days=3650,
        limit=10,
        top_k=5,
        min_support=1,
    )
    assert report["ok"] is True
    assert report["sessions_considered"] == 1
    assert report["coverage"]["snapshot_count"] == 1


def test_research_log_summary_aggregates_sessions_and_falls_back_from_index(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    managed = srv.write_session_snapshot(
        session_id="managed-session",
        goal="Managed session",
        done=["logged managed session"],
        open=["follow up managed"],
        next_command="resume managed",
    )
    assert managed["ok"] is True

    existing_run = _write_run(tmp_path, "attached_run", status="succeeded")
    attached = srv.log_research_event(
        session_id="attached-session",
        run_id="attached_run",
        kind="note",
        content="Attached run needs validation follow-up",
        tags=["validation"],
    )
    assert attached["ok"] is True
    snapshot = srv.write_session_snapshot(
        session_id="attached-session",
        run_id="attached_run",
        goal="Attached session",
        done=["logged attach path"],
        open=["follow up attached"],
        next_command="resume attached",
    )
    assert snapshot["ok"] is True
    assert existing_run.exists()

    digest = srv.research_session_digest(session_id="attached-session")
    assert digest["ok"] is True
    assert digest["run_id"] == "attached_run"

    summary = srv.research_log_summary(top_k=5)

    assert summary["ok"] is True
    assert summary["total_sessions"] == 2
    assert summary["sessions_with_snapshot"] == 2
    assert summary["managed_sessions"] == 1
    assert summary["synthetic_sessions"] == 1
    assert summary["attached_sessions"] == 1
    assert summary["closure_rate"] == 1.0
    assert summary["event_counts"]["note"] == 1
    assert any(
        item == {"open_item": "follow up attached", "count": 1}
        for item in summary["frequent_open_items"]
    )
    assert any(
        row["session_id"] == "attached-session"
        and row["managed_run"] is False
        and row["logging_mode"] == "attached"
        for row in summary["recent_sessions"]
    )


def test_session_risk_classify_flags_missing_source_client(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    snapshot = srv.write_session_snapshot(
        session_id="missing-client-session",
        goal="Update AGENTS.md guidance",
        done=["Verified git diff --check -- AGENTS.md."],
        open=["uncommitted-local: AGENTS.md remains local."],
        next_command="git diff -- AGENTS.md",
    )
    assert snapshot["ok"] is True

    result = srv.session_risk_classify(session_id="missing-client-session")

    assert result["ok"] is True
    codes = {issue["code"] for issue in result["classification"]["hygiene_issues"]}
    assert "missing_source_client" in codes


def test_session_risk_classify_flags_missing_final_snapshot(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    start = srv.log_research_event(
        session_id="running-session",
        source_client="codex",
        kind="start",
        content="Start prod rollout audit",
        tags=["prod"],
    )
    assert start["ok"] is True

    result = srv.session_risk_classify(session_id="running-session")

    assert result["ok"] is True
    codes = {issue["code"] for issue in result["classification"]["hygiene_issues"]}
    assert "missing_final_snapshot" in codes


def test_session_risk_classify_flags_vague_open_none(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    snapshot = srv.write_session_snapshot(
        session_id="vague-open-session",
        source_client="codex",
        goal="Fix API contract",
        done=["Changed API contract response shape."],
        open=["None"],
        next_command="git diff -- src/brain_researcher/services/mcp/server.py",
    )
    assert snapshot["ok"] is True

    result = srv.session_risk_classify(session_id="vague-open-session")

    assert result["ok"] is True
    codes = {issue["code"] for issue in result["classification"]["hygiene_issues"]}
    assert "vague_open_none" in codes


def test_session_risk_classify_flags_succeeded_without_validation_evidence(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    snapshot = srv.write_session_snapshot(
        session_id="no-validation-session",
        source_client="codex",
        goal="Update prompt wording",
        done=["Edited the wording."],
        open=["No follow-up selected."],
        next_command="git diff -- AGENTS.md",
    )
    assert snapshot["ok"] is True

    result = srv.session_risk_classify(session_id="no-validation-session")

    assert result["ok"] is True
    codes = {issue["code"] for issue in result["classification"]["hygiene_issues"]}
    assert "succeeded_without_validation_evidence" in codes


def test_session_risk_classify_recognizes_extended_validation_evidence(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    cases = [
        (
            "neurometabench-bundle",
            "Wrote coordinate_table.csv, included_studies.csv, metrics.json, "
            "provenance_manifest.json, and spatial_report.md.",
        ),
        (
            "test-prose",
            "Validated 56 behavior unit tests passing.",
        ),
        (
            "report-render",
            "Rerendered the PDF and verified pdfinfo, pdftotext, and md5 parity.",
        ),
        (
            "prod-operational",
            "Verified live MCP transport, fetched tools/list, and checked "
            "deployment image rollout status.",
        ),
        (
            "kg-literature",
            "Ran kg_search_nodes and DeepXiv search for publication evidence.",
        ),
    ]

    for evidence_type, done_item in cases:
        snapshot = srv.write_session_snapshot(
            session_id=f"extended-validation-{evidence_type}",
            source_client="codex",
            goal=f"Check {evidence_type} validation parsing",
            done=[done_item],
            open=[],
            next_command="exit",
        )
        assert snapshot["ok"] is True

        result = srv.session_risk_classify(
            session_id=f"extended-validation-{evidence_type}"
        )

        assert result["ok"] is True
        codes = {issue["code"] for issue in result["classification"]["hygiene_issues"]}
        evidence_types = {
            row["evidence_type"]
            for row in result["classification"]["validation_evidence"]
        }
        assert evidence_type in evidence_types
        assert "succeeded_without_validation_evidence" not in codes


def test_session_risk_classify_flags_prod_without_rollout_health_evidence(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    snapshot = srv.write_session_snapshot(
        session_id="prod-no-health-session",
        source_client="codex",
        goal="Prepare prod rollout notes for web-ui",
        done=["Prepared rollout notes."],
        open=["partial validation: live prod endpoint was not checked."],
        next_command="kubectl rollout status deployment/brain-researcher-web-ui",
        tags=["prod"],
    )
    assert snapshot["ok"] is True

    result = srv.session_risk_classify(session_id="prod-no-health-session")

    assert result["ok"] is True
    codes = {issue["code"] for issue in result["classification"]["hygiene_issues"]}
    assert "prod_without_rollout_health_evidence" in codes


def test_session_open_risks_query_filters_by_risk_label(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    snapshot = srv.write_session_snapshot(
        session_id="open-risk-session",
        source_client="codex",
        goal="Clean release files",
        done=["Verified git diff --check -- AGENTS.md."],
        open=["uncommitted-local: commit remains local only."],
        next_command="git status --short",
        tags=["repo-cleanup"],
    )
    assert snapshot["ok"] is True

    result = srv.session_open_risks_query(
        risk_label="uncommitted-local",
        since_days=30,
        limit=10,
    )

    assert result["ok"] is True
    assert any(row["session_id"] == "open-risk-session" for row in result["results"])


def test_session_learning_report_generate_aggregates_sessions(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    first = srv.write_session_snapshot(
        session_id="report-prod-session-1",
        source_client="codex",
        goal="Prepare prod rollout notes for web-ui",
        done=["Verified pytest -q tests/unit/mcp/test_research_event_tools.py."],
        open=["partial validation: live prod endpoint was not checked."],
        next_command="kubectl rollout status deployment/brain-researcher-web-ui",
        tags=["prod"],
    )
    second = srv.write_session_snapshot(
        session_id="report-prod-session-2",
        source_client="codex",
        goal="Prepare prod rollout notes for web-ui",
        done=["Changed rollout docs."],
        open=["partial validation: live prod browser path was not checked."],
        next_command="curl -fsS https://example.invalid/api/health",
        tags=["prod"],
    )
    running = srv.log_research_event(
        session_id="report-running-session",
        source_client="codex",
        kind="start",
        content="Start MCP session-learning follow-up",
        tags=["mcp"],
    )
    assert first["ok"] is True
    assert second["ok"] is True
    assert running["ok"] is True

    result = srv.session_learning_report_generate(
        since_days=3650,
        limit=10,
        top_k=10,
        min_support=1,
    )

    assert result["ok"] is True
    assert result["sessions_considered"] == 3
    assert result["coverage"]["snapshot_count"] == 2
    assert result["coverage"]["closure_rate"] == 0.6667
    assert any(
        row["surface"] == "prod-runtime" and row["count"] == 2
        for row in result["top_task_surfaces"]
    )
    assert any(
        row["risk_label"] == "partial-validation" and row["count"] == 2
        for row in result["repeated_open_risks"]
    )
    assert any(
        row["risk_code"] == "prod_without_rollout_health_evidence" and row["count"] == 2
        for row in result["hygiene_issues"]
    )
    assert any(
        card["issue_code"] == "prod_without_rollout_health_evidence"
        and card["support_count"] == 2
        for card in result["policy_card_candidates"]
    )
    assert any(
        row["session_id"] == "report-running-session"
        for row in result["stale_or_running_sessions"]
    )
    assert result["recommended_next_actions"]
    assert result["rigor_guards"]


def test_session_learning_report_generate_empty_report(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    result = srv.session_learning_report_generate(
        since_days=30,
        limit=10,
        top_k=5,
    )

    assert result["ok"] is True
    assert result["sessions_considered"] == 0
    assert result["coverage"]["closure_rate"] == 0.0
    assert result["top_task_surfaces"] == []
    assert result["repeated_open_risks"] == []
    assert result["hygiene_issues"] == []
    assert result["stale_or_running_sessions"] == []


def test_session_signal_report_generate_surfaces_silent_fail_signals(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    clean = srv.write_session_snapshot(
        session_id="signal-clean-layer-b",
        source_client="codex",
        goal="Produce NeuroMetaBench Layer B bundle",
        done=[
            "BR plan_preflight classified case as structured-coordinate-reproduction.",
            "BR audit verified study count, coordinate count, and space consistency.",
            "Wrote RUN_SUMMARY.json with metrics.json and spatial_report.md.",
        ],
        open=[],
        next_command="exit",
        tags=["neurometabench", "layer_b"],
    )
    assert clean["ok"] is True
    run_dir = Path(clean["run_dir"])
    with (run_dir / "tool_trace.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "trace_id": "trace_after_snapshot_1",
                    "event_type": "tool.call.started",
                    "timestamp": "2099-01-01T00:00:00Z",
                    "tool_name": "pipeline_plan_review",
                    "arguments": {
                        "plan": {
                            "steps": [
                                {
                                    "tool": "nilearn.connectome.ConnectivityMeasure",
                                    "params": {
                                        "kind": "partial correlation",
                                        "estimator": "EmpiricalCovariance",
                                    },
                                }
                            ]
                        }
                    },
                    "error": None,
                }
            )
            + "\n"
        )
        handle.write(
            json.dumps(
                {
                    "trace_id": "trace_after_snapshot_2",
                    "event_type": "tool.call.finished",
                    "timestamp": "2099-01-01T00:00:01Z",
                    "tool_name": "artifact_list",
                    "arguments": {},
                    "error": None,
                }
            )
            + "\n"
        )

    open_loop = srv.write_session_snapshot(
        session_id="signal-open-outer-harness",
        source_client="codex",
        goal="Produce Layer B condition bundle",
        done=["Generated coordinate_table.csv and included_studies.csv."],
        open=["Outer harness still needs to run benchmark evaluation/comparison."],
        next_command="python scripts/neurometabench_v1/run_layer_b_comparison.py",
        tags=["neurometabench", "layer_b"],
    )
    assert open_loop["ok"] is True

    result = srv.session_signal_report_generate(
        since_days=3650,
        limit=10,
        top_k=10,
        min_support=1,
    )

    assert result["ok"] is True
    assert result["sessions_considered"] == 2
    assert result["clean_snapshot_count"] == 1
    assert result["post_snapshot_activity"]["session_count"] == 1
    activity = result["post_snapshot_activity"]["examples"][0]
    assert activity["session_id"] == "signal-clean-layer-b"
    assert "pipeline_plan_review" in activity["review_tool_names"]
    assert "artifact_list" in activity["artifact_inspection_tool_names"]
    assert "partial correlation" in activity["trace_only_invariant_terms"]
    assert not any(
        row["session_id"] == "signal-clean-layer-b"
        for row in result["validation_parser_false_negative_candidates"]
    )
    assert any(
        row["theme"] == "outer_harness_evaluation"
        for row in result["unresolved_next_action_themes"]
    )


def test_session_backfill_to_kg_dry_run_returns_graph_rows(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    snapshot = srv.write_session_snapshot(
        session_id="kg-row-session",
        goal="Add session KG dry-run rows",
        done=[
            "Verified git diff --check -- "
            "src/brain_researcher/services/mcp/server.py."
        ],
        open=["uncommitted-local: MCP change remains local."],
        next_command="pytest -q tests/unit/mcp/test_research_event_tools.py",
        tags=["mcp", "session-lessons"],
    )
    assert snapshot["ok"] is True

    result = srv.session_backfill_to_kg(session_id="kg-row-session")

    assert result["ok"] is True
    assert result["dry_run"] is True
    labels = {label for node in result["nodes"] for label in node["labels"]}
    rel_types = {edge["type"] for edge in result["edges"]}
    assert {
        "AgentSession",
        "TaskSurface",
        "ValidationEvidence",
        "OpenRisk",
        "Outcome",
        "Lesson",
        "NextAction",
    } <= labels
    assert {
        "WORKED_ON_SURFACE",
        "VALIDATED_BY",
        "LEFT_OPEN_RISK",
        "PRODUCED_ARTIFACT",
        "EXPOSED_FAILURE_MODE",
        "HAS_REMEDIATION",
        "SHOULD_UPDATE_AGENT_POLICY",
    } <= rel_types
    node_ids = {node["id"] for node in result["nodes"]}
    assert all(
        edge["source"] in node_ids and edge["target"] in node_ids
        for edge in result["edges"]
    )
    session_node = next(
        node for node in result["nodes"] if "AgentSession" in node["labels"]
    )
    assert (
        session_node["properties"]["raw_session_json"]["session_id"] == "kg-row-session"
    )
    assert result["query_examples"]


def test_session_backfill_to_kg_apply_uses_writer(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    def fake_write(digests):
        captured["digests"] = digests
        return {
            "ok": True,
            "stats": {"nodes_written": 3, "relationships_written": 2},
            "node_count": 3,
            "edge_count": 2,
        }

    monkeypatch.setattr(srv, "_write_session_digests_to_kg", fake_write)

    snapshot = srv.write_session_snapshot(
        session_id="kg-apply-session",
        source_client="codex",
        goal="Apply session KG rows",
        done=["Verified pytest -q tests/unit/mcp/test_research_event_tools.py."],
        open=["partial-validation: live Neo4j was not used in unit test."],
        next_command="pytest -q tests/unit/mcp/test_research_event_tools.py",
        tags=["mcp", "session-lessons"],
    )
    assert snapshot["ok"] is True

    result = srv.session_backfill_to_kg(session_id="kg-apply-session", dry_run=False)

    assert result["ok"] is True
    assert result["dry_run"] is False
    assert result["kg_write_supported"] is True
    assert result["sessions_considered"] == 1
    assert captured["digests"][0]["session_id"] == "kg-apply-session"


def test_research_session_digest_includes_server_derived_signals_and_client_metadata(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)
    run_dir = _write_run(
        tmp_path,
        "existing_run_with_trace",
        status="failed",
        steps=[
            {
                "step_id": "s1",
                "tool_id": "atlas_fetch",
                "params": {},
                "status": "failed",
            },
            {
                "step_id": "s2",
                "tool_id": "connectivity_matrix",
                "params": {},
                "status": "succeeded",
            },
        ],
    )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event_type": "tool.call.started",
                        "payload": {"tool_id": "atlas_fetch"},
                    }
                ),
                json.dumps(
                    {
                        "event_type": "tool.call.finished",
                        "payload": {"status": "failed"},
                    }
                ),
                json.dumps(
                    {
                        "event_type": "stage",
                        "payload": {"status": "retrying"},
                    }
                ),
                json.dumps({"event_type": "error", "payload": {"message": "boom"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    event = srv.log_research_event(
        session_id="trace-session",
        run_id="existing_run_with_trace",
        kind="note",
        content="Attached run needs follow-up",
        source_client="cursor",
        client_session_id="cursor-chat-1",
    )
    assert event["ok"] is True
    snapshot = srv.write_session_snapshot(
        session_id="trace-session",
        run_id="existing_run_with_trace",
        goal="Review attached run",
        done=["captured run signals"],
        open=["inspect failure root cause"],
        next_command="open trace",
        source_client="cursor",
        client_session_id="cursor-chat-1",
    )
    assert snapshot["ok"] is True

    digest = srv.research_session_digest(session_id="trace-session")
    assert digest["ok"] is True
    server_signals = digest["digest"]["server_derived_signals"]
    assert digest["digest"]["source_client"] == "cursor"
    assert digest["digest"]["client_session_id"] == "cursor-chat-1"
    assert server_signals["tool_call_started"] == 1
    assert server_signals["tool_call_finished"] == 1
    assert server_signals["tool_call_non_success"] == 1
    assert server_signals["retry_like_events"] == 1
    assert server_signals["error_like_events"] == 1
    assert server_signals["failed_steps"] == 1
    assert server_signals["research_trace_events"] == 3
    assert server_signals["non_research_trace_events"] == 4

    summary = srv.research_log_summary(top_k=5)
    assert any(
        row == {"source_client": "cursor", "count": 1}
        for row in summary["source_client_counts"]
    )
    assert summary["server_signal_totals"]["tool_call_non_success"] >= 1
    assert summary["server_signal_totals"]["research_trace_events"] >= 3
    assert summary["server_signal_totals"]["non_research_trace_events"] >= 4
    assert summary["sessions_with_non_research_trace_events"] == 1


def test_log_research_event_can_attach_context_trace_rows(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    start = srv.log_research_event(
        session_id="context-trace-session",
        kind="start",
        content="Start session with attached trace rows",
        context={
            "trace_events": [
                {
                    "event_type": "tool.call.started",
                    "payload": {"tool_id": "docker_push"},
                },
                {"event_type": "tool.call.finished", "payload": {"status": "success"}},
                {"event_type": "warning", "payload": {"message": "slow rollout"}},
            ]
        },
    )
    assert start["ok"] is True
    assert start["attached_trace_event_count"] == 3

    snapshot = srv.write_session_snapshot(
        session_id="context-trace-session",
        goal="Close trace-attached session",
        done=["captured external evidence"],
        open=["wire this from clients"],
        next_command="resume with client integration",
    )
    assert snapshot["ok"] is True

    digest = srv.research_session_digest(session_id="context-trace-session")
    assert digest["ok"] is True
    server_signals = digest["digest"]["server_derived_signals"]
    assert server_signals["tool_call_started"] == 1
    assert server_signals["tool_call_finished"] == 1
    assert server_signals["warning_events"] == 1
    assert server_signals["non_research_trace_events"] == 3


def test_log_research_event_persists_attached_conversation_rows(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    start = srv.log_research_event(
        session_id="conversation-session",
        kind="start",
        content="Start session with attached conversation rows",
        context={
            "conversation_messages": [
                {
                    "role": "user",
                    "content": "Can you validate the rollout state?",
                    "timestamp": "2026-04-04T23:59:58Z",
                },
                {
                    "role": "assistant",
                    "content": "I will inspect the live deployment and report back.",
                    "metadata": {"channel": "commentary"},
                },
            ]
        },
    )
    assert start["ok"] is True
    assert start["attached_conversation_message_count"] == 2

    run_dir = tmp_path / "runs" / start["run_id"]
    rows = _read_jsonl(run_dir / "conversation_log.jsonl")
    transcript_rows = _read_jsonl(run_dir / "session_transcript.jsonl")
    assert len(rows) == 2
    assert transcript_rows == rows
    assert rows[0]["role"] == "user"
    assert rows[0]["content"] == "Can you validate the rollout state?"
    assert rows[1]["role"] == "assistant"
    assert rows[1]["metadata"] == {"channel": "commentary"}

    digest = srv.research_session_digest(session_id="conversation-session")
    assert digest["ok"] is True
    assert digest["digest"]["transcript_message_count"] == 2
    assert digest["digest"]["conversation_preview"][-1]["role"] == "assistant"
    assert (
        digest["digest"]["files"]["conversation_log_jsonl"] == "conversation_log.jsonl"
    )
    assert (
        digest["digest"]["files"]["session_transcript_jsonl"]
        == "session_transcript.jsonl"
    )


def test_log_research_event_dedupes_conversation_message_ids_and_accepts_transcript_aliases(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    start = srv.log_research_event(
        session_id="conversation-dedupe-session",
        kind="start",
        content="Start session with transcript aliases",
        context={
            "transcript": [
                {
                    "id": "msg-1",
                    "role": "user",
                    "content": "First user turn",
                    "timestamp": "2026-04-04T23:59:58Z",
                },
                {
                    "id": "msg-2",
                    "role": "assistant",
                    "content": "First assistant turn",
                    "timestamp": "2026-04-04T23:59:59Z",
                },
            ]
        },
    )
    assert start["ok"] is True
    assert start["attached_conversation_message_count"] == 2

    note = srv.log_research_event(
        session_id="conversation-dedupe-session",
        kind="note",
        content="Attach a duplicate plus one new row",
        context={
            "messages": [
                {
                    "message_id": "msg-2",
                    "role": "assistant",
                    "content": "Duplicate assistant turn",
                },
                {
                    "message_id": "msg-3",
                    "role": "user",
                    "content": "Second user turn",
                },
            ]
        },
    )
    assert note["ok"] is True
    assert note["attached_conversation_message_count"] == 1

    run_dir = tmp_path / "runs" / start["run_id"]
    rows = _read_jsonl(run_dir / "conversation_log.jsonl")
    assert [row["message_id"] for row in rows] == ["msg-1", "msg-2", "msg-3"]
    assert len(_read_jsonl(run_dir / "session_transcript.jsonl")) == 3

    digest = srv.research_session_digest(session_id="conversation-dedupe-session")
    assert digest["ok"] is True
    assert digest["digest"]["transcript_message_count"] == 3


def test_log_research_event_accepts_conversation_event_alias_and_preserves_fields(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    start = srv.log_research_event(
        session_id="conversation-fields-session",
        kind="start",
        content="Start session with richer transcript rows",
        context={
            "conversation_events": [
                {
                    "id": "msg-field-1",
                    "turn_id": "turn-001",
                    "kind": "assistant_message",
                    "name": "codex",
                    "role": "assistant",
                    "content": "I inspected the deployment.",
                    "timestamp": "2026-04-05T00:00:05Z",
                }
            ]
        },
    )
    assert start["ok"] is True
    assert start["attached_conversation_message_count"] == 1

    run_dir = tmp_path / "runs" / start["run_id"]
    rows = _read_jsonl(run_dir / "session_transcript.jsonl")
    assert rows[0]["message_id"] == "msg-field-1"
    assert rows[0]["turn_id"] == "turn-001"
    assert rows[0]["kind"] == "assistant_message"
    assert rows[0]["name"] == "codex"
    assert rows[0]["timestamp"] == "2026-04-05T00:00:05Z"


def test_log_research_event_accepts_chat_history_alias(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    start = srv.log_research_event(
        session_id="chat-history-session",
        kind="start",
        content="Start session with chat_history alias",
        context={
            "chat_history": [
                {
                    "id": "chat-msg-1",
                    "role": "user",
                    "content": "Please persist this turn from chat_history.",
                    "timestamp": "2026-04-05T00:00:15Z",
                }
            ]
        },
    )
    assert start["ok"] is True
    assert start["attached_conversation_message_count"] == 1

    run_dir = tmp_path / "runs" / start["run_id"]
    rows = _read_jsonl(run_dir / "session_transcript.jsonl")
    assert rows[0]["message_id"] == "chat-msg-1"
    assert rows[0]["content"] == "Please persist this turn from chat_history."


def test_write_session_snapshot_can_attach_transcript_and_trace_rows(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    start = srv.log_research_event(
        session_id="snapshot-attach-session",
        kind="start",
        content="Start before snapshot attachments",
    )
    assert start["ok"] is True

    snapshot = srv.write_session_snapshot(
        session_id="snapshot-attach-session",
        goal="Close with transcript and trace attachments",
        done=["persisted final transcript"],
        open=["wire richer client payloads"],
        next_command="resume with digest review",
        context={
            "transcript": [
                {
                    "id": "snap-1",
                    "role": "user",
                    "content": "Final user turn",
                    "timestamp": "2026-04-05T00:00:01Z",
                },
                {
                    "id": "snap-2",
                    "role": "assistant",
                    "content": "Final assistant turn",
                    "timestamp": "2026-04-05T00:00:02Z",
                },
            ],
            "trace_events": [
                {
                    "event_type": "tool.call.started",
                    "payload": {"tool_id": "docker_push"},
                },
                {"event_type": "tool.call.finished", "payload": {"status": "success"}},
            ],
        },
    )
    assert snapshot["ok"] is True
    assert snapshot["attached_conversation_message_count"] == 2
    assert snapshot["attached_trace_event_count"] == 2

    run_dir = tmp_path / "runs" / start["run_id"]
    assert len(_read_jsonl(run_dir / "conversation_log.jsonl")) == 2
    assert len(_read_jsonl(run_dir / "session_transcript.jsonl")) == 2
    tool_trace_rows = _read_jsonl(run_dir / "tool_trace.jsonl")
    assert [row["event_type"] for row in tool_trace_rows] == [
        "tool.call.started",
        "tool.call.finished",
    ]

    digest = srv.research_session_digest(session_id="snapshot-attach-session")
    assert digest["ok"] is True
    assert digest["digest"]["transcript_message_count"] == 2
    assert digest["digest"]["server_derived_signals"]["tool_call_started"] == 1
    assert digest["digest"]["server_derived_signals"]["tool_call_finished"] == 1


def test_write_session_snapshot_accepts_tool_trace_aliases(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    start = srv.log_research_event(
        session_id="trace-alias-session",
        kind="start",
        content="Start before tool trace alias attachment",
    )
    assert start["ok"] is True

    snapshot = srv.write_session_snapshot(
        session_id="trace-alias-session",
        goal="Close with tool trace alias attachment",
        done=["persisted external trace alias"],
        open=[],
        next_command="resume later",
        context={
            "tool_trace_events": [
                {
                    "event_type": "tool.call.started",
                    "tool_id": "kubectl",
                    "timestamp": "2026-04-05T00:00:10Z",
                },
                {
                    "event_type": "tool.call.finished",
                    "tool_id": "kubectl",
                    "status": "success",
                    "timestamp": "2026-04-05T00:00:12Z",
                },
            ]
        },
    )
    assert snapshot["ok"] is True
    assert snapshot["attached_trace_event_count"] == 2

    run_dir = tmp_path / "runs" / start["run_id"]
    tool_trace_rows = _read_jsonl(run_dir / "tool_trace.jsonl")
    assert [row["tool_name"] for row in tool_trace_rows] == ["kubectl", "kubectl"]
    assert [row["timestamp"] for row in tool_trace_rows] == [
        "2026-04-05T00:00:10Z",
        "2026-04-05T00:00:12Z",
    ]


def test_call_tool_wrapper_persists_tool_trace_rows_for_bound_session(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)
    ctx = _FakeToolContext("codex-client-trace")

    start = srv._run_async_sync(
        srv.mcp._tool_manager.call_tool(
            "log_research_event",
            {
                "kind": "start",
                "content": "Start wrapper-bound session",
                "source_client": "codex",
                "client_session_id": "trace-chat",
            },
            context=ctx,
        )
    )
    assert start["ok"] is True
    run_id = start["run_id"]

    payload = srv._run_async_sync(
        srv.mcp._tool_manager.call_tool(
            "run_get",
            {"run_id": run_id},
            context=ctx,
        )
    )
    assert payload["ok"] is True

    run_dir = tmp_path / "runs" / run_id
    rows = _read_jsonl(run_dir / "tool_trace.jsonl")
    run_get_rows = [row for row in rows if row.get("tool_name") == "run_get"]
    assert [row["event_type"] for row in run_get_rows] == [
        "tool.call.started",
        "tool.call.finished",
    ]
    assert run_get_rows[0]["arguments"] == {"run_id": run_id}
    assert run_get_rows[1]["result"]["ok"] is True

    snapshot = srv.write_session_snapshot(
        session_id="codex:trace-chat",
        goal="Close trace session",
        done=["captured tool trace"],
        open=["wire transcript ingestion from clients"],
        next_command="resume trace work",
        source_client="codex",
        client_session_id="trace-chat",
    )
    assert snapshot["ok"] is True

    digest = srv.research_session_digest(session_id="codex:trace-chat")
    assert digest["ok"] is True
    assert digest["digest"]["tool_trace_event_count"] >= 2
    assert digest["digest"]["server_derived_signals"]["tool_call_started"] >= 1
    assert digest["digest"]["server_derived_signals"]["tool_call_finished"] >= 1
    assert any(
        row["event_type"] == "tool.call.finished" and row["tool_name"] == "run_get"
        for row in digest["digest"]["tool_trace_preview"]
    )
    assert digest["digest"]["files"]["tool_trace_jsonl"] == "tool_trace.jsonl"


def test_call_tool_wrapper_emits_directive_and_auto_telemetry(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)
    ctx = _FakeToolContext("codex-client-1")

    start = srv._run_async_sync(
        srv.mcp._tool_manager.call_tool(
            "log_research_event",
            {
                "kind": "start",
                "content": "Start managed tool session",
                "source_client": "codex",
                "client_session_id": "chat-1",
            },
            context=ctx,
        )
    )
    assert start["ok"] is True
    directive = start["_agent_directive"]["research_logging"]
    assert directive["protocol"] == "br.research_logging.directive.v1"
    assert directive["state"]["session_id"] == "codex:chat-1"
    assert directive["state"]["transcript_capture_supported"] is True
    assert directive["state"]["external_trace_capture_supported"] is True
    assert directive["state"]["preferred_transcript_context_key"] == "transcript"
    assert directive["state"]["preferred_trace_context_key"] == "external_trace_events"
    assert _directive_action(directive, "bind_session")["payload"]["session_id"] == (
        "codex:chat-1"
    )
    assert _directive_action(directive, "write_snapshot_on_close")["required"] is True
    close_payload = _directive_action(directive, "write_snapshot_on_close")["payload"]
    assert close_payload["context_contract"]["preferred_transcript_key"] == "transcript"
    assert (
        close_payload["context_contract"]["preferred_trace_key"]
        == "external_trace_events"
    )
    assert close_payload["context_contract"]["transcript_aliases"] == [
        "transcript",
        "messages",
        "chat_history",
        "conversation_events",
        "conversation_messages",
        "conversation_log",
    ]
    assert close_payload["context_contract"]["trace_aliases"] == [
        "external_trace_events",
        "trace_events",
        "tool_trace",
        "tool_trace_events",
    ]
    assert (
        _directive_action(directive, "attach_transcript_on_close")["payload"][
            "preferred_context_key"
        ]
        == "transcript"
    )
    assert (
        _directive_action(directive, "attach_transcript_on_close")["payload"][
            "target_file"
        ]
        == "session_transcript.jsonl"
    )
    assert (
        _directive_action(directive, "attach_external_trace_on_close")["payload"][
            "preferred_context_key"
        ]
        == "external_trace_events"
    )
    assert (
        _directive_action(directive, "attach_external_trace_on_close")["payload"][
            "target_file"
        ]
        == "tool_trace.jsonl"
    )
    assert (
        _directive_action(directive, "log_optional_note")["payload"]["kind"] == "note"
    )

    run_id = start["run_id"]
    saw_compact_repeat = False
    for _ in range(5):
        payload = srv._run_async_sync(
            srv.mcp._tool_manager.call_tool(
                "run_get",
                {"run_id": run_id},
                context=ctx,
            )
        )
        assert payload["ok"] is True
        directive = payload["_agent_directive"]["research_logging"]
        assert directive["state"]["session_id"] == "codex:chat-1"
        saw_compact_repeat = saw_compact_repeat or (
            directive.get("directive_ref", {}).get("mode") == "compact_repeat"
        )
    assert saw_compact_repeat is True

    failing = srv._run_async_sync(
        srv.mcp._tool_manager.call_tool(
            "run_get",
            {"run_id": "missing-run"},
            context=ctx,
        )
    )
    assert failing["ok"] is False
    failing_directive = failing["_agent_directive"]["research_logging"]
    auto_action = _directive_action(failing_directive, "observe_server_auto_event")
    assert auto_action["payload"]["event_type"] == "research.auto.tool_error"

    digest = srv.research_session_digest(session_id="codex:chat-1")
    assert digest["ok"] is True
    assert digest["digest"]["event_counts"]["auto"] >= 2
    assert any(
        row["event_type"] == "research.auto.heartbeat"
        for row in digest["digest"]["auto_events"]
    )
    assert any(
        row["event_type"] == "research.auto.tool_error"
        for row in digest["digest"]["auto_events"]
    )


def test_research_event_kind_normalizer_coerces_and_never_raises():
    from brain_researcher.services.mcp import server as srv

    norm = srv._normalize_research_event_kind
    # canonical pass-through
    assert norm("start") == "start"
    assert norm("note") == "note"
    # case / separator insensitivity
    assert norm("SESSION_START") == "start"
    assert norm("session-start") == "start"
    assert norm("Begin") == "start"
    # synonyms collapse to the generic bucket
    for syn in ("event", "milestone", "update", "finding", "progress", "log"):
        assert norm(syn) == "note"
    # unknown / empty degrade to "note" instead of raising
    assert norm("totally-made-up") == "note"
    assert norm("") == "note"
    assert norm(None) == "note"


def test_research_log_source_normalizer_coerces_and_never_raises():
    from brain_researcher.services.mcp import server as srv

    norm = srv._normalize_research_log_source
    assert norm("agent") == "agent"
    assert norm("user") == "user"
    # agent synonyms (the exact values weak hosts guessed)
    for syn in ("assistant", "Codex", "claude-code", "gpt", "system"):
        assert norm(syn) == "agent"
    # user synonyms
    for syn in ("human", "Person", "researcher"):
        assert norm(syn) == "user"
    # unknown / empty fall back to the default author
    assert norm("reviewer") == "agent"
    assert norm("") == "agent"
    assert norm(None) == "agent"


def test_log_research_event_accepts_synonym_kind_and_source(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.log_research_event(
        session_id="codex-session-synonyms",
        kind="milestone",  # synonym → note
        content="Picked fMRIPrep pin from recipe summary",
        source="codex",  # synonym → agent
    )

    assert resp["ok"] is True
    assert resp.get("error") is None
    run_dir = tmp_path / "runs" / resp["run_id"]
    events = _read_jsonl(run_dir / "research_events.jsonl")
    assert events[0]["kind"] == "note"
    assert events[0]["source"] == "agent"


def test_log_research_event_schema_advertises_kind_and_source_enums():
    from brain_researcher.services.mcp import server as srv

    tools = srv._run_async_sync(srv.mcp.list_tools())
    schema = next(t.inputSchema for t in tools if t.name == "log_research_event")
    props = schema["properties"]
    assert props["kind"]["enum"] == ["start", "note"]
    assert props["source"]["enum"] == ["agent", "user"]
    # kind stays a plain string server-side (permissive) so synonyms still coerce
    assert props["kind"]["type"] == "string"
