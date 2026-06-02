"""Shared helpers for paradigm default resolvers.

Each paradigm resolver returns a :class:`BehaviorTaskSpecV1` wrapper that
composes a :class:`TaskProgramV1` (``engine="psyflow"``) plus BR-specific
fields (scanner, BIDS/HED, provenance, notes). Psyflow-specific knobs
(n_trials, conditions, timing, stimuli, response_keys, feedback, extras)
go into ``task_program.environment_config``.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from brain_researcher.behavior.task_spec import (
    BehaviorTaskSpecV1,
    ScannerProfile,
)
from brain_researcher.core.contracts.task_program import TaskProgramV1

BASE_BIDS_COLUMNS: list[str] = [
    "onset",
    "duration",
    "trial_type",
    "response_time",
    "response",
    "accuracy",
]


# Fields that live at the TaskProgramV1.environment_config layer (psyflow-side
# paradigm knobs). Everything else on the flat defaults dict goes to the
# BR wrapper (scanner/BIDS/HED/notes) or the TaskProgramV1 top level.
_ENV_CONFIG_KEYS = {
    "n_trials",
    "n_blocks",
    "trial_duration_sec",
    "iti_sec",
    "conditions",
    "response_keys",
    "feedback",
    "stimuli",
    "extras",
}


def _merge(
    defaults: dict[str, Any], overrides: dict[str, Any] | None
) -> dict[str, Any]:
    """Deep-merge ``overrides`` on top of ``defaults`` (non-destructive)."""
    out = deepcopy(defaults)
    if not overrides:
        return out
    for k, v in overrides.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def build_spec_from_flat(
    merged: dict[str, Any],
    *,
    engine: str = "psyflow",
    program_id: str | None = None,
) -> BehaviorTaskSpecV1:
    """Build a :class:`BehaviorTaskSpecV1` from a flat paradigm-defaults dict.

    The flat dict mirrors the pre-refactor shape used by catalog resolvers.
    Keys in ``_ENV_CONFIG_KEYS`` get routed into
    ``task_program.environment_config``; the rest are routed to the BR
    wrapper.
    """
    work = deepcopy(merged)

    paradigm = str(work.pop("paradigm", "")).strip()
    if not paradigm:
        raise ValueError("paradigm must be non-empty")

    paradigm_label = work.pop("paradigm_label", None)
    version = work.pop("version", "1.0")
    scanner = work.pop("scanner", None)
    if isinstance(scanner, dict):
        scanner = ScannerProfile(**scanner)
    bids_columns = list(work.pop("bids_columns", []) or [])
    hed_tags = dict(work.pop("hed_tags", {}) or {})
    notes = work.pop("notes", None)
    prompt_provenance = work.pop("prompt_provenance", None)
    review_metadata = dict(work.pop("review_metadata", {}) or {})

    environment_config: dict[str, Any] = {}
    for key in list(work.keys()):
        if key in _ENV_CONFIG_KEYS:
            environment_config[key] = work.pop(key)

    # Remaining unknown keys would trigger the wrapper's extra="forbid"
    # if we tried to shove them into the wrapper, so surface loudly.
    if work:
        raise ValueError(
            "unrecognized paradigm-defaults keys: " + ", ".join(sorted(work.keys()))
        )

    environment_config.setdefault("n_blocks", 1)
    environment_config.setdefault("conditions", [])
    environment_config.setdefault("response_keys", [])
    environment_config.setdefault("feedback", False)
    environment_config.setdefault("stimuli", {})
    environment_config.setdefault("extras", {})

    program = TaskProgramV1(
        program_id=program_id or f"psyflow::{paradigm}",
        canonical_task_id=paradigm,
        engine=engine,
        environment_id=f"psyflow:{paradigm}",
        environment_config=environment_config,
        observation_schema="behavior-trial-v1",
    )

    return BehaviorTaskSpecV1(
        task_program=program,
        paradigm_label=paradigm_label,
        version=version,
        scanner=scanner,
        bids_columns=bids_columns,
        hed_tags=hed_tags,
        prompt_provenance=prompt_provenance,
        review_metadata=review_metadata,
        notes=notes,
    )


def build_config_sections(spec: BehaviorTaskSpecV1) -> dict[str, Any]:
    """Common BR -> psyflow config skeleton used by all paradigm mappers.

    Reads through the wrapper's compatibility accessors so the emitted
    scaffold config is byte-identical to the pre-refactor shape.
    """
    scanner = None
    if spec.scanner is not None:
        scanner = spec.scanner.model_dump(mode="json")
    return {
        "task": {
            "paradigm": spec.paradigm,
            "paradigm_label": spec.paradigm_label,
            "version": spec.version,
            "n_trials": spec.n_trials,
            "n_blocks": spec.n_blocks,
            "feedback": bool(spec.feedback),
            "notes": spec.notes,
        },
        "timing": {
            "trial_duration_sec": spec.trial_duration_sec,
            "iti_sec": spec.iti_sec,
        },
        "conditions": list(spec.conditions),
        "response": {
            "keys": list(spec.response_keys),
        },
        "scanner": scanner,
        "bids": {
            "columns": list(spec.bids_columns),
            "hed_tags": dict(spec.hed_tags),
        },
        "stimuli": dict(spec.stimuli),
        "extras": dict(spec.extras),
    }


__all__ = [
    "BASE_BIDS_COLUMNS",
    "_merge",
    "build_config_sections",
    "build_spec_from_flat",
]
