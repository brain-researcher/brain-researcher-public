"""Flanker paradigm defaults and psyflow config mapping."""

from __future__ import annotations

from typing import Any

from brain_researcher.behavior.task_spec import BehaviorTaskSpecV1, ScannerProfile
from brain_researcher.behavior.catalog.base import (
    BASE_BIDS_COLUMNS,
    _merge,
    build_config_sections,
    build_spec_from_flat,
)


def _defaults() -> dict[str, Any]:
    return {
        "paradigm": "flanker",
        "paradigm_label": "Eriksen flanker",
        "n_trials": 96,
        "n_blocks": 3,
        "trial_duration_sec": 1.5,
        "iti_sec": 1.0,
        "conditions": ["congruent", "incongruent", "neutral"],
        "response_keys": ["left", "right"],
        "feedback": False,
        "bids_columns": BASE_BIDS_COLUMNS + ["congruency", "flanker_direction"],
        "hed_tags": {"congruency": "Task-property/Congruency"},
        "scanner": ScannerProfile(tr_sec=2.0),
    }


def build(overrides: dict[str, Any] | None = None) -> BehaviorTaskSpecV1:
    merged = _merge(_defaults(), overrides or {})
    scanner = merged.get("scanner")
    if isinstance(scanner, ScannerProfile):
        merged["scanner"] = scanner.model_dump(mode="json")
    return build_spec_from_flat(merged)


def to_psyflow_config(spec: BehaviorTaskSpecV1) -> dict[str, Any]:
    cfg = build_config_sections(spec)
    cfg["task"]["family"] = "cognitive_control"
    return cfg


__all__ = ["build", "to_psyflow_config"]
