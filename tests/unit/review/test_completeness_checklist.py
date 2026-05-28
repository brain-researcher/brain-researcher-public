"""Unit tests for expanded completeness checklist (P1).

These cover the new check functions added in
``brain_researcher.services.review.checks.completeness`` and exercise the
``build_completeness_checklist`` rollup for both the default-profile and
named-profile paths.
"""

from __future__ import annotations

from brain_researcher.core.contracts.code_review import CodeReviewBundle
from brain_researcher.services.review.checks.completeness import (
    autocorrelation_model_declared,
    build_completeness_checklist,
    cluster_table_declared,
    confound_columns_declared,
    contrast_table_declared,
    correction_summary_declared,
    design_matrix_declared,
    hrf_model_declared,
    nested_cv_structure_declared,
    peak_table_declared,
    sensitivity_package_declared,
    subject_manifest_declared,
)


def _bundle(review_context: dict | None = None, **observed: object) -> CodeReviewBundle:
    """Construct a CodeReviewBundle from a flat review_context + observed artifacts."""
    observed_artifacts: dict = {}
    if review_context is not None:
        observed_artifacts["analysis_bundle"] = {"review_context": review_context}
    observed_artifacts.update(observed)
    return CodeReviewBundle(observed_artifacts=observed_artifacts)


def _glm_fmri_review_context() -> dict:
    """A review_context with every GLM/fMRI completeness item declared."""
    return {
        "subject_manifest_path": "manifests/subjects.json",
        "subject_alignment_status": "aligned",
        "split": {
            "subject_manifest_path": "manifests/subjects.json",
            "n_subjects": 30,
        },
        "preprocessing": {
            "confound_columns": ["csf", "white_matter", "trans_x"],
            "feature_selection_scope": "train_only",
        },
        "design_model": {
            "hrf_model": "glover",
            "autocorrelation_model": "AR(1)",
            "design_matrix_path": "stats/design_matrix.tsv",
        },
        "statistical_inference": {
            "contrast_table_path": "stats/contrast_table.tsv",
            "correction_summary_path": "stats/correction_summary.json",
            "cluster_table_path": "stats/cluster_table.tsv",
            "peak_table_path": "stats/peak_table.tsv",
        },
        "sensitivity": {
            "sensitivity_requirements": ["alt_hrf", "alt_threshold"],
        },
    }


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------


class TestHrfModelDeclared:
    def test_declared_in_design_model(self):
        bundle = _bundle({"design_model": {"hrf_model": "glover"}})
        assert hrf_model_declared(bundle) is True

    def test_absent(self):
        bundle = _bundle({"design_model": {}})
        assert hrf_model_declared(bundle) is False


class TestAutocorrelationModelDeclared:
    def test_declared_autocorrelation_model(self):
        bundle = _bundle({"design_model": {"autocorrelation_model": "AR(1)"}})
        assert autocorrelation_model_declared(bundle) is True

    def test_declared_noise_model_alias(self):
        bundle = _bundle({"design_model": {"noise_model": "ar1"}})
        assert autocorrelation_model_declared(bundle) is True

    def test_absent(self):
        bundle = _bundle({"design_model": {"hrf_model": "glover"}})
        assert autocorrelation_model_declared(bundle) is False


class TestDesignMatrixDeclared:
    def test_declared_via_review_context(self):
        bundle = _bundle({"design_model": {"design_matrix_path": "d.tsv"}})
        assert design_matrix_declared(bundle) is True

    def test_declared_via_analysis_bundle_files(self):
        bundle = _bundle(
            None,
            analysis_bundle={"files": {"design_matrix": "out/design.tsv"}},
        )
        assert design_matrix_declared(bundle) is True

    def test_declared_via_observation_files(self):
        bundle = _bundle(
            None,
            observation={"files": {"design_matrix": "out/design.tsv"}},
        )
        assert design_matrix_declared(bundle) is True

    def test_absent(self):
        bundle = _bundle({"design_model": {}})
        assert design_matrix_declared(bundle) is False


