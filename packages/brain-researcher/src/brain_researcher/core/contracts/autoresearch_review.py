"""Contracts for autoresearch-specific scientific review bundles."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ValidationEvidenceItem(BaseModel):
    """Status for one validation evidence category."""

    name: str
    status: Literal["present", "mentioned_only", "missing"]
    artifact_paths: list[str] = Field(default_factory=list)
    report_mentions: list[str] = Field(default_factory=list)
    summary: str = ""


class AutoresearchIterationSummary(BaseModel):
    """Compact summary of one iteration row."""

    iteration: int | None = None
    action_type: str | None = None
    aggregate_mean_r: float | None = None
    coverage_fraction: float | None = None
    n_hit_mean: int | None = None
    verdict: str | None = None
    model: str | None = None
    fc_metric: str | None = None
    path: str | None = None


class AutoresearchComponentSummary(BaseModel):
    """Best/latest component-level summary across the ledger."""

    component: str
    reference_mean_r: float | None = None
    reference_best_r: float | None = None
    best_fold_mean_r: float | None = None
    latest_fold_mean_r: float | None = None
    best_iteration: int | None = None
    latest_iteration: int | None = None
    ever_hit_mean: bool = False
    ever_hit_best: bool = False


class AutoresearchLineDirective(BaseModel):
    """Controller-facing directive for the next autoresearch line shape."""

    line_type: str | None = None
    next_line_type: str | None = None
    loaded_modules: list[str] = Field(default_factory=list)
    forbidden_modules: list[str] = Field(default_factory=list)
    training_backend: str | None = None
    success_criterion: str | None = None


class AutoresearchReviewBundle(BaseModel):
    """Domain-adapted bundle for reviewing autoresearch loops."""

    task_id: str
    autoresearch_dir: str
    logs_dir: str | None = None
    fingerprint: str
    final_report_present: bool = False
    ledger_row_count: int = 0
    latest_iteration: int | None = None
    best_iteration: int | None = None
    latest_summary: AutoresearchIterationSummary | None = None
    best_summary: AutoresearchIterationSummary | None = None
    recent_iterations: list[AutoresearchIterationSummary] = Field(default_factory=list)
    component_summaries: list[AutoresearchComponentSummary] = Field(default_factory=list)
    quality_summary: dict[str, Any] = Field(default_factory=dict)
    claim_strength_declared: str | None = None
    validation_missing_declared: list[str] = Field(default_factory=list)
    validation_evidence: list[ValidationEvidenceItem] = Field(default_factory=list)
    self_critique_sections: list[str] = Field(default_factory=list)
    final_report_text: str | None = None
    review_context: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AutoresearchComponentSummary",
    "AutoresearchIterationSummary",
    "AutoresearchLineDirective",
    "AutoresearchReviewBundle",
    "ValidationEvidenceItem",
]
