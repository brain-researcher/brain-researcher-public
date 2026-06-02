"""Go/No-Go paradigm defaults and psyflow config mapping."""

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
        "paradigm": "go_no_go",
        "paradigm_label": "Go/No-Go inhibition",
        "n_trials": 80,
        "n_blocks": 2,
        "trial_duration_sec": 1.2,
        "iti_sec": 0.8,
        "conditions": ["go", "nogo"],
        "response_keys": ["space"],
        "feedback": False,
        "bids_columns": BASE_BIDS_COLUMNS + ["is_go", "inhibition_success"],
        "hed_tags": {
            "is_go": "Task-stimulus-role/Target",
            "inhibition_success": "Action/Inhibit",
        },
        "scanner": ScannerProfile(tr_sec=1.5),
    }


def build(overrides: dict[str, Any] | None = None) -> BehaviorTaskSpecV1:
    merged = _merge(_defaults(), overrides or {})
    scanner = merged.get("scanner")
    if isinstance(scanner, ScannerProfile):
        merged["scanner"] = scanner.model_dump(mode="json")
    return build_spec_from_flat(merged)


def to_psyflow_config(spec: BehaviorTaskSpecV1) -> dict[str, Any]:
    cfg = build_config_sections(spec)
    cfg["task"]["family"] = "response_inhibition"
    return cfg


__all__ = ["build", "to_psyflow_config"]