class TestContrastTableDeclared:
    def test_declared_via_review_context(self):
        bundle = _bundle(
            {"statistical_inference": {"contrast_table_path": "c.tsv"}}
        )
        assert contrast_table_declared(bundle) is True

    def test_declared_via_analysis_bundle_files(self):
        bundle = _bundle(
            None, analysis_bundle={"files": {"contrast_table": "c.tsv"}}
        )
        assert contrast_table_declared(bundle) is True

    def test_absent(self):
        bundle = _bundle({"statistical_inference": {}})
        assert contrast_table_declared(bundle) is False


class TestCorrectionSummaryDeclared:
    def test_declared_via_review_context(self):
        bundle = _bundle(
            {"statistical_inference": {"correction_summary_path": "cs.json"}}
        )
        assert correction_summary_declared(bundle) is True

    def test_declared_via_threshold_summary_alias(self):
        bundle = _bundle(
            {"statistical_inference": {"threshold_summary_path": "ts.json"}}
        )
        assert correction_summary_declared(bundle) is True

    def test_declared_via_analysis_bundle_files(self):
        bundle = _bundle(
            None,
            analysis_bundle={"files": {"correction_summary_json": "cs.json"}},
        )
        assert correction_summary_declared(bundle) is True

    def test_absent(self):
        bundle = _bundle({"statistical_inference": {}})
        assert correction_summary_declared(bundle) is False


class TestClusterTableDeclared:
    def test_declared_via_review_context(self):
        bundle = _bundle(
            {"statistical_inference": {"cluster_table_path": "clusters.tsv"}}
        )
        assert cluster_table_declared(bundle) is True

    def test_declared_via_analysis_bundle_files(self):
        bundle = _bundle(
            None, analysis_bundle={"files": {"cluster_table": "clusters.tsv"}}
        )
        assert cluster_table_declared(bundle) is True

    def test_absent(self):
        bundle = _bundle({"statistical_inference": {}})
        assert cluster_table_declared(bundle) is False


class TestPeakTableDeclared:
    def test_declared_via_review_context(self):
        bundle = _bundle(
            {"statistical_inference": {"peak_table_path": "peaks.tsv"}}
        )
        assert peak_table_declared(bundle) is True

    def test_declared_via_analysis_bundle_files(self):
        bundle = _bundle(
            None, analysis_bundle={"files": {"peak_table": "peaks.tsv"}}
        )
        assert peak_table_declared(bundle) is True

    def test_absent(self):
        bundle = _bundle({"statistical_inference": {}})
        assert peak_table_declared(bundle) is False


class TestConfoundColumnsDeclared:
    def test_declared_in_preprocessing(self):
        bundle = _bundle(
            {"preprocessing": {"confound_columns": ["csf", "white_matter"]}}
        )
        assert confound_columns_declared(bundle) is True

    def test_declared_in_design_model(self):
        bundle = _bundle(
            {"design_model": {"nuisance_regressors": ["trans_x", "trans_y"]}}
        )
        assert confound_columns_declared(bundle) is True

    def test_empty_list_is_not_declared(self):
        bundle = _bundle({"preprocessing": {"confound_columns": []}})
        assert confound_columns_declared(bundle) is False

    def test_absent(self):
        bundle = _bundle({"preprocessing": {}})
        assert confound_columns_declared(bundle) is False


class TestNestedCvStructureDeclared:
    def test_declared_with_outer_inner_cv(self):
        bundle = _bundle(
            {
                "selection": {
                    "nested_cv": True,
                    "outer_cv": {"n_folds": 5},
                    "inner_cv": {"n_folds": 3},
                }
            }
        )
        assert nested_cv_structure_declared(bundle) is True

    def test_nested_cv_flag_alone_is_not_enough(self):
        bundle = _bundle({"selection": {"nested_cv": True}})
        assert nested_cv_structure_declared(bundle) is False

    def test_nested_cv_dict_with_inline_structure(self):
        bundle = _bundle(
            {
                "selection": {
                    "nested_cv": {"inner_folds": 3, "outer_folds": 5},
                }
            }
        )
        assert nested_cv_structure_declared(bundle) is True

    def test_absent(self):
        bundle = _bundle({"selection": {}})
        assert nested_cv_structure_declared(bundle) is False


