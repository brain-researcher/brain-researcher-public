"""M4: persisted EARNED-CHECK registry — a per-axis "has this falsifier ever earned its keep?"
ledger the institution can reference across episodes.

The L4 coverage analyzer (:mod:`society.coverage`) already defines what "earned" means — an axis
is *validated* once it has genuinely refuted at least one claim, a *gap* if it ran genuinely but
never refuted (its refute path is untested), *always-degenerate* if it only ever infra-failed.
But that analyzer is in-memory and recomputed ad-hoc from a batch of cards (§32: "coverage
in-memory"); nothing persists it, so no gate can ask "was this axis ever shown to fire?".

This module persists that signal. It is a sibling of :mod:`society.calibration_store` — same
contract, different key: calibration is per-VOTER earned accuracy; this is per-AXIS earned
falsification. It REUSES :func:`society.coverage.accumulate_coverage` as the single definition of
the counts (never re-deriving "earned"), and copies CalibrationStore's persistence machinery
verbatim (path-injectable JSON under ``runs/society/``, atomic tmp+os.replace publish, schema
guard, corruption-degrades-to-fresh load). Pure-python, no DB, no network — safe inside
``autoresearch``.

Honesty contract (mirrors calibration_store): the earned status is DERIVED from system-recorded
falsifier outcomes (the conductor's claim card), never anything the model self-reports; zero data
== ``unknown`` (no axis is "earned" until it has actually refuted something).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cards import _utc_now
from .coverage import accumulate_coverage

logger = logging.getLogger(__name__)

#: Default store location, beside ``calibration_store.json``. Injectable everywhere.
DEFAULT_EARNED_CHECK_REGISTRY_PATH = Path("runs") / "society" / "earned_check_registry.json"

#: Per-axis earned-check status vocabulary (mirrors coverage.py's predicates exactly).
EARNED = "validated"  # genuinely refuted at least once -> its refute path is proven
GAP = "gap"  # ran genuinely but never refuted -> untested refute path (cheap silence)
ALWAYS_DEGENERATE = "always_degenerate"  # only ever infra-failed -> no genuine verdict
UNKNOWN = "unknown"  # never ran (no record)


class EarnedCheckEvent(BaseModel):
    """One immutable per-episode observation of an axis (cheap provenance trail)."""

    model_config = ConfigDict(frozen=True)

    axis: str
    episode_id: str
    refuted: bool = False
    degenerate: bool = False
    hard: bool = False
    reason: str | None = None
    at: str = Field(default_factory=_utc_now)


class EarnedCheckRecord(BaseModel):
    """One axis's accumulated coverage across episodes + immutable provenance trail.

    Count fields mirror :class:`society.coverage.AxisCoverageRecord` verbatim so the persisted
    aggregate and the batch analyzer agree on every tally.
    """

    model_config = ConfigDict(frozen=True)

    axis: str
    n_ran: int = Field(default=0, ge=0)
    n_genuine: int = Field(default=0, ge=0)
    n_degenerate: int = Field(default=0, ge=0)
    n_refuting: int = Field(default=0, ge=0)
    n_hard_refuting: int = Field(default=0, ge=0)
    example_refute_reasons: tuple[str, ...] = ()
    events: tuple[EarnedCheckEvent, ...] = ()

    @model_validator(mode="after")
    def _counts_coherent(self) -> EarnedCheckRecord:
        # Invariants maintained by update_from_card; enforced here so a hand-edited or foreign
        # on-disk record is rejected (and treated as corruption by load) rather than yielding a
        # nonsensical status.
        if self.n_genuine + self.n_degenerate > self.n_ran:
            raise ValueError("n_genuine + n_degenerate cannot exceed n_ran")
        if self.n_refuting > self.n_genuine:
            raise ValueError("n_refuting cannot exceed n_genuine")
        if self.n_hard_refuting > self.n_refuting:
            raise ValueError("n_hard_refuting cannot exceed n_refuting")
        return self

    @property
    def status(self) -> str:
        """Earned-check status — the SAME classification as coverage.py's predicates."""
        if self.n_refuting > 0:
            return EARNED
        if self.n_ran > 0 and self.n_genuine == 0:
            return ALWAYS_DEGENERATE
        if self.n_genuine > 0 and self.n_refuting == 0:
            return GAP
        return UNKNOWN

    @property
    def earned(self) -> bool:
        return self.status == EARNED


EarnedCheckRecord.model_rebuild()


