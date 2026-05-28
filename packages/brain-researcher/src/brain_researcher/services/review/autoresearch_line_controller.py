"""Generic controller skeleton for line-based autoresearch workspaces."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from brain_researcher.core.contracts.autoresearch_line import (
    AutoresearchLineStateV1,
    LineCloseoutV1,
    LineControllerDecisionV1,
    LineDecisionEventV1,
    LinePendingDirectiveV1,
    LinePivotOptionV1,
    LineReportPreflightV1,
)
from brain_researcher.core.contracts.scientific_review import ScientificReviewVerdict
from brain_researcher.services.review.autoresearch_line_workspace import (
    load_autoresearch_line_state,
    write_autoresearch_line_state,
)
from brain_researcher.services.review.autoresearch_report_preflight import (
    run_autoresearch_report_preflight,
)

UTC = timezone.utc


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _preflight_message(preflight: LineReportPreflightV1) -> str:
    codes = [issue.code for issue in preflight.issues[:5]]
    if not codes:
        return "Report preflight failed."
    return "Report preflight failed: " + ", ".join(codes)


def derive_line_controller_decision(
    line_state: AutoresearchLineStateV1,
    *,
    preflight: LineReportPreflightV1 | None = None,
    verdict: ScientificReviewVerdict | None = None,
    issued_at_utc: str | None = None,
) -> LineControllerDecisionV1:
    """Derive the next controller action from preflight and/or review signals."""

    timestamp = issued_at_utc or _utc_now()
    current_line_type = line_state.line_type or "exploration"

    if preflight is not None and not preflight.ready_for_review:
        return LineControllerDecisionV1(
            action="repair_report_preflight",
            updated_status="active",
            rationale=_preflight_message(preflight),
            pending_directive=LinePendingDirectiveV1(
                directive_type="repair_report_preflight",
                source="line_controller",
                issued_at_utc=timestamp,
                must_address_this_turn=True,
                message=_preflight_message(preflight),
                extra={
                    "report_path": preflight.report_path,
                    "issue_codes": [issue.code for issue in preflight.issues],
                },
            ),
            trace_event=LineDecisionEventV1(
                timestamp_utc=timestamp,
                event="report_preflight_failed",
                details={
                    "issue_codes": [issue.code for issue in preflight.issues],
                    "report_path": preflight.report_path,
                },
            ),
        )

    if verdict is None:
        return LineControllerDecisionV1(
            action="continue_current_line",
            updated_status="active",
            rationale="No scientific review verdict available; keep the current line active.",
            pending_directive=LinePendingDirectiveV1(
                directive_type="continue_current_line",
                source="line_controller",
                issued_at_utc=timestamp,
                must_address_this_turn=False,
                message="Continue the current line until a report is ready for review.",
            ),
            trace_event=LineDecisionEventV1(
                timestamp_utc=timestamp,
                event="controller_no_review_verdict",
                details={"line_type": current_line_type},
            ),
        )

    next_line_type = (
        verdict.line_directive.next_line_type if verdict.line_directive else None
    )

    if (
        verdict.overall_decision == "proceed"
        and verdict.report_action == "write_report"
    ):
        return LineControllerDecisionV1(
            action="accepted_closeout",
            updated_status="completed",
            rationale=verdict.rationale
            or "Scientific review accepted the current line.",
            closeout=LineCloseoutV1(
                outcome="halt",
                reason="review_accepted",
                summary=verdict.rationale or "Scientific review accepted the report.",
                review_decision=verdict.overall_decision,
                report_action=verdict.report_action,
                claim_strength=verdict.claim_strength,
                next_line_type=next_line_type,
            ),
            trace_event=LineDecisionEventV1(
                timestamp_utc=timestamp,
                event="review_accepted_closeout",
                details={
                    "claim_strength": verdict.claim_strength,
                    "next_line_type": next_line_type,
                },
            ),
        )

    if next_line_type and next_line_type != current_line_type:
        return LineControllerDecisionV1(
            action="pivot",
            updated_status="completed",
            rationale=verdict.rationale
            or f"Pivot from {current_line_type} to {next_line_type}.",
            closeout=LineCloseoutV1(
                outcome="pivot",
                reason="review_requested_sequel",
                summary=verdict.rationale
                or f"Review requested sequel line {next_line_type}.",
                review_decision=verdict.overall_decision,
                report_action=verdict.report_action,
                claim_strength=verdict.claim_strength,
                next_line_type=next_line_type,
                unresolved_blockers=list(verdict.required_next_actions),
                pivot_options=[
                    LinePivotOptionV1(
                        line_type=next_line_type,
                        rationale=verdict.rationale,
                        trigger=verdict.overall_decision,
                        priority=1,
                        blocked_by=list(verdict.required_next_actions),
                    )
                ],
            ),
            trace_event=LineDecisionEventV1(
                timestamp_utc=timestamp,
                event="review_requested_pivot",
                details={
                    "from_line_type": current_line_type,
                    "to_line_type": next_line_type,
                    "required_next_actions": list(verdict.required_next_actions),
                },
            ),
        )

    if (
        verdict.overall_decision == "stop_with_rationale"
        and verdict.report_action == "revise_report"
        and not verdict.required_next_actions
    ):
        return LineControllerDecisionV1(
            action="dead_end",
            updated_status="completed",
            rationale=verdict.rationale
            or "Scientific review closed the line with rationale.",
            closeout=LineCloseoutV1(
                outcome="dead_end",
                reason="review_stop_with_rationale",
                summary=verdict.rationale or "Scientific review stopped the line.",
                review_decision=verdict.overall_decision,
                report_action=verdict.report_action,
                claim_strength=verdict.claim_strength,
            ),
            trace_event=LineDecisionEventV1(
                timestamp_utc=timestamp,
                event="review_dead_end_closeout",
                details={"line_type": current_line_type},
            ),
        )

    return LineControllerDecisionV1(
        action="continue_current_line",
        updated_status="active",
        rationale=verdict.rationale
        or "Scientific review requires more work on the current line.",
        pending_directive=LinePendingDirectiveV1(
            directive_type="continue_current_line",
            source="line_controller",
            issued_at_utc=timestamp,
            must_address_this_turn=False,
            message=verdict.rationale
            or "Continue the current line and address review findings.",
            extra={
                "overall_decision": verdict.overall_decision,
                "report_action": verdict.report_action,
                "required_next_actions": list(verdict.required_next_actions),
                "line_directive": (
                    verdict.line_directive.model_dump()
                    if verdict.line_directive
                    else None
                ),
            },
        ),
        trace_event=LineDecisionEventV1(
            timestamp_utc=timestamp,
            event="review_continue_current_line",
            details={
                "overall_decision": verdict.overall_decision,
                "required_next_actions": list(verdict.required_next_actions),
            },
        ),
    )


def apply_line_controller_decision(
    line_state: AutoresearchLineStateV1,
    decision: LineControllerDecisionV1,
) -> AutoresearchLineStateV1:
    """Apply a controller decision to a line-state snapshot."""

    updated = line_state.model_copy(deep=True)
    updated.status = decision.updated_status
    updated.pending_directive = decision.pending_directive
    updated.closeout = decision.closeout
    if decision.trace_event is not None:
        updated.decision_trace.append(decision.trace_event)
        updated.updated_utc = decision.trace_event.timestamp_utc
    return updated


def close_line_dead_end(
    line_state: AutoresearchLineStateV1,
    *,
    reason: str,
    summary: str,
    next_line_type: str | None = None,
    blockers: list[str] | None = None,
    issued_at_utc: str | None = None,
) -> AutoresearchLineStateV1:
    """Convenience helper for explicit dead-end closeout outside scientific review."""

    timestamp = issued_at_utc or _utc_now()
    decision = LineControllerDecisionV1(
        action="dead_end",
        updated_status="completed",
        rationale=summary,
        closeout=LineCloseoutV1(
            outcome="dead_end",
            reason=reason,
            summary=summary,
            next_line_type=next_line_type,
            unresolved_blockers=list(blockers or []),
        ),
        trace_event=LineDecisionEventV1(
            timestamp_utc=timestamp,
            event="manual_dead_end_closeout",
            details={
                "reason": reason,
                "next_line_type": next_line_type,
                "blockers": list(blockers or []),
            },
        ),
    )
    return apply_line_controller_decision(line_state, decision)


def drive_autoresearch_line(
    workspace_or_state_path: str | Path,
    *,
    verdict: ScientificReviewVerdict | None = None,
    persist: bool = False,
    issued_at_utc: str | None = None,
) -> tuple[AutoresearchLineStateV1, LineControllerDecisionV1]:
    """Load, decide, and optionally persist the next state for a line workspace."""

    line_state = load_autoresearch_line_state(workspace_or_state_path)
    if line_state is None:
        raise FileNotFoundError(
            f"line_state.json not found under {workspace_or_state_path}"
        )
    preflight = run_autoresearch_report_preflight(workspace_or_state_path)
    decision = derive_line_controller_decision(
        line_state,
        preflight=preflight,
        verdict=verdict,
        issued_at_utc=issued_at_utc,
    )
    updated_state = apply_line_controller_decision(line_state, decision)
    if persist:
        write_autoresearch_line_state(updated_state, workspace_or_state_path)
    return updated_state, decision


__all__ = [
    "apply_line_controller_decision",
    "close_line_dead_end",
    "derive_line_controller_decision",
    "drive_autoresearch_line",
]
