"""Tests for the external scientific-review directive MCP surface.

Covers the stateless directive emitter
(``request_external_scientific_review_directive``) and the companion verdict
submitter (``submit_external_scientific_review_verdict``). The design is:
BR does not read the run — it only emits evaluation conditions and accepts a
verdict produced by an external coding agent.
"""

from __future__ import annotations

import json
from pathlib import Path


def _configure_run_root(monkeypatch, tmp_path: Path):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.review import kg_rule_registry

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "_run_roots_for_read", lambda: [tmp_path])
    monkeypatch.setattr(
        kg_rule_registry,
        "build_external_review_kg_criteria",
        lambda **_kwargs: {},
    )
    srv._ensure_dirs()
    return srv


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _minimal_valid_verdict(
    *,
    correctness: str = "pass",
    judgment: str = "sound",
    completeness: str = "complete",
    overall: str = "proceed",
) -> dict:
    return {
        "correctness": {"decision": correctness, "findings": []},
        "judgment": {
            "decision": judgment,
            "estimand_complete": True,
            "method_defensible": True,
            "issues": [],
            "reviewer_questions": [],
        },
        "completeness": {
            "decision": completeness,
            "checklist": {},
            "missing_caveats": [],
        },
        "overall_decision": overall,
    }


# ---------------------------------------------------------------------------
# Directive emission
# ---------------------------------------------------------------------------


