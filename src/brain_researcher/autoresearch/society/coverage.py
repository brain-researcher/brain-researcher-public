"""L4: axis-coverage tracking across society episodes.

Reads ``ClaimCardV1`` JSON records (produced by ``SocietyConductor.conduct()``)
and produces a ``CoverageReport``:

* per-strategy run/refute counts across all episodes
* "gap" strategies that ran but never refuted (no real test of their refute path)
* "silent" strategies that ran but were always degenerate (infra-failure)
* "validated" strategies with at least one confirmed genuine refute

Useful for spotting institutional blind-spots: an axis that ALWAYS passes may be
poorly calibrated, rubric-misconfigured, or structurally unable to fire on the
claims fed to it.

Usage::

    from brain_researcher.autoresearch.society.coverage import accumulate_coverage
    import json, pathlib

    cards = [
        json.loads(p.read_text())
        for p in pathlib.Path("outputs").rglob("claim_card.json")
    ]
    report = accumulate_coverage(cards)
    print(report.summary())
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class AxisCoverageRecord:
    """Per-strategy coverage across all episodes in a batch."""

    strategy: str
    n_ran: int = 0
    n_genuine: int = 0
    n_degenerate: int = 0
    n_refuting: int = 0
    n_hard_refuting: int = 0
    example_refute_reasons: list[str] = field(default_factory=list)

    @property
    def refute_rate(self) -> float | None:
        """Fraction of genuine runs that refuted; None when n_genuine==0."""
        return self.n_refuting / self.n_genuine if self.n_genuine > 0 else None

    @property
    def degenerate_rate(self) -> float | None:
        """Fraction of runs that were degenerate (infra-failure)."""
        return self.n_degenerate / self.n_ran if self.n_ran > 0 else None


@dataclass
class CoverageReport:
    """Coverage summary across a batch of episodes."""

    n_episodes: int
    records: dict[str, AxisCoverageRecord]

    @property
    def gap_strategies(self) -> list[str]:
        """Strategies that ran (with genuine verdicts) but NEVER refuted.

        These are institutional blind-spots: the axis ran in every episode but
        its refute path was never exercised — either the claims were all clean
        on this axis (valid) or the rubric cannot fire (suspect).
        """
        return [
            s
            for s, r in self.records.items()
            if r.n_genuine > 0 and r.n_refuting == 0
        ]

    @property
    def always_degenerate_strategies(self) -> list[str]:
        """Strategies that always degraded to infra-failure (no genuine verdict)."""
        return [
            s for s, r in self.records.items() if r.n_ran > 0 and r.n_genuine == 0
        ]

    @property
    def validated_strategies(self) -> list[str]:
        """Strategies with at least one confirmed genuine refute."""
        return [s for s, r in self.records.items() if r.n_refuting > 0]

    def summary(self) -> str:
        lines = [
            f"Coverage report — {self.n_episodes} episode(s), "
            f"{len(self.records)} strateg(ies)\n",
        ]
        header = f"{'strategy':20s} {'ran':>5} {'genuine':>8} {'refuted':>8} {'rate':>6}  flags"
        lines.append(header)
        lines.append("-" * len(header))
        for strategy, r in sorted(self.records.items()):
            rate = f"{r.refute_rate:.0%}" if r.refute_rate is not None else "  n/a"
            flags = []
            if strategy in self.gap_strategies:
                flags.append("GAP")
            if strategy in self.always_degenerate_strategies:
                flags.append("ALWAYS-DEGEN")
            if strategy in self.validated_strategies:
                flags.append("validated")
            flag_str = ", ".join(flags)
            lines.append(
                f"{strategy:20s} {r.n_ran:>5} {r.n_genuine:>8} {r.n_refuting:>8} "
                f"{rate:>6}  {flag_str}"
            )
        if self.gap_strategies:
            lines.append(
                f"\nWARNING: GAP axes ({len(self.gap_strategies)}): never refuted "
                "across all episodes."
            )
            lines.append(
                "   These may be correctly calibrated (clean claims) OR structurally "
                "unable to fire.\n   Recommend: test each gap axis against a known-bad "
                "claim on that axis (e.g. a leaked-CV claim for 'leakage')."
            )
        return "\n".join(lines)


def accumulate_coverage(claim_cards: list[dict]) -> CoverageReport:
    """Build a ``CoverageReport`` from a list of ``ClaimCardV1`` JSON dicts.

    Each dict should be the parsed JSON of a ``claim_card.json`` file produced
    by ``SocietyConductor.conduct()``.  Unknown / missing fields are skipped
    gracefully so the function is forward-compatible with card schema updates.
    """
    records: dict[str, AxisCoverageRecord] = defaultdict(
        lambda: AxisCoverageRecord(strategy="__unknown__")
    )

    for card in claim_cards:
        fb = card.get("falsification_budget_spent") or {}
        strategies = fb.get("strategies") or []
        degenerate_set = set(fb.get("degenerate_strategies") or [])
        hard_set = set(fb.get("hard_refutations") or [])
        failed_checks: list[str] = card.get("failed_checks") or []

        # Parse which strategies refuted from failed_checks strings like
        # "motion: judgment failed — <reason>"
        refuting_strategies: dict[str, str] = {}
        for entry in failed_checks:
            parts = entry.split(":", 1)
            if parts:
                s = parts[0].strip()
                reason = parts[1].strip() if len(parts) > 1 else ""
                refuting_strategies[s] = reason

        for strategy in strategies:
            if strategy not in records:
                records[strategy] = AxisCoverageRecord(strategy=strategy)
            rec = records[strategy]
            rec.n_ran += 1
            if strategy in degenerate_set:
                rec.n_degenerate += 1
            else:
                rec.n_genuine += 1
                if strategy in refuting_strategies:
                    rec.n_refuting += 1
                    if strategy in hard_set:
                        rec.n_hard_refuting += 1
                    reason = refuting_strategies[strategy]
                    if reason and len(rec.example_refute_reasons) < 3:
                        rec.example_refute_reasons.append(reason)

    return CoverageReport(
        n_episodes=len(claim_cards),
        records=dict(records),
    )
