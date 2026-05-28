from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.core.contracts.autoresearch_line import AutoresearchLineStateV1
from brain_researcher.core.contracts.autoresearch_review import (
    AutoresearchLineDirective,
)
from brain_researcher.core.contracts.scientific_review import (
    CompletenessVerdict,
    CorrectnessVerdict,
    JudgmentVerdict,
    ScientificReviewVerdict,
)
from brain_researcher.services.review.autoresearch_line_controller import (
    apply_line_controller_decision,
    close_line_dead_end,
    derive_line_controller_decision,
    drive_autoresearch_line,
)
from brain_researcher.services.review.autoresearch_line_workspace import (
    load_autoresearch_line_state,
)
from brain_researcher.services.review.autoresearch_report_preflight import (
    run_autoresearch_report_preflight,
)


def _write_workspace(
    root: Path, *, report_text: str, line_type: str = "exploration"
) -> None:
    (root / "outputs").mkdir(parents=True, exist_ok=True)
    (root / "runner_logs").mkdir(parents=True, exist_ok=True)
    (root / "loop_body_prompt.md").write_text("# loop\n", encoding="utf-8")
    (root / "predict.py").write_text(
        "def get_config():\n    return {}\n", encoding="utf-8"
    )
    (root / "experiments.jsonl").write_text(
        json.dumps(
            {
                "iteration": 1,
                "action_type": "final_report",
                "config": {"model": "Ridge", "terms": ["cov"]},
                "results": {"aggregate_mean_r": 0.1, "coverage_fraction": 1.0},
                "self_critique": {"verdict": "ADVANCE"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "outputs" / "final_report.md").write_text(report_text, encoding="utf-8")
    (root / "line_state.json").write_text(
        json.dumps(
            {
                "schema_version": "liu_component_line_state_v0",
                "line_type": line_type,
                "status": "active",
                "workspace": str(root),
                "loaded_modules": ["base", line_type],
                "training_backend": "cpu_local",
                "success_criterion": "do_the_next_thing_honestly",
            }
        ),
        encoding="utf-8",
    )


def _good_report() -> str:
    return """# Final Report

## Pre-Report Self-Critique Checkpoint

### So What
This result matters.

### Method Sensitivity
Primary analysis: baseline model.
Sensitivity analysis: repeated CV and robustness checks.

### Structured Exploratory Pass
We include null and exploratory outcomes.

### Claim Strength
claim_strength: internally_supported
validation_missing: none
final_stopping_condition: PASS
"""


def _review_verdict(
    *,
    overall_decision: str,
    report_action: str,
    line_type: str | None = None,
    next_line_type: str | None = None,
    required_next_actions: list[str] | None = None,
) -> ScientificReviewVerdict:
    return ScientificReviewVerdict(
        correctness=CorrectnessVerdict(decision="pass", findings=[]),
        judgment=JudgmentVerdict(decision="sound"),
        completeness=CompletenessVerdict(decision="complete", checklist={}),
        review_scope="autoresearch_loop",
        overall_decision=overall_decision,
        report_action=report_action,
        claim_strength="internally_supported",
        required_next_actions=required_next_actions or [],
        validation_status={"structural_correctness": "ok"},
        line_directive=AutoresearchLineDirective(
            line_type=line_type,
            next_line_type=next_line_type,
            loaded_modules=["base"],
            forbidden_modules=[],
            training_backend="cpu_local",
            success_criterion="be_honest",
        ),
        rationale="controller test rationale",
    )


def test_report_preflight_accepts_generic_contract(tmp_path: Path) -> None:
    _write_workspace(tmp_path, report_text=_good_report())

    preflight = run_autoresearch_report_preflight(tmp_path)

    assert preflight.ready_for_review is True
    assert preflight.required_fields["claim_strength"] == "internally_supported"
    assert preflight.semantic_checks["primary_analysis_declared"] is True
    assert preflight.semantic_checks["sensitivity_analysis_declared"] is True


def test_report_preflight_flags_missing_blocks(tmp_path: Path) -> None:
    _write_workspace(
        tmp_path,
        report_text="# Final Report\n\nclaim_strength: internally_supported\n",
    )

    preflight = run_autoresearch_report_preflight(tmp_path)

    assert preflight.ready_for_review is False
    codes = {issue.code for issue in preflight.issues}
    assert "MISSING_BLOCK_PRE_REPORT_SELF_CRITIQUE_CHECKPOINT" in codes
    assert "MISSING_FINAL_STOPPING_CONDITION" in codes


def test_controller_accepts_closeout_on_proceed() -> None:
    line_state = AutoresearchLineStateV1(line_type="validation", status="active")
    verdict = _review_verdict(
        overall_decision="proceed",
        report_action="write_report",
        line_type="closeout",
    )

    decision = derive_line_controller_decision(line_state, verdict=verdict)
    updated = apply_line_controller_decision(line_state, decision)

    assert decision.action == "accepted_closeout"
    assert updated.status == "completed"
    assert updated.closeout is not None
    assert updated.closeout.outcome == "halt"


def test_controller_pivots_when_review_requests_sequel() -> None:
    line_state = AutoresearchLineStateV1(line_type="exploration", status="active")
    verdict = _review_verdict(
        overall_decision="diagnose",
        report_action="continue_loop",
        line_type="validation",
        next_line_type="validation",
        required_next_actions=["run_deterministic_audit_rerun"],
    )

    decision = derive_line_controller_decision(line_state, verdict=verdict)

    assert decision.action == "pivot"
    assert decision.closeout is not None
    assert decision.closeout.next_line_type == "validation"


def test_controller_uses_preflight_before_review() -> None:
    line_state = AutoresearchLineStateV1(line_type="exploration", status="active")
    preflight = run_autoresearch_report_preflight("/tmp/does-not-exist-line")

    decision = derive_line_controller_decision(line_state, preflight=preflight)

    assert decision.action == "repair_report_preflight"
    assert decision.pending_directive is not None
    assert decision.pending_directive.directive_type == "repair_report_preflight"


def test_drive_autoresearch_line_persists_updated_state(tmp_path: Path) -> None:
    _write_workspace(tmp_path, report_text=_good_report(), line_type="validation")
    verdict = _review_verdict(
        overall_decision="proceed",
        report_action="write_report",
        line_type="closeout",
    )

    updated_state, decision = drive_autoresearch_line(
        tmp_path,
        verdict=verdict,
        persist=True,
        issued_at_utc="2026-04-18T01:00:00Z",
    )
    reloaded = load_autoresearch_line_state(tmp_path)

    assert decision.action == "accepted_closeout"
    assert updated_state.status == "completed"
    assert reloaded is not None
    assert reloaded.status == "completed"
    assert reloaded.closeout is not None
    assert reloaded.updated_utc == "2026-04-18T01:00:00Z"


def test_close_line_dead_end_marks_completed() -> None:
    line_state = AutoresearchLineStateV1(
        line_type="foundation_transfer", status="active"
    )

    updated = close_line_dead_end(
        line_state,
        reason="missing_required_input_modality",
        summary="Cannot continue without ROI time-series inputs.",
        blockers=["roi_timeseries_missing"],
        issued_at_utc="2026-04-18T01:05:00Z",
    )

    assert updated.status == "completed"
    assert updated.closeout is not None
    assert updated.closeout.outcome == "dead_end"
    assert updated.closeout.unresolved_blockers == ["roi_timeseries_missing"]
