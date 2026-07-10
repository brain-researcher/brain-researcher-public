"""Per-seat editorial CALIBRATION TRACKING (HTML section 09, "calibration x confidence").

The editorial layer (:mod:`society.editorial`) weights every juror / editor vote by
``calibration x confidence``, where ``calibration`` is the voter's *historical
accuracy* and is SYSTEM-SUPPLIED — the model never self-reports it (see the
``editorial`` module docstring; that invariant is load-bearing and preserved here).

Until now ``calibration`` was a static convention (:data:`editorial.DEFAULT_CALIBRATION`
== 0.7) for every voter. This module makes it *earned*: a small, deterministic,
pure-python JSON store tracking each voter's correct/total tally as a Beta(alpha, beta)
posterior, so a seat with a poor track record gets a lower aggregation weight and a
seat with a good one gets a higher weight, converging toward the empirical hit-rate.

Design contract:

* **Zero-data == DEFAULT_CALIBRATION.** The Beta prior is chosen so a voter with NO
  recorded outcomes has calibration EXACTLY :data:`DEFAULT_CALIBRATION` (0.7) — the
  store is therefore drop-in: default-off behaviour is byte-identical to the static
  prior. ``prior_strength`` is the prior's pseudo-count weight (alpha + beta); the
  default of 1.0 means a single real outcome carries weight 1/(1+1) = 0.5, i.e. the
  estimate becomes the average of the prior mean and that observation.
* **Converges to the empirical hit-rate.** As correct/total grows, the posterior mean
  ``(alpha + correct) / (alpha + beta + total)`` -> ``correct / total``.
* **Bounded [0, 1]** by construction (a Beta mean of non-negative pseudo-counts).
* **Never self-reported.** :meth:`record_votes` scores votes against a SYSTEM-known
  realized status; the model's vote is the *prediction* being graded, not a
  calibration it supplies.

Voter id = the board ``seat`` (stable across episodes) and the juror ``juror_id``.

This is a v0 in-memory + JSON-file store; no DB, no network. Nothing here imports the
service tier, so it is safe inside ``autoresearch``. The signal that drives it (when
a realized / ground-truth status becomes known) is wired at
:meth:`SocietyConductor.record_editorial_outcome` and documented as an integration
point; this module does NOT fabricate an outcome.
"""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cards import ClaimStatusV1, _utc_now
from .editorial import DEFAULT_CALIBRATION

if TYPE_CHECKING:  # annotations only; runtime import is lazy to avoid an import cycle
    from .economy import EditorVote, JurorVote

logger = logging.getLogger(__name__)

#: Default store location, under the repo runs/ dir (mirrors
#: ``economy.DEFAULT_ECONOMY_LEDGER_PATH``). Injectable everywhere.
DEFAULT_CALIBRATION_STORE_PATH = Path("runs") / "society" / "calibration_store.json"

#: Default Beta prior pseudo-count weight (alpha + beta). A small strength so a
#: voter's empirical record dominates quickly; 1.0 == one pseudo-observation total.
DEFAULT_PRIOR_STRENGTH = 1.0


class CalibrationRecord(BaseModel):
    """One voter's append-only accuracy tally + immutable provenance trail (v0)."""

    model_config = ConfigDict(frozen=True)

    voter_id: str
    correct: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    # Cheap immutable provenance: one event per recorded outcome.
    events: tuple["CalibrationEvent", ...] = ()

    @model_validator(mode="after")
    def _correct_within_total(self) -> "CalibrationRecord":
        # An invariant maintained by `record`; enforced here so a hand-edited or
        # foreign on-disk record with correct > total is rejected (and treated as
        # corruption by `CalibrationStore.load`, which falls back to a fresh store)
        # rather than yielding an `empirical_rate` above 1.0.
        if self.correct > self.total:
            raise ValueError(
                f"correct ({self.correct}) cannot exceed total ({self.total})"
            )
        return self


class CalibrationEvent(BaseModel):
    """An immutable record of one scored outcome (cheap provenance trail)."""

    model_config = ConfigDict(frozen=True)

    voter_id: str
    correct: bool
    voted: str | None = None  # the status the voter cast, when known
    realized: str | None = None  # the system-known realized status, when known
    at: str = Field(default_factory=_utc_now)


CalibrationRecord.model_rebuild()