def test_directive_shape_without_hints(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.request_external_scientific_review_directive(
        goal="Review my cluster fitlins run",
    )

    assert resp["ok"] is True
    assert resp["protocol"] == "br.external_review.directive.v1"
    assert resp["review_type"] == "scientific_review"
    assert resp["goal"] == "Review my cluster fitlins run"
    assert resp["directive_id"].startswith("ext_review_dir_")
    assert resp["verdict_schema_ref"] == "br.ScientificReviewVerdict.v1"
    assert resp["verdict_schema"]["title"] == "ScientificReviewVerdict"
    assert "ReviewFinding" in resp["verdict_schema"]["$defs"]
    assert resp["submission_tool"] == "submit_external_scientific_review_verdict"
    assert resp["hints_applied"] == {}
    assert resp["tailored_checks"] == []
    assert set(resp["evaluation_axes"].keys()) == {
        "correctness",
        "completeness",
        "judgment",
        "overall",
    }
    # No session_id supplied → we should not have emitted a research event.
    assert "logged_event_id" not in resp
    assert "logged_run_id" not in resp


def test_directive_echoes_normalized_client_session_binding(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.request_external_scientific_review_directive(
        goal="Review my cluster fitlins run",
        client_session_id="thread-123",
        source_client="chatgpt_codex",
    )

    assert resp["ok"] is True
    assert resp["session_id"] == "chatgpt_codex:thread-123"
    assert resp["client_session_id"] == "thread-123"
    assert resp["source_client"] == "chatgpt_codex"
    assert any(
        "session binding fields returned in this directive" in line
        for line in resp["agent_instructions"]
    )


def test_directive_decision_spaces_match_contract(tmp_path, monkeypatch):
    """Directive must stay in lockstep with ScientificReviewVerdict literals."""

    srv = _configure_run_root(monkeypatch, tmp_path)
    from brain_researcher.core.contracts.scientific_review import (
        CompletenessVerdict,
        CorrectnessVerdict,
        JudgmentVerdict,
        ScientificReviewVerdict,
    )

    resp = srv.request_external_scientific_review_directive(goal="parity check")
    axes = resp["evaluation_axes"]

    def _literal_values(model, field):
        # pydantic v2: field annotation is Literal[...] whose __args__ are the values.
        return set(model.model_fields[field].annotation.__args__)

    assert set(axes["correctness"]["decision_space"]) == _literal_values(
        CorrectnessVerdict, "decision"
    )
    assert set(axes["judgment"]["decision_space"]) == _literal_values(
        JudgmentVerdict, "decision"
    )
    assert set(axes["completeness"]["decision_space"]) == _literal_values(
        CompletenessVerdict, "decision"
    )
    assert set(axes["overall"]["decision_space"]) == _literal_values(
        ScientificReviewVerdict, "overall_decision"
    )
    assert (
        "Non-blocking structural correctness flags -> diagnose."
        in axes["overall"]["criteria"]
    )


def test_directive_hint_tailors_fitlins_multiverse(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.request_external_scientific_review_directive(
        goal="Review fitlins multiverse cluster output",
        hints={"adapter": "fitlins_multiverse"},
    )

    assert resp["ok"] is True
    assert resp["hints_applied"] == {"adapter": "fitlins_multiverse"}
    tailored = resp["tailored_checks"]
    assert tailored, "expected adapter-specific tailored checks"
    axes_present = {block["axis"] for block in tailored}
    assert {"correctness", "completeness", "judgment"}.issubset(axes_present)
    for block in tailored:
        assert block["hint"] == "fitlins_multiverse"
        assert block["criteria"]


def test_directive_unknown_hint_has_no_tailoring(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.request_external_scientific_review_directive(
        goal="some run",
        hints={"adapter": "never_heard_of_this"},
    )
    assert resp["ok"] is True
    assert resp["tailored_checks"] == []


def test_directive_attaches_kg_criteria_under_existing_axes(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)
    from brain_researcher.services.review import kg_rule_registry

    monkeypatch.setattr(
        kg_rule_registry,
        "build_external_review_kg_criteria",
        lambda **_kwargs: {
            "correctness": [
                {
                    "rule_id": "UNCORRECTED_WHOLEBRAIN",
                    "kg_node_id": "review_rule:uncorrected_wholebrain",
                    "severity": "BLOCK",
                    "lifecycle_status": "implemented",
                    "br_executable": True,
                    "agent_instruction": "cite this rule when triggered",
                }
            ],
            "judgment": [
                {
                    "rule_id": "REVERSE_INFERENCE",
                    "kg_node_id": "review_rule:reverse_inference",
                    "severity": "WARN",
                    "lifecycle_status": "nlp_llm_candidate",
                    "br_executable": False,
                    "agent_instruction": "check claim inflation",
                }
            ],
        },
    )

    resp = srv.request_external_scientific_review_directive(
        goal="external agent should review a paper text",
    )

    assert resp["ok"] is True
    assert resp["protocol"] == "br.external_review.directive.v1"
    assert set(resp["evaluation_axes"].keys()) == {
        "correctness",
        "completeness",
        "judgment",
        "overall",
    }
    correctness_criteria = resp["evaluation_axes"]["correctness"][
        "kg_derived_criteria"
    ]
    assert correctness_criteria[0]["rule_id"] == "UNCORRECTED_WHOLEBRAIN"
    assert correctness_criteria[0]["br_executable"] is True
    assert resp["evaluation_axes"]["judgment"]["kg_derived_criteria"][0][
        "rule_id"
    ] == "REVERSE_INFERENCE"
    assert resp["kg_rule_registry"]["criteria_count"] == 2
    assert any(
        "cite matching KG rule_id values" in line
        for line in resp["agent_instructions"]
    )


def test_directive_missing_goal_returns_error(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)
    resp = srv.request_external_scientific_review_directive(goal="")
    assert resp["ok"] is False
    assert resp["error"] == "invalid_arguments"


def test_directive_logs_event_when_session_id_given(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.request_external_scientific_review_directive(
        goal="Review my fitlins run",
        hints={"adapter": "fitlins_multiverse"},
        session_id="ext-review-session-1",
    )

    assert resp["ok"] is True
    assert resp.get("logged_event_id")
    run_id = resp["logged_run_id"]
    events = _read_jsonl(
        tmp_path / "runs" / run_id / "research_events.jsonl"
    )
    assert events
    last = events[-1]
    assert "directive_issued" in last["tags"]
    assert last["context"]["directive_id"] == resp["directive_id"]
    assert last["context"]["tailoring_keys"] == ["fitlins_multiverse"]


def test_directive_logging_failure_fails_closed(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)
    monkeypatch.setattr(
        srv,
        "log_research_event",
        lambda **kwargs: {"ok": False, "error": "synthetic_log_failure"},
    )

    resp = srv.request_external_scientific_review_directive(
        goal="Review my fitlins run",
        session_id="ext-review-session-2",
    )

    assert resp["ok"] is False
    assert resp["error"] == "directive_logging_failed"
    assert resp["session_id"] == "ext-review-session-2"


def test_request_scientific_review_routes_run_id_to_full_br_review(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)
    calls: dict[str, dict] = {}

    def fake_run_scientific_review(run_id, **kwargs):
        calls["run"] = {"run_id": run_id, **kwargs}
        return {"ok": True, "overall_decision": "proceed"}

    monkeypatch.setattr(srv, "run_scientific_review", fake_run_scientific_review)

    resp = srv.request_scientific_review(
        run_id="br_123",
        workflow_id="wf_1",
        use_judgment_critic=False,
        force_recompute=True,
    )

    assert resp["ok"] is True
    assert resp["overall_decision"] == "proceed"
    assert resp["review_route"] == {
        "selected": "run_scientific_review",
        "source": {"kind": "run_id", "value": "br_123"},
        "target_tool": "run_scientific_review",
    }
    assert calls["run"] == {
        "run_id": "br_123",
        "workflow_id": "wf_1",
        "use_judgment_critic": False,
        "force_recompute": True,
    }


def test_request_scientific_review_routes_autoresearch_dir(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)
    calls: dict[str, dict] = {}

    def fake_run_autoresearch_scientific_review(autoresearch_dir, **kwargs):
        calls["autoresearch"] = {"autoresearch_dir": autoresearch_dir, **kwargs}
        return {"ok": True, "overall_decision": "explore_more"}

    monkeypatch.setattr(
        srv,
        "run_autoresearch_scientific_review",
        fake_run_autoresearch_scientific_review,
    )

    resp = srv.request_scientific_review(
        autoresearch_dir="/tmp/ar",
        logs_dir="/tmp/ar/logs",
        task_id="task-x",
        use_judgment_critic=False,
        force_recompute=True,
    )

    assert resp["ok"] is True
    assert resp["overall_decision"] == "explore_more"
    assert resp["review_route"] == {
        "selected": "run_autoresearch_scientific_review",
        "source": {"kind": "autoresearch_dir", "value": "/tmp/ar"},
        "target_tool": "run_autoresearch_scientific_review",
    }
    assert calls["autoresearch"] == {
        "autoresearch_dir": "/tmp/ar",
        "logs_dir": "/tmp/ar/logs",
        "task_id": "task-x",
        "use_judgment_critic": False,
        "force_recompute": True,
    }


def test_request_scientific_review_without_source_returns_external_directive(
    tmp_path, monkeypatch
):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.request_scientific_review(
        goal="Review an external fitlins run",
        hints={"adapter": "fitlins_multiverse"},
    )

    assert resp["ok"] is True
    assert resp["protocol"] == "br.external_review.directive.v1"
    assert resp["submission_tool"] == "submit_external_scientific_review_verdict"
    assert resp["review_route"] == {
        "selected": "external_directive",
        "source": {"kind": "external", "value": None},
        "target_tool": "request_external_scientific_review_directive",
    }


def test_request_scientific_review_rejects_ambiguous_sources(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.request_scientific_review(
        run_id="br_123",
        autoresearch_dir="/tmp/ar",
    )

    assert resp["ok"] is False
    assert resp["error"] == "ambiguous_review_source"


# ---------------------------------------------------------------------------
# Verdict submission
# ---------------------------------------------------------------------------


def test_submit_verdict_happy_path_clean_proceed(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    directive = srv.request_external_scientific_review_directive(
        goal="clean run",
        session_id="ext-session-clean",
    )
    assert directive["ok"] is True

    resp = srv.submit_external_scientific_review_verdict(
        directive_id=directive["directive_id"],
        verdict=_minimal_valid_verdict(),
        session_id="ext-session-clean",
        reviewer="external_coding_agent",
    )

    assert resp["ok"] is True
    assert resp["directive_id"] == directive["directive_id"]
    assert resp["verdict_id"].startswith("ext_review_verdict_")
    assert resp["reviewer"] == "external_coding_agent"
    assert resp["inner_verdict"]["overall_decision"] == "proceed"
    # Clean verdict → no handoff directive.
    assert "_agent_directive" not in resp
    # Event recorded.
    run_id = resp["logged_run_id"]
    events = _read_jsonl(
        tmp_path / "runs" / run_id / "research_events.jsonl"
    )
    verdict_events = [
        e for e in events if "external_review_verdict" in e.get("tags", [])
    ]
    assert verdict_events
    assert verdict_events[-1]["context"]["verdict_id"] == resp["verdict_id"]


def test_submit_verdict_flag_emits_review_handoff_directive(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    directive = srv.request_external_scientific_review_directive(
        goal="flagged run",
        session_id="ext-session-flag",
    )
    assert directive["ok"] is True

    verdict = _minimal_valid_verdict(
        correctness="flag",
        judgment="sound",
        completeness="complete",
        overall="diagnose",
    )
    resp = srv.submit_external_scientific_review_verdict(
        directive_id=directive["directive_id"],
        verdict=verdict,
        session_id="ext-session-flag",
    )

    assert resp["ok"] is True
    assert "_agent_directive" in resp
    handoff = resp["_agent_directive"]["review_handoff"]
    assert handoff["protocol"] == "br.review_handoff.directive.v1"
    assert handoff["review_type"] == "scientific_review"
    assert handoff["inner_verdict"]["overall_decision"] == "diagnose"


def test_submit_verdict_logs_kg_rule_feedback(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)
    from brain_researcher.services.review import kg_rule_registry

    calls: dict[str, dict] = {}

    def fake_summarize(verdict, **_kwargs):
        calls["summarize"] = verdict
        return {
            "registry_id": "scientific_review_rule_registry_v1",
            "cited_rule_ids": ["UNCORRECTED_WHOLEBRAIN"],
            "kg_rule_hits": [
                {
                    "kg_rule_id": "UNCORRECTED_WHOLEBRAIN",
                    "kg_node_id": "review_rule:uncorrected_wholebrain",
                    "cited_rule_ids": ["UNCORRECTED_WHOLEBRAIN"],
                    "severity": "BLOCK",
                    "lifecycle_status": "implemented",
                }
            ],
            "unknown_rule_ids": [],
            "status": "ok",
        }

    def fake_record(**kwargs):
        calls["record"] = kwargs
        return {"ok": True, "status": "recorded", "created": 1}

    monkeypatch.setattr(
        kg_rule_registry,
        "summarize_external_review_rule_feedback",
        fake_summarize,
    )
    monkeypatch.setattr(
        kg_rule_registry,
        "record_external_review_rule_feedback",
        fake_record,
    )

    directive = srv.request_external_scientific_review_directive(
        goal="blocked run",
        session_id="ext-session-kg-feedback",
    )
    assert directive["ok"] is True

    verdict = _minimal_valid_verdict(
        correctness="block",
        judgment="sound",
        completeness="complete",
        overall="stop_with_rationale",
    )
    verdict["correctness"]["findings"] = [
        {
            "rule_id": "UNCORRECTED_WHOLEBRAIN",
            "severity": "error",
            "action": "block",
            "message": "Whole-brain result used p<0.05 uncorrected.",
        }
    ]

    resp = srv.submit_external_scientific_review_verdict(
        directive_id=directive["directive_id"],
        verdict=verdict,
        session_id="ext-session-kg-feedback",
        reviewer="external_coding_agent",
    )

    assert resp["ok"] is True
    assert resp["kg_rule_feedback"]["kg_write"]["status"] == "recorded"
    assert calls["record"]["directive_id"] == directive["directive_id"]
    assert calls["record"]["session_id"] == "ext-session-kg-feedback"
    run_id = resp["logged_run_id"]
    events = _read_jsonl(
        tmp_path / "runs" / run_id / "research_events.jsonl"
    )
    verdict_event = [
        e for e in events if "external_review_verdict" in e.get("tags", [])
    ][-1]
    feedback = verdict_event["context"]["kg_rule_feedback"]
    assert feedback["kg_rule_hits"][0]["kg_node_id"] == (
        "review_rule:uncorrected_wholebrain"
    )


def test_submit_verdict_rejects_unknown_directive_for_session(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    directive = srv.request_external_scientific_review_directive(
        goal="clean run",
        session_id="ext-session-boundary",
    )
    assert directive["ok"] is True

    resp = srv.submit_external_scientific_review_verdict(
        directive_id="ext_review_dir_missing",
        verdict=_minimal_valid_verdict(),
        session_id="ext-session-boundary",
    )

    assert resp["ok"] is False
    assert resp["error"] == "directive_not_found"


def test_submit_verdict_requires_session_binding(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.submit_external_scientific_review_verdict(
        directive_id="ext_review_dir_unit",
        verdict=_minimal_valid_verdict(),
    )

    assert resp["ok"] is False
    assert resp["error"] == "session_binding_required"


def test_submit_verdict_rejects_rollup_inconsistency(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    directive = srv.request_external_scientific_review_directive(
        goal="contradictory run",
        session_id="ext-session-inconsistent",
    )
    assert directive["ok"] is True

    verdict = _minimal_valid_verdict(correctness="block", overall="proceed")
    verdict["correctness"]["findings"] = [
        {"rule_id": "R1", "severity": "critical", "message": "bad model"}
    ]
    resp = srv.submit_external_scientific_review_verdict(
        directive_id=directive["directive_id"],
        verdict=verdict,
        session_id="ext-session-inconsistent",
    )

    assert resp["ok"] is False
    assert resp["error"] == "verdict_inconsistent"
    assert resp["provided_overall_decision"] == "proceed"
    assert resp["expected_overall_decision"] == "stop_with_rationale"


def test_submit_verdict_schema_invalid(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    directive = srv.request_external_scientific_review_directive(
        goal="bad schema run",
        session_id="ext-session-schema-invalid",
    )
    assert directive["ok"] is True
    bad = _minimal_valid_verdict()
    bad.pop("overall_decision")  # required field missing
    resp = srv.submit_external_scientific_review_verdict(
        directive_id=directive["directive_id"],
        verdict=bad,
        session_id="ext-session-schema-invalid",
    )

    assert resp["ok"] is False
    assert resp["error"] == "verdict_schema_invalid"
    assert resp["directive_id"] == directive["directive_id"]
    assert resp["schema_errors"]


def test_submit_verdict_rejects_missing_directive_id(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.submit_external_scientific_review_verdict(
        directive_id="",
        verdict=_minimal_valid_verdict(),
    )
    assert resp["ok"] is False
    assert resp["error"] == "invalid_arguments"


def test_submit_verdict_rejects_non_dict_verdict(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    directive = srv.request_external_scientific_review_directive(
        goal="wrong type run",
        session_id="ext-session-nondict",
    )
    assert directive["ok"] is True
    resp = srv.submit_external_scientific_review_verdict(
        directive_id=directive["directive_id"],
        verdict="not-an-object",  # type: ignore[arg-type]
        session_id="ext-session-nondict",
    )
    assert resp["ok"] is False
    assert resp["error"] == "invalid_arguments"


def test_submit_verdict_logging_failure_fails_closed(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    directive = srv.request_external_scientific_review_directive(
        goal="clean run",
        session_id="ext-session-logfail",
    )
    assert directive["ok"] is True
    monkeypatch.setattr(
        srv,
        "log_research_event",
        lambda **kwargs: {"ok": False, "error": "synthetic_log_failure"},
    )

    resp = srv.submit_external_scientific_review_verdict(
        directive_id=directive["directive_id"],
        verdict=_minimal_valid_verdict(),
        session_id="ext-session-logfail",
    )

    assert resp["ok"] is False
    assert resp["error"] == "verdict_logging_failed"