class TestSubjectManifestDeclared:
    def test_declared_via_split_manifest_path(self):
        bundle = _bundle(
            {"split": {"subject_manifest_path": "manifests/subjects.json"}}
        )
        assert subject_manifest_declared(bundle) is True

    def test_declared_via_subject_counts(self):
        bundle = _bundle(
            {"split": {"n_subjects_train": 20, "n_subjects_test": 10}}
        )
        assert subject_manifest_declared(bundle) is True

    def test_absent(self):
        bundle = _bundle({"split": {}})
        assert subject_manifest_declared(bundle) is False


class TestSensitivityPackageDeclared:
    def test_declared_with_sensitivity_requirements(self):
        bundle = _bundle(
            {"sensitivity": {"sensitivity_requirements": ["alt_hrf"]}}
        )
        assert sensitivity_package_declared(bundle) is True

    def test_declared_with_robustness_checks(self):
        bundle = _bundle(
            {"sensitivity": {"robustness_checks": ["alt_threshold"]}}
        )
        assert sensitivity_package_declared(bundle) is True

    def test_empty_list_is_not_declared(self):
        bundle = _bundle({"sensitivity": {"sensitivity_requirements": []}})
        assert sensitivity_package_declared(bundle) is False

    def test_absent(self):
        bundle = _bundle({"sensitivity": {}})
        assert sensitivity_package_declared(bundle) is False


# ---------------------------------------------------------------------------
# build_completeness_checklist integration
# ---------------------------------------------------------------------------


class TestBuildCompletenessChecklist:
    def test_glm_fmri_profile_all_declared(self):
        review_context = _glm_fmri_review_context()
        bundle = CodeReviewBundle(
            observed_artifacts={
                "review_contract": {
                    "scientific_review_profile": "glm_fmri_review",
                },
                "analysis_bundle": {"review_context": review_context},
            }
        )
        checklist = build_completeness_checklist(bundle)
        expected_keys = {
            "random_seed_pinned",
            "atlas_version_pinned",
            "subject_alignment_declared",
            "preprocessing_choices_declared",
            "confound_columns_declared",
            "hrf_model_declared",
            "autocorrelation_model_declared",
            "design_matrix_declared",
            "contrast_table_declared",
            "correction_summary_declared",
            "cluster_table_declared",
            "peak_table_declared",
            "sensitivity_package_declared",
        }
        assert set(checklist.keys()) == expected_keys
        for key, value in checklist.items():
            assert value is True, f"expected {key} True, got False"

    def test_glm_fmri_profile_missing_hrf(self):
        review_context = _glm_fmri_review_context()
        review_context["design_model"].pop("hrf_model")
        bundle = CodeReviewBundle(
            observed_artifacts={
                "review_contract": {
                    "scientific_review_profile": "glm_fmri_review",
                },
                "analysis_bundle": {"review_context": review_context},
            }
        )
        checklist = build_completeness_checklist(bundle)
        assert checklist["hrf_model_declared"] is False
        for key, value in checklist.items():
            if key == "hrf_model_declared":
                continue
            assert value is True, f"expected {key} True, got False"

    def test_predictive_profile_includes_nested_cv_keys(self):
        bundle = CodeReviewBundle(
            observed_artifacts={
                "review_contract": {
                    "scientific_review_profile": "predictive_model_review",
                }
            }
        )
        checklist = build_completeness_checklist(bundle)
        assert "nested_cv_structure_declared" in checklist
        assert "subject_manifest_declared" in checklist
        assert "sensitivity_package_declared" in checklist

    def test_default_profile_still_three_keys(self):
        bundle = CodeReviewBundle(
            observed_artifacts={"review_contract": {}}
        )
        checklist = build_completeness_checklist(bundle)
        assert set(checklist.keys()) == {
            "random_seed_pinned",
            "atlas_version_pinned",
            "ordering_rule_declared",
        }
