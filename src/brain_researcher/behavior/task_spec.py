"""Pydantic v2 contracts for behavior task generation.

Schemas
-------
- ``behavior-task-spec-v1``: canonical BR behavior task wrapper that COMPOSES
  a portable :class:`TaskProgramV1` (``engine="psyflow"``) with BR-specific
  fields that do not belong in the engine-agnostic program contract
  (scanner profile, prompt provenance, resolved/unresolved params,
  BIDS/HED mapping, review metadata, free-form notes).
- ``behavior-review-v1``: human/automated review payload binding to a spec
  digest (approval gate input).
- ``psyflow-task-bundle-v1``: metadata describing a written psyflow scaffold.

Design notes
------------
This wrapper is a thin composition layer. All psyflow-specific task knobs
(trial count, block structure, timing, conditions, stimuli, response
mapping, etc.) live inside ``task_program.environment_config`` so that
when the ``landing/neurogym-stack`` branch merges, psyflow slots in as a
second engine alongside ``engine="neurogym"`` without any contract
migration. ``observation_schema`` defaults to ``"behavior-trial-v1"``
which matches what the psyflow ingest path already emits.

All models use ``extra="forbid"`` so typos surface loudly. The ported
``TaskProgramV1`` keeps its upstream permissive shape unchanged.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from brain_researcher.core.contracts.task_program import (
    TaskInterventionRefV1,
    TaskProgramV1,
)


class ScannerProfile(BaseModel):
    """Optional scanner-session knobs for in-scanner paradigms."""

    model_config = ConfigDict(extra="forbid")

    tr_sec: float = Field(..., description="Repetition time (seconds)")
    n_volumes: int | None = Field(default=None, ge=1)
    dummy_scans: int = Field(default=0, ge=0)
    planned_duration_sec: float | None = Field(
        default=None,
        gt=0,
        description="Planned task duration excluding dummy scans (seconds)",
    )
    trigger_key: str = Field(
        default="5", description="Keypress that marks scanner trigger"
    )
    iti_jitter_sec: tuple[float, float] | None = Field(
        default=None, description="(low, high) uniform ITI jitter in seconds"
    )
    synchronize_to_trigger: bool = True
    mri_safe_response: bool = True
    notes: str | None = None

    @field_validator("tr_sec")
    @classmethod
    def _tr_positive(cls, v: float) -> float:
        if v is None or float(v) <= 0:
            raise ValueError("tr_sec must be > 0")
        return float(v)

    @field_validator("iti_jitter_sec")
    @classmethod
    def _jitter_ok(cls, v: tuple[float, float] | None) -> tuple[float, float] | None:
        if v is None:
            return None
        try:
            low, high = float(v[0]), float(v[1])
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError("iti_jitter_sec must be a (low, high) tuple") from exc
        if low < 0:
            raise ValueError("iti_jitter_sec low must be >= 0")
        if low > high:
            raise ValueError("iti_jitter_sec low must be <= high")
        return (low, high)

    @model_validator(mode="after")
    def _validate_scan_budget(self) -> "ScannerProfile":
        if self.n_volumes is not None and self.n_volumes <= self.dummy_scans:
            raise ValueError("n_volumes must exceed dummy_scans")
        if self.planned_duration_sec is None:
            return self
        dummy_budget = float(self.dummy_scans) * float(self.tr_sec)
        if float(self.planned_duration_sec) <= dummy_budget:
            raise ValueError(
                "planned_duration_sec must exceed the time consumed by dummy_scans * tr_sec"
            )
        if self.n_volumes is not None:
            usable_budget = float(self.n_volumes - self.dummy_scans) * float(
                self.tr_sec
            )
            if float(self.planned_duration_sec) > usable_budget + 1e-6:
                raise ValueError(
                    "planned_duration_sec exceeds the available scan budget implied by "
                    "n_volumes, dummy_scans, and tr_sec"
                )
        return self


class BehaviorPromptProvenance(BaseModel):
    """Optional provenance describing how a spec was elicited from a prompt."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = None
    planner: str | None = None
    candidate_label: str | None = None
    resolved_overrides: dict[str, Any] = Field(default_factory=dict)
    unresolved_fields: list[str] = Field(default_factory=list)
    notes: str | None = None


