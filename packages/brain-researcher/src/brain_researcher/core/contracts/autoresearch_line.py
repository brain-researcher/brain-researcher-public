"""Generic contracts for line-based autoresearch workspaces."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class LineBudgetEnvelopeV1(BaseModel):
    """Execution budget envelope for one autoresearch line."""

    max_runner_turns: int | None = Field(
        default=None, description="Maximum controller or runner turns allowed."
    )
    max_wallclock_hours: float | None = Field(
        default=None, description="Maximum wallclock budget in hours."
    )
    max_extension_turns: int | None = Field(
        default=None, description="Maximum extra turns that may be granted."
    )
    max_consecutive_no_growth: int | None = Field(
        default=None,
        description="Maximum consecutive iterations without meaningful progress.",
    )
    exploration_floor_iters: int | None = Field(
        default=None,
        description=(
            "Minimum number of non-confirmation iterations that must be logged "
            "before the line may write final_report.md. Confirmation-style "
            "actions (hit_ref_probe, baseline_replicate) do not count toward "
            "this floor."
        ),
    )
    max_confirmation_fraction: float | None = Field(
        default=None,
        description=(
            "Upper bound on the share of iterations that may be confirmation "
            "actions (hit_ref_probe + baseline_replicate). A value of 0.4 means "
            "at most 40% of rows may be confirmation; the rest must advance or "
            "diagnose. Checked at close-time by verify.py."
        ),
    )
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_nonnegative(self) -> LineBudgetEnvelopeV1:
        for field_name in (
            "max_runner_turns",
            "max_wallclock_hours",
            "max_extension_turns",
            "max_consecutive_no_growth",
            "exploration_floor_iters",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if (
            self.max_confirmation_fraction is not None
            and not 0.0 <= self.max_confirmation_fraction <= 1.0
        ):
            raise ValueError("max_confirmation_fraction must be in [0, 1]")
        return self


class LinePendingDirectiveV1(BaseModel):
    """Controller directive that must be handled by the current line."""

    directive_type: str
    source: str | None = None
    issued_at_utc: str | None = None
    must_address_this_turn: bool = False
    message: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class LineTransitionRulesV1(BaseModel):
    """Lifecycle rules that define how a line should react to key events."""

    on_review_accept: str | None = None
    on_review_reject: str | None = None
    on_budget_checkpoint: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class LineDecisionEventV1(BaseModel):
    """One controller-visible lifecycle event for a line."""

    timestamp_utc: str | None = None
    event: str
    details: dict[str, Any] = Field(default_factory=dict)


class LineLatestSummaryV1(BaseModel):
    """Compact summary of the latest completed iteration for a line."""

    iteration: int | None = None
    action_type: str | None = None
    model: str | None = None
    metric: str | None = None
    coverage_fraction: float | None = None
    aggregate_mean_r: float | None = None
    verdict: str | None = None


class LinePivotOptionV1(BaseModel):
    """One candidate sequel or pivot line considered at closeout."""

    line_type: str
    rationale: str | None = None
    trigger: str | None = None
    priority: int | None = None
    blocked_by: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class LineReportPreflightIssueV1(BaseModel):
    """One deterministic report-preflight issue."""

    code: str
    severity: Literal["error", "warn"] = "error"
    message: str
    fix_hint: str | None = None


class LineReportPreflightV1(BaseModel):
    """Deterministic report-preflight result for a line workspace."""

    schema_version: Literal["line-report-preflight-v1"] = "line-report-preflight-v1"

    report_path: str | None = None
    report_present: bool = False
    parse_status: Literal["ok", "missing", "unreadable"] = "missing"
    required_blocks: dict[str, bool] = Field(default_factory=dict)
    required_fields: dict[str, Any] = Field(default_factory=dict)
    semantic_checks: dict[str, bool] = Field(default_factory=dict)
    issues: list[LineReportPreflightIssueV1] = Field(default_factory=list)
    ready_for_review: bool = False


class LineControllerDecisionV1(BaseModel):
    """Controller decision derived from preflight or review signals."""

    schema_version: Literal["line-controller-decision-v1"] = (
        "line-controller-decision-v1"
    )

    action: Literal[
        "repair_report_preflight",
        "continue_current_line",
        "accepted_closeout",
        "pivot",
        "dead_end",
    ]
    updated_status: Literal["draft", "active", "completed", "archived"]
    rationale: str
    pending_directive: LinePendingDirectiveV1 | None = None
    closeout: LineCloseoutV1 | None = None
    trace_event: LineDecisionEventV1 | None = None


class LineCloseoutV1(BaseModel):
    """Terminal or near-terminal closeout summary for a line."""

    outcome: str | None = Field(
        default=None,
        description="Recommended closeout outcome, such as pivot, halt, or dead_end.",
    )
    reason: str | None = None
    summary: str | None = None
    review_decision: str | None = None
    report_action: str | None = None
    claim_strength: str | None = None
    next_line_type: str | None = None
    unresolved_blockers: list[str] = Field(default_factory=list)
    pivot_options: list[LinePivotOptionV1] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class AutoresearchWorkspaceLayoutV1(BaseModel):
    """Stable file-system layout for a line-based autoresearch workspace."""

    schema_version: Literal["autoresearch-workspace-layout-v1"] = (
        "autoresearch-workspace-layout-v1"
    )

    root_dir: str
    line_state_path: str
    experiments_path: str
    bootstrap_ledger_path: str | None = None
    prompt_path: str
    outputs_dir: str
    runner_logs_dir: str
    final_report_path: str
    reference_dirs: list[str] = Field(default_factory=list)
    entrypoint_paths: list[str] = Field(default_factory=list)
    required_paths: list[str] = Field(default_factory=list)
    optional_paths: list[str] = Field(default_factory=list)
    existing_paths: list[str] = Field(default_factory=list)


class AutoresearchLineStateV1(BaseModel):
    """Generic controller state for one autoresearch line."""

    schema_version: Literal["autoresearch-line-state-v1"] = "autoresearch-line-state-v1"

    source_schema_version: str | None = Field(
        default=None,
        description="Original on-disk schema tag when coercing a legacy line_state.json.",
    )
    line_id: str | None = None
    line_type: str | None = None
    status: str = "draft"
    created_utc: str | None = None
    updated_utc: str | None = None
    workspace: str | None = None
    parent_workspace: str | None = None
    reference_workspace: str | None = None
    budget_envelope: LineBudgetEnvelopeV1 | None = None
    runner_turns_completed: int | None = None
    budget_extensions_used: int | None = None
    pending_directive: LinePendingDirectiveV1 | None = None
    transition_rules: LineTransitionRulesV1 | None = None
    spawn_history: list[dict[str, Any]] = Field(default_factory=list)
    decision_trace: list[LineDecisionEventV1] = Field(default_factory=list)
    consecutive_no_growth: int | None = None
    loaded_modules: list[str] = Field(default_factory=list)
    forbidden_modules: list[str] = Field(default_factory=list)
    training_backend: str | None = None
    success_criterion: str | None = None
    last_completed_runner_turn: int | None = None
    last_completed_utc: str | None = None
    last_latest_summary: LineLatestSummaryV1 | None = None
    closeout: LineCloseoutV1 | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_nonnegative(self) -> AutoresearchLineStateV1:
        for field_name in (
            "runner_turns_completed",
            "budget_extensions_used",
            "consecutive_no_growth",
            "last_completed_runner_turn",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        return self


__all__ = [
    "AutoresearchLineStateV1",
    "AutoresearchWorkspaceLayoutV1",
    "LineBudgetEnvelopeV1",
    "LineCloseoutV1",
    "LineDecisionEventV1",
    "LineLatestSummaryV1",
    "LinePendingDirectiveV1",
    "LinePivotOptionV1",
    "LineReportPreflightIssueV1",
    "LineReportPreflightV1",
    "LineControllerDecisionV1",
    "LineTransitionRulesV1",
]
