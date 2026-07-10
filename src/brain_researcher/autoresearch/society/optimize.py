"""NeuroProgram design-family OPTIMIZER (objective-safe).

Searches the PRE-REGISTERED design space to pick the best design FAMILY (a set of multiverse
variants) on properties that are INDEPENDENT of the observed effect magnitude, COMMITS to it
(fingerprint-lock), so the family can then be run and reported as a whole. It chooses *which
experiments to run*, never *which result to keep*.

OBJECTIVE-SAFETY (the whole point — every guard below was forced by adversarial review):

* The fitness reads only the DESIGN: decision points, the contrast vector, and event TIMING
  (the stimulus protocol, not data). It NEVER reads confounds.tsv VALUES (BOLD-derived) or any
  z-map/beta. ``score_design_family`` has no results/confounds-value parameter, and contrast
  efficiency is computed from a SYNTHETIC, orthonormalised confound block sized only by the
  per-variant regressor COUNT — so two different ``confounds.tsv`` files give byte-identical
  scores (the load-bearing CI invariant, ``test_optimize``).
* ``mean_efficiency`` is used only as a FLOOR (a poorly-estimable design is ineligible), never
  maximised — a high mean efficiency is a detection-power proxy for the pre-chosen contrast, so
  maximising it would be a back door to result-favourable selection. The maximised robustness
  signal is ``efficiency_stability`` (concordance ACROSS variants).
* Coverage is entropy over the FULL axis space (not the prior-restricted axes), with a hard
  ``k>=2`` and a per-axis spread floor, so a near-delta prior cannot silently collapse the
  multiverse to a single favourable pipeline. A degenerate prior forces ``exploratory`` mode
  unless a pre-data ``prior_provenance`` attestation is supplied.
* The commitment fingerprint covers the CHOSEN family (variant-id set + k + seed + K + objective
  weights), not just the priors, so the lock pins *what was selected*. ``resolve_committed_family``
  fails closed: if the executed family != the committed family, the robustness binding is capped.
* The optimiser output is still bounded by ``compose_ceilings`` (min-law) — optimisation buys
  better experiments, never a stronger claim than the evidence warrants.

Service-free + import-light: nilearn / the review rule engine are reached only through INJECTED
callables (``efficiency_fn`` / ``constraint_fn``); the default factories lazy-import them.

TRUSTED-CALLABLE BOUNDARY (objective-safety caveat): ``score_design_family`` /
``optimize_design_family`` accept caller-supplied ``efficiency_fn`` / ``constraint_fn``. The
objective-safety guarantee holds for the SHIPPED factories (``make_efficiency_fn``,
``make_count_efficiency_fn``, ``make_constraint_fn``) — which provably never read a result,
z-map, or confounds value — and the ``neuroprogram_optimize_design`` MCP tool uses only those.
A caller that injects a *custom* fitness reading observed effects could violate the invariant;
the injection seam is a PRIVILEGED interface (for tests / vetted extensions), not the
agent-facing surface. Do not expose raw ``efficiency_fn`` injection to untrusted callers.
"""

from __future__ import annotations

import math
import random
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from .cards import ClaimStatusV1, fingerprint
from .multiverse import CeilingResult
from .neuroprogram import NeuroObjectiveV1, NeuroProgramV1

# Full axis space for the coverage floor — MUST mirror spec_family._DEFAULT_AXES and NOT the
# prior-restricted axes (else a near-delta prior makes a 1-level family look 'fully covered').
_FULL_AXES: dict[str, list[str]] = {
    "hrf_basis": ["canonical", "derivs", "glover", "fir"],
    "confounds": ["6mot", "24mot", "24mot_physio", "24mot_pupil", "24mot_physio_pupil"],
    "high_pass": ["128", "256"],
}
_COVERAGE_AXES: tuple[str, ...] = ("hrf_basis", "confounds", "high_pass")

#: Floors (conventions, pending calibration — like the multiverse _MV_* thresholds).
MIN_VARIANTS = 2  # a multiverse of 1 is not a multiverse
MIN_AXES_VARIED = 2  # the family must genuinely vary on >= this many of the 3 axes
MIN_MEAN_EFFICIENCY = 1e-6  # a design with an unestimable contrast is ineligible

#: Deterministic regressor COUNT per confounds label — STRUCTURE only, never the values.
_CONFOUND_REGRESSOR_COUNT: dict[str, int] = {
    "6mot": 6, "24mot": 24, "24mot_physio": 32, "24mot_pupil": 25, "24mot_physio_pupil": 33,
}