class BehaviorTaskSpecV1(BaseModel):
    """Canonical BR behavior task spec (v1).

    Thin wrapper composing a portable :class:`TaskProgramV1`
    (``engine="psyflow"``) plus BR-specific fields that do not belong
    in the engine-agnostic portable contract.

    The psyflow paradigm parameters (n_trials, trial_duration_sec, iti_sec,
    n_blocks, conditions, response_keys, feedback, stimuli, extras) live
    inside ``task_program.environment_config`` — this wrapper exposes
    compatibility accessors (``paradigm``, ``n_trials``, ``trial_duration_sec``,
    etc.) that read through to the composed program's environment_config.
    """

    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["behavior-task-spec-v1"] = "behavior-task-spec-v1"
    version: str = "1.0"

    task_program: TaskProgramV1

    paradigm_label: str | None = None
    scanner: ScannerProfile | None = None
    bids_columns: list[str] = Field(default_factory=list)
    hed_tags: dict[str, str] = Field(default_factory=dict)
    prompt_provenance: BehaviorPromptProvenance | None = None
    review_metadata: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_program(self) -> "BehaviorTaskSpecV1":
        prog = self.task_program
        # psyflow wrapper requires engine=psyflow and the canonical behavior
        # observation contract.
        if prog.engine != "psyflow":
            raise ValueError(
                f"BehaviorTaskSpecV1 requires task_program.engine='psyflow', "
                f"got {prog.engine!r}"
            )
        if prog.observation_schema not in (None, "behavior-trial-v1"):
            raise ValueError(
                "BehaviorTaskSpecV1 requires task_program.observation_schema="
                "'behavior-trial-v1' (psyflow ingest emits BehaviorTrial rows)"
            )
        paradigm = (prog.canonical_task_id or "").strip()
        if not paradigm:
            raise ValueError("task_program.canonical_task_id must be non-empty")

        env = prog.environment_config or {}
        # Required psyflow-side knobs.
        for key in ("n_trials", "trial_duration_sec", "iti_sec"):
            if key not in env:
                raise ValueError(
                    f"task_program.environment_config missing required psyflow key: {key!r}"
                )
        n_trials = env.get("n_trials")
        if not isinstance(n_trials, int) or n_trials < 1:
            raise ValueError("environment_config.n_trials must be int >= 1")
        if float(env.get("trial_duration_sec", 0.0)) <= 0:
            raise ValueError("environment_config.trial_duration_sec must be > 0")
        if float(env.get("iti_sec", -1.0)) < 0:
            raise ValueError("environment_config.iti_sec must be >= 0")
        n_blocks = env.get("n_blocks", 1)
        if not isinstance(n_blocks, int) or n_blocks < 1:
            raise ValueError("environment_config.n_blocks must be int >= 1")
        return self

    # ------------------------------------------------------------------
    # Compatibility accessors — these read through to task_program fields
    # so existing catalog / adapter / tool code does not have to unpack
    # the wrapper everywhere.
    # ------------------------------------------------------------------

    @property
    def paradigm(self) -> str:
        return self.task_program.canonical_task_id

    @property
    def environment_config(self) -> dict[str, Any]:
        return dict(self.task_program.environment_config or {})

    @property
    def n_trials(self) -> int:
        return int(self.environment_config.get("n_trials"))

    @property
    def n_blocks(self) -> int:
        return int(self.environment_config.get("n_blocks", 1))

    @property
    def trial_duration_sec(self) -> float:
        return float(self.environment_config.get("trial_duration_sec"))

    @property
    def iti_sec(self) -> float:
        return float(self.environment_config.get("iti_sec"))

    @property
    def conditions(self) -> list[str]:
        return list(self.environment_config.get("conditions") or [])

    @property
    def response_keys(self) -> list[str]:
        return list(self.environment_config.get("response_keys") or [])

    @property
    def feedback(self) -> bool:
        return bool(self.environment_config.get("feedback") or False)

    @property
    def stimuli(self) -> dict[str, Any]:
        return dict(self.environment_config.get("stimuli") or {})

    @property
    def extras(self) -> dict[str, Any]:
        return dict(self.environment_config.get("extras") or {})


class BehaviorReviewV1(BaseModel):
    """Reviewer sign-off bound to a specific spec digest."""

    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["behavior-review-v1"] = "behavior-review-v1"
    spec_digest: str = Field(..., min_length=1)
    approved: bool
    reviewer: str | None = None
    comments: str | None = None
    concerns: list[str] = Field(default_factory=list)
    timestamp: str | None = None


class PsyflowTaskBundleV1(BaseModel):
    """Metadata for a written psyflow scaffold bundle."""

    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["psyflow-task-bundle-v1"] = "psyflow-task-bundle-v1"
    spec_digest: str = Field(..., min_length=1)
    paradigm: str = Field(..., min_length=1)
    bundle_dir: str
    entrypoint: str = "main.py"
    config_path: str = "config/config.yaml"
    planned_dir: str
    run_dir: str | None = None
    files: list[str] = Field(default_factory=list)
    created_ts: str | None = None
    psyflow_commit: str | None = None

    @model_validator(mode="after")
    def _coerce_paths(self) -> "PsyflowTaskBundleV1":
        # planned_dir and bundle_dir default to strings already.
        return self


def spec_digest(spec: BehaviorTaskSpecV1) -> str:
    """Return a deterministic SHA-256 hex digest of the composed spec wrapper.

    The canonical byte form is ``json.dumps(sort_keys=True,
    separators=(',',':'))`` of ``spec.model_dump(mode='json')``. Because the
    wrapper serializes the full ``task_program`` (including
    ``environment_config``), changes to psyflow parameters still change the
    digest deterministically.
    """
    payload = spec.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ScannerProfile",
    "BehaviorPromptProvenance",
    "BehaviorTaskSpecV1",
    "BehaviorReviewV1",
    "PsyflowTaskBundleV1",
    "TaskProgramV1",
    "TaskInterventionRefV1",
    "spec_digest",
]
