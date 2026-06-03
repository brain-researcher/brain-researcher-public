"""N-back paradigm defaults and psyflow config mapping."""

from __future__ import annotations

from typing import Any

from brain_researcher.behavior.catalog.base import (
    BASE_BIDS_COLUMNS,
    _merge,
    build_config_sections,
    build_spec_from_flat,
)
from brain_researcher.behavior.task_spec import BehaviorTaskSpecV1, ScannerProfile


def _defaults() -> dict[str, Any]:
    return {
        "paradigm": "n_back",
        "paradigm_label": "N-back working memory",
        "n_trials": 60,
        "n_blocks": 3,
        "trial_duration_sec": 2.0,
        "iti_sec": 1.0,
        "conditions": ["0-back", "1-back", "2-back"],
        "response_keys": ["space"],
        "feedback": False,
        "bids_columns": BASE_BIDS_COLUMNS + ["n_back_level", "is_target"],
        "hed_tags": {"n_back_level": "Task-property/Working-memory"},
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
    cfg["task"]["family"] = "working_memory"
    cfg.setdefault("stimuli", {})
    cfg["stimuli"].setdefault("letters", ["A", "B", "C", "D", "E", "F"])
    return cfg


__all__ = ["build", "to_psyflow_config"]
