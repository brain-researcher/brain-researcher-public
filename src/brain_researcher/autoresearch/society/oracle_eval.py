"""Paper-grade CI / stability reporting over society-vs-oracle results.

Today the predictive_society arm scripts hand-roll oracle-match counting
(``match = society == oracle``; ``rate = n_match / n``) and report a bare point estimate
with NO interval, NO per-gate confusion, NO multi-rep stability. This thin, pure-function
module adds the honest statistics that turn proof-of-mechanism into reportable evidence:

* a binomial confidence interval on the oracle-match rate (Clopper-Pearson / Wilson),
* per-gate sensitivity / specificity with intervals,
* a generic bootstrap CI,
* rep-to-rep stability for the nondeterministic LLM full-stack (the deterministic gates
  are exactly reproducible, so their reps are identical by construction).

HONESTY: with the current n=5-6 BangHCP claims an interval is WIDE — this is single-episode
CALIBRATION, NOT a generalization claim. ``oracle_match_summary`` emits an explicit ``n<10``
warning so a report cannot quietly present a point estimate as a generalization result.
Dependency-light (numpy + statsmodels); no I/O, no LLM.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
from statsmodels.stats.proportion import proportion_confint

#: Below this n a binomial interval is too wide to support a generalization claim.
SMALL_N_WARNING_THRESHOLD = 10


def binom_ci(k: int, n: int, *, method: str = "beta", alpha: float = 0.05) -> tuple[float, float]:
    """Binomial proportion CI. ``method='beta'`` = Clopper-Pearson (exact), ``'wilson'`` = score."""
    if n <= 0:
        return (0.0, 1.0)
    lo, hi = proportion_confint(k, n, alpha=alpha, method=method)
    return (float(lo), float(hi))


def oracle_match_summary(
    pairs: Sequence[tuple[str, str]], *, method: str = "beta", alpha: float = 0.05
) -> dict[str, Any]:
    """Oracle-match rate + binomial CI over ``[(society_status, oracle_status), ...]``."""
    n = len(pairs)
    k = sum(1 for s, o in pairs if s == o)
    lo, hi = binom_ci(k, n, method=method, alpha=alpha)
    return {
        "n": n,
        "n_match": k,
        "rate": (k / n if n else None),
        "ci_low": lo,
        "ci_high": hi,
        "ci_method": method,
        "warning": (
            f"n<{SMALL_N_WARNING_THRESHOLD}: interval is wide — single-episode CALIBRATION, "
            "NOT a generalization claim"
            if n < SMALL_N_WARNING_THRESHOLD
            else None
        ),
    }


def gate_confusion(
    rows: Sequence[dict[str, Any]], gate: str, *, method: str = "beta"
) -> dict[str, Any]:
    """Sensitivity / specificity (with CIs) for one gate.

    Each row: ``{"gate": str, "fired": bool, "should_fire": bool}`` where ``should_fire``
    is the INDEPENDENT label (e.g. the oracle says ``rejected`` => permutation_null SHOULD
    fire on that claim). Caller decides which claims a gate is responsible for (a gate is
    typically don't-care on claims another gate owns).
    """
    g = [r for r in rows if r.get("gate") == gate]
    pos = [r for r in g if r["should_fire"]]
    neg = [r for r in g if not r["should_fire"]]
    sens_k = sum(1 for r in pos if r["fired"])
    spec_k = sum(1 for r in neg if not r["fired"])
    return {
        "gate": gate,
        "n": len(g),
        "sensitivity": {
            "k": sens_k,
            "n": len(pos),
            "rate": (sens_k / len(pos) if pos else None),
            "ci": binom_ci(sens_k, len(pos), method=method),
        },
        "specificity": {
            "k": spec_k,
            "n": len(neg),
            "rate": (spec_k / len(neg) if neg else None),
            "ci": binom_ci(spec_k, len(neg), method=method),
        },
    }


def bootstrap_ci(
    values: Sequence[float],
    stat: Callable[[np.ndarray], float] = np.mean,
    *,
    n_boot: int = 10000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap CI of ``stat`` over ``values`` (deterministic for a fixed seed)."""
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    boots = [float(stat(rng.choice(arr, size=arr.size, replace=True))) for _ in range(n_boot)]
    return (float(np.quantile(boots, alpha / 2)), float(np.quantile(boots, 1 - alpha / 2)))


def rep_stability(
    rep_matrix: dict[str, list[str]], *, oracle: dict[str, str] | None = None
) -> dict[str, Any]:
    """Rep-to-rep stability of the (nondeterministic) full-stack verdict per claim.

    ``rep_matrix[claim_id] = [status_rep1, status_rep2, ...]``. Reports each claim's modal
    status + agreement fraction, the mean agreement, and (when ``oracle`` given) how often
    the MODAL verdict matches the oracle. Deterministic gates yield identical reps =>
    agreement 1.0 by construction. Leads with the agreement fraction (no Fleiss-kappa
    instability on a single-category matrix).
    """
    per_claim: dict[str, Any] = {}
    agreements: list[float] = []
    modal_matches: list[bool] = []
    for cid, reps in rep_matrix.items():
        if not reps:
            continue
        counts = Counter(reps)
        modal, modal_n = counts.most_common(1)[0]
        agree = modal_n / len(reps)
        per_claim[cid] = {
            "modal_status": modal,
            "agreement": agree,
            "n_reps": len(reps),
            "unanimous": agree == 1.0,
        }
        agreements.append(agree)
        if oracle is not None and cid in oracle:
            per_claim[cid]["modal_matches_oracle"] = modal == oracle[cid]
            modal_matches.append(modal == oracle[cid])
    out: dict[str, Any] = {
        "per_claim": per_claim,
        "mean_agreement": (float(np.mean(agreements)) if agreements else None),
        "n_unanimous": sum(1 for c in per_claim.values() if c["unanimous"]),
        "n_claims": len(per_claim),
    }
    if modal_matches:
        out["modal_oracle_match_rate"] = float(np.mean(modal_matches))
    return out


__all__ = [
    "SMALL_N_WARNING_THRESHOLD",
    "binom_ci",
    "oracle_match_summary",
    "gate_confusion",
    "bootstrap_ci",
    "rep_stability",
]