class EarnedCheckRegistry(BaseModel):
    """Persistent per-axis earned-check tracker (M4).

    A path-injectable JSON store mapping ``axis -> EarnedCheckRecord``. Updated per episode from
    the conductor's persisted claim card (the recorded falsifier outcomes), queried by a gate /
    annotator to tell an EARNED axis's silence (proven refute path) from a GAP axis's silence
    (cheap / untested). Persistence is explicit (:meth:`save` / :meth:`load`); :meth:`update_from_card`
    mutates the in-memory tally and returns immediately.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: Path | None = None
    records: dict[str, EarnedCheckRecord] = Field(default_factory=dict)

    # -- reads --------------------------------------------------------------- #
    def status(self, axis: str) -> str:
        rec = self.records.get(str(axis))
        return rec.status if rec is not None else UNKNOWN

    def is_earned(self, axis: str) -> bool:
        return self.status(axis) == EARNED

    def record_for(self, axis: str) -> EarnedCheckRecord | None:
        return self.records.get(str(axis))

    def annotation(self, axis: str) -> dict[str, Any]:
        """A small, JSON-safe earned-check tag for one axis (status + raw counts)."""
        rec = self.records.get(str(axis))
        if rec is None:
            return {"status": UNKNOWN, "n_refuting": 0, "n_genuine": 0, "n_ran": 0}
        return {
            "status": rec.status,
            "n_refuting": rec.n_refuting,
            "n_genuine": rec.n_genuine,
            "n_ran": rec.n_ran,
        }

    # -- writes -------------------------------------------------------------- #
    def update_from_card(self, card: dict, *, episode_id: str) -> None:
        """Fold ONE episode's claim card into the registry.

        Reuses :func:`accumulate_coverage` on the single card so the per-axis deltas are counted
        by the EXACT same rule as the batch analyzer — no re-derivation of "earned". Each axis
        that ran this episode gets one appended :class:`EarnedCheckEvent`. Mutates in memory only;
        call :meth:`save` to persist.
        """
        per_card = accumulate_coverage([card]).records
        for axis, delta in per_card.items():
            prev = self.records.get(axis)
            base = prev or EarnedCheckRecord(axis=axis)
            reasons = list(base.example_refute_reasons)
            for r in delta.example_refute_reasons:
                if r and len(reasons) < 3 and r not in reasons:
                    reasons.append(r)
            event = EarnedCheckEvent(
                axis=axis,
                episode_id=str(episode_id),
                refuted=delta.n_refuting > 0,
                degenerate=delta.n_degenerate > 0,
                hard=delta.n_hard_refuting > 0,
                reason=delta.example_refute_reasons[0] if delta.example_refute_reasons else None,
            )
            self.records[axis] = base.model_copy(
                update={
                    "n_ran": base.n_ran + delta.n_ran,
                    "n_genuine": base.n_genuine + delta.n_genuine,
                    "n_degenerate": base.n_degenerate + delta.n_degenerate,
                    "n_refuting": base.n_refuting + delta.n_refuting,
                    "n_hard_refuting": base.n_hard_refuting + delta.n_hard_refuting,
                    "example_refute_reasons": tuple(reasons),
                    "events": base.events + (event,),
                }
            )

    # -- persistence --------------------------------------------------------- #
    def save(self, path: str | Path | None = None) -> Path:
        """Write the registry to JSON (default :attr:`path`). Returns the written path."""
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError(
                "EarnedCheckRegistry.save requires a path (none injected on the registry)"
            )
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "schema_version": "earned-check-registry-v1",
            "records": {
                axis: rec.model_dump(mode="json") for axis, rec in self.records.items()
            },
            "saved_at": _utc_now(),
        }
        # Atomic publish (tmp + os.replace) so a crash mid-write can never leave a truncated file
        # that would poison every subsequent load().
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, target)
        return target

    @classmethod
    def load(cls, path: str | Path) -> EarnedCheckRegistry:
        """Load a registry from JSON, or a fresh empty one if absent.

        Robust by design: a missing, empty, truncated, corrupt, or unknown-schema file degrades to
        a FRESH registry (logged) rather than crashing the caller — and an unknown schema is NOT
        silently loaded as empty (that would silently reset every axis's earned tally).
        """
        p = Path(path)
        if not p.exists():
            return cls(path=p)
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("earned-check registry root is not a JSON object")
            schema = raw.get("schema_version")
            if schema != "earned-check-registry-v1":
                raise ValueError(f"unknown earned-check registry schema_version: {schema!r}")
            records = {
                axis: EarnedCheckRecord.model_validate(rec)
                for axis, rec in (raw.get("records") or {}).items()
            }
            return cls(path=p, records=records)
        except (OSError, ValueError, TypeError, ValidationError) as exc:
            logger.warning(
                "EarnedCheckRegistry.load: %s is unreadable/corrupt (%s); falling back to a "
                "fresh registry",
                p,
                exc,
            )
            return cls(path=p)


def annotate_survived_axes(card: Any, registry: EarnedCheckRegistry) -> None:
    """Tag each SURVIVED axis on a claim card with its HISTORICAL earned-check status (read-only).

    Annotate-only (M4 minimal teeth): writes ``card.extra['earned_checks']`` mapping each axis in
    the card's OWN ``survived_checks`` list to its earned status from PAST episodes — so an auditor
    can tell a survive on a proven (EARNED) axis from a survive on an untested (GAP) one. Reads the
    registry as it stands BEFORE this episode is folded in (call this before ``update_from_card``);
    never changes status, ceilings, or the survived_checks list.

    The annotated set is derived from ``survived_checks`` — NOT from the raw outcome list — so it is
    consistent with the card by construction: an axis the synthesizer excluded from
    ``survived_checks`` (e.g. a ``commission_abstained_inputs_present`` probe, which is neither
    survived nor failed) is never annotated as a survive.
    """
    survived = getattr(card, "survived_checks", None) or []
    if not survived:
        return
    ec = card.extra.setdefault("earned_checks", {})
    for entry in survived:
        # survived_checks entries are formatted "<strategy>: survived<provenance tag>".
        axis = str(entry).split(":", 1)[0].strip()
        if axis:
            ec[axis] = registry.annotation(axis)


__all__ = [
    "DEFAULT_EARNED_CHECK_REGISTRY_PATH",
    "EARNED",
    "GAP",
    "ALWAYS_DEGENERATE",
    "UNKNOWN",
    "EarnedCheckEvent",
    "EarnedCheckRecord",
    "EarnedCheckRegistry",
    "annotate_survived_axes",
]
