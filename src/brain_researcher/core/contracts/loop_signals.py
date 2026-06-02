"""Cross-stage loop signal contracts (v1).

Signals are typed records produced by R1-R5 stages so downstream components can
consume them programmatically (instead of free-text summaries).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Mapping
from uuid import uuid4

from pydantic import BaseModel, Field, TypeAdapter

SignalType = Literal[
    "condition_tag",
    "sensitivity_finding",
    "design_constraint",
    "hypothesis_delta",
    "user_feedback",
]

StageType = Literal["R1", "R2", "R3", "R4", "R5", "unknown"]


def _new_signal_id() -> str:
    return f"ls_{uuid4().hex[:12]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LoopSignalBaseV1(BaseModel):
    schema_version: Literal["loop-signal-v1"] = "loop-signal-v1"
    signal_id: str = Field(default_factory=_new_signal_id)
    signal_type: SignalType
    stage: StageType = "unknown"
    run_id: str | None = None
    plan_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: str = Field(default_factory=_utc_now)
    provenance: dict[str, Any] = Field(default_factory=dict)


class ConditionTagSignalV1(LoopSignalBaseV1):
    signal_type: Literal["condition_tag"] = "condition_tag"
    condition_key: str
    condition_value: str
    conclusion: str | None = None
    conflict_state: str | None = None


class SensitivityFindingSignalV1(LoopSignalBaseV1):
    signal_type: Literal["sensitivity_finding"] = "sensitivity_finding"
    analysis_axis: str
    eta_squared: float = Field(ge=0.0, le=1.0)
    stability_label: str | None = None
    recommended_action: str | None = None


class DesignConstraintSignalV1(LoopSignalBaseV1):
    signal_type: Literal["design_constraint"] = "design_constraint"
    constraint_type: str
    target: str
    requirement: str


class HypothesisDeltaSignalV1(LoopSignalBaseV1):
    signal_type: Literal["hypothesis_delta"] = "hypothesis_delta"
    hypothesis_id: str
    delta_metric: str
    prior_value: float | None = None
    posterior_value: float | None = None
    delta_value: float | None = None


class UserFeedbackSignalV1(LoopSignalBaseV1):
    signal_type: Literal["user_feedback"] = "user_feedback"
    rating: float | None = Field(default=None, ge=0.0, le=5.0)
    helpful: bool | None = None
    feedback_text: str | None = None


LoopSignalRecordV1 = Annotated[
    ConditionTagSignalV1
    | SensitivityFindingSignalV1
    | DesignConstraintSignalV1
    | HypothesisDeltaSignalV1
    | UserFeedbackSignalV1,
    Field(discriminator="signal_type"),
]

_LOOP_SIGNAL_ADAPTER = TypeAdapter(LoopSignalRecordV1)


class ConditionConstraintV1(BaseModel):
    condition_key: str
    condition_value: str
    expected_conclusion: str | None = None
    source_signal_id: str | None = None


class SensitivityConstraintV1(BaseModel):
    analysis_axis: str
    min_eta_squared: float | None = Field(default=None, ge=0.0, le=1.0)
    recommendation: str | None = None
    source_signal_id: str | None = None


class DesignConstraintV1(BaseModel):
    constraint_type: str
    target: str
    requirement: str
    source_signal_id: str | None = None


class CrossStageContextV1(BaseModel):
    schema_version: Literal["cross-stage-context-v1"] = "cross-stage-context-v1"
    task_family: str | None = None
    dataset_id: str | None = None
    predicted_intents: list[str] = Field(default_factory=list)
    condition_constraints: list[ConditionConstraintV1] = Field(default_factory=list)
    sensitivity_constraints: list[SensitivityConstraintV1] = Field(default_factory=list)
    design_constraints: list[DesignConstraintV1] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def parse_loop_signal_record(raw: Any) -> LoopSignalBaseV1 | None:
    if isinstance(raw, LoopSignalBaseV1):
        return raw
    if not isinstance(raw, Mapping):
        return None
    try:
        return _LOOP_SIGNAL_ADAPTER.validate_python(dict(raw))
    except Exception:
        return None


def parse_loop_signals(raw: Any) -> list[LoopSignalBaseV1]:
    if not isinstance(raw, (list, tuple)):
        return []
    parsed: list[LoopSignalBaseV1] = []
    for row in raw:
        signal = parse_loop_signal_record(row)
        if signal is not None:
            parsed.append(signal)
    return parsed


def _as_mapping(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, Mapping) else {}


def coerce_cross_stage_context(raw: Any) -> CrossStageContextV1 | None:
    if raw is None:
        return None
    if isinstance(raw, CrossStageContextV1):
        return raw
    if isinstance(raw, str):
        return CrossStageContextV1(notes=[raw])

    data = _as_mapping(raw)
    if not data:
        return None

    # Accept both new keys and legacy aliases.
    if "condition_constraints" not in data and isinstance(
        data.get("condition_tags"), list
    ):
        normalized: list[dict[str, Any]] = []
        for row in data.get("condition_tags") or []:
            if not isinstance(row, Mapping):
                continue
            normalized.append(
                {
                    "condition_key": row.get("condition_key")
                    or row.get("key")
                    or "condition",
                    "condition_value": row.get("condition_value")
                    or row.get("value")
                    or "",
                    "expected_conclusion": row.get("expected_conclusion")
                    or row.get("conclusion"),
                    "source_signal_id": row.get("source_signal_id")
                    or row.get("signal_id"),
                }
            )
        data["condition_constraints"] = normalized

    if "sensitivity_constraints" not in data and isinstance(
        data.get("sensitivity_findings"), list
    ):
        normalized_sens: list[dict[str, Any]] = []
        for row in data.get("sensitivity_findings") or []:
            if not isinstance(row, Mapping):
                continue
            normalized_sens.append(
                {
                    "analysis_axis": row.get("analysis_axis")
                    or row.get("axis")
                    or "unknown",
                    "min_eta_squared": row.get("min_eta_squared")
                    or row.get("eta_squared"),
                    "recommendation": row.get("recommendation")
                    or row.get("recommended_action"),
                    "source_signal_id": row.get("source_signal_id")
                    or row.get("signal_id"),
                }
            )
        data["sensitivity_constraints"] = normalized_sens

    try:
        return CrossStageContextV1.model_validate(data)
    except Exception:
        fallback = CrossStageContextV1(
            task_family=(
                str(data.get("task_family")) if data.get("task_family") else None
            ),
            dataset_id=str(data.get("dataset_id")) if data.get("dataset_id") else None,
            predicted_intents=[
                str(x) for x in (data.get("predicted_intents") or []) if x
            ],
        )
        summary = data.get("summary")
        if isinstance(summary, str) and summary.strip():
            fallback.notes.append(summary.strip())
        return fallback


def build_cross_stage_context(
    *,
    task_family: str | None,
    dataset_id: str | None,
    predicted_intents: list[str] | None = None,
    query_understanding: Mapping[str, Any] | None = None,
    loop_signals: list[LoopSignalBaseV1] | None = None,
) -> CrossStageContextV1:
    ctx = CrossStageContextV1(
        task_family=task_family,
        dataset_id=dataset_id,
        predicted_intents=[str(x) for x in (predicted_intents or []) if x],
    )

    raw_qur = _as_mapping(query_understanding)
    if raw_qur:
        curated = coerce_cross_stage_context(raw_qur.get("cross_stage_context"))
        if curated:
            ctx.condition_constraints.extend(curated.condition_constraints)
            ctx.sensitivity_constraints.extend(curated.sensitivity_constraints)
            ctx.design_constraints.extend(curated.design_constraints)
            ctx.notes.extend(curated.notes)
        elif isinstance(raw_qur.get("summary"), str):
            ctx.notes.append(str(raw_qur["summary"]))

    for signal in loop_signals or []:
        if signal.signal_type == "condition_tag":
            signal = ConditionTagSignalV1.model_validate(signal.model_dump())
            ctx.condition_constraints.append(
                ConditionConstraintV1(
                    condition_key=signal.condition_key,
                    condition_value=signal.condition_value,
                    expected_conclusion=signal.conclusion,
                    source_signal_id=signal.signal_id,
                )
            )
        elif signal.signal_type == "sensitivity_finding":
            signal = SensitivityFindingSignalV1.model_validate(signal.model_dump())
            ctx.sensitivity_constraints.append(
                SensitivityConstraintV1(
                    analysis_axis=signal.analysis_axis,
                    min_eta_squared=signal.eta_squared,
                    recommendation=signal.recommended_action,
                    source_signal_id=signal.signal_id,
                )
            )
        elif signal.signal_type == "design_constraint":
            signal = DesignConstraintSignalV1.model_validate(signal.model_dump())
            ctx.design_constraints.append(
                DesignConstraintV1(
                    constraint_type=signal.constraint_type,
                    target=signal.target,
                    requirement=signal.requirement,
                    source_signal_id=signal.signal_id,
                )
            )

    return ctx


__all__ = [
    "ConditionConstraintV1",
    "ConditionTagSignalV1",
    "CrossStageContextV1",
    "DesignConstraintSignalV1",
    "DesignConstraintV1",
    "HypothesisDeltaSignalV1",
    "LoopSignalBaseV1",
    "LoopSignalRecordV1",
    "SensitivityConstraintV1",
    "SensitivityFindingSignalV1",
    "UserFeedbackSignalV1",
    "build_cross_stage_context",
    "coerce_cross_stage_context",
    "parse_loop_signal_record",
    "parse_loop_signals",
]
