"""Autonomous probe commissioning for the BR Society confound gate.

The confound deterministic gate reads a precomputed ``retained_pct`` scalar from
``scorer_payload.robustness_probes``. That makes the gate only as honest as whoever
filled in that scalar: an experimenter could hand-feed a passing number and the society
would certify a confounded claim by *reading a note* rather than by a genuine
result-probing axis.

This module lets the society COMPUTE ``retained_pct`` itself from RAW out-of-sample
arrays — per-subject predictions, the outcome target, candidate confounds — that a real
predictor naturally emits (e.g. ``cv_predictions.npy``).

THE HONESTY INVARIANT IS LOAD-BEARING AT THE SIGNATURE LEVEL:
``compute_residualization_probe`` has NO ``retained_pct`` / ``residualized_r`` /
``unadjusted_r`` parameter, so there is no channel through which a pre-supplied answer
can enter the computation (mirrors ``evidence_quality.score_evidence_quality``, which
never accepts the p-value it is meant to compute). Two further teeth:
  * ``ProbeInputsV1`` forbids extra keys and a denylist scan flags any hand-fed answer
    key (``inputs_tainted``) — it is recorded and IGNORED, never read.
  * when both a supplied scalar and raw arrays exist, the society RECOMPUTES and compares;
    a mismatch marks the probe ``supplied_inconsistent``.

retained_pct = 100 * residualized_r / unadjusted_r  (ratio of fold-mean Pearson r,
SIGNED — a confound that flips the sign yields a negative retention that correctly
refutes). This matches the BangHCP oracle's ``fraction_retained`` definition.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cards import fingerprint
from .falsifiers import CORRECTION_FRAGILE_ALPHA, PERMUTATION_NULL_ALPHA

logger = logging.getLogger(__name__)

COMMISSIONER_VERSION = "resid-probe-v1"

#: Minimum |unadjusted_r| for retained_pct to be defined. Below this the effect is at
#: noise level: residualization-retention is meaningless (a tiny r divided by a tiny r
#: is unstable and can exceed 100% or flip sign on noise). The confound gate then
#: ABSTAINS — proving an effect even EXISTS is the permutation_null gate's job, not the
#: confound gate's. (Verify finding: eps=1e-9 let unadj_r=-0.016 -> 130% pass the gate.)
NEAR_ZERO_R_FLOOR: float = 0.05

#: Minimum subjects for a meaningful residualization probe.
MIN_SUBJECTS: int = 20

#: Default tolerance (percentage points) for the supplied-vs-computed cross-check.
CROSS_CHECK_TOL_PCT: float = 5.0

#: Default / floor permutation count for the commissioned null. N and the seed are method
#: knobs OWNED BY THE COMMISSIONER (constructor), never readable from probe_inputs — so a
#: payload cannot coarsen the null (e.g. set N=5) to launder a verdict.
DEFAULT_N_PERMUTATIONS: int = 2000
MIN_PERMUTATIONS: int = 200

#: Answer keys that must NEVER enter the probe-input channel. If present they are
#: recorded (inputs_tainted) and stripped — a hand-fed answer is structurally ignored.
#: Includes the residualization keys (confound) AND the inferential p-value keys read by
#: the permutation_null / correction_fragile gates (so a hand-fed p cannot ride in either).
_BANNED_ANSWER_KEYS: frozenset[str] = frozenset(
    {
        "retained_pct",
        "residualized_r",
        "unadjusted_r",
        "effect_retention",
        "retention",
        "retained_fraction",
        "fraction_retained",
        "robustness_probes",
        "deconf_fold_mean_r",
        "family_block_p",
        "permutation_p",
        "max_T_p",
        "post_selection_p",
        "max_T_post_selection_p",
        "selection_retained_pct",
        "selection_r_oos",
        "selection_gap",
        "effect_size_ci_low",
        "effect_size_ci_high",
        "fold_dispersion_retained_pct",
    }
)


class ProbeLaunderingError(ValueError):
    """Raised in strict mode when a probe-input blob carries a hand-fed answer key."""


class ProbeInputsV1(BaseModel):
    """Raw arrays a real predictor emits — NEVER an answer scalar.

    Rides inside the rich scorer payload at ``scorer_payload['probe_inputs']``. All
    per-subject fields are column-aligned to the same S subjects.
    """

    model_config = ConfigDict(extra="forbid")

    y_pred: list[float]
    y_true: list[float]
    # confounds is OPTIONAL: a permutation_null-only payload carries no confounds (the
    # confound commission abstains on an empty dict, so confound behaviour is unchanged).
    confounds: dict[str, list[float]] = Field(default_factory=dict)
    fold_ids: list[int] | None = None
    confound_to_test: str | None = None
    confound_design: str = "per_column"  # "per_column" | "joint_matrix"
    # correction_fragile only: per-candidate out-of-sample predictions (the S x K matrix the
    # multiplicity correction needs) + which candidate is the reported headline. Both None
    # for confound/permutation_null payloads (those commissioners ignore them).
    candidate_preds: dict[str, list[float]] | None = None
    headline_candidate: str | None = None
    # correction_fragile, TARGET-FAMILY mode: when the family is K *different* targets (e.g.
    # the K behavioural components a single predictor was applied to), each candidate is scored
    # against its OWN target. Keys must match ``candidate_preds``; ``headline_candidate`` is
    # then REQUIRED and names the claim under adjudication (not argmax-forced — argmax across
    # different targets is meaningless). When None, the existing same-target / model-selection
    # correction (argmax-forced headline) is used.
    candidate_targets: dict[str, list[float]] | None = None
    # correction_fragile, REFIT-NULL channel (oracle-power): per-candidate REFIT statistic DRAWS
    # the EPISODE computed (the society cannot refit — it has no model/features). Keys MUST equal
    # candidate_preds/candidate_targets; every list has the SAME length N; index i is permutation
    # i ALIGNED across candidates (row-wise max over candidates is a valid per-perm family max).
    # value = the candidate's refit fold-mean signed Pearson r under permutation i. ANSWER-PROOF:
    # there is NO p / observed-stat input — the society recomputes the observed statistic from
    # candidate_preds/candidate_targets and derives the p itself; the draws only supply the null
    # the society can't recompute. Trust posture is a DOWNGRADE (tamper-evident, not tamper-proof).
    refit_null_stats: dict[str, list[float]] | None = None
    subject_ids: list[str] | None = None
    target_name: str | None = None
    meta: dict[str, str] | None = None

    @model_validator(mode="after")
    def _validate_refit_null_stats(self) -> ProbeInputsV1:
        """Unbypassable structural contract for the refit-null channel.

        Runs on EVERY construction (incl. the commissioner's ``ProbeInputsV1(**clean)`` path
        that bypasses ``build_probe_inputs``), so a malformed refit payload can never reach the
        compute path: it raises at the model boundary instead of yielding a silent wrong p.
        """
        rns = self.refit_null_stats
        if rns is None:
            return self
        if not rns:
            raise ValueError("refit_null_stats must be non-empty when present")
        if len(rns) < 2:
            raise ValueError("refit_null_stats needs >=2 candidates (no multiplicity for K=1)")
        # observed stat must be SOCIETY-computable -> require the family preds AND targets, ==keys
        if self.candidate_preds is None or self.candidate_targets is None:
            raise ValueError("refit_null_stats requires candidate_preds AND candidate_targets")
        keys = set(rns)
        if keys != set(self.candidate_preds) or keys != set(self.candidate_targets):
            raise ValueError(
                "refit_null_stats keys must EQUAL candidate_preds and candidate_targets keys "
                "(the full declared family — a subset would silently shrink M_perm)"
            )
        banned = keys & _BANNED_ANSWER_KEYS
        if banned:
            raise ValueError(f"refit_null_stats column name(s) collide with answer keys: {sorted(banned)}")
        lengths = {len(v) for v in rns.values()}
        if len(lengths) != 1:
            raise ValueError(f"refit_null_stats columns must share one length N; got {sorted(lengths)}")
        n = lengths.pop()
        if n < MIN_PERMUTATIONS:
            raise ValueError(f"refit_null_stats N={n} < MIN_PERMUTATIONS={MIN_PERMUTATIONS}")
        # the OBSERVED stat is recomputed from candidate_preds/candidate_targets, so every
        # family column MUST be subject-aligned to y_true — else commission() hits an IndexError
        # instead of a clean abstain. (refit_null_stats columns are length-N, checked above.)
        s = len(self.y_true)
        bad = {k: len(v) for k, v in self.candidate_preds.items() if len(v) != s}
        bad.update({f"target:{k}": len(v) for k, v in self.candidate_targets.items() if len(v) != s})
        if bad:
            raise ValueError(f"candidate columns must be length S={s} (y_true); off: {bad}")
        if self.fold_ids is not None and len(self.fold_ids) != s:
            raise ValueError(f"fold_ids length {len(self.fold_ids)} != S={s}")
        return self


@runtime_checkable
class ProbeCommissionerProtocol(Protocol):
    """The conductor depends only on this surface (tests can stub it)."""

    def commission(
        self, strategy: str, results: dict[str, Any], *, scorer_payload_path: str | None = ...
    ) -> list[dict[str, Any]] | None: ...


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson r over the finite-paired entries; nan if <2 pairs or zero variance."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    if mask.sum() < 2:
        return float("nan")
    a, b = a[mask], b[mask]
    if np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _ols_resid(
    design_fit: np.ndarray, y_fit: np.ndarray, design_apply: np.ndarray, y_apply: np.ndarray
) -> np.ndarray:
    """Residualize ``y_apply`` against ``design_apply`` using betas fit on
    ``(design_fit, y_fit)`` (intercept assumed already in the design)."""
    beta, *_ = np.linalg.lstsq(design_fit, y_fit, rcond=None)
    return y_apply - design_apply @ beta


def _augment(design: np.ndarray, train_means: np.ndarray) -> np.ndarray:
    """Impute NaNs with the given per-column means and prepend an intercept column."""
    d = np.array(design, dtype=float, copy=True)
    inds = np.where(np.isnan(d))
    if inds[0].size:
        d[inds] = np.take(train_means, inds[1])
    return np.column_stack([np.ones(len(d)), d])


def compute_residualization_probe(
    y_pred: list[float] | np.ndarray,
    y_true: list[float] | np.ndarray,
    confound_design: list[list[float]] | np.ndarray,
    *,
    confound_name: str,
    fold_ids: list[int] | np.ndarray | None = None,
    fit_scope: str = "leakage_free",
    version: str = COMMISSIONER_VERSION,
) -> dict[str, Any]:
    """Compute the confound-residualization probe from RAW arrays.

    THE ONLY source of ``retained_pct``. Has no answer parameter by construction.

    Args:
        y_pred: per-subject out-of-sample predictions, shape (S,).
        y_true: the outcome target, shape (S,).
        confound_design: nuisance design columns, shape (S, k).
        confound_name: label for the probe (e.g. "general intelligence").
        fold_ids: optional CV fold assignment, shape (S,). Enables leakage-free
            fold-wise residualization; absent → single in-sample fit (``fold_wise=False``).
        fit_scope: "leakage_free" (default, honest: prediction betas fit on TRAIN) or
            "oracle_compat" (prediction betas fit on the SAME TEST block — the BangHCP
            "upper-bound deconfounding" that reproduces 56/16/80).

    Returns the gate-shaped probe dict (all scalars plain ``float``):
    ``{confound, unadjusted_r, residualized_r, retained_pct, n_subjects, fold_wise,
    method, fit_scope, provenance, inputs_fingerprint, commissioner_version, status}``.
    """
    yp = np.asarray(y_pred, dtype=float)
    yt = np.asarray(y_true, dtype=float)
    C = np.asarray(confound_design, dtype=float)
    if C.ndim == 1:
        C = C.reshape(-1, 1)
    S = len(yt)
    if not (len(yp) == S == len(C)):
        raise ValueError(
            f"length mismatch: y_pred={len(yp)} y_true={S} confound={len(C)}"
        )
    if S < 2:
        raise ValueError("need >=2 subjects to residualize")

    if fold_ids is None:
        fold_list = [(np.arange(S), np.arange(S))]
        fold_wise = False
    else:
        fids = np.asarray(fold_ids)
        fold_list = []
        for k in np.unique(fids):
            test = np.where(fids == k)[0]
            train = np.where(fids != k)[0]
            if len(train) == 0 or len(test) == 0:
                train = test = np.arange(S)
            fold_list.append((train, test))
        fold_wise = True

    r_resid: list[float] = []
    r_unadj: list[float] = []
    for train, test in fold_list:
        train_means = np.nanmean(C[train], axis=0)
        train_means = np.where(np.isfinite(train_means), train_means, 0.0)
        C_tr = _augment(C[train], train_means)
        C_te = _augment(C[test], train_means)
        yt_res = _ols_resid(C_tr, yt[train], C_te, yt[test])
        if fit_scope == "oracle_compat":
            yp_res = _ols_resid(C_te, yp[test], C_te, yp[test])
        else:
            yp_res = _ols_resid(C_tr, yp[train], C_te, yp[test])
        r_resid.append(_pearson(yt_res, yp_res))
        r_unadj.append(_pearson(yt[test], yp[test]))

    residualized_r = float(np.nanmean(r_resid))
    unadjusted_r = float(np.nanmean(r_unadj))

    status = "ok"
    if not math.isfinite(unadjusted_r) or abs(unadjusted_r) < NEAR_ZERO_R_FLOOR:
        retained_pct: float | None = None
        status = "unresolved_near_zero_effect"
    else:
        retained_pct = 100.0 * residualized_r / unadjusted_r

    probe: dict[str, Any] = {
        "confound": confound_name,
        "unadjusted_r": unadjusted_r,
        "residualized_r": residualized_r,
        "retained_pct": retained_pct,
        "n_subjects": int(S),
        "fold_wise": fold_wise,
        "method": "partial_correlation_ols",
        "fit_scope": fit_scope,
        "provenance": "commissioned",
        "status": status,
        "commissioner_version": version,
    }
    probe["inputs_fingerprint"] = fingerprint(
        {
            "y_pred": [float(x) for x in yp.tolist()],
            "y_true": [float(x) for x in yt.tolist()],
            "confound_design": [[float(x) for x in row] for row in C.tolist()],
            "fold_ids": None if fold_ids is None else [int(x) for x in np.asarray(fold_ids).tolist()],
            "confound_name": confound_name,
        }
    )
    return probe


def _fold_mean_r(
    y_pred: np.ndarray, y_true: np.ndarray, fold_index: list[np.ndarray]
) -> float:
    """Fold-mean signed Pearson r (the headline predictive statistic) — NOT pooled r.
    Pooled r silently gives a different number; the oracle reports the fold-mean."""
    return float(np.nanmean([_pearson(y_pred[idx], y_true[idx]) for idx in fold_index]))


def compute_permutation_null_probe(
    y_pred: list[float] | np.ndarray,
    y_true: list[float] | np.ndarray,
    fold_ids: list[int] | np.ndarray,
    *,
    n_permutations: int = DEFAULT_N_PERMUTATIONS,
    seed: int = 0,
    version: str = COMMISSIONER_VERSION,
) -> dict[str, Any]:
    """Compute a permutation-null p for the headline predictive effect from RAW arrays.

    THE ONLY source of the null p. Answer-proof by construction: there is no
    ``family_block_p`` / ``permutation_p`` parameter — the p cannot be supplied, only
    computed.

    Statistic = fold-mean signed Pearson r between ``y_pred`` and ``y_true``. Null =
    within-fold permutation of ``y_true`` against the FROZEN ``y_pred`` (a real predictor
    is not refit; we test whether the observed alignment exceeds chance under
    label-shuffling that respects the CV fold structure). One-sided UPPER tail with the
    plus-one estimator: ``p = (1 + #{r_perm >= r_obs}) / (N + 1)`` (never 0).

    ``fold_ids`` is MANDATORY: pooled r over all subjects is a different statistic from
    the fold-mean the oracle reports. ``n_permutations`` / ``seed`` are method knobs the
    caller (commissioner) owns; they are never read from the payload.

    NOTE (honest scope): this is a FREE within-fold label shuffle. For exchangeable
    subjects it is exact; for a dataset with strongly correlated families (e.g. many
    twins) it is mildly anti-conservative. HCP-YA is ~1 twin pair in 325, so free shuffle
    is empirically near-exact (a proper family-restricted permutation is a follow-up).
    """
    yp = np.asarray(y_pred, dtype=float)
    yt = np.asarray(y_true, dtype=float)
    fids = np.asarray(fold_ids)
    S = len(yt)
    if not (len(yp) == S == len(fids)):
        raise ValueError(f"length mismatch: y_pred={len(yp)} y_true={S} fold_ids={len(fids)}")
    if S < 2:
        raise ValueError("need >=2 subjects for a permutation null")
    fold_index = [np.where(fids == k)[0] for k in np.unique(fids)]

    r_obs = _fold_mean_r(yp, yt, fold_index)
    rng = np.random.default_rng(seed)
    ge = 0
    perm_stats: list[float] = []
    for _ in range(int(n_permutations)):
        y_perm = yt.copy()
        for idx in fold_index:
            y_perm[idx] = rng.permutation(yt[idx])
        r_perm = _fold_mean_r(yp, y_perm, fold_index)
        perm_stats.append(r_perm)
        if r_perm >= r_obs:
            ge += 1
    p = (1.0 + ge) / (int(n_permutations) + 1.0)

    return {
        "metric": "fold_mean_r",
        "observed_fold_mean_r": r_obs,
        "family_block_p": float(p),
        "n_permutations": int(n_permutations),
        "n_subjects": int(S),
        "null_sd": float(np.nanstd(perm_stats)) if perm_stats else float("nan"),
        "method": "within_fold_label_permutation",
        "exchangeability": "free_within_fold",
        "provenance": "commissioned",
        "commissioner_version": version,
        # tells the conductor to OVERWRITE the top-level p the gate reads (vs the
        # confound probe which appends to robustness_probes).
        "scorer_payload_inject": {"family_block_p": float(p)},
        "inputs_fingerprint": fingerprint(
            {
                "y_pred": [float(x) for x in yp.tolist()],
                "y_true": [float(x) for x in yt.tolist()],
                "fold_ids": [int(x) for x in fids.tolist()],
            }
        ),
    }


#: Minimum |fold-mean r| of the headline candidate for a correction-fragility verdict to be
#: trustworthy. Below this the effect is at noise level and the corrected/uncorrected p ratio
#: is meaningless (existence is permutation_null's job, not correction_fragile's).
CORRECTION_FRAGILE_MIN_R: float = 0.05


def compute_correction_fragility_probe(
    candidate_preds: dict[str, list[float] | np.ndarray],
    y_true: list[float] | np.ndarray,
    *,
    fold_ids: list[int] | np.ndarray | None = None,
    headline_candidate: str | None = None,
    n_permutations: int = DEFAULT_N_PERMUTATIONS,
    seed: int = 0,
    version: str = COMMISSIONER_VERSION,
) -> dict[str, Any]:
    """Frozen-prediction Westfall-Young max-T correction-fragility probe from RAW arrays.

    THE ONLY source of the corrected p. Answer-proof: there is no p-value parameter.

    Given K candidates' out-of-sample predictions (the S x K matrix the multiplicity
    correction needs) and the shared target, computes the headline's UNCORRECTED p and a
    max-T (family-wise) CORRECTED p under one shared within-fold permutation null:
      * statistic per candidate = fold-mean signed Pearson r (the same ``_fold_mean_r``);
      * per permutation, ONE within-fold shuffle of ``y_true``, recompute ALL candidates,
        ``M_perm = max_k stat_k``;
      * ``uncorrected_p = (1 + #{stat_head_perm >= stat_head_obs}) / (N + 1)``;
      * ``max_T_p       = (1 + #{M_perm          >= stat_head_obs}) / (N + 1)``  (>= uncorrected).
    The gate fires (-> qualified) when ``uncorrected_p <= alpha`` but ``max_T_p > alpha``.

    HONEST SCOPE (synthetic-only): this corrects over the EMITTED FROZEN candidates (e.g.
    components). It is NOT the oracle's refit-PIPELINE correction (which re-runs each pipeline
    variant per permutation) and does NOT reproduce the real PERSEMO max_T_post_selection_p
    — it is a weaker, lower-bound multiplicity axis. The headline is FORCED to the argmax|r|
    candidate (a supplied ``headline_candidate`` is recorded as metadata only, never trusted)
    so a caller cannot launder the verdict by naming a convenient winner.
    """
    yt = np.asarray(y_true, dtype=float)
    S = len(yt)
    names = list(candidate_preds)
    if not names:
        raise ValueError("need >=1 candidate")
    preds = {n: np.asarray(candidate_preds[n], dtype=float) for n in names}
    for n, arr in preds.items():
        if len(arr) != S:
            raise ValueError(f"candidate {n!r} length {len(arr)} != S={S}")

    if fold_ids is None:
        fold_index = [np.arange(S)]
    else:
        fids = np.asarray(fold_ids)
        fold_index = [np.where(fids == k)[0] for k in np.unique(fids)]

    obs = {n: _fold_mean_r(preds[n], yt, fold_index) for n in names}
    finite_obs = {n: v for n, v in obs.items() if math.isfinite(v)}
    if not finite_obs:
        return {
            "metric": "fold_mean_r",
            "status": "unresolved_degenerate",
            "method": "westfall_young_maxT_frozen_candidates",
            "provenance": "commissioned",
            "commissioner_version": version,
        }
    # headline FORCED to argmax|r| — never trust a supplied name for the verdict.
    headline = max(finite_obs, key=lambda n: abs(finite_obs[n]))
    t_head = obs[headline]

    rng = np.random.default_rng(seed)
    ge_unc = 0
    ge_max = 0
    N = int(n_permutations)
    for _ in range(N):
        y_perm = yt.copy()
        for idx in fold_index:
            y_perm[idx] = rng.permutation(yt[idx])
        perm_stats = [_fold_mean_r(preds[n], y_perm, fold_index) for n in names]
        finite_perm = [v for v in perm_stats if math.isfinite(v)]
        if not finite_perm:
            continue
        if perm_stats[names.index(headline)] >= t_head and math.isfinite(
            perm_stats[names.index(headline)]
        ):
            ge_unc += 1
        if max(finite_perm) >= t_head:
            ge_max += 1
    uncorrected_p = (1.0 + ge_unc) / (N + 1.0)
    max_T_p = (1.0 + ge_max) / (N + 1.0)

    status = "ok"
    if abs(t_head) < CORRECTION_FRAGILE_MIN_R:
        status = "unresolved_near_zero_effect"  # don't certify fragility on noise

    probe: dict[str, Any] = {
        "metric": "fold_mean_r",
        "headline_candidate": headline,
        "supplied_headline_candidate": headline_candidate,
        "headline_is_argmax": True,
        "n_candidates": len(names),
        "observed_fold_mean_r": float(t_head),
        "uncorrected_p": float(uncorrected_p),
        "corrected_max_T_p": float(max_T_p),
        "n_permutations": N,
        "n_subjects": int(S),
        "method": "westfall_young_maxT_frozen_candidates",
        "multiplicity_axis": "frozen_emitted_candidates",
        "scope_note": (
            "corrects over emitted frozen candidates (e.g. components); a WEAKER axis than "
            "the oracle's refit-pipeline correction — does NOT reproduce real PERSEMO 0.105"
        ),
        "provenance": "commissioned",
        "status": status,
        "commissioner_version": version,
        # the gate reads family_block_p (uncorrected) + a strict corrected key; supply both.
        "scorer_payload_inject": (
            {
                "family_block_p": float(uncorrected_p),
                "max_T_post_selection_p": float(max_T_p),
            }
            if status == "ok"
            else {}
        ),
        "inputs_fingerprint": fingerprint(
            {
                "candidate_preds": {n: [float(x) for x in preds[n].tolist()] for n in sorted(names)},
                "y_true": [float(x) for x in yt.tolist()],
                "fold_ids": None if fold_ids is None else [int(x) for x in np.asarray(fold_ids).tolist()],
            }
        ),
    }
    return probe


def compute_target_family_correction_probe(
    candidate_preds: dict[str, list[float] | np.ndarray],
    candidate_targets: dict[str, list[float] | np.ndarray],
    *,
    headline: str,
    fold_ids: list[int] | np.ndarray | None = None,
    n_permutations: int = 2000,
    seed: int = 0,
    version: str = "resid-probe-v1",
) -> dict[str, Any]:
    """Frozen-prediction max-T correction over a family of K *different* targets.

    THE ONLY source of the corrected p for the TARGET family (e.g. the K behavioural
    components a single predictor was applied to, each with its own outcome). Answer-proof:
    there is no p-value parameter.

    Unlike :func:`compute_correction_fragility_probe` (K predictors for ONE shared target,
    headline forced to argmax|r|), here each candidate ``k`` is scored against its OWN target
    ``candidate_targets[k]`` and the ``headline`` names the claim under adjudication (argmax
    across different targets is meaningless, so the caller fixes it). The multiplicity null is
    the SHARED row permutation the oracle uses — one within-fold reordering applied jointly to
    every target column (preserves cross-target correlation) — but over FROZEN predictions
    instead of refitting:

      * statistic per candidate = fold-mean signed Pearson r (``_fold_mean_r``);
      * per permutation, ONE within-fold index reorder applied to ALL targets, recompute every
        candidate, ``M_perm = max_k stat_k``;
      * ``uncorrected_p = (1 + #{stat_head_perm >= stat_head_obs}) / (N + 1)``;
      * ``max_T_p       = (1 + #{M_perm          >= stat_head_obs}) / (N + 1)``  (>= uncorrected).
    The gate fires (-> qualified) when ``uncorrected_p <= alpha`` but ``max_T_p > alpha``.

    HONEST SCOPE: (1) frozen ~= refit empirically (BangHCP 5-component family: this probe
    reproduces the oracle's refit max-T fragility class 5/5; the headline component's frozen
    max-T slightly UNDER-estimates the refit value — 0.054 vs oracle 0.068 — so it is more
    boundary-sensitive near alpha). (2) The correction is only as strong as the DECLARED
    family: under-declaring candidates understates fragility. This is a completeness caveat,
    not laundering protection — the headline is caller-fixed by the claim, so the integrity
    burden is "declare the full family you tested", recorded in ``family_members``.
    """
    names = list(candidate_preds)
    if len(names) < 2:
        raise ValueError("target-family correction needs >=2 candidates")
    if set(candidate_targets) != set(candidate_preds):
        raise ValueError("candidate_targets keys must match candidate_preds keys")
    if headline not in candidate_preds:
        raise ValueError(f"headline {headline!r} not in candidate family {names}")

    preds = {n: np.asarray(candidate_preds[n], dtype=float) for n in names}
    targs = {n: np.asarray(candidate_targets[n], dtype=float) for n in names}
    S = len(targs[headline])
    for n in names:
        if len(preds[n]) != S or len(targs[n]) != S:
            raise ValueError(f"candidate {n!r} arrays length != S={S}")

    if fold_ids is None:
        fold_index = [np.arange(S)]
    else:
        fids = np.asarray(fold_ids)
        fold_index = [np.where(fids == k)[0] for k in np.unique(fids)]

    obs = {n: _fold_mean_r(preds[n], targs[n], fold_index) for n in names}
    t_head = obs[headline]
    if not math.isfinite(t_head):
        return {
            "metric": "fold_mean_r",
            "status": "unresolved_degenerate",
            "method": "westfall_young_maxT_frozen_target_family",
            "headline_candidate": headline,
            "provenance": "commissioned",
            "commissioner_version": version,
        }

    rng = np.random.default_rng(seed)
    N = int(n_permutations)
    ge_unc = 0
    ge_max = 0
    for _ in range(N):
        perm_targs = {}
        for n in names:
            col = targs[n].copy()
            perm_targs[n] = col
        # ONE shared within-fold reorder applied to every target column jointly.
        for idx in fold_index:
            reorder = rng.permutation(idx)
            for n in names:
                perm_targs[n][idx] = targs[n][reorder]
        perm_stats = [_fold_mean_r(preds[n], perm_targs[n], fold_index) for n in names]
        finite_perm = [v for v in perm_stats if math.isfinite(v)]
        if not finite_perm:
            continue
        head_perm = perm_stats[names.index(headline)]
        if math.isfinite(head_perm) and head_perm >= t_head:
            ge_unc += 1
        if max(finite_perm) >= t_head:
            ge_max += 1
    uncorrected_p = (1.0 + ge_unc) / (N + 1.0)
    max_T_p = (1.0 + ge_max) / (N + 1.0)

    status = "ok"
    if abs(t_head) < CORRECTION_FRAGILE_MIN_R:
        status = "unresolved_near_zero_effect"

    probe: dict[str, Any] = {
        "metric": "fold_mean_r",
        "headline_candidate": headline,
        "headline_is_argmax": False,
        "n_candidates": len(names),
        "family_members": sorted(names),
        "observed_fold_mean_r": float(t_head),
        "uncorrected_p": float(uncorrected_p),
        "corrected_max_T_p": float(max_T_p),
        "n_permutations": N,
        "n_subjects": int(S),
        "method": "westfall_young_maxT_frozen_target_family",
        "multiplicity_axis": "frozen_target_family",
        "scope_note": (
            "corrects over a family of K different targets (frozen predictions, shared "
            "row-permutation null); reproduces the oracle refit max-T fragility class but "
            "slightly under-estimates the corrected p near alpha. Only as strong as the "
            "declared family_members."
        ),
        "provenance": "commissioned",
        "status": status,
        "commissioner_version": version,
        "scorer_payload_inject": (
            {
                "family_block_p": float(uncorrected_p),
                "max_T_post_selection_p": float(max_T_p),
            }
            if status == "ok"
            else {}
        ),
        "inputs_fingerprint": fingerprint(
            {
                "candidate_preds": {n: [float(x) for x in preds[n].tolist()] for n in sorted(names)},
                "candidate_targets": {n: [float(x) for x in targs[n].tolist()] for n in sorted(names)},
                "headline": headline,
                "fold_ids": None if fold_ids is None else [int(x) for x in np.asarray(fold_ids).tolist()],
            }
        ),
    }
    return probe


def _draws_integrity_flags(draws: dict[str, np.ndarray]) -> list[str]:
    """Cheap plausibility flags over SUPPLIED refit draws (tamper-evident, not tamper-proof)."""
    flags: list[str] = []
    cols = list(draws.values())
    for name, col in draws.items():
        finite = col[np.isfinite(col)]
        if finite.size == 0:
            flags.append(f"{name}:all_nonfinite")
            continue
        if float(np.nanstd(col)) < 1e-9:
            flags.append(f"{name}:constant")
        if np.nanmax(np.abs(col)) > 1.0 + 1e-9:
            flags.append(f"{name}:abs_r_gt_1")  # a fold-mean Pearson r cannot exceed 1
    if len(cols) >= 2 and all(np.allclose(cols[0], c, equal_nan=True) for c in cols[1:]):
        flags.append("all_columns_identical")
    return flags


def compute_refit_null_correction_probe(
    candidate_preds: dict[str, list[float] | np.ndarray],
    candidate_targets: dict[str, list[float] | np.ndarray],
    refit_null_stats: dict[str, list[float] | np.ndarray],
    *,
    headline: str,
    fold_ids: list[int] | np.ndarray | None = None,
    version: str = "resid-probe-v1",
) -> dict[str, Any]:
    """Oracle-power max-T correction from EPISODE-supplied REFIT null statistic draws.

    The society cannot refit the predictor (it has no model/features), so the cheap frozen
    max-T (:func:`compute_target_family_correction_probe`) under-detects fragility near alpha.
    Here the EPISODE — which can refit — supplies the per-candidate REFIT statistic DRAWS
    (the N x K matrix the multiplicity correction needs); the society computes the corrected p
    itself. ANSWER-PROOF: there is NO p / observed-stat input. The observed statistic is
    recomputed by the society from the frozen ``candidate_preds``/``candidate_targets`` it
    already holds (identical ``_fold_mean_r`` to the other probes); the draws only supply the
    null the society cannot recompute.

      * ``stat_obs[k]`` = fold-mean signed Pearson r (SOCIETY-computed);
      * ``uncorrected_p`` = (1 + #{ draws[head][i] >= stat_obs[head] }) / (N + 1);
      * ``M_perm[i]``    = max over k of finite ``draws[k][i]``;
      * ``max_T_p``      = (1 + #{ M_perm[i] >= stat_obs[head] }) / (N + 1)   (>= uncorrected).
    Non-finite draws at permutation i are dropped from BOTH legs consistently (``nan >= obs``
    is False in numpy, which would silently bias the p downward = anti-conservative).

    TRUST DOWNGRADE: provenance is ``commissioned_refit_null_supplied`` (not plain
    ``commissioned``) and the draws ride the attestation fingerprint, so a forged-draws
    fabrication is tamper-EVIDENT. A frozen lower-bound is computed in parallel as a
    disagreement tripwire (forgery that says "survives" while frozen says "fragile" is flagged).
    """
    if set(refit_null_stats) != set(candidate_preds) or set(refit_null_stats) != set(candidate_targets):
        raise ValueError("refit_null_stats keys must equal candidate_preds and candidate_targets keys")
    if headline not in candidate_preds:
        raise ValueError(f"headline {headline!r} not in family {sorted(candidate_preds)}")
    names = sorted(candidate_preds)
    preds = {n: np.asarray(candidate_preds[n], dtype=float) for n in names}
    targs = {n: np.asarray(candidate_targets[n], dtype=float) for n in names}
    draws = {n: np.asarray(refit_null_stats[n], dtype=float) for n in names}
    lengths = {len(draws[n]) for n in names}
    if len(lengths) != 1:
        raise ValueError("refit_null_stats columns must share one length N")
    N = lengths.pop()
    if N < 2:
        raise ValueError("need N>=2 permutation draws")

    if fold_ids is None:
        fold_index = [np.arange(len(targs[headline]))]
    else:
        fids = np.asarray(fold_ids)
        fold_index = [np.where(fids == k)[0] for k in np.unique(fids)]

    # OBSERVED statistic: society-computed from frozen preds/targets (never supplied).
    stat_obs = {n: _fold_mean_r(preds[n], targs[n], fold_index) for n in names}
    t_head = stat_obs[headline]
    base = {
        "metric": "fold_mean_r",
        "headline_candidate": headline,
        "headline_is_argmax": False,
        "n_candidates": len(names),
        "family_members": names,
        "n_permutations": int(N),
        "method": "westfall_young_maxT_refit_null_supplied",
        "multiplicity_axis": "refit_null_supplied",
        "correction_step": "single_step_westfall_young",
        "provenance": "commissioned_refit_null_supplied",
        "commissioner_version": version,
        "draws_integrity_flags": _draws_integrity_flags(draws),
    }
    if not math.isfinite(t_head):
        return {**base, "status": "unresolved_degenerate", "scorer_payload_inject": {}}
    if abs(t_head) < CORRECTION_FRAGILE_MIN_R:
        return {**base, "observed_fold_mean_r": float(t_head),
                "status": "unresolved_near_zero_effect", "scorer_payload_inject": {}}

    head_draws = draws[headline]
    ge_unc = 0
    ge_max = 0
    eff_n = 0
    for i in range(N):
        hd = head_draws[i]
        col = np.array([draws[n][i] for n in names], dtype=float)
        finite = col[np.isfinite(col)]
        if not math.isfinite(hd) or finite.size == 0:
            continue  # drop this permutation from BOTH legs (consistent denominator)
        eff_n += 1
        if hd >= t_head:
            ge_unc += 1
        if finite.max() >= t_head:
            ge_max += 1
    if eff_n < 0.5 * N:
        return {**base, "observed_fold_mean_r": float(t_head),
                "status": "unresolved_too_many_nonfinite_draws",
                "effective_n": int(eff_n), "scorer_payload_inject": {}}
    uncorrected_p = (1.0 + ge_unc) / (eff_n + 1.0)
    max_T_p = (1.0 + ge_max) / (eff_n + 1.0)

    # parallel FROZEN lower-bound cross-check (disagreement tripwire)
    frozen_max_T_p = None
    disagreement = None
    try:
        frz = compute_target_family_correction_probe(
            candidate_preds, candidate_targets, headline=headline, fold_ids=fold_ids,
            n_permutations=max(N, MIN_PERMUTATIONS), seed=0, version=version)
        frozen_max_T_p = frz.get("corrected_max_T_p")
        if frozen_max_T_p is not None:
            # forgery hides where supplied-refit says SURVIVES but frozen says FRAGILE
            disagreement = bool(max_T_p <= CORRECTION_FRAGILE_ALPHA < frozen_max_T_p)
    except Exception:  # cross-check is best-effort; never blocks the verdict
        frozen_max_T_p = None

    probe = {
        **base,
        "observed_fold_mean_r": float(t_head),
        "uncorrected_p": float(uncorrected_p),
        "corrected_max_T_p": float(max_T_p),
        "effective_n": int(eff_n),
        "n_dropped_nonfinite": int(N - eff_n),
        "frozen_max_T_p_crosscheck": (None if frozen_max_T_p is None else float(frozen_max_T_p)),
        "frozen_disagreement": disagreement,
        "scope_note": (
            "max-T from EPISODE-supplied refit null draws (oracle-power); society computes the "
            "observed stat + the p. TRUST DOWNGRADE: draws are caller-supplied (tamper-evident "
            "via attestation, not tamper-proof). frozen lower-bound computed as a disagreement "
            "tripwire. single-step Westfall-Young."
        ),
        "status": "ok",
        "scorer_payload_inject": {
            "family_block_p": float(uncorrected_p),
            "max_T_post_selection_p": float(max_T_p),
        },
        "inputs_fingerprint": fingerprint(
            {
                "candidate_preds": {n: [float(x) for x in preds[n].tolist()] for n in names},
                "candidate_targets": {n: [float(x) for x in targs[n].tolist()] for n in names},
                "refit_null_stats": {n: [float(x) for x in draws[n].tolist()] for n in names},
                "headline": headline,
                "fold_ids": None if fold_ids is None else [int(x) for x in np.asarray(fold_ids).tolist()],
            }
        ),
    }
    return probe


def compute_selection_leakage_probe(
    candidate_preds: dict[str, list[float] | np.ndarray],
    y_true: list[float] | np.ndarray,
    *,
    fold_ids: list[int] | np.ndarray | None = None,
    headline_candidate: str | None = None,
    version: str = "resid-probe-v1",
) -> dict[str, Any]:
    """Deterministic SELECTION-optimism probe (circular analysis / double-dipping).

    Given K candidate predictors of the SAME target (a model-selection family — e.g. K
    pipelines/metrics tried for one outcome) and CV folds, quantifies how much of the
    post-hoc "best candidate" effect is selection-induced optimism (the Kriegeskorte 2009
    double-dipping / "voodoo correlations" error: selecting AND evaluating the winner on the
    same data):

      * ``r_pooled`` = fold-mean signed Pearson r of the argmax candidate, selected on ALL
        folds (the naive post-hoc-selected headline);
      * ``r_oos``    = honest NESTED leave-one-fold-out selection: for each fold f, pick the
        candidate with the best fold-mean r over folds != f, score THAT candidate on the
        held-out fold f, then average — the generalization of "select by CV, then apply";
      * ``selection_retained_pct`` = 100 * r_oos / r_pooled.
    The gate fires (-> qualified) when retained_pct is low: the apparent winner is largely a
    selection artifact (its lead does not survive honest nested selection).

    ANSWER-PROOF: there is NO retained/gap/r_oos parameter; the society recomputes everything
    from the frozen candidate matrix. The winner is FORCED to the argmax candidate (a supplied
    ``headline_candidate`` is recorded as metadata only) so a caller cannot name a convenient
    winner. K=1 means no selection occurred -> abstain (the honest tripwire; under-declaring
    the family to K=1 hides selection, same caveat as correction_fragile).
    """
    names = list(candidate_preds)
    if len(names) < 2:
        raise ValueError("selection_leakage needs >=2 candidates (no selection for K=1)")
    yt = np.asarray(y_true, dtype=float)
    S = len(yt)
    preds = {n: np.asarray(candidate_preds[n], dtype=float) for n in names}
    for n in names:
        if len(preds[n]) != S:
            raise ValueError(f"candidate {n!r} length {len(preds[n])} != S={S}")

    base = {
        "metric": "fold_mean_r",
        "n_candidates": len(names),
        "method": "nested_leave_fold_out_selection_vs_pooled",
        "multiplicity_axis": "candidate_selection",
        "provenance": "commissioned",
        "commissioner_version": version,
        "supplied_headline_candidate": headline_candidate,
        "headline_is_argmax": True,
    }
    if fold_ids is None:
        return {**base, "status": "unresolved_no_folds", "scorer_payload_inject": {}}
    fids = np.asarray(fold_ids)
    uniq = list(np.unique(fids))
    if len(uniq) < 2:
        return {**base, "status": "unresolved_single_fold", "scorer_payload_inject": {}}
    fold_index = {int(f): np.where(fids == f)[0] for f in uniq}
    fold_list = [fold_index[int(f)] for f in uniq]

    def _fmr_over(pred: np.ndarray, idxs: list[np.ndarray]) -> float:
        rs = [_pearson(pred[idx], yt[idx]) for idx in idxs]
        rs = [r for r in rs if math.isfinite(r)]
        return float(np.mean(rs)) if rs else float("nan")

    # pooled: argmax SIGNED fold-mean r over ALL folds (the "best predictor" an analyst reports)
    pooled = {n: _fold_mean_r(preds[n], yt, fold_list) for n in names}
    finite = {n: v for n, v in pooled.items() if math.isfinite(v)}
    if not finite:
        return {**base, "status": "unresolved_degenerate", "scorer_payload_inject": {}}
    winner = max(finite, key=lambda n: finite[n])
    r_pooled = pooled[winner]

    # honest nested leave-one-fold-out selection
    oos = []
    for f in uniq:
        train = [fold_index[int(g)] for g in uniq if g != f]
        train_r = {n: _fmr_over(preds[n], train) for n in names}
        ftrain = {n: v for n, v in train_r.items() if math.isfinite(v)}
        if not ftrain:
            continue
        sel = max(ftrain, key=lambda n: ftrain[n])
        r_test = _pearson(preds[sel][fold_index[int(f)]], yt[fold_index[int(f)]])
        if math.isfinite(r_test):
            oos.append(r_test)
    if not oos:
        return {**base, "status": "unresolved_degenerate", "scorer_payload_inject": {}}
    r_oos = float(np.mean(oos))

    status = "ok"
    # SIGNED floor: a "FC predicts X" claim needs a POSITIVE best-candidate effect. r_pooled is
    # the argmax SIGNED fold-mean r, so r_pooled < floor covers both near-zero and all-negative
    # families (no positive predictive effect to attribute to selection) -> abstain. This also
    # keeps the ratio sign interpretable (denominator is a positive effect).
    if r_pooled < NEAR_ZERO_R_FLOOR:
        status = "unresolved_near_zero_effect"
    retained_pct = 100.0 * r_oos / r_pooled if r_pooled > 0 else float("nan")

    probe = {
        **base,
        "headline_candidate": winner,
        "r_pooled": float(r_pooled),
        "r_oos": float(r_oos),
        "selection_retained_pct": (None if not math.isfinite(retained_pct) else float(retained_pct)),
        "n_subjects": int(S),
        "n_folds": len(uniq),
        "n_oos_folds": len(oos),  # folds that contributed a finite nested-selection score
        "scope_note": (
            "in/out selection gap over the frozen candidate matrix; only as strong as the "
            "DECLARED family — a K=1 family hides selection (abstains). detects selection "
            "optimism, not feature-level double-dipping inside a single pipeline."
        ),
        "status": status,
        "scorer_payload_inject": (
            {"selection_retained_pct": float(retained_pct)}
            if status == "ok" and math.isfinite(retained_pct)
            else {}
        ),
        "inputs_fingerprint": fingerprint(
            {
                "candidate_preds": {n: [float(x) for x in preds[n].tolist()] for n in sorted(names)},
                "y_true": [float(x) for x in yt.tolist()],
                "fold_ids": [int(x) for x in fids.tolist()],
            }
        ),
    }
    return probe


def compute_effect_size_floor_probe(
    y_pred: list[float] | np.ndarray,
    y_true: list[float] | np.ndarray,
    fold_ids: list[int] | np.ndarray,
    *,
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
    version: str = "resid-probe-v1",
) -> dict[str, Any]:
    """Deterministic EFFECT-SIZE-FLOOR probe (statistically significant but practically trivial).

    permutation_null answers "is the effect above chance"; this answers "is the effect big
    enough to matter". A huge-N study can make a trivially small effect (r≈0.03) highly
    significant. Over the headline OOS arrays this computes the fold-mean signed Pearson r and a
    fold-respecting percentile BOOTSTRAP CI (resample subjects WITHIN each fold, recompute
    fold-mean r). The gate fires (-> qualified) when the effect is RELIABLY POSITIVE
    (ci_low > 0) yet RELIABLY TRIVIAL (ci_high < a small-effect floor): we are confident the
    true effect, while nonzero, is below practical significance.

    Why a CI, not the point estimate: at modest N a modest effect has a WIDE CI (ci_high stays
    above the floor) -> does NOT fire, so honest modest-N studies are not penalised; only when
    the CI is tight AND entirely sub-trivial (the big-N / vanishing-effect regime) does it fire.

    ANSWER-PROOF: no effect-size / CI / verdict input; the society computes everything from the
    arrays. n_boot/seed are commissioner-owned (a payload cannot coarsen the bootstrap).
    """
    yp = np.asarray(y_pred, dtype=float)
    yt = np.asarray(y_true, dtype=float)
    fids = np.asarray(fold_ids)
    S = len(yt)
    base = {
        "metric": "fold_mean_r",
        "method": "fold_respecting_bootstrap_ci",
        "multiplicity_axis": "effect_magnitude",
        "provenance": "commissioned",
        "commissioner_version": version,
        "n_subjects": int(S),
    }
    if len(yp) != S or len(fids) != S:
        return {**base, "status": "unresolved_degenerate", "scorer_payload_inject": {}}
    uniq = list(np.unique(fids))
    fold_index = [np.where(fids == f)[0] for f in uniq]
    point_r = _fold_mean_r(yp, yt, fold_index)
    if not math.isfinite(point_r):
        return {**base, "status": "unresolved_degenerate", "scorer_payload_inject": {}}

    rng = np.random.default_rng(seed)
    N = int(n_boot)
    boots = np.empty(N, dtype=float)
    n_ok = 0
    for _ in range(N):
        rs = []
        for idx in fold_index:
            if idx.size < 2:
                continue
            pick = rng.integers(0, idx.size, size=idx.size)  # resample WITHIN the fold
            sub = idx[pick]
            r = _pearson(yp[sub], yt[sub])
            if math.isfinite(r):
                rs.append(r)
        if rs:
            boots[n_ok] = float(np.mean(rs))
            n_ok += 1
    if n_ok < max(10, N // 2):
        return {**base, "observed_fold_mean_r": float(point_r),
                "status": "unresolved_too_few_bootstraps", "scorer_payload_inject": {}}
    boots = boots[:n_ok]
    ci_low = float(np.quantile(boots, alpha / 2))
    ci_high = float(np.quantile(boots, 1 - alpha / 2))

    probe = {
        **base,
        "observed_fold_mean_r": float(point_r),
        "effect_size_ci_low": ci_low,
        "effect_size_ci_high": ci_high,
        "n_boot": int(n_ok),
        "ci_alpha": float(alpha),
        "scope_note": (
            "fold-respecting percentile bootstrap CI of the fold-mean signed Pearson r; the "
            "gate flags reliably-positive-but-reliably-trivial effects (the big-N vanishing-"
            "effect regime). Magnitude only — does NOT assert chance-level (permutation_null) "
            "or robustness."
        ),
        "status": "ok",
        "scorer_payload_inject": {
            "effect_size_ci_low": ci_low,
            "effect_size_ci_high": ci_high,
        },
        "inputs_fingerprint": fingerprint(
            {
                "y_pred": [float(x) for x in yp.tolist()],
                "y_true": [float(x) for x in yt.tolist()],
                "fold_ids": [int(x) for x in fids.tolist()],
            }
        ),
    }
    return probe


def compute_fold_dispersion_probe(
    y_pred: list[float] | np.ndarray,
    y_true: list[float] | np.ndarray,
    fold_ids: list[int] | np.ndarray,
    *,
    version: str = "resid-probe-v1",
) -> dict[str, Any]:
    """Deterministic FOLD-DISPERSION probe (best-fold cherry-pick / non-robust headline).

    The headline fold-mean r can be carried by a single lucky CV fold while the rest are
    near-zero — a non-robust effect that an analyst could report by spotlighting the fold that
    worked. Over the headline OOS arrays this computes the per-fold signed Pearson r and asks
    how much of the all-fold mean survives DROPPING THE SINGLE BEST FOLD:

      * ``all_fold_mean_r``       = mean of per-fold r over all folds (the headline);
      * ``leave_best_fold_out_r`` = mean of per-fold r after removing the largest-r fold;
      * ``fold_dispersion_retained_pct`` = 100 * leave_best_fold_out_r / all_fold_mean_r.
    The gate fires (-> qualified) when retained_pct is low: the effect collapses without its
    best fold, so the headline is best-fold-driven rather than robust across the sample.

    For a robust effect (similar r every fold) dropping the best leaves the mean ~unchanged
    (retained ~100%); for a one-fold-driven effect it collapses (low / negative retained).
    ANSWER-PROOF: no dispersion/retained/r input; recomputed from the arrays. K<3 folds ->
    abstain (dropping 1 of 2 is not a meaningful robustness perturbation).
    """
    yp = np.asarray(y_pred, dtype=float)
    yt = np.asarray(y_true, dtype=float)
    fids = np.asarray(fold_ids)
    S = len(yt)
    base = {
        "metric": "fold_mean_r",
        "method": "leave_best_fold_out",
        "multiplicity_axis": "fold_dispersion",
        "provenance": "commissioned",
        "commissioner_version": version,
        "n_subjects": int(S),
    }
    if len(yp) != S or len(fids) != S:
        return {**base, "status": "unresolved_degenerate", "scorer_payload_inject": {}}
    uniq = list(np.unique(fids))
    per_fold = []
    for f in uniq:
        idx = np.where(fids == f)[0]
        r = _pearson(yp[idx], yt[idx])
        if math.isfinite(r):
            per_fold.append(r)
    if len(per_fold) < 3:
        # need >=3 finite folds: dropping 1 of <=2 is not a meaningful robustness check
        return {**base, "status": "unresolved_too_few_folds", "scorer_payload_inject": {}}
    per_fold_arr = np.asarray(per_fold, dtype=float)
    all_mean = float(np.mean(per_fold_arr))
    best_i = int(np.argmax(per_fold_arr))
    lbo_mean = float(np.mean(np.delete(per_fold_arr, best_i)))

    status = "ok"
    if all_mean < NEAR_ZERO_R_FLOOR:
        status = "unresolved_near_zero_effect"  # need a positive headline to attribute to a fold
    retained_pct = 100.0 * lbo_mean / all_mean if all_mean > 0 else float("nan")

    probe = {
        **base,
        "all_fold_mean_r": all_mean,
        "leave_best_fold_out_r": lbo_mean,
        "best_fold_r": float(per_fold_arr[best_i]),
        "n_folds": len(per_fold),
        "fold_dispersion_retained_pct": (None if not math.isfinite(retained_pct) else float(retained_pct)),
        "scope_note": (
            "leave-single-best-fold-out retention of the fold-mean r; flags effects carried by "
            "one CV fold (non-robust / best-fold cherry-pick). Within-claim fold robustness — "
            "not chance-level (permutation_null), magnitude (effect_size_floor), or selection."
        ),
        "status": status,
        "scorer_payload_inject": (
            {"fold_dispersion_retained_pct": float(retained_pct)}
            if status == "ok" and math.isfinite(retained_pct)
            else {}
        ),
        "inputs_fingerprint": fingerprint(
            {
                "y_pred": [float(x) for x in yp.tolist()],
                "y_true": [float(x) for x in yt.tolist()],
                "fold_ids": [int(x) for x in fids.tolist()],
            }
        ),
    }
    return probe


def build_probe_inputs(
    y_pred: list[float] | np.ndarray,
    y_true: list[float] | np.ndarray,
    *,
    fold_ids: list[int] | np.ndarray | None = None,
    confounds: dict[str, list[float] | np.ndarray] | None = None,
    confound_design: str = "per_column",
    candidate_preds: dict[str, list[float] | np.ndarray] | None = None,
    headline_candidate: str | None = None,
    candidate_targets: dict[str, list[float] | np.ndarray] | None = None,
    refit_null_stats: dict[str, list[float] | np.ndarray] | None = None,
    target_name: str | None = None,
    subject_ids: list[str] | None = None,
    meta: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the canonical ``probe_inputs`` block a scorer writes into
    ``scorer_payload['probe_inputs']`` — the ONE supported, misuse-proof way to emit the
    raw-array channel the society's probe commissioner reads.

    It (a) coerces arrays to plain JSON lists, (b) validates that every per-subject column
    is length-S, and (c) REFUSES to emit any answer key (``retained_pct`` / a p-value /
    etc.) — both as a top-level field and as a confound name — so a producer cannot
    accidentally OR deliberately hand-feed the verdict. The result round-trips through
    ``ProbeInputsV1`` (extra='forbid') before being returned.

    A real predictor's scorer calls this once with its out-of-sample predictions, the
    target, the CV fold ids, and any candidate confound columns; the society then COMPUTES
    retained_pct / the permutation-null p itself.
    """
    yp = [float(x) for x in np.asarray(y_pred, dtype=float).ravel()]
    yt = [float(x) for x in np.asarray(y_true, dtype=float).ravel()]
    S = len(yt)
    if len(yp) != S:
        raise ValueError(f"y_pred ({len(yp)}) and y_true ({S}) must be the same length")
    if S == 0:
        raise ValueError("probe_inputs needs at least one subject")

    out: dict[str, Any] = {"y_pred": yp, "y_true": yt}
    if fold_ids is not None:
        fids = [int(x) for x in np.asarray(fold_ids).ravel()]
        if len(fids) != S:
            raise ValueError(f"fold_ids ({len(fids)}) must be length S={S}")
        out["fold_ids"] = fids
    if confounds:
        conf: dict[str, list[float]] = {}
        for name, col in confounds.items():
            if name in _BANNED_ANSWER_KEYS:
                raise ProbeLaunderingError(
                    f"confound name {name!r} collides with an answer key; rename it"
                )
            c = [float(x) for x in np.asarray(col, dtype=float).ravel()]
            if len(c) != S:
                raise ValueError(f"confound {name!r} ({len(c)}) must be length S={S}")
            conf[name] = c
        out["confounds"] = conf
        out["confound_design"] = confound_design
    if candidate_preds:
        cand: dict[str, list[float]] = {}
        for name, col in candidate_preds.items():
            if name in _BANNED_ANSWER_KEYS:
                raise ProbeLaunderingError(
                    f"candidate name {name!r} collides with an answer key; rename it"
                )
            c = [float(x) for x in np.asarray(col, dtype=float).ravel()]
            if len(c) != S:
                raise ValueError(f"candidate {name!r} ({len(c)}) must be length S={S}")
            cand[name] = c
        out["candidate_preds"] = cand
        if headline_candidate is not None:
            out["headline_candidate"] = headline_candidate
        if candidate_targets:
            # TARGET-FAMILY mode: K different targets paired by key to candidate_preds.
            if set(candidate_targets) != set(cand):
                raise ValueError("candidate_targets keys must match candidate_preds keys")
            ctargs: dict[str, list[float]] = {}
            for name, col in candidate_targets.items():
                if name in _BANNED_ANSWER_KEYS:
                    raise ProbeLaunderingError(
                        f"candidate target name {name!r} collides with an answer key; rename it"
                    )
                c = [float(x) for x in np.asarray(col, dtype=float).ravel()]
                if len(c) != S:
                    raise ValueError(f"candidate target {name!r} ({len(c)}) must be length S={S}")
                ctargs[name] = c
            out["candidate_targets"] = ctargs
            if headline_candidate is None:
                raise ValueError("target-family mode requires headline_candidate")
        if refit_null_stats:
            # REFIT-NULL channel: per-candidate refit statistic draws (N per candidate, aligned).
            if not candidate_targets:
                raise ValueError("refit_null_stats requires candidate_targets (to compute observed)")
            if headline_candidate is None:
                raise ValueError("refit_null_stats requires headline_candidate")
            if set(refit_null_stats) != set(cand):
                raise ValueError("refit_null_stats keys must equal candidate_preds keys (full family)")
            rns: dict[str, list[float]] = {}
            ns: set[int] = set()
            for name, col in refit_null_stats.items():
                if name in _BANNED_ANSWER_KEYS:
                    raise ProbeLaunderingError(
                        f"refit_null_stats column {name!r} collides with an answer key; rename it"
                    )
                d = [float(x) for x in np.asarray(col, dtype=float).ravel()]
                ns.add(len(d))
                rns[name] = d
            if len(ns) != 1:
                raise ValueError(f"refit_null_stats columns must share one length N; got {sorted(ns)}")
            out["refit_null_stats"] = rns
    elif candidate_targets or refit_null_stats:
        raise ValueError("candidate_targets / refit_null_stats given without candidate_preds")
    if target_name is not None:
        out["target_name"] = target_name
    if subject_ids is not None:
        out["subject_ids"] = [str(s) for s in subject_ids]
    if meta is not None:
        out["meta"] = {str(k): str(v) for k, v in meta.items()}

    # honesty guard: the emitted block must carry NO answer key, ever.
    banned = set(out) & _BANNED_ANSWER_KEYS
    if banned:
        raise ProbeLaunderingError(f"probe_inputs must not carry answer key(s): {sorted(banned)}")
    # validate the canonical shape (extra='forbid' rejects stray keys too).
    ProbeInputsV1(**out)
    return out


def has_probe_inputs(payload: dict[str, Any] | None) -> bool:
    """True iff the payload carries a probe-input channel the commissioner can read."""
    if not payload:
        return False
    return bool(payload.get("probe_inputs") or payload.get("probe_inputs_path"))


# ---------------------------------------------------------------------------
# Tamper-EVIDENCE: plausibility scan over the raw arrays + provenance attestation
# ---------------------------------------------------------------------------

INTEGRITY_VERSION = "probe-integrity-v1"
INTEGRITY_MIN_STD_REL: float = 1e-6      # std/(|mean|+1) below this => (near-)constant
INTEGRITY_PERFECT_FIT_R: float = 0.999   # |r(y_pred,y_true)| above this => implausible
INTEGRITY_DUP_ROW_FRAC: float = 0.50     # >50% non-unique rows => copy-paste padding
INTEGRITY_MIN_UNIQUE_FRAC: float = 0.02  # continuous predictor with <2% unique values
INTEGRITY_MAX_NONFINITE_FRAC: float = 0.20
INTEGRITY_MAX_FOLD_IMBALANCE: float = 20.0
INTEGRITY_ABS_Z_OUTLIER: float = 12.0

_DISCRETE_TASKS = frozenset(
    {"classification", "binary", "multiclass", "discrete", "categorical"}
)


def _canonical_arrays_fingerprint(inputs: ProbeInputsV1) -> str:
    """Stable sha256 over the core raw arrays (same canonical-JSON convention as
    cards.fingerprint) — the attestation cross-check anchor."""
    return fingerprint(
        {
            "y_pred": [float(x) for x in inputs.y_pred],
            "y_true": [float(x) for x in inputs.y_true],
            "fold_ids": None if inputs.fold_ids is None else [int(x) for x in inputs.fold_ids],
            "confounds": {
                k: [float(x) for x in v] for k, v in sorted(inputs.confounds.items())
            },
        }
    )


def assess_probe_integrity(inputs: ProbeInputsV1) -> dict[str, Any]:
    """Plausibility / tamper-EVIDENCE scan over the RAW arrays.

    This RAISES THE BAR against fabricated arrays; it is NOT tamper-PROOF. A forger who
    synthesises realistic arrays (plausible moments, a noisy y_pred~y_true relationship,
    balanced folds) passes every check. What it catches is LAZY/DEGENERATE fabrication: a
    constant predictor, y_pred copied from y_true, padded duplicate rows, an implausibly
    perfect fit, a non-finite flood, or a fold structure no real CV split produces. The
    verdict is RECORDED and surfaced on the claim card; it does NOT by itself flip the gate
    (plausibility != truth) unless the conductor is run with integrity_caps_certification.
    """
    yp = np.asarray(inputs.y_pred, dtype=float)
    yt = np.asarray(inputs.y_true, dtype=float)
    S = len(yt)
    flags: list[str] = []
    metrics: dict[str, Any] = {"n_subjects": int(S)}
    # classification/discrete tasks legitimately have low-cardinality, duplicated rows.
    discrete = str((inputs.meta or {}).get("task_type", "")).lower() in _DISCRETE_TASKS

    def _rel_std(a: np.ndarray) -> float:
        m = float(np.nanmean(a)) if a.size else 0.0
        return float(np.nanstd(a) / (abs(m) + 1.0)) if a.size else 0.0

    metrics["y_pred_rel_std"] = _rel_std(yp)
    metrics["y_true_rel_std"] = _rel_std(yt)
    if metrics["y_pred_rel_std"] < INTEGRITY_MIN_STD_REL:
        flags.append("constant_y_pred")
    if metrics["y_true_rel_std"] < INTEGRITY_MIN_STD_REL:
        flags.append("constant_y_true")
    if S and np.array_equal(yp, yt):
        flags.append("prediction_equals_target")

    finite = np.isfinite(yp) & np.isfinite(yt)
    metrics["nonfinite_frac"] = float(1.0 - (finite.mean() if S else 1.0))
    if metrics["nonfinite_frac"] > INTEGRITY_MAX_NONFINITE_FRAC:
        flags.append("excess_nonfinite")
    if finite.sum() >= 2 and np.std(yp[finite]) > 1e-12 and np.std(yt[finite]) > 1e-12:
        r = abs(float(np.corrcoef(yp[finite], yt[finite])[0, 1]))
        metrics["abs_r"] = r
        if r > INTEGRITY_PERFECT_FIT_R:
            flags.append("implausibly_perfect_fit")

    # duplicated rows — NOTE: rows containing NaN count as DISTINCT under np.unique, so a
    # non-finite flood will not also trip duplicated_rows (the two flags stay independent).
    if S:
        rows = np.column_stack([yp, yt])
        dup_frac = 1.0 - len(np.unique(rows, axis=0)) / S
        metrics["dup_row_frac"] = float(dup_frac)
        uniq_frac = (len(np.unique(yp[np.isfinite(yp)])) / S) if S else 0.0
        metrics["y_pred_unique_frac"] = float(uniq_frac)
        if not discrete and dup_frac > INTEGRITY_DUP_ROW_FRAC:
            flags.append("duplicated_rows")
        if not discrete and uniq_frac < INTEGRITY_MIN_UNIQUE_FRAC:
            flags.append("low_cardinality_y_pred")

    if metrics["y_pred_rel_std"] > 0 and finite.any():
        sd = np.std(yp[finite])
        if sd > 1e-12:
            zmax = float(np.max(np.abs((yp[finite] - np.mean(yp[finite])) / sd)))
            metrics["max_abs_z"] = zmax
            if zmax > INTEGRITY_ABS_Z_OUTLIER:
                flags.append("extreme_outlier")

    if inputs.fold_ids is not None and inputs.fold_ids:
        from collections import Counter

        counts = list(Counter(inputs.fold_ids).values())
        metrics["n_folds"] = len(counts)
        if len(counts) == 1:
            flags.append("single_fold")
        elif min(counts) and max(counts) / min(counts) > INTEGRITY_MAX_FOLD_IMBALANCE:
            flags.append("fold_imbalance")

    return {
        "verdict": "suspicious" if flags else "clean",
        "flags": flags,
        "metrics": metrics,
        "version": INTEGRITY_VERSION,
    }


class ProbeCommissioner:
    """Computes confound-residualization probes from raw arrays in the scorer payload.

    Default-constructed and passed to ``SocietyConductor(probe_commissioner=...)``. When
    the confound gate would otherwise read a (possibly hand-fed) scalar, the conductor
    asks this commissioner to recompute from raw arrays; the computed probe is injected so
    the gate fires on the genuine number.
    """

    def __init__(
        self,
        *,
        version: str = COMMISSIONER_VERSION,
        fit_scope: str = "leakage_free",
        min_subjects: int = MIN_SUBJECTS,
        cross_check_tol_pct: float = CROSS_CHECK_TOL_PCT,
        n_permutations: int = DEFAULT_N_PERMUTATIONS,
        perm_seed: int = 0,
        strict: bool = False,
    ) -> None:
        self._version = version
        self._fit_scope = fit_scope
        self._min_subjects = min_subjects
        self._cross_tol = cross_check_tol_pct
        # N / seed for the permutation null are COMMISSIONER-owned (never payload-readable)
        # so a payload cannot coarsen the null to launder a verdict. N is floored.
        self._n_permutations = max(int(n_permutations), MIN_PERMUTATIONS)
        self._perm_seed = int(perm_seed)
        self._strict = strict

    def commission(
        self,
        strategy: str,
        results: dict[str, Any],
        *,
        scorer_payload_path: str | None = None,
    ) -> list[dict[str, Any]] | None:
        if strategy not in (
            "confound", "permutation_null", "correction_fragile",
            "selection_leakage", "effect_size_floor", "fold_dispersion",
        ):
            return None
        payload = results.get("scorer_payload") or {}
        raw = self._locate_raw(payload, scorer_payload_path)
        if raw is None:
            return None

        offending = sorted(k for k in raw if k in _BANNED_ANSWER_KEYS)
        inputs_tainted = bool(offending)
        if inputs_tainted:
            logger.warning(
                "probe_commissioner: probe_inputs carried banned answer key(s) %s; "
                "ignoring them and computing the probe from raw arrays",
                offending,
            )
            if self._strict:
                raise ProbeLaunderingError(f"probe_inputs carried answer key(s): {offending}")
        clean = {k: v for k, v in raw.items() if k not in _BANNED_ANSWER_KEYS}

        try:
            inputs = ProbeInputsV1(**clean)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("probe_commissioner: invalid probe_inputs: %s", exc)
            return None

        S = len(inputs.y_true)
        if S < self._min_subjects:
            return None
        if len(inputs.y_pred) != S:
            return None
        if inputs.fold_ids is not None and len(inputs.fold_ids) != S:
            return None

        if strategy == "confound":
            probes = self._commission_confound(payload, inputs, offending, inputs_tainted)
        elif strategy == "permutation_null":
            probes = self._commission_permutation_null(payload, inputs, offending, inputs_tainted)
        elif strategy == "selection_leakage":
            probes = self._commission_selection_leakage(payload, inputs, offending, inputs_tainted)
        elif strategy == "effect_size_floor":
            probes = self._commission_effect_size_floor(payload, inputs, offending, inputs_tainted)
        elif strategy == "fold_dispersion":
            probes = self._commission_fold_dispersion(payload, inputs, offending, inputs_tainted)
        else:
            probes = self._commission_correction_fragile(payload, inputs, offending, inputs_tainted)
        if not probes:
            return probes
        # Tamper-EVIDENCE: stamp a plausibility verdict + provenance attestation on every
        # commissioned probe. Recorded for the claim card; raises the bar against lazy
        # fabrication but is NOT tamper-proof (a realistic forgery passes).
        integrity = assess_probe_integrity(inputs)
        attestation = {
            "array_fingerprint": _canonical_arrays_fingerprint(inputs),
            "n_subjects": len(inputs.y_true),
            "meta": dict(inputs.meta or {}),
        }
        for pr in probes:
            pr["integrity"] = integrity["verdict"]
            pr["integrity_flags"] = integrity["flags"]
            pr["integrity_metrics"] = integrity["metrics"]
            pr["provenance_attestation"] = attestation
        return probes

    # ----- per-strategy commissioners ---------------------------------------
    def _commission_confound(
        self,
        payload: dict[str, Any],
        inputs: ProbeInputsV1,
        offending: list[str],
        inputs_tainted: bool,
    ) -> list[dict[str, Any]] | None:
        if not inputs.confounds:
            return None
        S = len(inputs.y_true)
        for name, col in inputs.confounds.items():
            if len(col) != S:
                logger.warning("probe_commissioner: confound %s wrong length; skipping all", name)
                return None

        supplied = self._supplied_retained(payload)
        probes: list[dict[str, Any]] = []
        for confound_name, design in self._designs(inputs):
            try:
                probe = compute_residualization_probe(
                    inputs.y_pred,
                    inputs.y_true,
                    design,
                    confound_name=confound_name,
                    fold_ids=inputs.fold_ids,
                    fit_scope=self._fit_scope,
                    version=self._version,
                )
            except ValueError as exc:
                logger.warning("probe_commissioner: compute failed for %s: %s", confound_name, exc)
                continue
            if inputs_tainted:
                probe["inputs_tainted"] = True
                probe["tainted_keys"] = offending
            if (
                supplied is not None
                and probe["retained_pct"] is not None
                and abs(supplied - probe["retained_pct"]) > self._cross_tol
            ):
                probe["provenance"] = "supplied_inconsistent"
                probe["supplied_retained_pct"] = supplied
            probes.append(probe)
        return probes or None

    def _commission_permutation_null(
        self,
        payload: dict[str, Any],
        inputs: ProbeInputsV1,
        offending: list[str],
        inputs_tainted: bool,
    ) -> list[dict[str, Any]] | None:
        # fold_ids is MANDATORY (the statistic is fold-mean r, not pooled r).
        if inputs.fold_ids is None:
            logger.warning("probe_commissioner: permutation_null needs fold_ids; abstaining")
            return None
        try:
            probe = compute_permutation_null_probe(
                inputs.y_pred,
                inputs.y_true,
                inputs.fold_ids,
                n_permutations=self._n_permutations,
                seed=self._perm_seed,
                version=self._version,
            )
        except ValueError as exc:
            logger.warning("probe_commissioner: permutation_null compute failed: %s", exc)
            return None
        if inputs_tainted:
            probe["inputs_tainted"] = True
            probe["tainted_keys"] = offending
        # VERDICT-level cross-check: a supplied p and the computed p are only "inconsistent"
        # if they land on OPPOSITE sides of alpha (the gate decision differs). A legitimate
        # method that differs in the 3rd decimal but agrees on the verdict is NOT flagged.
        supplied = self._supplied_headline_p(payload)
        if supplied is not None:
            computed = probe["family_block_p"]
            if (supplied > PERMUTATION_NULL_ALPHA) != (computed > PERMUTATION_NULL_ALPHA):
                probe["provenance"] = "supplied_inconsistent"
                probe["supplied_family_block_p"] = supplied
        return [probe]

    def _commission_selection_leakage(
        self,
        payload: dict[str, Any],
        inputs: ProbeInputsV1,
        offending: list[str] | None = None,
        inputs_tainted: bool = False,
    ) -> list[dict[str, Any]] | None:
        # SAME-TARGET model-selection family only: K candidate predictors of inputs.y_true.
        # candidate_targets present => a different-target (component) family, where selecting
        # an argmax across targets is meaningless => abstain. fold_ids mandatory (nested
        # leave-fold-out selection needs folds).
        cand = inputs.candidate_preds or {}
        if len(cand) < 2 or inputs.candidate_targets:
            return None
        if inputs.fold_ids is None:
            logger.warning("probe_commissioner: selection_leakage needs fold_ids; abstaining")
            return None
        for name, col in cand.items():
            if len(col) != len(inputs.y_true):
                logger.warning("probe_commissioner: candidate %s wrong length; abstaining", name)
                return None
        try:
            probe = compute_selection_leakage_probe(
                cand,
                inputs.y_true,
                fold_ids=inputs.fold_ids,
                headline_candidate=inputs.headline_candidate,
                version=self._version,
            )
        except ValueError as exc:
            logger.warning("probe_commissioner: selection_leakage compute failed: %s", exc)
            return None
        return [probe]

    def _commission_effect_size_floor(
        self,
        payload: dict[str, Any],
        inputs: ProbeInputsV1,
        offending: list[str] | None = None,
        inputs_tainted: bool = False,
    ) -> list[dict[str, Any]] | None:
        # Single-headline magnitude probe: needs only y_pred/y_true + fold_ids (mandatory — the
        # statistic is fold-mean r and the bootstrap resamples within folds).
        if inputs.fold_ids is None:
            logger.warning("probe_commissioner: effect_size_floor needs fold_ids; abstaining")
            return None
        try:
            probe = compute_effect_size_floor_probe(
                inputs.y_pred,
                inputs.y_true,
                inputs.fold_ids,
                n_boot=self._n_permutations,  # commissioner-owned resample count (floored)
                seed=self._perm_seed,
                version=self._version,
            )
        except ValueError as exc:
            logger.warning("probe_commissioner: effect_size_floor compute failed: %s", exc)
            return None
        return [probe]

    def _commission_fold_dispersion(
        self,
        payload: dict[str, Any],
        inputs: ProbeInputsV1,
        offending: list[str] | None = None,
        inputs_tainted: bool = False,
    ) -> list[dict[str, Any]] | None:
        # Single-headline within-claim robustness probe: needs y_pred/y_true + fold_ids
        # (mandatory — the statistic is per-fold r and the perturbation is leave-best-fold-out).
        if inputs.fold_ids is None:
            logger.warning("probe_commissioner: fold_dispersion needs fold_ids; abstaining")
            return None
        try:
            probe = compute_fold_dispersion_probe(
                inputs.y_pred,
                inputs.y_true,
                inputs.fold_ids,
                version=self._version,
            )
        except ValueError as exc:
            logger.warning("probe_commissioner: fold_dispersion compute failed: %s", exc)
            return None
        return [probe]

    def _commission_correction_fragile(
        self,
        payload: dict[str, Any],
        inputs: ProbeInputsV1,
        offending: list[str] | None = None,
        inputs_tainted: bool = False,
    ) -> list[dict[str, Any]] | None:
        # Needs the full candidate set (>=2 OOS prediction columns). Dispatch precedence:
        # refit_null_stats (oracle-power) > candidate_targets (frozen lower bound) > same-target.
        offending = offending or []
        cand = inputs.candidate_preds or {}
        if len(cand) < 2:
            return None
        for name, col in cand.items():
            if len(col) != len(inputs.y_true):
                logger.warning("probe_commissioner: candidate %s wrong length; abstaining", name)
                return None
        ctargs = inputs.candidate_targets or {}
        rns = inputs.refit_null_stats or {}
        try:
            if rns:
                # REFIT-NULL channel (highest precedence, oracle-power). A present-but-invalid
                # top tier HARD-ABSTAINS — it must never silently DOWNGRADE to the frozen tier
                # (that would judge the claim on a different statistic than the producer intended).
                if not inputs.headline_candidate or not ctargs:
                    logger.warning(
                        "probe_commissioner: refit-null channel needs headline + candidate_targets; "
                        "abstaining"
                    )
                    return None
                probe = compute_refit_null_correction_probe(
                    cand,
                    ctargs,
                    rns,
                    headline=inputs.headline_candidate,
                    fold_ids=inputs.fold_ids,
                    version=self._version,
                )
                if inputs_tainted:
                    probe["inputs_tainted"] = True
                    probe["tainted_keys"] = offending
                return [probe]
            if ctargs:
                # TARGET-FAMILY: K different targets; headline fixed by the claim (required).
                if not inputs.headline_candidate:
                    logger.warning(
                        "probe_commissioner: target-family correction needs headline_candidate; "
                        "abstaining"
                    )
                    return None
                probe = compute_target_family_correction_probe(
                    cand,
                    ctargs,
                    headline=inputs.headline_candidate,
                    fold_ids=inputs.fold_ids,
                    n_permutations=self._n_permutations,
                    seed=self._perm_seed,
                    version=self._version,
                )
            else:
                # SAME-TARGET / model-selection family: headline forced to argmax|r|.
                probe = compute_correction_fragility_probe(
                    cand,
                    inputs.y_true,
                    fold_ids=inputs.fold_ids,
                    headline_candidate=inputs.headline_candidate,
                    n_permutations=self._n_permutations,
                    seed=self._perm_seed,
                    version=self._version,
                )
        except ValueError as exc:
            logger.warning("probe_commissioner: correction_fragile compute failed: %s", exc)
            return None
        return [probe]

    # ----- helpers ----------------------------------------------------------
    def _designs(self, inputs: ProbeInputsV1) -> list[tuple[str, np.ndarray]]:
        """Yield (name, design_matrix) pairs to test."""
        conf = inputs.confounds
        if inputs.confound_to_test and inputs.confound_to_test in conf:
            return [(inputs.confound_to_test, np.asarray(conf[inputs.confound_to_test], float).reshape(-1, 1))]
        if inputs.confound_design == "joint_matrix":
            names = list(conf)
            design = np.column_stack([np.asarray(conf[n], float) for n in names])
            label = "joint(" + ",".join(names) + ")"
            return [(label, design)]
        return [
            (name, np.asarray(col, float).reshape(-1, 1)) for name, col in conf.items()
        ]

    def _supplied_headline_p(self, payload: dict[str, Any]) -> float | None:
        """The hand-fed headline null p (first present of the _NULL_P_KEYS order), if any,
        captured BEFORE the conductor overwrites it with the computed value."""
        for key in ("family_block_p", "permutation_p", "max_T_p", "post_selection_p"):
            val = payload.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return None
        return None

    def _supplied_retained(self, payload: dict[str, Any]) -> float | None:
        """The smallest supplied retained_pct, if the experimenter pre-filled one."""
        vals: list[float] = []
        for p in payload.get("robustness_probes") or []:
            if isinstance(p, dict) and p.get("retained_pct") is not None and p.get("provenance") != "commissioned":
                try:
                    vals.append(float(p["retained_pct"]))
                except (TypeError, ValueError):
                    pass
        return min(vals) if vals else None

    def _locate_raw(
        self, payload: dict[str, Any], scorer_payload_path: str | None
    ) -> dict[str, Any] | None:
        """Find the raw probe-input blob: inline, else a path-guarded side .json."""
        inline = payload.get("probe_inputs")
        if isinstance(inline, dict):
            return inline
        rel = payload.get("probe_inputs_path")
        if not rel or not scorer_payload_path:
            return None
        root = Path(scorer_payload_path).resolve().parent
        target = (root / rel).resolve()
        # path-traversal guard (artifacts.py idiom)
        if not (str(target) == str(root) or str(target).startswith(str(root) + "/")):
            logger.warning("probe_commissioner: probe_inputs_path escapes payload dir; refusing")
            return None
        if not target.exists() or target.suffix != ".json":
            return None
        try:
            import json

            blob = json.loads(target.read_text(encoding="utf-8"))
            return blob if isinstance(blob, dict) else None
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("probe_commissioner: could not read %s: %s", target, exc)
            return None