class CalibrationStore(BaseModel):
    """Persistent per-voter calibration tracker (HTML section 09).

    A path-injectable JSON store mapping ``voter_id -> CalibrationRecord``. The
    calibration of a voter is the Beta posterior mean of its correct/total tally
    under a prior whose ZERO-DATA mean is exactly :data:`DEFAULT_CALIBRATION`.

    Persistence is explicit (:meth:`save` / :meth:`load`) so a caller controls when
    the durable file is written; :meth:`record` / :meth:`record_votes` mutate the
    in-memory tally and return immediately (call :meth:`save` to persist).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: Path | None = None
    prior_strength: float = DEFAULT_PRIOR_STRENGTH
    #: The zero-data calibration the prior must reproduce. Defaults to the editorial
    #: convention so the store is a drop-in replacement for the static prior.
    prior_mean: float = DEFAULT_CALIBRATION
    records: dict[str, CalibrationRecord] = Field(default_factory=dict)

    # -- prior pseudo-counts ------------------------------------------------- #

    @property
    def _alpha0(self) -> float:
        """Prior ``alpha`` pseudo-count: ``prior_mean * prior_strength``."""
        return max(0.0, self.prior_mean) * max(0.0, self.prior_strength)

    @property
    def _beta0(self) -> float:
        """Prior ``beta`` pseudo-count: ``(1 - prior_mean) * prior_strength``."""
        return max(0.0, 1.0 - self.prior_mean) * max(0.0, self.prior_strength)

    # -- reads --------------------------------------------------------------- #

    def calibration(self, voter_id: str) -> float:
        """Smoothed posterior-mean calibration for ``voter_id`` in ``[0, 1]``.

        Zero-data (no recorded outcomes) returns EXACTLY :attr:`prior_mean`
        (== :data:`DEFAULT_CALIBRATION` by default). As evidence accrues the value
        converges toward the empirical hit-rate ``correct / total``. Always bounded
        to ``[0, 1]`` by construction.
        """
        rec = self.records.get(str(voter_id))
        correct = rec.correct if rec is not None else 0
        total = rec.total if rec is not None else 0
        alpha = self._alpha0 + correct
        beta = self._beta0 + (total - correct)
        denom = alpha + beta
        # Fall back to the prior mean (or the hard default if even that is corrupt)
        # whenever the posterior is undefined or non-finite — e.g. a corrupt loaded
        # prior_strength/prior_mean of inf/NaN, which `max/min` would otherwise
        # silently launder into 1.0 instead of degrading safely.
        safe_prior = self.prior_mean if math.isfinite(self.prior_mean) else DEFAULT_CALIBRATION
        if denom <= 0 or not math.isfinite(alpha) or not math.isfinite(denom):
            return max(0.0, min(1.0, safe_prior))
        result = alpha / denom
        if not math.isfinite(result):
            return max(0.0, min(1.0, safe_prior))
        return max(0.0, min(1.0, result))

    def empirical_rate(self, voter_id: str) -> float | None:
        """Raw ``correct / total`` hit-rate, or ``None`` with no data."""
        rec = self.records.get(str(voter_id))
        if rec is None or rec.total <= 0:
            return None
        return rec.correct / rec.total

    # -- writes -------------------------------------------------------------- #

    def record(
        self,
        voter_id: str,
        correct: bool,
        *,
        voted: str | None = None,
        realized: str | None = None,
    ) -> CalibrationRecord:
        """Record one scored outcome for ``voter_id`` and return the new record.

        Appends an immutable :class:`CalibrationEvent` to the provenance trail and
        increments the correct/total tally. Mutates in memory only; call
        :meth:`save` to persist.
        """
        vid = str(voter_id)
        prev = self.records.get(vid)
        event = CalibrationEvent(
            voter_id=vid,
            correct=bool(correct),
            voted=voted,
            realized=realized,
        )
        if prev is None:
            updated = CalibrationRecord(
                voter_id=vid,
                correct=1 if correct else 0,
                total=1,
                events=(event,),
            )
        else:
            updated = prev.model_copy(
                update={
                    "correct": prev.correct + (1 if correct else 0),
                    "total": prev.total + 1,
                    "events": prev.events + (event,),
                }
            )
        self.records[vid] = updated
        return updated

    def record_votes(
        self,
        votes: Iterable["EditorVote | JurorVote"],
        realized_status: ClaimStatusV1,
        *,
        acceptable_alts: Sequence[ClaimStatusV1] = (),
    ) -> int:
        """Score each vote against a SYSTEM-known realized status; update the store.

        A vote is *correct* iff ``vote.vote == realized_status`` OR it is in
        ``acceptable_alts`` (mirroring the blueprint oracle's
        ``acceptable_alt_verdicts``). The voter id is the board ``seat`` (stable) for
        an :class:`EditorVote`, or the ``juror_id`` for a :class:`JurorVote`.

        This is the no-self-inflation entry point: the model's vote is the
        *prediction* being graded, not a calibration it supplies. Returns the number
        of votes scored. Mutates in memory only; call :meth:`save` to persist.
        """
        from .economy import EditorVote, JurorVote  # local: avoid import cycle

        acceptable = {ClaimStatusV1(a) for a in acceptable_alts}
        target = ClaimStatusV1(realized_status)
        n = 0
        for vote in votes:
            if isinstance(vote, EditorVote):
                voter_id = vote.seat
            elif isinstance(vote, JurorVote):
                voter_id = vote.juror_id
            else:  # pragma: no cover - defensive; unknown vote shape is skipped
                logger.warning("record_votes: unrecognized vote type %r", type(vote))
                continue
            is_correct = vote.vote == target or vote.vote in acceptable
            self.record(
                voter_id,
                is_correct,
                voted=vote.vote.value,
                realized=target.value,
            )
            n += 1
        return n

    def calibrations_for(self, voter_ids: Sequence[str]) -> list[float]:
        """Calibration priors for an ordered seat/juror list (feeds the runners).

        The returned list lines up positionally with ``voter_ids`` so it can be
        passed straight to ``run_editor_board_votes(calibrations=...)`` /
        ``run_jury_votes(calibrations=...)``.
        """
        return [self.calibration(v) for v in voter_ids]

    # -- persistence --------------------------------------------------------- #

    def save(self, path: str | Path | None = None) -> Path:
        """Write the store to JSON (default :attr:`path`). Returns the written path."""
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError(
                "CalibrationStore.save requires a path (none injected on the store)"
            )
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "schema_version": "calibration-store-v1",
            "prior_strength": self.prior_strength,
            "prior_mean": self.prior_mean,
            "records": {
                vid: rec.model_dump(mode="json") for vid, rec in self.records.items()
            },
            "saved_at": _utc_now(),
        }
        # Atomic publish: write to a sibling temp file then os.replace, so a crash or
        # concurrent writer mid-write can never leave a truncated file that would
        # poison every subsequent load().
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, target)
        return target

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        prior_strength: float = DEFAULT_PRIOR_STRENGTH,
        prior_mean: float = DEFAULT_CALIBRATION,
    ) -> "CalibrationStore":
        """Load a store from JSON, or return a fresh empty store if the file is absent.

        The on-disk ``prior_strength`` / ``prior_mean`` (when present) take precedence
        over the supplied defaults, so a round-tripped store reproduces its own prior.

        Robust by design: a missing, empty, truncated, corrupt, or unknown-schema file
        degrades to a FRESH store with the supplied prior defaults (logged), rather than
        crashing the caller — losing an unreadable accuracy tally is preferable to
        propagating a hard error onto a live settlement path.
        """
        p = Path(path)
        if not p.exists():
            return cls(path=p, prior_strength=prior_strength, prior_mean=prior_mean)
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("calibration store root is not a JSON object")
            schema = raw.get("schema_version")
            if schema != "calibration-store-v1":
                # An unknown/missing schema must NOT silently load as an empty store
                # (that would silently reset every voter's earned tally).
                raise ValueError(f"unknown calibration store schema_version: {schema!r}")
            records = {
                vid: CalibrationRecord.model_validate(rec)
                for vid, rec in (raw.get("records") or {}).items()
            }
            return cls(
                path=p,
                prior_strength=float(raw.get("prior_strength", prior_strength)),
                prior_mean=float(raw.get("prior_mean", prior_mean)),
                records=records,
            )
        except (OSError, ValueError, TypeError, ValidationError) as exc:
            logger.warning(
                "CalibrationStore.load: %s is unreadable/corrupt (%s); falling back to "
                "a fresh store with the default prior",
                p,
                exc,
            )
            return cls(path=p, prior_strength=prior_strength, prior_mean=prior_mean)


__all__ = [
    "DEFAULT_CALIBRATION_STORE_PATH",
    "DEFAULT_PRIOR_STRENGTH",
    "CalibrationEvent",
    "CalibrationRecord",
    "CalibrationStore",
]
