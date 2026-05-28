"""Run card contract (v1).

RunCard is the human-/UI-oriented summary of a run. This contract is
intentionally lenient to support legacy payloads while the platform converges
producers to a single source of truth.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .ids import IdsV1
from .loop_signals import (
    CrossStageContextV1,
    LoopSignalRecordV1,
    coerce_cross_stage_context,
    parse_loop_signals,
)
from .policy_ref import PolicyRefV1, build_policy_ref_v1
from .version_ref import VersionRefV1, get_cached_version_ref_v1


class RunCardV1(BaseModel):
    schema_version: Literal["run-card-v1"] = "run-card-v1"

    # M0 primitives (first-class; stable envelope)
    ids: IdsV1 = Field(default_factory=IdsV1)
    policy: PolicyRefV1 = Field(default_factory=build_policy_ref_v1)
    versions: VersionRefV1 = Field(default_factory=get_cached_version_ref_v1)

    # Canonical fields (newer shape used by orchestrator/web_ui)
    id: str | None = None
    version: str | None = None
    timestamp: datetime | None = None
    title: str | None = None
    description: str | None = None
    execution: dict[str, Any] | None = None
    inputs: dict[str, Any] | None = None
    # Support both legacy list outputs and newer dict outputs.
    outputs: dict[str, Any] | list[dict[str, Any]] | None = None
    provenance: dict[str, Any] | None = None
    reproducibility: dict[str, Any] | None = None
    cross_stage_context: CrossStageContextV1 | dict[str, Any] | None = None
    loop_signals: list[LoopSignalRecordV1] = Field(default_factory=list)

    # Legacy fields (kept for backward compatibility)
    created_at: str | None = None
    analysis: dict[str, Any] | None = None
    datasets: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    citations: list[Any] = Field(default_factory=list)
    environment: dict[str, Any] | None = None
    reproducibility_score: float | None = None

    @model_validator(mode="after")
    def _backfill_ids(self) -> "RunCardV1":
        # Legacy producers use `id` as job_id.
        if self.ids.job_id is None and self.id:
            self.ids.job_id = self.id
        return self

    @model_validator(mode="after")
    def _normalize_reproducibility_score(self) -> "RunCardV1":
        """Normalize reproducibility scores to 0..1 and keep fields consistent."""

        def _to_float(value: Any) -> float | None:
            if value is None:
                return None
            if isinstance(value, bool):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def _normalize_01(value: float | None) -> float | None:
            if value is None:
                return None
            # Legacy payloads sometimes used 0..100 "percent" scores.
            if value > 1.0 and value <= 100.0:
                value = value / 100.0
            value = max(0.0, min(1.0, value))
            return float(value)

        repro = self.reproducibility if isinstance(self.reproducibility, dict) else None
        repro_score = _to_float(repro.get("score")) if repro else None
        legacy_score = _to_float(self.reproducibility_score)

        normalized = _normalize_01(repro_score if repro_score is not None else legacy_score)
        if normalized is None:
            return self

        self.reproducibility_score = normalized
        if repro is None:
            self.reproducibility = {"score": normalized, "is_reproducible": normalized >= 0.8}
        else:
            repro["score"] = normalized
            repro.setdefault("is_reproducible", normalized >= 0.8)
            self.reproducibility = repro

        return self

    @model_validator(mode="after")
    def _normalize_loop_contracts(self) -> "RunCardV1":
        """Forward-compatible adapter for legacy RunCard payloads."""
        context = coerce_cross_stage_context(self.cross_stage_context)
        self.cross_stage_context = context.model_dump() if context else None
        self.loop_signals = parse_loop_signals(self.loop_signals)
        return self


__all__ = ["RunCardV1"]
