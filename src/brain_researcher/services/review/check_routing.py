"""Stage / family aware routing for scientific-review correctness checks.

Background
----------
``distill_scientific_review_records`` (see ``distill_review.py``) runs a large,
flat tuple of ``check_fn(bundle) -> ReviewFinding | None`` callables
unconditionally against every bundle. Many of those checks are only meaningful
for a particular analysis family (e.g. predictive / neuroAI cross-validation
leakage checks for ``tribe_prediction`` runs, correlation-matrix sanity checks
for functional-connectivity runs). Running all of them on every run is correct
but wasteful: each check that needs LLM-backed plausibility lookups or KG
round-trips costs tokens / latency even when it can only ever no-op.

This module provides a *conservative*, declarative routing layer that decides
which checks are worth running for a given bundle, based on the analysis
family / design type / statistical method / modality already inferred by
``bundle_builder._build_kg_context`` plus the *presence* of structured
``review_context`` keys.

Design contract (read before editing)
-------------------------------------
1. **False-negative-averse.** The router only *skips* a check when it has
   positive evidence the check is irrelevant for this bundle. Any ambiguity --
   unknown family, missing signals, an unrecognised check name -- resolves to
   *run the check*. A check we cannot classify is always kept.

2. **Always-on safety floor.** A fixed set of safety-critical check *groups*
   (data leakage, value-domain contracts, null-model validity, and core
   structural integrity) is *never* skipped, regardless of routing signals.
   ``select_checks`` enforces this even if a future edit to the routing map
   tries to gate them.

3. **Observable.** ``select_checks`` returns a :class:`RoutingDecision` whose
   ``skipped`` mapping records *which* checks were dropped and *why*, and it
   emits a single structured ``logging`` record describing the decision so the
   skip is auditable from run logs.

The module deliberately keys off *check function names* (``check_fn.__name__``)
rather than importing the check callables, so it stays import-cheap and never
creates a circular import against ``distill_review`` / the ``checks`` package.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "CheckGroup",
    "RoutingDecision",
    "ALWAYS_ON_GROUPS",
    "CHECK_GROUPS",
    "classify_check",
    "select_checks",
    "routing_shadow_report",
]


# ---------------------------------------------------------------------------
# Group taxonomy
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CheckGroup:
    """A named bucket of related checks with the routing predicate metadata.

    Attributes:
        name: Stable identifier used in logs and the ``skipped`` map.
        always_on: When True the group is part of the safety floor and is never
            skipped by :func:`select_checks`.
        analysis_families: Analysis families (as produced by
            ``_infer_analysis_family``) that make this group relevant. ``None``
            means "not gated on analysis family".
        statistical_methods: Statistical methods (``_infer_statistical_method``)
            that make this group relevant. ``None`` means "not gated".
        design_types: Design types (``_infer_design_type``) that make this group
            relevant. ``None`` means "not gated".
        modalities: Lowercase modality tokens that make this group relevant.
            ``None`` means "not gated on modality".
        review_context_keys: ``review_context`` keys whose *presence* makes this
            group relevant even when the coarse family signals do not match.
            This is the primary false-negative guard: if a contract sidecar
            exists, we run the matching checks regardless of inferred family.
    """

    name: str
    always_on: bool = False
    analysis_families: frozenset[str] | None = None
    statistical_methods: frozenset[str] | None = None
    design_types: frozenset[str] | None = None
    modalities: frozenset[str] | None = None
    review_context_keys: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_gated(self) -> bool:
        """True when the group has at least one positive relevance condition."""
        return any(
            cond is not None
            for cond in (
                self.analysis_families,
                self.statistical_methods,
                self.design_types,
                self.modalities,
            )
        ) or bool(self.review_context_keys)


# ---------------------------------------------------------------------------
# Check -> group membership.
#
# Keyed by check function ``__name__``. Every name referenced in the
# distill_review correctness tuple should appear here; any name NOT listed is
# treated as "unclassified" and is ALWAYS run (false-negative-averse).
# ---------------------------------------------------------------------------

# Safety floor groups -- never skipped.
ALWAYS_ON_GROUPS: frozenset[str] = frozenset(
    {
        "structural_integrity",
        "value_domain",
        "leakage",
        "null_model",
        "review_context_integrity",
    }
)

_GROUP_DEFINITIONS: tuple[CheckGroup, ...] = (
    # --- Always-on safety floor -------------------------------------------
    CheckGroup(name="structural_integrity", always_on=True),
    CheckGroup(name="value_domain", always_on=True),
    CheckGroup(name="leakage", always_on=True),
    CheckGroup(name="null_model", always_on=True),
    CheckGroup(name="review_context_integrity", always_on=True),
    # --- Conditional groups -----------------------------------------------
    CheckGroup(
        name="correlation_matrix",
        analysis_families=frozenset({"embedding_analysis"}),
        statistical_methods=frozenset(
            {"correlation_pearson", "embedding_autoresearch"}
        ),
        modalities=frozenset({"fmri", "rsfmri", "rs-fmri", "func", "bold"}),
        review_context_keys=frozenset(
            {
                "correlation_matrix",
                "connectivity",
                "functional_connectivity",
                "netmats",
                "partial_correlation",
            }
        ),
    ),
    CheckGroup(
        name="predictive_neuroai",
        analysis_families=frozenset({"tribe_prediction", "embedding_analysis"}),
        statistical_methods=frozenset(
            {
                "neural_encoding_prediction",
                "embedding_autoresearch",
                "linear_regression",
            }
        ),
        review_context_keys=frozenset(
            {
                "split_manifest",
                "splits",
                "cross_validation",
                "cv",
                "nested_cv",
                "feature_contract",
                "predictive",
                "selection",
                "subject_manifest",
                "subject_intersection",
            }
        ),
    ),
    CheckGroup(
        name="glm_design",
        analysis_families=frozenset({"glm"}),
        statistical_methods=frozenset(
            {
                "paired_t_test",
                "independent_t_test",
                "one_sample_t_test",
                "anova_oneway",
                "anova_repeated",
                "anova_mixed",
                "mixed_effects_model",
                "linear_regression",
            }
        ),
        review_context_keys=frozenset(
            {"design_matrix", "contrast", "contrasts", "glm", "first_level"}
        ),
    ),
    CheckGroup(
        name="task_construct",
        analysis_families=frozenset({"glm"}),
        review_context_keys=frozenset(
            {
                "task",
                "task_design",
                "events",
                "behavioral",
                "ppi",
                "stimulus",
            }
        ),
    ),
    CheckGroup(
        name="sensitivity_packages",
        analysis_families=frozenset({"glm", "embedding_analysis"}),
        review_context_keys=frozenset(
            {
                "gsr",
                "global_signal_regression",
                "dynamic_fc",
                "graph",
                "atlas",
                "hrf",
                "sensitivity",
            }
        ),
    ),
    CheckGroup(
        name="method_appropriateness",
        # Gated on the presence of *any* design/method signal; if we inferred a
        # design or a method, design-method compatibility is meaningful.
        analysis_families=frozenset({"glm"}),
        statistical_methods=frozenset(
            {
                "paired_t_test",
                "independent_t_test",
                "one_sample_t_test",
                "anova_oneway",
                "anova_repeated",
                "anova_mixed",
                "mixed_effects_model",
                "correlation_pearson",
                "mann_whitney",
                "wilcoxon_signed_rank",
                "permutation_test",
                "linear_regression",
            }
        ),
        design_types=frozenset(
            {
                "repeated_measures",
                "independent_groups",
                "one_sample",
                "factorial",
                "mixed_design",
                "longitudinal",
                "correlation",
            }
        ),
    ),
)

CHECK_GROUPS: dict[str, CheckGroup] = {g.name: g for g in _GROUP_DEFINITIONS}


# Check function name -> group name. Names absent from this map are
# unclassified and therefore ALWAYS run.
_CHECK_TO_GROUP: dict[str, str] = {
    # --- structural_integrity (always-on) ---------------------------------
    "design_matrix_rank_check": "structural_integrity",
    "contrast_vector_dim_check": "structural_integrity",
    "cross_file_n_subjects_check": "structural_integrity",
    "effect_tstat_shape_check": "structural_integrity",
    "condition_number_check": "structural_integrity",
    "contrast_estimability_check": "structural_integrity",
    "design_matrix_confound_column_consistency_check": "structural_integrity",
    "multiple_comparison_metadata_consistency_check": "structural_integrity",
    "correction_summary_numeric_consistency_check": "structural_integrity",
    "contrast_table_semantics_check": "structural_integrity",
    "cluster_table_count_consistency_check": "structural_integrity",
    "cluster_table_semantics_check": "structural_integrity",
    "peak_table_semantics_check": "structural_integrity",
    "peak_cluster_membership_consistency_check": "structural_integrity",
    "cluster_peak_cardinality_check": "structural_integrity",
    "design_model_metadata_consistency_check": "structural_integrity",
    # cross-step assumption consistency: cheap, structural, keep always-on.
    "bandpass_glm_drift_overlap": "structural_integrity",
    "preprocessing_stats_space_mismatch": "structural_integrity",
    "bandpass_before_confound_regression": "structural_integrity",
    "atlas_registration_space_mismatch": "structural_integrity",
    # --- value_domain (always-on) -----------------------------------------
    "value_domain_contract_violation_check": "value_domain",
    "predictive_fisher_z_input_domain_check": "value_domain",
    # --- leakage (always-on) ----------------------------------------------
    "predictive_cv_leakage_check": "leakage",
    "predictive_split_integrity_check": "leakage",
    "review_context_leakage_circularity_flag_check": "leakage",
    "neuroai_selection_on_test_check": "leakage",
    "neuroai_split_grouping_mismatch_check": "leakage",
    # --- null_model (always-on) -------------------------------------------
    "permutation_exchangeability_check": "null_model",
    "spatial_null_validity_check": "null_model",
    "surface_volume_correction_domain_mismatch_check": "null_model",
    # --- review_context_integrity (always-on) -----------------------------
    "predictive_review_context_metadata_check": "review_context_integrity",
    "predictive_required_diagnostics_check": "review_context_integrity",
    "review_context_mirror_conflict_check": "review_context_integrity",
    "external_evidence_path_integrity_check": "review_context_integrity",
    # --- correlation_matrix (conditional) ---------------------------------
    "corr_has_nan_check": "correlation_matrix",
    "corr_symmetric_check": "correlation_matrix",
    "corr_diag_check": "correlation_matrix",
    "corr_range_check": "correlation_matrix",
    "corr_positive_semidefinite_check": "correlation_matrix",
    "corr_region_count_check": "correlation_matrix",
    "partial_correlation_required_diagnostics_check": "correlation_matrix",
    "partial_correlation_estimator_hazard_check": "correlation_matrix",
    # --- predictive_neuroai (conditional) ---------------------------------
    "neuroai_declared_subject_set_missing_subject_column_check": "predictive_neuroai",
    "neuroai_subject_manifest_coverage_check": "predictive_neuroai",
    "neuroai_subject_manifest_selection_source_subset_conflict_check": "predictive_neuroai",
    "neuroai_subject_intersection_coverage_check": "predictive_neuroai",
    "neuroai_subject_intersection_selection_source_subset_conflict_check": "predictive_neuroai",
    "neuroai_subject_intersection_subset_conflict_check": "predictive_neuroai",
    "neuroai_subject_selection_source_coverage_check": "predictive_neuroai",
    "neuroai_split_manifest_missing_group_keys_check": "predictive_neuroai",
    "neuroai_split_manifest_partition_conflict_check": "predictive_neuroai",
    "neuroai_nested_cv_schema_missing_fold_keys_check": "predictive_neuroai",
    "neuroai_nested_cv_outer_partition_gap_check": "predictive_neuroai",
    "neuroai_nested_cv_outer_missing_inner_resampling_check": "predictive_neuroai",
    "neuroai_nested_cv_inner_partition_gap_check": "predictive_neuroai",
    "neuroai_nested_cv_outer_holdout_conflict_check": "predictive_neuroai",
    "neuroai_selection_multiplicity_accounting_check": "predictive_neuroai",
    "neuroai_winner_without_candidate_set_check": "predictive_neuroai",
    "neuroai_selection_validation_gap_check": "predictive_neuroai",
    # --- glm_design (conditional) -----------------------------------------
    # (structural GLM checks are always-on; these are the plausibility ones)
    "effect_size_plausibility_check": "glm_design",
    "meta_analytic_spatial_plausibility_check": "glm_design",
    # --- task_construct (conditional) -------------------------------------
    "stimulus_fixed_effect_risk_check": "task_construct",
    "behavioral_imbalance_not_modeled_check": "task_construct",
    "task_fc_ppi_evoked_response_control_check": "task_construct",
    # --- sensitivity_packages (conditional) -------------------------------
    "gsr_sensitivity_package_check": "sensitivity_packages",
    "dynamic_fc_sensitivity_package_check": "sensitivity_packages",
    "graph_atlas_hrf_sensitivity_package_check": "sensitivity_packages",
    # --- method_appropriateness (conditional) -----------------------------
    "method_appropriateness_check": "method_appropriateness",
    # NOTE: claim/epistemic checks (claim_inflation_check,
    # reverse_inference_risk_check, model_fit_mechanism_overreach_check,
    # controversial_choice_sensitivity_check, construct_validity_confound_check,
    # epistemic_claim_policy_check, cross_study_coordinate_comparison_check,
    # directional_claim_contradiction_check) are intentionally LEFT OUT of this
    # map. They apply to any run that makes claims, so they remain
    # unclassified -> always run.
}


# ---------------------------------------------------------------------------
# Routing decision
# ---------------------------------------------------------------------------
@dataclass
class RoutingDecision:
    """Result of :func:`select_checks`.

    Attributes:
        selected: Check names that should be run, preserving input order.
        skipped: ``{check_name: reason}`` for every check dropped from the
            input set.
        active_groups: Group names judged relevant for this bundle (the
            always-on floor plus matched conditional groups).
        signals: The routing signals extracted from the bundle (for logging /
            debugging).
        unclassified: Check names not present in the group map; always kept.
    """

    selected: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    active_groups: set[str] = field(default_factory=set)
    signals: dict[str, Any] = field(default_factory=dict)
    unclassified: list[str] = field(default_factory=list)

    def select_callables(self, check_fns: Iterable[Any]) -> list[Any]:
        """Filter an iterable of check callables to the selected subset.

        Convenience for the caller in ``distill_review``: pass the original
        tuple of ``check_fn`` objects and get back only those whose
        ``__name__`` is in :attr:`selected`, preserving order.
        """
        selected_set = set(self.selected)
        return [fn for fn in check_fns if getattr(fn, "__name__", None) in selected_set]


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------
def _extract_signals(bundle: Any) -> dict[str, Any]:
    """Pull routing signals off the bundle.

    Mirrors the fields populated by ``bundle_builder._build_kg_context`` and the
    declared modality list. All extraction is defensive: a malformed / partial
    bundle yields empty signals, which (per the conservative contract) makes the
    router keep everything.
    """
    kg_context = getattr(bundle, "kg_context", None)
    kg_context = kg_context if isinstance(kg_context, Mapping) else {}

    review_context = getattr(bundle, "review_context", None)
    review_context = review_context if isinstance(review_context, Mapping) else {}

    declared = getattr(bundle, "declared_modalities", None)
    modalities: set[str] = set()
    if isinstance(declared, list | tuple | set):
        modalities = {str(m).strip().lower() for m in declared if str(m).strip()}

    def _norm(value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
        return None

    return {
        "analysis_family": _norm(kg_context.get("analysis_family")),
        "statistical_method": _norm(kg_context.get("statistical_method")),
        "design_type": _norm(kg_context.get("design_type")),
        "modalities": modalities,
        "review_context_keys": {
            str(k).strip().lower() for k in review_context.keys() if str(k).strip()
        },
        # Whether we have *any* coarse family signal at all. If not, the router
        # is maximally conservative and keeps every group.
        "has_family_signal": bool(
            _norm(kg_context.get("analysis_family"))
            or _norm(kg_context.get("statistical_method"))
            or _norm(kg_context.get("design_type"))
            or modalities
        ),
    }


def _group_is_relevant(
    group: CheckGroup, signals: Mapping[str, Any]
) -> tuple[bool, str]:
    """Decide whether a conditional group is relevant for the signals.

    Returns ``(relevant, reason)``. The reason explains the *negative* case
    (why it was skipped); for the positive case it names the matching signal.

    Conservative rules:
      * Always-on groups are relevant unconditionally.
      * If the bundle exposes no coarse family signal at all, every group is
        relevant (we cannot prove irrelevance).
      * ``review_context`` key presence alone is enough to make a group
        relevant, independent of family.
      * Otherwise the group is relevant if ANY of its declared positive
        conditions match a present signal.
    """
    if group.always_on:
        return True, "always_on"

    if not signals.get("has_family_signal"):
        return True, "no_family_signal:conservative_keep"

    # review_context key presence is a strong positive (a contract sidecar
    # exists for this concern), and overrides family-based skipping.
    present_keys: set[str] = signals.get("review_context_keys") or set()
    if group.review_context_keys and (group.review_context_keys & present_keys):
        matched = sorted(group.review_context_keys & present_keys)
        return True, f"review_context_key:{','.join(matched)}"

    family = signals.get("analysis_family")
    method = signals.get("statistical_method")
    design = signals.get("design_type")
    modalities: set[str] = signals.get("modalities") or set()

    if group.analysis_families and family and family in group.analysis_families:
        return True, f"analysis_family:{family}"
    if group.statistical_methods and method and method in group.statistical_methods:
        return True, f"statistical_method:{method}"
    if group.design_types and design and design in group.design_types:
        return True, f"design_type:{design}"
    if group.modalities and (group.modalities & modalities):
        matched = sorted(group.modalities & modalities)
        return True, f"modality:{','.join(matched)}"

    # We have family signals but none matched this group's positive conditions.
    return False, "no_signal_matched_group_conditions"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def classify_check(check_name: str) -> str | None:
    """Return the group name for a check, or ``None`` if unclassified."""
    return _CHECK_TO_GROUP.get(check_name)


def select_checks(
    bundle: Any,
    all_check_names: Iterable[str],
    *,
    log: bool = True,
) -> RoutingDecision:
    """Select the subset of checks worth running for ``bundle``.

    Args:
        bundle: The ``CodeReviewBundle`` (anything exposing ``kg_context``,
            ``review_context``, ``declared_modalities``).
        all_check_names: The full set of check function names that
            ``distill_review`` would otherwise run (typically
            ``[fn.__name__ for fn in (...)]``).
        log: Emit a structured INFO/DEBUG log of the decision when True.

    Returns:
        A :class:`RoutingDecision`. ``selected`` always:
          * includes every always-on / safety-floor check,
          * includes every unclassified check (false-negative-averse),
          * includes checks whose group matched a routing signal.
        ``skipped`` records dropped checks with a per-check reason.

    The function never raises on a malformed bundle; on any extraction error it
    degrades to "run everything".
    """
    names = list(all_check_names)

    try:
        signals = _extract_signals(bundle)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "check_routing: signal extraction failed (%s); running all checks", exc
        )
        return RoutingDecision(
            selected=list(names),
            skipped={},
            active_groups=set(ALWAYS_ON_GROUPS),
            signals={"error": str(exc)},
            unclassified=[n for n in names if classify_check(n) is None],
        )

    # Decide group relevance once.
    group_relevance: dict[str, tuple[bool, str]] = {}
    for group_name, group in CHECK_GROUPS.items():
        group_relevance[group_name] = _group_is_relevant(group, signals)

    active_groups = {
        name for name, (relevant, _reason) in group_relevance.items() if relevant
    }
    # Belt-and-suspenders: the safety floor is always active even if a future
    # edit removes a group's always_on flag.
    active_groups |= ALWAYS_ON_GROUPS

    decision = RoutingDecision(
        active_groups=active_groups,
        signals=signals,
    )

    for name in names:
        group_name = classify_check(name)
        if group_name is None:
            # Unclassified -> always run (cannot prove irrelevance).
            decision.selected.append(name)
            decision.unclassified.append(name)
            continue
        if group_name in ALWAYS_ON_GROUPS:
            decision.selected.append(name)
            continue
        relevant, reason = group_relevance.get(group_name, (True, "unknown_group"))
        if relevant:
            decision.selected.append(name)
        else:
            decision.skipped[name] = f"group={group_name}:{reason}"

    if log:
        _log_decision(bundle, decision)

    return decision


def routing_shadow_report(
    bundle: Any,
    all_check_names: Iterable[str],
) -> dict[str, Any]:
    """Compute what routing *would* skip without changing live behaviour.

    This is a non-default, observability-only helper. It runs the same
    :func:`select_checks` logic with logging suppressed and returns a plain
    serialisable summary describing the hypothetical decision. The intended use
    is shadow logging while routing remains default-OFF: callers can emit this
    alongside the (full) check run to gather field evidence on *which* checks a
    future routing rollout would drop, and on which bundles, without ever
    actually dropping a check.

    The function never mutates the bundle, never raises on a malformed bundle
    (it inherits :func:`select_checks`'s defensive degradation to "keep
    everything"), and is independent of the ``BR_REVIEW_CHECK_ROUTING`` flag.

    Returns:
        A mapping with keys:
          * ``would_skip``: ``{check_name: reason}`` that routing would drop.
          * ``would_skip_count``: ``len(would_skip)``.
          * ``would_run_count``: number of checks that would be kept.
          * ``total``: total checks considered.
          * ``skipped_groups``: sorted distinct group names contributing skips.
          * ``active_groups``: sorted groups judged relevant.
          * ``signals``: the extracted routing signals (sets coerced to sorted
            lists for serialisability).
          * ``run_id``: the bundle ``run_id`` if present.
          * ``would_change``: True when ``would_skip`` is non-empty.
    """
    decision = select_checks(bundle, all_check_names, log=False)

    signals = dict(decision.signals)
    modalities = signals.get("modalities")
    if isinstance(modalities, set):
        signals["modalities"] = sorted(modalities)
    rc_keys = signals.get("review_context_keys")
    if isinstance(rc_keys, set):
        signals["review_context_keys"] = sorted(rc_keys)

    skipped_groups = sorted(
        {
            reason.split(":", 1)[0].replace("group=", "")
            for reason in decision.skipped.values()
        }
    )
    return {
        "run_id": getattr(bundle, "run_id", None),
        "would_skip": dict(decision.skipped),
        "would_skip_count": len(decision.skipped),
        "would_run_count": len(decision.selected),
        "total": len(decision.selected) + len(decision.skipped),
        "skipped_groups": skipped_groups,
        "active_groups": sorted(decision.active_groups),
        "signals": signals,
        "would_change": bool(decision.skipped),
    }


def _log_decision(bundle: Any, decision: RoutingDecision) -> None:
    run_id = getattr(bundle, "run_id", None)
    signals = decision.signals
    if decision.skipped:
        skipped_groups = sorted(
            {
                reason.split(":", 1)[0].replace("group=", "")
                for reason in decision.skipped.values()
            }
        )
        logger.info(
            "check_routing[run=%s]: selected=%d skipped=%d "
            "(family=%s method=%s design=%s modalities=%s) "
            "skipped_groups=%s active_groups=%s",
            run_id,
            len(decision.selected),
            len(decision.skipped),
            signals.get("analysis_family"),
            signals.get("statistical_method"),
            signals.get("design_type"),
            sorted(signals.get("modalities") or set()),
            skipped_groups,
            sorted(decision.active_groups),
        )
        # Per-check detail at DEBUG to keep INFO logs compact but auditable.
        for name, reason in sorted(decision.skipped.items()):
            logger.debug("check_routing[run=%s]: skip %s (%s)", run_id, name, reason)
    else:
        logger.debug(
            "check_routing[run=%s]: ran all %d checks (no skips; family=%s)",
            run_id,
            len(decision.selected),
            signals.get("analysis_family"),
        )
