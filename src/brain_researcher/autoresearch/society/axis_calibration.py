"""Adversarial axis-calibration harness for the BR Society falsifier population.

The L4 coverage tracker (``coverage.py``) flags method axes that *ran but never
refuted* as ``GAP`` — but a GAP is ambiguous: either the claims were genuinely clean
on that axis (correct silence) OR the axis is structurally unable to fire (a broken
rubric/prompt). This harness disambiguates by running each axis against a matched pair
of fixtures:

* a **known-bad** method record that *affirmatively states the flaw* the axis exists to
  catch (omission is not enough — the rubrics default to PASS and treat an unmentioned
  control as the norm, so an omission-only fixture would correctly PASS a healthy axis
  and mislabel it broken), and
* a **known-clean** method record that affirmatively states the control is in place.

Each axis lands in one of four cells:

* ``VALIDATED``   — refuted the known-bad AND passed the known-clean (specific + sensitive)
* ``BLIND``       — ran on the known-bad but did NOT refute it (the rubric/prompt cannot
                    catch its own flaw → the GAP is a real defect to fix)
* ``OVER_FIRING`` — refuted the known-clean (false positive; over-suspicious)
* ``INFRA_DEGEN`` — the critic was unavailable/degenerate (LLM down — an infra problem,
                    NOT evidence about the axis; the arm-E no-key false-negative case)

The harness drives the SAME ``build_falsifier_rubric → critic → classify_verdict`` path
as production via ``falsifiers.evaluate_llm_falsifier_axis``, so a ``VALIDATED`` verdict
is a statement about the real adjudication path, not a parallel mock.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from .falsifiers import (
    HARD_STRATEGIES,
    FalsifierOutcome,
    build_falsifier_rubric,
    evaluate_llm_falsifier_axis,
    load_rule_registry,
)


class CalibrationCell(str, Enum):
    """The disambiguated state of one method axis after adversarial calibration."""

    VALIDATED = "VALIDATED"
    BLIND = "BLIND"
    OVER_FIRING = "OVER_FIRING"
    INFRA_DEGEN = "INFRA_DEGEN"


@dataclass(frozen=True)
class AxisFixture:
    """A matched known-bad / known-clean pair for one axis."""

    strategy: str
    known_bad: dict[str, Any]
    known_clean: dict[str, Any]


@dataclass
class AxisCalibrationResult:
    """The calibration outcome for one axis."""

    strategy: str
    cell: CalibrationCell
    bad_outcome: FalsifierOutcome
    clean_outcome: FalsifierOutcome

    @property
    def is_validated(self) -> bool:
        return self.cell is CalibrationCell.VALIDATED


def classify_calibration_cell(
    bad_outcome: FalsifierOutcome, clean_outcome: FalsifierOutcome
) -> CalibrationCell:
    """Map a (known-bad, known-clean) outcome pair to a calibration cell.

    Order matters: an infra-degenerate critic tells us nothing about the axis, so it
    dominates. A blind axis (missed its own planted flaw) is the real defect and is
    reported even if it also happens to pass the clean fixture.
    """
    if bad_outcome.degenerate or clean_outcome.degenerate:
        return CalibrationCell.INFRA_DEGEN
    if not bad_outcome.refuted:
        # Ran (not degenerate) yet failed to catch the affirmatively-stated flaw.
        return CalibrationCell.BLIND
    if clean_outcome.refuted:
        # Caught the bad one but ALSO refuted a clean control → over-suspicious.
        return CalibrationCell.OVER_FIRING
    return CalibrationCell.VALIDATED


def run_axis_calibration(
    fixture: AxisFixture,
    *,
    registry: dict[str, dict[str, Any]],
    critic_runner: Callable[..., Any],
    router: Any,
    critic_model: str | None,
    rubric_dir: str | Path,
    claim_id: str = "calibration",
) -> AxisCalibrationResult:
    """Run one axis against its known-bad and known-clean fixtures."""
    strategy = fixture.strategy
    rubric_text = build_falsifier_rubric(strategy, registry)
    rubric_dir = Path(rubric_dir)
    rubric_dir.mkdir(parents=True, exist_ok=True)
    rubric_path = rubric_dir / f"falsifier_{strategy}.md"
    rubric_path.write_text(rubric_text, encoding="utf-8")
    hard = strategy in HARD_STRATEGIES

    def _run(payload: dict[str, Any], tag: str) -> FalsifierOutcome:
        return evaluate_llm_falsifier_axis(
            strategy,
            {"scorer_payload": payload},
            rubric_path=str(rubric_path),
            critic_runner=critic_runner,
            router=router,
            critic_model=critic_model,
            claim_id=f"{claim_id}:{strategy}:{tag}",
            hard=hard,
        )

    bad_outcome = _run(fixture.known_bad, "bad")
    clean_outcome = _run(fixture.known_clean, "clean")
    cell = classify_calibration_cell(bad_outcome, clean_outcome)
    return AxisCalibrationResult(
        strategy=strategy,
        cell=cell,
        bad_outcome=bad_outcome,
        clean_outcome=clean_outcome,
    )


@dataclass
class AxisCalibrationReport:
    """Aggregated calibration results across axes, with a coverage-style summary."""

    results: list[AxisCalibrationResult]

    def _by_cell(self, cell: CalibrationCell) -> list[str]:
        return [r.strategy for r in self.results if r.cell is cell]

    @property
    def validated(self) -> list[str]:
        return self._by_cell(CalibrationCell.VALIDATED)

    @property
    def blind(self) -> list[str]:
        return self._by_cell(CalibrationCell.BLIND)

    @property
    def over_firing(self) -> list[str]:
        return self._by_cell(CalibrationCell.OVER_FIRING)

    @property
    def infra_degen(self) -> list[str]:
        return self._by_cell(CalibrationCell.INFRA_DEGEN)

    @property
    def all_validated(self) -> bool:
        """True iff every axis is VALIDATED — this is what discharges the L4 GAP
        recommendation (every GAP axis proven sensitive + specific, none broken)."""
        return bool(self.results) and all(r.is_validated for r in self.results)

    def summary(self) -> str:
        lines = [
            f"Axis calibration report — {len(self.results)} axis(es)\n",
        ]
        header = f"{'strategy':20s} {'known_bad':>12} {'known_clean':>12}  cell"
        lines.append(header)
        lines.append("-" * len(header))
        for r in sorted(self.results, key=lambda x: x.strategy):
            bad = "DEGEN" if r.bad_outcome.degenerate else (
                "refuted" if r.bad_outcome.refuted else "passed"
            )
            clean = "DEGEN" if r.clean_outcome.degenerate else (
                "refuted" if r.clean_outcome.refuted else "passed"
            )
            lines.append(f"{r.strategy:20s} {bad:>12} {clean:>12}  {r.cell.value}")
        # actionable rollups
        if self.blind:
            lines.append(
                f"\nBLIND axes ({len(self.blind)}): {', '.join(sorted(self.blind))} — "
                "ran but missed an affirmatively-stated flaw → the rubric/prompt is the "
                "defect. Fix via STRATEGY_RULE_IDS / _FALLBACK_SEEDS for these axes."
            )
        if self.over_firing:
            lines.append(
                f"OVER-FIRING axes ({len(self.over_firing)}): "
                f"{', '.join(sorted(self.over_firing))} — refuted a clean control "
                "(false positive / over-suspicion)."
            )
        if self.infra_degen:
            lines.append(
                f"INFRA-DEGEN axes ({len(self.infra_degen)}): "
                f"{', '.join(sorted(self.infra_degen))} — critic unavailable; "
                "re-run with a working LLM (not evidence about the axis)."
            )
        if self.all_validated:
            lines.append(
                "\nALL axes VALIDATED — every calibrated axis is sensitive (catches its "
                "flaw) and specific (passes its control). This discharges the L4 coverage "
                "GAP recommendation for the calibrated axes."
            )
        return "\n".join(lines)


def load_axis_fixtures(path: str | Path) -> list[AxisFixture]:
    """Load adversarial fixtures from a YAML file.

    Schema::

        axes:
          site:
            known_bad: {claim_text: ..., method_summary: ...}
            known_clean: {claim_text: ..., method_summary: ...}
          motion: {...}
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    axes = data.get("axes") or {}
    fixtures: list[AxisFixture] = []
    for strategy, pair in axes.items():
        # YAML 1.1 parses a bare ``null:`` key as Python None — map it back to the
        # "null" strategy so an unquoted key in the fixtures file still works.
        strategy_name = "null" if strategy is None else str(strategy)
        pair = pair or {}
        known_bad = pair.get("known_bad") or {}
        known_clean = pair.get("known_clean") or {}
        fixtures.append(
            AxisFixture(
                strategy=strategy_name,
                known_bad=dict(known_bad),
                known_clean=dict(known_clean),
            )
        )
    return fixtures


def calibrate_axes(
    fixtures: list[AxisFixture],
    *,
    registry_path: str | Path | None,
    critic_runner: Callable[..., Any],
    router: Any,
    critic_model: str | None,
    rubric_dir: str | Path,
) -> AxisCalibrationReport:
    """Run calibration for every fixture and aggregate into a report."""
    registry = load_rule_registry(registry_path)
    results = [
        run_axis_calibration(
            fx,
            registry=registry,
            critic_runner=critic_runner,
            router=router,
            critic_model=critic_model,
            rubric_dir=rubric_dir,
        )
        for fx in fixtures
    ]
    return AxisCalibrationReport(results=results)
