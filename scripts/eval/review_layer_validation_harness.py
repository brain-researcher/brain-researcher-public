#!/usr/bin/env python3
"""Build and score review-layer validation mutations.

The harness uses the production run manifest as the sampling frame, then applies
controlled, labeled review-context/artifact mutations to clean base bundles.
It is intentionally separate from prod artifact export: when full prod bundles
are available they can replace the minimal base bundles without changing the
case/result/summary schema.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding
from brain_researcher.services.review.checks.artifact_structure import (
    contrast_estimability_check,
    design_matrix_rank_check,
    design_model_metadata_consistency_check,
)
from brain_researcher.services.review.checks.claim_validity import (
    claim_inflation_check,
    construct_validity_confound_check,
    reverse_inference_risk_check,
)
from brain_researcher.services.review.checks.neuroai_validity import (
    neuroai_selection_on_test_check,
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
from brain_researcher.services.review.checks.sensitivity_packages import (
    dynamic_fc_sensitivity_package_check,
    graph_atlas_hrf_sensitivity_package_check,
    gsr_sensitivity_package_check,
)

MutationFn = Callable[[dict[str, Any]], dict[str, Any]]
CheckFn = Callable[[CodeReviewBundle], ReviewFinding | None]

CHECKS: tuple[CheckFn, ...] = (
    design_matrix_rank_check,
    contrast_estimability_check,
    predictive_cv_leakage_check,
    predictive_split_integrity_check,
    neuroai_selection_on_test_check,
    neuroai_split_grouping_mismatch_check,
    permutation_exchangeability_check,
    spatial_null_validity_check,
    surface_volume_correction_domain_mismatch_check,
    design_model_metadata_consistency_check,
    construct_validity_confound_check,
    claim_inflation_check,
    reverse_inference_risk_check,
    gsr_sensitivity_package_check,
    dynamic_fc_sensitivity_package_check,
    graph_atlas_hrf_sensitivity_package_check,
)

DEFAULT_EXPECTED_RULE_IDS: dict[str, tuple[str, ...]] = {
    "design_matrix_rank": (
        "REVIEW_DESIGN_MATRIX_RANK_DEFICIENT",
        "REVIEW_CONTRAST_NOT_ESTIMABLE",
    ),
    "cv_split_leakage": (
        "REVIEW_PREDICTIVE_CV_LEAKAGE",
        "REVIEW_PREDICTIVE_SPLIT_INTEGRITY",
        "REVIEW_NEUROAI_SELECTION_ON_TEST",
    ),
    "preprocessing_leakage": ("REVIEW_PREDICTIVE_CV_LEAKAGE",),
    "null_model_spatial": (
        "REVIEW_PERMUTATION_EXCHANGEABILITY_INVALID",
        "REVIEW_SPATIAL_NULL_INVALID",
    ),
    "correction_domain": ("REVIEW_SURFACE_VOLUME_CORRECTION_DOMAIN_MISMATCH",),
    "design_model_metadata": ("REVIEW_DESIGN_MODEL_METADATA_MISMATCH",),
    "construct_confound": ("REVIEW_CONSTRUCT_VALIDITY_CONFOUND",),
    "claim_inflation": (
        "REVIEW_CLAIM_INFLATION",
        "REVIEW_REVERSE_INFERENCE_RISK",
        "REVIEW_GSR_SENSITIVITY_PACKAGE",
    ),
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _run_id(row: Mapping[str, Any]) -> str:
    return str(row.get("run_id") or "").strip()


def _minimal_clean_bundle(run_meta: Mapping[str, Any]) -> dict[str, Any]:
    """Return a high-specificity clean base bundle for false-positive controls."""

    primary_tool = str(run_meta.get("primary_tool") or "")
    route = str(run_meta.get("route") or "")
    return {
        "run_id": _run_id(run_meta),
        "workflow_id": primary_tool if route == "pipeline_execute" else None,
        "plan_steps": [
            {
                "step_id": "step_001",
                "tool": primary_tool or "review_validation_control",
                "params": {"tr": 2.0, "fwhm": 6.0},
            }
        ],
        "declared_modalities": ["fmri"],
        "declared_spaces": ["MNI152"],
        "stats_metrics": {
            "design_matrix_rank": 3,
            "design_matrix_ncols": 3,
            "contrast_dims": 3,
            "contrast_estimable": True,
            "design_matrix_condition_number": 25.0,
            "mean_fd": 0.12,
            "scrubbing_fraction": 0.03,
            "r_squared": 0.35,
            "cohens_d_max": 0.45,
            "observed_hrf_model": "canonical",
            "observed_basis_set": "spm",
            "observed_autocorrelation_model": "ar1",
            "observed_temporal_derivative": False,
            "observed_dispersion_derivative": False,
        },
        "review_context": {
            "scientific_review_profile": "glm_fmri_review",
            "design_model": {
                "hrf_model": "canonical",
                "basis_set": "spm",
                "autocorrelation_model": "ar1",
                "temporal_derivative": False,
                "dispersion_derivative": False,
            },
            "preprocessing": {
                "confounds": ["motion", "wm_csf"],
            },
            "null_model": {
                "permutation_manifest": {
                    "scheme": "restricted",
                    "exchangeability_status": "valid",
                    "blocks": ["subject"],
                },
                "spatial_null": {"method": "spin_test", "valid": True},
            },
            "construct_validity": {
                "behavioral_imbalance": {},
                "controlled_covariates": [],
            },
            "sensitivity": {
                "robustness_checks": [
                    "threshold_sweep",
                    "atlas variant",
                    "basis sensitivity",
                ],
            },
        },
        "observed_artifacts": {
            "claim_report": {
                "claims": [
                    {
                        "claim_text": (
                            "The fitted GLM is consistent with the declared task contrast."
                        )
                    }
                ]
            }
        },
        "kg_context": {"analysis_family": "glm"},
    }


def _mutation_design_matrix_rank(bundle: dict[str, Any]) -> dict[str, Any]:
    mutated = copy.deepcopy(bundle)
    metrics = mutated.setdefault("stats_metrics", {})
    metrics.update(
        {
            "design_matrix_rank": 2,
            "design_matrix_ncols": 3,
            "contrast_estimable": False,
        }
    )
    return mutated


def _mutation_cv_split_leakage(bundle: dict[str, Any]) -> dict[str, Any]:
    mutated = copy.deepcopy(bundle)
    context = mutated.setdefault("review_context", {})
    context["scientific_review_profile"] = "predictive_model_review"
    context["preprocessing"] = {
        "feature_selection_scope": "full_dataset",
        "standardization_scope": "train_only",
    }
    context["split"] = {
        "split_unit": "subject",
        "train_subject_ids": ["sub-01", "sub-02"],
        "test_subject_ids": ["sub-02", "sub-03"],
        "train_test_independence": True,
    }
    context["selection"] = {
        "selection_on_test": True,
        "selection_scope": "heldout",
        "best_model": "layer-12",
    }
    mutated["kg_context"] = {"analysis_family": "embedding_analysis"}
    return mutated


def _mutation_preprocessing_leakage(bundle: dict[str, Any]) -> dict[str, Any]:
    mutated = copy.deepcopy(bundle)
    context = mutated.setdefault("review_context", {})
    context["scientific_review_profile"] = "predictive_model_review"
    context["preprocessing"] = {
        "feature_selection_scope": "train_only",
        "standardization_scope": "full_dataset",
        "harmonization_fit_scope": "outside_cv",
    }
    return mutated


def _mutation_null_model_spatial(bundle: dict[str, Any]) -> dict[str, Any]:
    mutated = copy.deepcopy(bundle)
    mutated["review_context"]["null_model"] = {
        "permutation_manifest": {
            "scheme": "unrestricted",
            "exchangeability_status": "violated",
            "blocks": ["subject"],
        },
        "spatial_null": {
            "method": "spin_test",
            "valid": False,
            "domain": "surface",
        },
    }
    return mutated


def _mutation_correction_domain(bundle: dict[str, Any]) -> dict[str, Any]:
    mutated = copy.deepcopy(bundle)
    context = mutated.setdefault("review_context", {})
    context.update(
        {
            "data_domain": "surface",
            "analysis_domain": "surface",
            "correction_domain": "volume",
            "cluster_correction_domain": "volume",
        }
    )
    context["null_model"] = {
        "analysis_domain": "surface",
        "correction_domain": "volume",
    }
    return mutated


def _mutation_design_model_metadata(bundle: dict[str, Any]) -> dict[str, Any]:
    mutated = copy.deepcopy(bundle)
    context = mutated.setdefault("review_context", {})
    context["design_model"] = {
        "hrf_model": "canonical",
        "basis_set": "spm",
        "autocorrelation_model": "ar1",
        "temporal_derivative": False,
    }
    metrics = mutated.setdefault("stats_metrics", {})
    metrics.update(
        {
            "observed_hrf_model": "fir",
            "observed_basis_set": "fir",
            "observed_autocorrelation_model": "none",
            "observed_temporal_derivative": True,
        }
    )
    return mutated


def _mutation_construct_confound(bundle: dict[str, Any]) -> dict[str, Any]:
    mutated = copy.deepcopy(bundle)
    mutated["review_context"]["construct_validity"] = {
        "behavioral_imbalance": {
            "reaction_time": "large_group_difference",
            "difficulty": True,
        },
        "controlled_covariates": [],
    }
    return mutated


def _mutation_claim_inflation(bundle: dict[str, Any]) -> dict[str, Any]:
    mutated = copy.deepcopy(bundle)
    mutated["review_context"]["preprocessing"] = {"confounds": ["motion", "wm_csf", "gsr"]}
    mutated["observed_artifacts"] = {
        "claim_report": {
            "claims": [
                {
                    "claim_text": (
                        "TPJ activation indicates mentalizing and predicts cognition "
                        "as the causal mechanism."
                    )
                },
                {
                    "claim_text": (
                        "Because the encoding model fits best, the brain uses the "
                        "same algorithm."
                    ),
                    "claim_type": "mechanistic",
                },
            ]
        }
    }
    mutated["kg_context"] = {"analysis_family": "neural_encoding_prediction"}
    return mutated


MUTATIONS: dict[str, MutationFn] = {
    "design_matrix_rank": _mutation_design_matrix_rank,
    "cv_split_leakage": _mutation_cv_split_leakage,
    "preprocessing_leakage": _mutation_preprocessing_leakage,
    "null_model_spatial": _mutation_null_model_spatial,
    "correction_domain": _mutation_correction_domain,
    "design_model_metadata": _mutation_design_model_metadata,
    "construct_confound": _mutation_construct_confound,
    "claim_inflation": _mutation_claim_inflation,
}


def _rule_ids(findings: Iterable[ReviewFinding]) -> list[str]:
    return sorted({finding.rule_id for finding in findings})


def evaluate_bundle(bundle_payload: Mapping[str, Any]) -> list[ReviewFinding]:
    bundle = CodeReviewBundle.model_validate(bundle_payload)
    findings = []
    for check in CHECKS:
        finding = check(bundle)
        if finding is not None:
            findings.append(finding)
    return findings


def build_validation_cases(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    run_sets = manifest.get("run_sets") if isinstance(manifest.get("run_sets"), dict) else {}
    controls = _as_list(run_sets.get("control_60"))
    mutation_bases = _as_list(run_sets.get("mutation_base_20"))
    natural_bad = _as_list(run_sets.get("natural_bad_12"))
    family_specs = _as_list(manifest.get("fault_injection_families"))

    cases: list[dict[str, Any]] = []
    for index, run_meta in enumerate(controls, start=1):
        if not isinstance(run_meta, Mapping) or not _run_id(run_meta):
            continue
        cases.append(
            {
                "case_id": f"control_{index:03d}",
                "case_type": "control",
                "run_id": _run_id(run_meta),
                "source_set": "control_60",
                "expected_rule_ids": [],
                "expected_decision": "no_findings",
                "bundle": _minimal_clean_bundle(run_meta),
            }
        )

    for family in family_specs:
        if not isinstance(family, Mapping):
            continue
        family_id = str(family.get("family_id") or "").strip()
        mutation = MUTATIONS.get(family_id)
        if mutation is None:
            continue
        expected_rule_ids = list(DEFAULT_EXPECTED_RULE_IDS[family_id])
        registry_expected_rule_ids = [
            str(item) for item in _as_list(family.get("expected_rule_ids"))
        ]
        for index, run_meta in enumerate(mutation_bases, start=1):
            if not isinstance(run_meta, Mapping) or not _run_id(run_meta):
                continue
            base = _minimal_clean_bundle(run_meta)
            cases.append(
                {
                    "case_id": f"{family_id}_{index:03d}",
                    "case_type": "mutation",
                    "family_id": family_id,
                    "family_label": family.get("label"),
                    "target_level": family.get("target_level"),
                    "run_id": _run_id(run_meta),
                    "source_set": "mutation_base_20",
                    "expected_rule_ids": expected_rule_ids,
                    "registry_expected_rule_ids": registry_expected_rule_ids,
                    "expected_decision": "finding",
                    "bundle": mutation(base),
                }
            )

    for index, run_meta in enumerate(natural_bad, start=1):
        if not isinstance(run_meta, Mapping) or not _run_id(run_meta):
            continue
        code_decision = run_meta.get("code_review_decision")
        scientific_decision = run_meta.get("scientific_review_overall")
        cases.append(
            {
                "case_id": f"natural_bad_{index:03d}",
                "case_type": "natural_bad_regression",
                "run_id": _run_id(run_meta),
                "source_set": "natural_bad_12",
                "evaluation_mode": "manifest_existing_verdict",
                "expected_decision": "non_proceed_or_block",
                "expected_rule_ids": list(run_meta.get("code_review_rule_ids") or []),
                "manifest_decisions": {
                    "code_review_decision": code_decision,
                    "scientific_review_overall": scientific_decision,
                    "scientific_review_judgment": run_meta.get("scientific_review_judgment"),
                },
                "caught_by_manifest": (
                    code_decision == "block"
                    or scientific_decision in {"diagnose", "explore_more", "stop_with_rationale"}
                ),
            }
        )

    return cases


def evaluate_case(case: Mapping[str, Any]) -> dict[str, Any]:
    case_type = str(case.get("case_type") or "")
    if case_type == "natural_bad_regression":
        caught = bool(case.get("caught_by_manifest"))
        return {
            "case_id": case.get("case_id"),
            "case_type": case_type,
            "run_id": case.get("run_id"),
            "evaluation_mode": "manifest_existing_verdict",
            "expected_rule_ids": case.get("expected_rule_ids") or [],
            "actual_rule_ids": [],
            "caught": caught,
            "false_positive": False,
            "finding_count": 0,
        }

    bundle = case.get("bundle")
    if not isinstance(bundle, Mapping):
        raise ValueError(f"Case has no bundle payload: {case.get('case_id')}")
    findings = evaluate_bundle(bundle)
    actual_rule_ids = _rule_ids(findings)
    expected_rule_ids = [str(item) for item in _as_list(case.get("expected_rule_ids"))]
    expected_set = set(expected_rule_ids)
    actual_set = set(actual_rule_ids)
    caught = bool(expected_set & actual_set) if expected_set else not actual_set
    false_positive = case_type == "control" and bool(actual_rule_ids)
    return {
        "case_id": case.get("case_id"),
        "case_type": case_type,
        "family_id": case.get("family_id"),
        "family_label": case.get("family_label"),
        "target_level": case.get("target_level"),
        "run_id": case.get("run_id"),
        "evaluation_mode": "deterministic_bundle_checks",
        "expected_rule_ids": expected_rule_ids,
        "actual_rule_ids": actual_rule_ids,
        "caught": caught,
        "false_positive": false_positive,
        "finding_count": len(findings),
        "findings": [finding.model_dump() for finding in findings],
    }


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float | None]:
    if total <= 0:
        return [None, None]
    p = successes / total
    denom = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total) / denom
    return [max(0.0, center - margin), min(1.0, center + margin)]


def _rate(successes: int, total: int) -> float | None:
    return successes / total if total else None


def summarize_results(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_family: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_level: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for result in results:
        case_type = str(result.get("case_type") or "")
        by_type[case_type].append(result)
        family_id = str(result.get("family_id") or "")
        if family_id:
            by_family[family_id].append(result)
        target_level = str(result.get("target_level") or "")
        if target_level:
            by_level[target_level].append(result)

    controls = by_type.get("control", [])
    mutations = by_type.get("mutation", [])
    natural = by_type.get("natural_bad_regression", [])
    false_positives = sum(1 for result in controls if result.get("false_positive"))
    true_negatives = len(controls) - false_positives
    caught_mutations = sum(1 for result in mutations if result.get("caught"))
    natural_caught = sum(1 for result in natural if result.get("caught"))

    family_metrics = {}
    for family_id, rows in sorted(by_family.items()):
        caught = sum(1 for row in rows if row.get("caught"))
        family_metrics[family_id] = {
            "n": len(rows),
            "caught": caught,
            "catch_rate": _rate(caught, len(rows)),
            "catch_rate_ci95_wilson": _wilson_interval(caught, len(rows)),
        }

    level_metrics = {}
    for target_level, rows in sorted(by_level.items()):
        caught = sum(1 for row in rows if row.get("caught"))
        level_metrics[target_level] = {
            "n": len(rows),
            "caught": caught,
            "catch_rate": _rate(caught, len(rows)),
            "catch_rate_ci95_wilson": _wilson_interval(caught, len(rows)),
        }

    return {
        "schema_version": "br.review_layer_validation.summary.v1",
        "total_cases": len(results),
        "case_type_counts": dict(sorted(Counter(str(r.get("case_type") or "") for r in results).items())),
        "control_false_positives": false_positives,
        "control_false_positive_rate": _rate(false_positives, len(controls)),
        "control_false_positive_rate_ci95_wilson": _wilson_interval(
            false_positives,
            len(controls),
        ),
        "control_true_negatives": true_negatives,
        "control_specificity": _rate(true_negatives, len(controls)),
        "control_specificity_ci95_wilson": _wilson_interval(true_negatives, len(controls)),
        "mutation_cases": len(mutations),
        "mutation_caught": caught_mutations,
        "mutation_sensitivity": _rate(caught_mutations, len(mutations)),
        "mutation_sensitivity_ci95_wilson": _wilson_interval(
            caught_mutations,
            len(mutations),
        ),
        "natural_bad_regression_cases": len(natural),
        "natural_bad_manifest_caught": natural_caught,
        "natural_bad_manifest_catch_rate": _rate(natural_caught, len(natural)),
        "family_metrics": family_metrics,
        "level_metrics": level_metrics,
    }


def run_harness(manifest_path: Path) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    cases = build_validation_cases(manifest)
    results = [evaluate_case(case) for case in cases]
    return {
        "cases": cases,
        "results": results,
        "summary": summarize_results(results),
    }


def main() -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=root
        / "benchmarks"
        / "review_layer_validation"
        / "prod_run_manifest.v1.json",
    )
    parser.add_argument(
        "--out-cases-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "review_layer_validation"
        / "review_layer_validation_cases.v1.jsonl",
    )
    parser.add_argument(
        "--out-results-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "review_layer_validation"
        / "review_layer_validation_results.v1.jsonl",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=root
        / "benchmarks"
        / "review_layer_validation"
        / "review_layer_validation_summary.v1.json",
    )
    args = parser.parse_args()

    payload = run_harness(args.manifest)
    _write_jsonl(args.out_cases_jsonl, payload["cases"])
    _write_jsonl(args.out_results_jsonl, payload["results"])
    _write_json(args.summary_json, payload["summary"])
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
