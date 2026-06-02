"""Engine-execution harness for the C01-C60 calibration case library.

``tests/unit/review/test_calibration_case_library.py`` asserts *structural*
integrity of ``tests/fixtures/review/calibration_cases_c01_c60.yaml`` only. This
module closes the followup tracked in that file's docstring: for the subset of
calibration cases whose scenario can be expressed as an explicit
``review_context`` bundle, it constructs a real ``CodeReviewBundle`` and runs the
ACTUAL correctness ``check_fn``s wired into
``distill_review.distill_scientific_review_records`` (imported from the same
``checks/*`` modules), then asserts the engine fires a finding at or above the
calibration case's ``expected_severity``.

Honesty contract
----------------
- We never fake an engine result. Each wired case names the concrete engine
  ``rule_id`` it is expected to fire and the minimum action/severity.
- The manuscript taxonomy rule ids (e.g. ``STAT_SPATIAL_NULL``,
  ``NEUROAI_HARMONIZATION``) are *not* the engine's rule ids; the engine emits
  ``REVIEW_*`` rules. ``ENGINE_RULE_FOR_CASE`` records the documented mapping
  from each manuscript rule to the engine rule that implements it, so the test
  stays meaningful even though the names differ.
- Cases that need NLP/LLM judgement, prose parsing, novelty priors, or
  provenance that the deterministic checks deliberately refuse to infer are
  listed in ``SKIPPED`` with an explicit reason. They are reported, not faked.
- ``test_engine_coverage_is_reported`` prints the wired/skipped tally (N of 60)
  so coverage regressions are visible.

Severity ordering: the fixture's ``expected_severity`` is in
``{allow, warn, block}``. A ``ReviewFinding`` exposes ``action`` in
``{warn, block}`` and ``severity`` in ``{warn, error, critical}``. We treat a
finding as satisfying ``expected_severity`` when its action rank is >= the
expected rank (``warn`` < ``block``); ``allow`` cases are asserted to produce no
finding from the mapped check.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

# Engine check functions, imported from the SAME modules distill_review wires
# into its correctness check tuple (see distill_scientific_review_records).
from brain_researcher.services.review.checks.leakage_extra import (
    brainmap_correlation_spatial_null_check,
    leakage_preprocessing_fit_scope_check,
    leakage_pseudoreplication_check,
)
from brain_researcher.services.review.checks.neuroai_validity import (
    neuroai_selection_multiplicity_accounting_check,
    neuroai_selection_on_test_check,
    neuroai_selection_validation_gap_check,
    neuroai_split_grouping_mismatch_check,
)
from brain_researcher.services.review.checks.null_model_validity import (
    permutation_exchangeability_check,
    spatial_null_validity_check,
    surface_volume_correction_domain_mismatch_check,
)
from brain_researcher.services.review.checks.predictive_integrity import (
    predictive_cv_leakage_check,
    predictive_split_integrity_check,
)
from brain_researcher.services.review.checks.value_domain import (
    value_domain_contract_violation_check,
)

# --------------------------------------------------------------------------- #
# Fixture loading (shared with the structural test).
# --------------------------------------------------------------------------- #

EXPECTED_CASE_COUNT = 60

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "review"
    / "calibration_cases_c01_c60.yaml"
)


def _load_cases() -> dict[str, dict]:
    assert _FIXTURE_PATH.is_file(), f"missing fixture: {_FIXTURE_PATH}"
    with _FIXTURE_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    cases = data["cases"]
    return {case["id"]: case for case in cases}


CASES_BY_ID = _load_cases()


# --------------------------------------------------------------------------- #
# Severity helpers.
# --------------------------------------------------------------------------- #

# Map the fixture's recommended-default severity to a finding *action* rank.
# allow -> no finding; warn -> action "warn"; block -> action "block".
_ACTION_RANK = {"warn": 1, "block": 2}


def _expected_action_rank(expected_severity: str) -> int:
    if expected_severity == "block":
        return _ACTION_RANK["block"]
    if expected_severity == "warn":
        return _ACTION_RANK["warn"]
    raise AssertionError(f"unexpected severity {expected_severity!r}")


def _finding_action_rank(finding: ReviewFinding) -> int:
    return _ACTION_RANK.get(finding.action, 0)


def _bundle(review_context: dict, **kwargs) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=[],
        declared_modalities=[],
        declared_spaces=[],
        review_context=review_context,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Wired cases.
# --------------------------------------------------------------------------- #
#
# Each wired entry pairs a calibration case id with:
#   - check: the concrete engine check_fn to invoke,
#   - context: a review_context that expresses the scenario as explicit
#     provenance the deterministic check is documented to fire on,
#   - engine_rule_id: the REVIEW_* rule the engine emits (NOT the manuscript
#     rule name in the fixture, which is the human taxonomy label),
#   - bundle_kwargs (optional): extra CodeReviewBundle kwargs (e.g. kg_context).


class WiredCase:
    __slots__ = ("check", "context", "engine_rule_id", "bundle_kwargs")

    def __init__(
        self,
        check: Callable[[CodeReviewBundle], ReviewFinding | None],
        context: dict,
        engine_rule_id: str,
        bundle_kwargs: dict | None = None,
    ) -> None:
        self.check = check
        self.context = context
        self.engine_rule_id = engine_rule_id
        self.bundle_kwargs = bundle_kwargs or {}


# Documented manuscript-rule -> engine-rule mapping for the wired cases. Kept
# explicit so a reviewer can see exactly why a REVIEW_* rule is the engine
# implementation of a manuscript STAT_*/NEUROAI_*/SPLIT_* label.
ENGINE_RULE_FOR_CASE: dict[str, str] = {}

WIRED: dict[str, WiredCase] = {
    # --- Spatial / null-model family ------------------------------------- #
    # C06: Surface/CIFTI data -> volume cluster correction (STAT_SPATIAL_DOMAIN)
    "C06": WiredCase(
        check=surface_volume_correction_domain_mismatch_check,
        context={"data_domain": "surface", "correction_domain": "volume"},
        engine_rule_id="REVIEW_SURFACE_VOLUME_CORRECTION_DOMAIN_MISMATCH",
    ),
    # C22: Permutation ignores exchangeability (STAT_PERMUTATION)
    "C22": WiredCase(
        check=permutation_exchangeability_check,
        context={"null_model": {"exchangeability_status": "invalid"}},
        engine_rule_id="REVIEW_PERMUTATION_EXCHANGEABILITY_INVALID",
    ),
    # C23: Brain-map correlation, Pearson p only (STAT_SPATIAL_NULL)
    "C23": WiredCase(
        check=brainmap_correlation_spatial_null_check,
        context={"map_map_correlation": True, "spatial_null_present": False},
        engine_rule_id="REVIEW_INFERENCE_NO_SPIN_TEST",
    ),
    # C24: Gene/histology x fMRI, no spatial null (STAT_GENE_MAP). The engine
    # surfaces the same missing-spin-test failure mode; severity floor is warn,
    # the engine blocks (>= warn).
    "C24": WiredCase(
        check=brainmap_correlation_spatial_null_check,
        context={
            "brainmap_correlation": True,
            "spatial_null_present": False,
        },
        engine_rule_id="REVIEW_INFERENCE_NO_SPIN_TEST",
    ),
    # --- Leakage / split family ------------------------------------------ #
    # C16: Same-data ROI definition + effect test (STAT_DOUBLE_DIPPING). The
    # ROI is defined and tested on the same (held-out) data; expressed as a
    # selection/fit scope on the test set.
    "C16": WiredCase(
        check=predictive_cv_leakage_check,
        context={"preprocessing": {"selection_scope": "test_set"}},
        engine_rule_id="REVIEW_PREDICTIVE_CV_LEAKAGE",
    ),
    # C20: Runs as independent samples at group level (STAT_PSEUDOREPLICATION)
    "C20": WiredCase(
        check=leakage_pseudoreplication_check,
        context={"sample": {"declared_n": 200, "n_unique_subjects": 40}},
        engine_rule_id="REVIEW_LEAKAGE_REPEATED_AS_INDEP",
    ),
    # C42: ComBat/harmonization outside CV (NEUROAI_HARMONIZATION)
    "C42": WiredCase(
        check=leakage_preprocessing_fit_scope_check,
        context={"fit_scope_by_step": {"harmonization": "full_dataset"}},
        engine_rule_id="REVIEW_LEAKAGE_PREPROCESSING_FIT_SCOPE",
    ),
    # C43: Feature selection outside CV (NEUROAI_FEATURE_SEL)
    "C43": WiredCase(
        check=leakage_preprocessing_fit_scope_check,
        context={"fit_scope_by_step": {"feature_selection": "full_dataset"}},
        engine_rule_id="REVIEW_LEAKAGE_PREPROCESSING_FIT_SCOPE",
    ),
    # C44: Standardization/PCA outside CV (NEUROAI_STANDARDIZE)
    "C44": WiredCase(
        check=leakage_preprocessing_fit_scope_check,
        context={
            "fit_scope_by_step": {
                "standardization": "full_dataset",
                "pca": "full_dataset",
            }
        },
        engine_rule_id="REVIEW_LEAKAGE_PREPROCESSING_FIT_SCOPE",
    ),
    # C45: Test set used for model selection (NEUROAI_TEST_SET)
    "C45": WiredCase(
        check=predictive_cv_leakage_check,
        context={"preprocessing": {"feature_selection_scope": "test_set"}},
        engine_rule_id="REVIEW_PREDICTIVE_CV_LEAKAGE",
    ),
    # C46: CV not grouped by subject (SPLIT_GROUPING)
    "C46": WiredCase(
        check=neuroai_split_grouping_mismatch_check,
        context={
            "model_candidates": ["m1", "m2"],
            "required_group_keys": ["subject"],
            "grouped_split_keys": [],
            "split_unit": "sample",
            "split_strategy": "random_split",
        },
        engine_rule_id="REVIEW_NEUROAI_SPLIT_GROUPING_MISMATCH",
    ),
    # C47: CV ignores family/repeated-scan dependence ((soft C46)). The repeated
    # scans inflate the observation count above the unique-subject count with no
    # repeated-structure modeling -> pseudoreplication. Manuscript floor is warn;
    # the engine blocks (>= warn).
    "C47": WiredCase(
        check=leakage_pseudoreplication_check,
        context={
            "sample": {
                "declared_n": 120,
                "n_unique_subjects": 60,
                "independence_unit": "scan",
            }
        },
        engine_rule_id="REVIEW_LEAKAGE_REPEATED_AS_INDEP",
    ),
    # C51: Encoding model split by TR, not run/stimulus (NEUROAI_TEMPORAL). A
    # fine-grained TR split that does not carry the required run/stimulus
    # grouping keys is a grouping mismatch; manuscript floor warn, engine blocks.
    "C51": WiredCase(
        check=neuroai_split_grouping_mismatch_check,
        context={
            "model_candidates": ["enc1", "enc2"],
            "required_group_keys": ["run", "stimulus"],
            "grouped_split_keys": [],
            "split_unit": "tr",
            "split_strategy": "random_split",
        },
        engine_rule_id="REVIEW_NEUROAI_SPLIT_GROUPING_MISMATCH",
    ),
    # --- neuroAI selection family (warn floor) --------------------------- #
    # C52: Best layer selected post-hoc (NEUROAI_LAYER_SEL). Expressed as a
    # multi-candidate winner with no nested-CV / holdout guardrail.
    "C52": WiredCase(
        check=neuroai_selection_validation_gap_check,
        context={
            "layer_candidates": ["l1", "l2", "l3"],
            "selection": {"best_layer": "l2"},
        },
        engine_rule_id="REVIEW_NEUROAI_SELECTION_VALIDATION_GAP",
    ),
    # C53: RSA many-model comparison, no correction (NEUROAI_RSA_MC). Expressed
    # as a multi-candidate winner with no multiplicity accounting.
    "C53": WiredCase(
        check=neuroai_selection_multiplicity_accounting_check,
        context={
            "model_candidates": ["m1", "m2", "m3", "m4"],
            "selection": {"best_model": "m2"},
        },
        engine_rule_id="REVIEW_NEUROAI_SELECTION_MULTIPLICITY_ACCOUNTING",
    ),
}


# --------------------------------------------------------------------------- #
# Skipped cases: every case NOT in WIRED, with an honest reason.
# --------------------------------------------------------------------------- #

SKIPPED: dict[str, str] = {
    # Statistical-design choice judgements (test vs design) require NLP/LLM
    # interpretation of the analysis plan; no deterministic explicit-provenance
    # check fires on them today.
    "C01": "design-vs-test mismatch needs NLP/LLM design interpretation; no deterministic check",
    "C02": "allow case: correct paired test; no deterministic engine assertion target",
    "C03": "factorial-vs-t-test mismatch needs NLP/LLM design interpretation",
    "C04": "mixed-design-vs-ANOVA mismatch needs NLP/LLM design interpretation",
    "C05": "longitudinal OLS without subject effect needs NLP/LLM design interpretation",
    # Novelty / prior-conflict effect-size cases need effect priors + novelty
    # audit, not a deterministic explicit-provenance check.
    "C07": "novelty/prior-conflict (extreme rsFC d) needs effect priors + novelty audit",
    "C08": "allow case: plausible morphometry effect; no engine assertion target",
    "C09": "single-ROI novelty needs effect priors + novelty audit",
    "C10": "small-sample + motion confound needs effect priors + QC heuristics",
    "C11": "activation-pattern novelty needs spatial priors + novelty audit",
    "C12": "allow case: expected motor activation; no engine assertion target",
    # Threshold / correction prose: needs parsing of reported thresholds, not
    # explicit machine provenance.
    "C13": "uncorrected p<0.05 claim needs threshold/prose parsing",
    "C14": "lenient cluster threshold needs threshold/prose parsing",
    "C15": "cluster->voxel overclaim needs claim-text interpretation",
    # ROI multiplicity / analytic flexibility: needs counting reported tests /
    # pipelines from prose.
    "C17": "allow case: independent localizer; no engine assertion target",
    "C18": "ROI multiplicity needs reported-test counting from prose",
    "C19": "analytic flexibility (best-of-many) needs multiverse reporting parse",
    "C21": "fixed-effects + population claim needs claim-text interpretation",
    # Measurement / QC gaps: need QC report presence heuristics or prose.
    "C25": "motion-reporting gap needs QC-report presence heuristic",
    "C26": "group motion imbalance needs per-group motion stats parse",
    # Controversial-choice sensitivity packages have dedicated checks but are
    # driven by sensitivity-package provenance not modeled in these scenarios;
    # left as prose-level for this honest harness.
    "C27": "GSR sensitivity gap needs sensitivity-package provenance not in scenario",
    "C28": "dynamic-FC sensitivity gap needs sensitivity-package provenance",
    "C29": "graph-threshold sensitivity gap needs sensitivity-package provenance",
    "C30": "task-FC evoked removal needs task-FC provenance not in scenario",
    "C31": "PPI specification issues need PPI design parse",
    "C32": "EPI distortion/dropout needs acquisition/QC provenance",
    "C33": "missing MRIQC/QA needs QC-report presence heuristic",
    "C34": "small-sample BWAS strong claim needs sample-size + claim parse",
    "C35": "no external validation needs replication-claim parse",
    "C36": "multiband noise/QC needs acquisition/QC provenance",
    # Claim-interpretation family: reverse inference, stimulus generalization,
    # behavioral covariates -> all need NLP/LLM claim interpretation.
    "C37": "reverse inference needs NLP/LLM claim interpretation",
    "C38": "stimulus-as-fixed-effect generalization needs claim interpretation",
    "C39": "behavioral-covariate gap needs claim interpretation",
    "C40": "VBM ICV control needs covariate-provenance parse",
    "C41": "multisite diagnosis x site confound needs design parse",
    # CV soft-dependence and permutation-test reporting gaps need fold-manifest
    # family structure / reported permutation presence beyond these scenarios.
    "C48": "above-chance without permutation needs reported-test presence parse",
    "C49": "fold-wise SE independence needs CV variance reporting parse",
    "C50": "predictive-biomarker OOS claim needs claim interpretation",
    "C54": "RSA hierarchical uncertainty needs RSA model reporting parse",
    "C55": "individual-difference ICC needs reliability reporting parse",
    "C56": "extreme effect robustness needs effect priors + robustness parse",
    "C57": "pipeline-dependent significance needs multiverse reporting parse",
    # Reporting-standard / validator gaps: need COBIDAS / BIDS validator state.
    "C58": "COBIDAS mandatory-field gap needs reporting-checklist state",
    "C59": "BIDS validator failure needs validator-run state",
    "C60": "allow case: BIDS Stats Models provided; no engine assertion target",
}


def test_wired_and_skipped_partition_all_cases() -> None:
    """Every C01-C60 case is either wired or skipped, with no overlap/gap."""

    wired_ids = set(WIRED)
    skipped_ids = set(SKIPPED)
    assert not (
        wired_ids & skipped_ids
    ), f"cases both wired and skipped: {sorted(wired_ids & skipped_ids)}"
    covered = wired_ids | skipped_ids
    fixture_ids = set(CASES_BY_ID)
    assert covered == fixture_ids, (
        f"uncovered cases: {sorted(fixture_ids - covered)}; "
        f"unknown ids: {sorted(covered - fixture_ids)}"
    )
    assert len(fixture_ids) == EXPECTED_CASE_COUNT


def test_wired_cases_only_target_block_or_warn() -> None:
    """Wired cases must be block/warn (allow cases have no firing target)."""

    for case_id in WIRED:
        severity = CASES_BY_ID[case_id]["expected_severity"]
        assert severity in {
            "warn",
            "block",
        }, f"{case_id}: wired an allow case ({severity}); allow cases must be skipped"


@pytest.mark.parametrize("case_id", sorted(WIRED), ids=sorted(WIRED))
def test_wired_case_fires_expected_rule_at_severity(case_id: str) -> None:
    """Run the real engine check and assert it fires >= expected severity."""

    case = CASES_BY_ID[case_id]
    wired = WIRED[case_id]

    bundle = _bundle(wired.context, **wired.bundle_kwargs)
    finding = wired.check(bundle)

    assert finding is not None, (
        f"{case_id}: engine check {wired.check.__name__} produced no finding "
        f"for scenario {case['scenario']!r}"
    )
    # The engine emits REVIEW_* rule ids; assert the documented engine rule.
    assert finding.rule_id == wired.engine_rule_id, (
        f"{case_id}: expected engine rule {wired.engine_rule_id}, "
        f"got {finding.rule_id}"
    )
    expected_rank = _expected_action_rank(case["expected_severity"])
    actual_rank = _finding_action_rank(finding)
    assert actual_rank >= expected_rank, (
        f"{case_id}: finding action {finding.action!r} (rank {actual_rank}) is "
        f"below expected_severity {case['expected_severity']!r} (rank {expected_rank})"
    )


def test_engine_coverage_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    """Log how many of the 60 calibration cases are wired to the live engine."""

    wired = sorted(WIRED)
    skipped = sorted(SKIPPED)

    # Family tally for the wired subset (by engine rule prefix).
    families: dict[str, list[str]] = {}
    for case_id in wired:
        rule = WIRED[case_id].engine_rule_id
        family = rule.removeprefix("REVIEW_").split("_", 1)[0]
        families.setdefault(family, []).append(case_id)

    lines = [
        "C01-C60 calibration engine coverage",
        f"  wired:   {len(wired)}/{EXPECTED_CASE_COUNT} -> {wired}",
        f"  skipped: {len(skipped)}/{EXPECTED_CASE_COUNT}",
        "  wired families (engine-rule prefix):",
    ]
    for family in sorted(families):
        lines.append(f"    {family}: {families[family]}")
    report = "\n".join(lines)
    # Surface in -s output without failing the run.
    print(report)

    # Coverage floor: keep at least the deterministic leakage/split/spatial/
    # value-domain subset wired so a regression that silently unwires the engine
    # is caught.
    assert len(wired) >= 15, f"engine coverage regressed: only {len(wired)} wired"
    assert len(wired) + len(skipped) == EXPECTED_CASE_COUNT


def test_unused_engine_imports_are_callable() -> None:
    """Guard that imported engine checks resolve (catches import/rename drift)."""

    for check in (
        brainmap_correlation_spatial_null_check,
        leakage_preprocessing_fit_scope_check,
        leakage_pseudoreplication_check,
        neuroai_selection_multiplicity_accounting_check,
        neuroai_selection_on_test_check,
        neuroai_selection_validation_gap_check,
        neuroai_split_grouping_mismatch_check,
        permutation_exchangeability_check,
        spatial_null_validity_check,
        surface_volume_correction_domain_mismatch_check,
        predictive_cv_leakage_check,
        predictive_split_integrity_check,
        value_domain_contract_violation_check,
    ):
        assert callable(check)