#: How a NeuroObjectiveV1 maps to a (magnitude-free) score dimension. Note: NO mapping to
#: mean_efficiency or any magnitude quantity — only stability / coverage / constraints / cost.
_OBJECTIVE_DIMENSION: dict[NeuroObjectiveV1, str] = {
    NeuroObjectiveV1.maximize_robustness: "efficiency_stability",
    NeuroObjectiveV1.maximize_coverage: "coverage",
    NeuroObjectiveV1.maximize_reproducibility: "constraint_pass_frac",
    NeuroObjectiveV1.maximize_generalization: "coverage",
    NeuroObjectiveV1.minimize_compute_cost: "neg_cost",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DesignFamilyScore:
    """Magnitude-free fitness of one candidate design family (a set of variants)."""

    variant_ids: tuple[str, ...]
    seed: int
    coverage: float  # normalized entropy over the FULL axis space
    mean_efficiency: float  # FLOOR only — never maximized
    efficiency_stability: float  # the maximized robustness signal (across-variant concordance)
    constraint_pass_frac: float
    est_cost_units: float
    n_axes_varied: int
    disqualified_variants: tuple[str, ...] = ()
    eligible: bool = True
    ineligible_reason: str = ""
    #: the PASSING variants' decision points (aligned to variant_ids) — carried so a downstream
    #: runner can EXECUTE the committed family (the ids alone are content hashes).
    variants: tuple[dict, ...] = ()


class OptimizeResultV1(BaseModel):
    """The locked outcome of a design-family optimization (pre-registration, pre-observe)."""

    schema_version: Literal["neuroprogram-optimize-v1"] = "neuroprogram-optimize-v1"
    program_id: str
    winner_variant_ids: list[str]
    #: the chosen family's PASSING decision points (aligned to winner_variant_ids) — what a runner
    #: executes; the committed family is the SET of these, locked into the commitment fingerprint.
    winner_variants: list[dict[str, Any]] = Field(default_factory=list)
    winner_seed: int
    winner_scores: dict[str, Any]
    objectives: list[str]
    weights: dict[str, float]
    n_candidates: int
    n_eligible: int
    pareto_size: int
    #: forced to 'exploratory' when a degenerate prior lacks a pre-data provenance attestation,
    #: OR a declared constraint is unknown to the engine, OR no candidate met the eligibility floors.
    claim_mode: Literal["confirmatory", "exploratory"]
    prior_degenerate: bool
    #: which search strategy generated the candidates ('grid' | 'evolutionary').
    search: str = "grid"
    #: True iff at least one candidate family met the eligibility floors (k>=2, varies, estimable).
    winner_eligible: bool = True
    #: declared constraint ids the review engine does not know (fail-closed: forces exploratory).
    unknown_constraints: list[str] = Field(default_factory=list)
    #: fingerprint over the CHOSEN family (not just priors) — commit-before-observe.
    commitment_hash: str
    status_not_ground_truth: bool = True
    generated_at: str = Field(default_factory=_utc_now)


# ======================================================================================
# magnitude-free fitness
# ======================================================================================


def _axis_value(decision_points: dict, axis: str) -> str:
    return str(decision_points.get(axis, ""))


def _coverage_entropy(specs: Sequence[dict]) -> tuple[float, int]:
    """Normalized Shannon entropy of the family's decision values over the FULL axis space.

    Returns ``(coverage, n_axes_varied)``. The denominator is the full axis cardinality (not the
    realized/prior options), so collapsing an axis via a near-delta prior lowers coverage rather
    than hiding it.
    """
    total = 0.0
    n_axes = 0
    varied = 0
    for axis, full_options in _FULL_AXES.items():
        if axis not in _COVERAGE_AXES:
            continue
        n_axes += 1
        counts: dict[str, int] = {}
        for spec in specs:
            v = _axis_value(spec.get("decision_points", spec), axis)
            counts[v] = counts.get(v, 0) + 1
        distinct = len([v for v in counts if v])
        if distinct >= 2:
            varied += 1
        if not counts:
            continue
        n = sum(counts.values())
        ent = -sum((c / n) * math.log(c / n) for c in counts.values() if c)
        # normalize by log of the FULL axis size (max possible entropy on this axis), and CLAMP
        # to 1.0 so a prior that injects extra (out-of-catalog) levels cannot inflate coverage
        # past the anti-gaming ceiling.
        max_ent = math.log(max(len(full_options), 1)) or 1.0
        total += min(1.0, ent / max_ent)
    coverage = total / n_axes if n_axes else 0.0
    return coverage, varied


def score_design_family(
    specs: Sequence[dict],
    *,
    efficiency_fn: Callable[[dict], float],
    constraint_fn: Callable[[dict], bool],
    seed: int = 0,
) -> DesignFamilyScore:
    """Score one candidate family on magnitude-free design properties.

    ``efficiency_fn(decision_points) -> float`` is the per-variant contrast efficiency (computed
    from event timing + synthetic confound STRUCTURE; never confounds values or results).
    ``constraint_fn(decision_points) -> bool`` returns True iff that variant has a BLOCKING review
    finding (which DISQUALIFIES the variant — a hard cut, not a fractional penalty). Neither
    callable — and this function — takes any results/z-map/confounds-value argument.
    """
    # Partition into passing vs disqualified FIRST. A blocked variant is never run, so it must
    # NOT inflate coverage and must NOT be committed — coverage + variant_ids are over PASSING.
    passing_specs: list[dict] = []
    disqualified: list[str] = []
    seen: set[str] = set()
    for i, spec in enumerate(specs):
        dp = spec.get("decision_points", spec)
        vid = str(spec.get("variant_id", i))
        if constraint_fn(dp):  # blocking finding -> disqualify the variant (hard)
            disqualified.append(vid)
            continue
        if vid in seen:
            # De-duplicate: a committed multiverse is a SET of DISTINCT pipelines. Duplicate
            # variants must not inflate the count (vs MIN_VARIANTS), coverage, or
            # efficiency_stability — closes a coverage/robustness-gaming path a with-replacement
            # search (the GA) could otherwise exploit and the de-duplicating grid cannot.
            continue
        seen.add(vid)
        passing_specs.append(spec)

    variant_ids = tuple(str(s.get("variant_id", i)) for i, s in enumerate(passing_specs))
    coverage, n_varied = _coverage_entropy(passing_specs)
    effs = [float(efficiency_fn(s.get("decision_points", s))) for s in passing_specs]

    mean_eff = float(sum(effs) / len(effs)) if effs else 0.0
    if len(effs) >= 2 and mean_eff > 0:
        std = (sum((e - mean_eff) ** 2 for e in effs) / len(effs)) ** 0.5
        cv = std / mean_eff
        eff_stability = 1.0 / (1.0 + cv)
    else:
        eff_stability = 0.0
    n_pass = len(passing_specs)
    constraint_pass_frac = n_pass / len(specs) if specs else 0.0
    est_cost = float(n_pass)  # you only run the passing variants

    eligible = True
    reason = ""
    if n_pass < MIN_VARIANTS:  # the RUNNABLE family must have >= MIN_VARIANTS variants
        eligible, reason = False, f"passing variants {n_pass} < MIN_VARIANTS={MIN_VARIANTS}"
    elif n_varied < MIN_AXES_VARIED:
        eligible, reason = False, f"family varies on only {n_varied} axes (< {MIN_AXES_VARIED})"
    elif not effs or mean_eff < MIN_MEAN_EFFICIENCY:
        eligible, reason = False, "no estimable variant (mean_efficiency below floor)"

    return DesignFamilyScore(
        variant_ids=variant_ids, seed=seed, coverage=coverage, mean_efficiency=mean_eff,
        efficiency_stability=eff_stability, constraint_pass_frac=constraint_pass_frac,
        est_cost_units=est_cost, n_axes_varied=n_varied,
        disqualified_variants=tuple(disqualified), eligible=eligible, ineligible_reason=reason,
        variants=tuple(dict(s.get("decision_points", s)) for s in passing_specs),
    )


# ======================================================================================
# default injected callables (lazy service-tier; the optimizer core never imports these)
# ======================================================================================


def make_efficiency_fn(
    *,
    conditions: Sequence[str],
    resolved: Sequence[Any],
    tr: float,
    n_scans: int,
    events_df: Any,
) -> Callable[[dict], float]:
    """Build a magnitude-free efficiency_fn over the task's event timing (NO BOLD, NO confounds values).

    ``resolved`` are ``ContrastResolution`` objects (``.condition_list`` / ``.weights``). The
    returned fn computes, for a variant's decision points, the mean contrast efficiency
    ``1/(c (XtX)^-1 c^T)`` from a nilearn design matrix built from: event timing (shared across
    variants), the HRF basis (decision point), a cosine drift (from high_pass), and a SYNTHETIC
    orthonormalised confound block whose ONLY data-derived input is the per-variant regressor
    COUNT mapped from the confounds label. confounds.tsv values are never read.
    """
    hrf_map = {"canonical": "spm", "derivs": "spm + derivative", "glover": "glover", "fir": "fir"}

    def _eff(decision_points: dict) -> float:
        import numpy as np  # lazy
        from nilearn.glm.first_level import make_first_level_design_matrix  # lazy

        frame_times = np.arange(int(n_scans)) * float(tr)
        hp = decision_points.get("high_pass", 128)
        try:
            high_pass = 1.0 / float(hp)
        except (TypeError, ValueError, ZeroDivisionError):
            high_pass = 1.0 / 128.0
        n_conf = _CONFOUND_REGRESSOR_COUNT.get(str(decision_points.get("confounds", "6mot")), 6)
        # synthetic, orthonormalised confound STRUCTURE — DETERMINISTIC (seed = count only, never
        # a process-salted hash and never a data value), value-free, count-only.
        rng = np.random.default_rng(int(n_conf))
        add = rng.standard_normal((int(n_scans), int(n_conf)))
        q, _ = np.linalg.qr(add)  # orthonormal columns -> XtX reflects count+geometry, not values
        add_regs = q
        add_names = [f"conf{i:02d}" for i in range(add_regs.shape[1])]
        hrf_model = hrf_map.get(str(decision_points.get("hrf_basis", "canonical")), "spm")
        X = make_first_level_design_matrix(
            frame_times, events=events_df, hrf_model=hrf_model, drift_model="cosine",
            high_pass=high_pass, add_regs=add_regs, add_reg_names=add_names,
        )
        cols = list(X.columns)
        XtX_inv = np.linalg.pinv(X.values.T @ X.values)

        def _match_col(cond: str) -> str | None:
            # compiled contrasts use dotted design names ('trial_type.Finger'); nilearn's
            # make_first_level_design_matrix names categorical columns by the bare trial_type
            # VALUE ('Finger'). Align via exact -> bare-suffix -> compact-key (strip separators).
            if cond in cols:
                return cond
            bare = str(cond).split(".")[-1]
            if bare in cols:
                return bare
            key = re.sub(r"[._:\-]+", "", str(cond).lower())
            bkey = re.sub(r"[._:\-]+", "", bare.lower())
            for col in cols:
                ck = re.sub(r"[._:\-]+", "", str(col).lower())
                if ck == key or ck == bkey:
                    return col
            return None

        effs: list[float] = []
        for res in resolved:
            c = np.zeros(len(cols))
            ok = True
            for cond, w in zip(res.condition_list, res.weights, strict=False):
                matched = _match_col(cond)
                if matched is not None:
                    c[cols.index(matched)] = float(w)
                else:
                    ok = False
            denom = float(c @ XtX_inv @ c.T)
            if ok and denom > 0:
                effs.append(1.0 / denom)
        return float(sum(effs) / len(effs)) if effs else 0.0

    return _eff


def make_count_efficiency_fn() -> Callable[[dict], float]:
    """An EVENTS-FREE, value-free structural efficiency proxy: ``1/(1+n_regressors)``.

    For the fully-offline path (no raw events.tsv available) — rewards parsimonious confound
    models deterministically from the regressor COUNT only (never any data value or result). It
    is a crude DOF proxy, NOT a real design-matrix efficiency; use ``make_efficiency_fn`` (which
    builds the actual nilearn design matrix from event timing) when events are available.
    """

    def _eff(decision_points: dict) -> float:
        n_conf = _CONFOUND_REGRESSOR_COUNT.get(str(decision_points.get("confounds", "6mot")), 6)
        # HRF derivative/dispersion add per-condition regressors -> slightly fewer DOF.
        hrf_extra = {"canonical": 0, "glover": 0, "derivs": 2, "fir": 6}.get(
            str(decision_points.get("hrf_basis", "canonical")), 0)
        return 1.0 / (1.0 + n_conf + hrf_extra)

    return _eff


def make_constraint_fn(
    *,
    builder_arg: dict,
    dataset_id: str,
    task: str,
    hypothesis_id: str,
    declared_constraints: Sequence[str],
    project_root: str = "/app/data",
) -> Callable[[dict], bool]:
    """Build a constraint_fn that returns True iff a variant's plan trips a BLOCKING review rule.

    Reuses ``neuroprogram._check_constraints`` (which wraps the plan in SimpleNamespace, builds
    the review bundle, and runs ``evaluate_plan(rule_ids=...)``). Lazy import keeps this service-free.
    """
    import re

    from .compile_design import _variant_design_params  # lazy (sibling, pure)

    def _blocked(decision_points: dict) -> bool:
        from .neuroprogram import _check_constraints  # lazy

        hrf_model, cutoff, _confounds_mode = _variant_design_params(decision_points)
        params: dict[str, Any] = {
            "bids_dir": f"{project_root}/openneuro/{dataset_id}",
            "output_dir": f"{project_root}/fitlins_out/{hypothesis_id}",
            "hrf_model": hrf_model,
            "analysis_level": "dataset",
            "contrasts": builder_arg,
        }
        if cutoff is not None:
            params["high_pass_cutoff"] = cutoff
        step_id = re.sub(r"[^A-Za-z0-9_-]+", "_", f"fitlins_{dataset_id}_{task}")
        plan = {
            "project_root": project_root.rstrip("/"),
            "run_tag": f"hyp_{hypothesis_id}",
            "steps": [{"tool": "fitlins", "params": params, "step_id": step_id}],
        }
        _checked, _findings, _unknown, blocked = _check_constraints(plan, declared_constraints)
        return bool(blocked)

    return _blocked


# ======================================================================================
# commit-before-observe over the CHOSEN family + fail-closed reconciliation
# ======================================================================================


def family_commitment_fingerprint(
    program: NeuroProgramV1,
    *,
    variant_ids: Sequence[str],
    k: int,
    seed: int,
    n_candidates: int,
    weights: dict[str, float],
) -> str:
    """Fingerprint covering the program pre-registration AND the chosen family.

    Distinct from ``NeuroProgramV1.commitment_fingerprint`` (which covers only the priors) — two
    runs with the same priors but different selected families must NOT collide.
    """
    return fingerprint(
        {
            "program": program.commitment_fingerprint(),
            "variant_ids": sorted(str(v) for v in variant_ids),
            "k": int(k),
            "seed": int(seed),
            "n_candidates": int(n_candidates),
            "weights": {k2: round(float(v), 6) for k2, v in sorted(weights.items())},
        }
    )


def resolve_committed_family(
    committed_ids: Sequence[str],
    executed_ids: Sequence[str],
) -> CeilingResult:
    """Fail-closed: the executed family must be a SUPERSET of the locked committed family.

    A shrunk / swapped family is a non-verifiable robustness binding (selection laundering), so
    it caps the claim at ``qualified`` rather than letting a hand-picked subset borrow the
    committed family's robustness. Mirrors ``multiverse.resolve_multiverse_ceiling`` fail-closed.
    """
    committed = {str(v) for v in committed_ids}
    executed = {str(v) for v in executed_ids}
    if committed and committed <= executed:
        return CeilingResult(
            status=ClaimStatusV1.supported_within_scope,
            display="committed-family-verified",
            rationale="executed family is a superset of the locked committed family.",
            inputs={"committed": sorted(committed), "executed": sorted(executed)},
        )
    return CeilingResult(
        status=ClaimStatusV1.qualified,
        display="unverifiable-family-binding",
        rationale=(
            "executed design family does not match the pre-registered committed family "
            "(missing: " + ", ".join(sorted(committed - executed)) + ") — robustness binding "
            "is not verifiable; capped."
        ),
        inputs={"committed": sorted(committed), "executed": sorted(executed),
                "missing": sorted(committed - executed)},
    )


# ======================================================================================
# the optimizer
# ======================================================================================


def _prior_is_degenerate(priors: dict | None) -> bool:
    """True if any coverage axis prior is a near-delta (one option carries ~all the mass)."""
    if not priors:
        return False
    for axis in _COVERAGE_AXES:
        dist = priors.get(axis)
        if not isinstance(dist, dict) or not dist:
            continue
        weights = [float(w) for w in dist.values() if isinstance(w, (int, float))]
        total = sum(w for w in weights if w > 0)
        if total <= 0:
            continue
        if any(w / total >= 0.99 for w in weights):
            return True
    return False


def _normalize(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


# ======================================================================================
# evolutionary (genetic) search — an alternative candidate generator over the SAME
# pre-registered design space. Objective-safety is preserved by construction: fitness is the
# magnitude-free DesignFamilyScore, mutation never leaves the prior-allowed axis values, and the
# winner is still fingerprint-locked downstream. A harder search just finds better-COVERING /
# better-estimable / more-valid families — it cannot find result-favourable ones (fitness is
# blind to results), and the coverage floor + multi-objective fitness prevent collapse onto one
# axis. Fully DETERMINISTIC given ``seed`` (seeded ``random.Random``, no wall-clock/global RNG).
# ======================================================================================


def _ga_axes(priors: dict | None) -> dict[str, list]:
    """Allowed mutation values per coverage axis = the prior's positive-weight options (else the
    full catalog). The GA NEVER mutates outside these, so it stays inside the committed space."""
    axes: dict[str, list] = {}
    for axis, full in _FULL_AXES.items():
        if axis not in _COVERAGE_AXES:
            continue
        dist = (priors or {}).get(axis)
        if dist is None:
            vals = list(full)  # axis NOT pre-registered -> full catalog (the no-prior default)
        elif isinstance(dist, dict) and dist:
            pos = [k for k, wv in dist.items() if isinstance(wv, (int, float)) and wv > 0]
            # An EXPLICITLY-declared axis confines mutation to its DECLARED options — never the
            # full catalog. A present-but-no-positive-weight axis must NOT let the GA escape into
            # un-pre-registered values; fall back to the declared keys, not the catalog.
            vals = pos or list(dist.keys())
        else:
            # An axis declared but EMPTY ({}) or non-dict has no derivable pre-registered value
            # set. Fail CLOSED — never silently expand to the full catalog (that would let the GA
            # mutate into un-pre-registered values for a malformed prior).
            raise ValueError(
                f"design_priors axis {axis!r} is declared but has no usable options "
                f"({dist!r}); provide a non-empty {{value: weight}} mapping or omit the axis."
            )
        if axis == "high_pass":  # match generate_spec_family's int high-pass values
            vals = [int(v) if str(v).isdigit() else v for v in vals]
        axes[axis] = vals
    return axes


def _ga_variant(decision_points: dict) -> dict:
    """A spec dict (variant_id + decision_points) for a GA individual's gene; id is content-derived."""
    dp = {k: decision_points[k] for k in ("hrf_basis", "high_pass", "confounds")
          if k in decision_points}
    return {"variant_id": "ga_" + fingerprint(dict(sorted(dp.items())))[:12], "decision_points": dp}


def _random_family(axes: dict[str, list], k: int, rng: random.Random) -> list[dict]:
    return [_ga_variant({a: rng.choice(vals) for a, vals in axes.items()}) for _ in range(k)]


def _scalar_fitness(
    score: DesignFamilyScore,
    objectives: Sequence[NeuroObjectiveV1],
    weights: dict[str, float],
) -> float:
    """Absolute (population-independent) scalar fitness from the magnitude-free score. Ineligible
    families are pushed below eligible ones so the GA climbs toward the floors."""
    dimvals = {
        "coverage": score.coverage,
        "efficiency_stability": score.efficiency_stability,
        "constraint_pass_frac": score.constraint_pass_frac,
        "neg_cost": 1.0 / (1.0 + score.est_cost_units),
    }
    total = sum(float(weights.get(o.value, 1.0)) * dimvals[_OBJECTIVE_DIMENSION[o]]
                for o in objectives)
    # A dominating penalty so an eligible family ALWAYS outranks an ineligible one in GA
    # selection regardless of composite weight scale (the downstream eligible-first selection is
    # the hard gate; this just keeps the search pressure correctly ordered).
    return total if score.eligible else total - 1e9


def _evolve(
    program: NeuroProgramV1,
    *,
    efficiency_fn: Callable[[dict], float],
    constraint_fn: Callable[[dict], bool],
    objectives: Sequence[NeuroObjectiveV1],
    weights: dict[str, float],
    k_variants: int,
    pop_size: int,
    generations: int,
    seed: int,
) -> list[DesignFamilyScore]:
    """Genetic search over design families; returns the FINAL population's scores (the caller's
    standard Pareto/weighted selection + commit-lock then pick the winner). Tournament selection,
    uniform crossover (per-variant), single-gene mutation within prior-allowed axes, 2-elitism."""
    from brain_researcher.core.multiverse.spec_family import generate_spec_family  # lazy

    rng = random.Random(int(seed))
    axes = _ga_axes(program.design_priors)
    pop_size = max(4, int(pop_size))
    k = max(1, int(k_variants))

    def _fit(family: list[dict]) -> tuple[float, DesignFamilyScore]:
        s = score_design_family(family, efficiency_fn=efficiency_fn,
                                constraint_fn=constraint_fn, seed=int(seed))
        return _scalar_fitness(s, objectives, weights), s

    # seed initial population: half from generate_spec_family (good coverage start), half random.
    pop: list[list[dict]] = []
    for i in range(pop_size):
        if i % 2 == 0:
            specs = generate_spec_family(program.design_priors or {}, k=k, seed=seed + i)
            pop.append([_ga_variant(s.get("decision_points", s)) for s in specs])
        else:
            pop.append(_random_family(axes, k, rng))

    def _mutate(family: list[dict]) -> list[dict]:
        child = [dict(v) for v in family]
        vi = rng.randrange(len(child))
        axis = rng.choice(list(axes))
        dp = dict(child[vi]["decision_points"])
        dp[axis] = rng.choice(axes[axis])  # stays within prior-allowed values (objective-safe)
        child[vi] = _ga_variant(dp)
        return child

    def _crossover(a: list[dict], b: list[dict]) -> list[dict]:
        n = min(len(a), len(b))
        return [a[i] if rng.random() < 0.5 else b[i] for i in range(n)]

    def _tournament(scored: list[tuple], t: int = 3) -> list[dict]:
        return max(rng.sample(scored, min(t, len(scored))), key=lambda x: x[0])[2]

    scored = [(*_fit(f), f) for f in pop]  # (fitness, DesignFamilyScore, family)
    for _gen in range(max(1, int(generations))):
        scored.sort(key=lambda x: x[0], reverse=True)
        children: list[list[dict]] = [s[2] for s in scored[:2]]  # elitism
        while len(children) < pop_size:
            child = _crossover(_tournament(scored), _tournament(scored))
            if rng.random() < 0.4:
                child = _mutate(child)
            children.append(child)
        scored = [(*_fit(f), f) for f in children]

    return [s for (_f, s, _fam) in scored]


def optimize_design_family(
    program: NeuroProgramV1,
    *,
    efficiency_fn: Callable[[dict], float],
    constraint_fn: Callable[[dict], bool],
    k_variants: int = 6,
    n_candidates: int = 8,
    weights: dict[str, float] | None = None,
    prior_provenance: str | None = None,
    unknown_constraints: Sequence[str] = (),
    search: Literal["grid", "evolutionary"] = "grid",
    generations: int = 6,
    pop_size: int | None = None,
    seed: int = 0,
) -> OptimizeResultV1:
    """Search the pre-registered design space for the best-covering, well-estimable, valid family.

    ``search='grid'`` (default) enumerates ``n_candidates`` families via
    ``generate_spec_family(priors, seed=i)``; ``search='evolutionary'`` runs a genetic search
    (tournament + crossover + within-prior mutation + elitism, ``generations`` gens of
    ``pop_size`` families). BOTH score each candidate with the same magnitude-free fitness, keep
    the eligible ones, take the Pareto front over (coverage, efficiency_stability,
    constraint_pass_frac, -cost), and pick the winner by a weighted sum of the declared
    ``objectives``; the winner is ``family_commitment_fingerprint``-locked BEFORE execution. A
    degenerate prior with no pre-data ``prior_provenance`` forces ``claim_mode='exploratory'``.
    The search strategy is purely a candidate GENERATOR — objective-safety (magnitude-free
    fitness, within-prior moves, commit-before-observe, ceiling min-law) is identical either way.
    """
    from brain_researcher.core.multiverse.spec_family import generate_spec_family  # lazy

    objectives = list(program.objectives) or [NeuroObjectiveV1.maximize_coverage]
    w = dict(weights or {})
    for obj in objectives:
        w.setdefault(obj.value, 1.0)
    # Validate weights: a NEGATIVE weight would invert a 'maximize' objective (e.g. minimize
    # coverage) while the result still reports the safe objective label — a real gaming path.
    for _name, _val in w.items():
        if not isinstance(_val, (int, float)) or not math.isfinite(_val) or _val < 0:
            raise ValueError(
                f"objective weight {_name}={_val!r} must be a finite, non-negative number "
                "(negative weights would invert a maximize-objective and are forbidden)."
            )

    unknown = sorted({str(c) for c in (unknown_constraints or [])})
    degenerate = _prior_is_degenerate(program.design_priors)
    claim_mode: Literal["confirmatory", "exploratory"] = program.claim_mode
    if degenerate and not prior_provenance:
        claim_mode = "exploratory"  # hand-narrowed prior cannot license a confirmatory claim
    if unknown:
        # a declared constraint the review engine does not know cannot be GUARANTEED satisfied —
        # fail-closed (mirror compile_program surfacing unknown constraints), drop to exploratory.
        claim_mode = "exploratory"

    if search == "evolutionary":
        candidates = _evolve(
            program, efficiency_fn=efficiency_fn, constraint_fn=constraint_fn,
            objectives=objectives, weights=w, k_variants=k_variants,
            pop_size=pop_size or n_candidates, generations=generations, seed=seed)
    else:
        candidates = []
        for i in range(max(1, int(n_candidates))):
            specs = generate_spec_family(program.design_priors or {}, k=k_variants, seed=i)
            candidates.append(score_design_family(
                specs, efficiency_fn=efficiency_fn, constraint_fn=constraint_fn, seed=i))

    eligible = [c for c in candidates if c.eligible]
    winner_eligible = bool(eligible)
    if not winner_eligible:
        # No family met the floors (all blocked / too few passing / not estimable). Fail-closed:
        # return the least-bad candidate but mark it ineligible and force exploratory — it must
        # NOT be presented as a clean confirmatory design.
        claim_mode = "exploratory"
    pool = eligible or candidates

    # Pareto front over the maximized dims (cost negated).
    def _dominates(a: DesignFamilyScore, b: DesignFamilyScore) -> bool:
        ge = (a.coverage >= b.coverage and a.efficiency_stability >= b.efficiency_stability
              and a.constraint_pass_frac >= b.constraint_pass_frac
              and a.est_cost_units <= b.est_cost_units)
        gt = (a.coverage > b.coverage or a.efficiency_stability > b.efficiency_stability
              or a.constraint_pass_frac > b.constraint_pass_frac
              or a.est_cost_units < b.est_cost_units)
        return ge and gt

    pareto = [c for c in pool if not any(_dominates(o, c) for o in pool if o is not c)]
    front = pareto or pool

    # Weighted-sum selection over normalized score dimensions for the declared objectives.
    dims = {
        "coverage": _normalize([c.coverage for c in front]),
        "efficiency_stability": _normalize([c.efficiency_stability for c in front]),
        "constraint_pass_frac": _normalize([c.constraint_pass_frac for c in front]),
        "neg_cost": _normalize([-c.est_cost_units for c in front]),
    }
    best_idx, best_val = 0, float("-inf")
    for idx in range(len(front)):
        total = 0.0
        for obj in objectives:
            dim = _OBJECTIVE_DIMENSION[obj]
            total += w.get(obj.value, 1.0) * dims[dim][idx]
        if total > best_val:
            best_idx, best_val = idx, total
    winner = front[best_idx]

    commitment = family_commitment_fingerprint(
        program, variant_ids=winner.variant_ids, k=k_variants, seed=winner.seed,
        n_candidates=n_candidates, weights=w,
    )
    return OptimizeResultV1(
        program_id=program.program_id,
        winner_variant_ids=list(winner.variant_ids),
        winner_variants=[dict(v) for v in winner.variants],
        winner_seed=winner.seed,
        winner_scores={
            "coverage": winner.coverage, "mean_efficiency": winner.mean_efficiency,
            "efficiency_stability": winner.efficiency_stability,
            "constraint_pass_frac": winner.constraint_pass_frac,
            "est_cost_units": winner.est_cost_units, "n_axes_varied": winner.n_axes_varied,
            "eligible": winner.eligible, "ineligible_reason": winner.ineligible_reason,
            "disqualified_variants": list(winner.disqualified_variants),
        },
        objectives=[o.value for o in objectives],
        weights=w,
        n_candidates=len(candidates),
        n_eligible=len(eligible),
        pareto_size=len(pareto),
        claim_mode=claim_mode,
        prior_degenerate=degenerate,
        search=search,
        winner_eligible=winner_eligible,
        unknown_constraints=unknown,
        commitment_hash=commitment,
    )


__all__ = [
    "DesignFamilyScore",
    "OptimizeResultV1",
    "score_design_family",
    "make_efficiency_fn",
    "make_count_efficiency_fn",
    "make_constraint_fn",
    "family_commitment_fingerprint",
    "resolve_committed_family",
    "optimize_design_family",
]
