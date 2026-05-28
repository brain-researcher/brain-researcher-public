"""Unit tests for three-verdict scientific review (Phase 3)."""

from __future__ import annotations

import json

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding
from brain_researcher.core.contracts.scientific_review import (
    CompletenessVerdict,
    CorrectnessVerdict,
    JudgmentVerdict,
    roll_up_scientific_decision,
)

# ---------------------------------------------------------------------------
# Artifact structure checks (correctness)
# ---------------------------------------------------------------------------


class TestArtifactStructure:
    def test_design_matrix_confound_column_consistency_flags_missing_declared_columns(
        self,
    ):
        from brain_researcher.services.review.checks.artifact_structure import (
            design_matrix_confound_column_consistency_check,
        )

        bundle = CodeReviewBundle(
            review_context={
                "preprocessing": {
                    "confound_columns": ["age", "site"],
                }
            },
            stats_metrics={
                "design_matrix_columns": ["intercept", "age", "sex"],
            },
        )
        finding = design_matrix_confound_column_consistency_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_DESIGN_MATRIX_CONFOUND_COLUMNS_MISMATCH"
        assert finding.severity == "error"
        assert finding.action == "block"
        assert finding.reason_tags == ["confound", "null_mismatch"]

    def test_multiple_comparison_metadata_consistency_flags_mismatch(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            multiple_comparison_metadata_consistency_check,
        )

        bundle = CodeReviewBundle(
            review_context={
                "statistical_inference": {
                    "multiple_comparison_correction": "fdr",
                    "correction_alpha": 0.05,
                    "cluster_forming_threshold": 3.1,
                }
            },
            stats_metrics={
                "observed_multiple_comparison_correction": "bonferroni",
                "observed_multiple_comparison_alpha": 0.01,
                "observed_cluster_forming_threshold": 2.3,
            },
        )
        finding = multiple_comparison_metadata_consistency_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_MULTIPLE_COMPARISON_METADATA_MISMATCH"
        assert finding.severity == "error"
        assert finding.action == "block"
        assert finding.reason_tags == ["null_mismatch"]

    def test_multiple_comparison_metadata_consistency_allows_match(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            multiple_comparison_metadata_consistency_check,
        )

        bundle = CodeReviewBundle(
            review_context={
                "statistical_inference": {
                    "multiple_comparison_correction": "fdr_bh",
                    "correction_alpha": 0.05,
                    "height_control": "fpr",
                }
            },
            stats_metrics={
                "observed_multiple_comparison_correction": "fdr",
                "observed_multiple_comparison_alpha": 0.05,
                "observed_height_control": "fpr",
            },
        )
        assert multiple_comparison_metadata_consistency_check(bundle) is None

    def test_cluster_table_semantics_flags_missing_cluster_columns(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            cluster_table_semantics_check,
        )

        bundle = CodeReviewBundle(
            review_context={
                "statistical_inference": {
                    "cluster_table_path": "cluster_table.csv",
                }
            },
            stats_metrics={
                "observed_cluster_table_rows": 2,
                "observed_cluster_table_has_cluster_size": False,
                "observed_cluster_table_has_significance": False,
                "observed_cluster_table_has_stat": False,
            },
        )
        finding = cluster_table_semantics_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CLUSTER_TABLE_SEMANTICS_INVALID"
        assert finding.severity == "error"
        assert finding.action == "block"

    def test_correction_summary_numeric_consistency_flags_impossible_counts(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            correction_summary_numeric_consistency_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={
                "observed_multiple_comparison_n_tests": 10,
                "observed_multiple_comparison_rejected_count": 12,
                "observed_multiple_comparison_fraction_significant": 0.2,
            },
        )
        finding = correction_summary_numeric_consistency_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CORRECTION_SUMMARY_NUMERIC_MISMATCH"
        assert finding.severity == "error"
        assert finding.action == "block"

    def test_contrast_table_semantics_flags_missing_expected_contrast(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            contrast_table_semantics_check,
        )

        bundle = CodeReviewBundle(
            kg_context={"contrast": "task > rest"},
            review_context={
                "statistical_inference": {
                    "contrast_table_path": "contrast_table.csv",
                }
            },
            stats_metrics={
                "observed_contrast_table_rows": 2,
                "observed_contrast_table_has_contrast_name": True,
                "observed_contrast_table_rows_missing_contrast_name": 0,
                "observed_contrast_table_names": ["rest > fixation", "task > fixation"],
                "observed_contrast_table_vector_lengths": [3],
                "design_matrix_ncols": 3,
            },
        )
        finding = contrast_table_semantics_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CONTRAST_TABLE_SEMANTICS_INVALID"
        assert finding.severity == "error"
        assert finding.action == "block"

    def test_peak_table_semantics_flags_missing_coordinates(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            peak_table_semantics_check,
        )

        bundle = CodeReviewBundle(
            review_context={
                "statistical_inference": {
                    "peak_table_path": "peak_table.csv",
                }
            },
            stats_metrics={
                "observed_peak_table_rows": 2,
                "observed_peak_table_has_coordinates": False,
                "observed_peak_table_has_stat": True,
            },
        )
        finding = peak_table_semantics_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_PEAK_TABLE_SEMANTICS_INVALID"
        assert finding.severity == "error"
        assert finding.action == "block"

    def test_cluster_table_count_consistency_flags_mismatch(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            cluster_table_count_consistency_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={
                "observed_cluster_table_rows": 2,
                "observed_n_clusters_found": 4,
                "observed_n_clusters_surviving": 3,
            },
        )
        finding = cluster_table_count_consistency_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CLUSTER_TABLE_COUNT_MISMATCH"
        assert finding.severity == "error"
        assert finding.action == "block"

    def test_peak_cluster_membership_consistency_flags_missing_cluster_ids(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            peak_cluster_membership_consistency_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={
                "observed_cluster_table_rows": 2,
                "observed_cluster_table_has_cluster_id": True,
                "observed_cluster_table_cluster_ids": ["1", "2"],
                "observed_cluster_table_duplicate_cluster_ids": False,
                "observed_peak_table_has_cluster_id": True,
                "observed_peak_table_rows": 2,
                "observed_peak_table_rows_missing_cluster_id": 0,
                "observed_peak_table_cluster_ids": ["1", "3"],
            },
        )
        finding = peak_cluster_membership_consistency_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_PEAK_CLUSTER_MEMBERSHIP_INVALID"
        assert finding.severity == "error"
        assert finding.action == "block"

    def test_cluster_peak_cardinality_flags_cluster_without_peak(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            cluster_peak_cardinality_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={
                "observed_cluster_table_cluster_ids": ["1", "2", "3"],
                "observed_peak_table_cluster_ids": ["1", "3"],
            },
        )
        finding = cluster_peak_cardinality_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CLUSTER_PEAK_CARDINALITY_MISMATCH"
        assert finding.severity == "error"
        assert finding.action == "block"

    def test_design_model_metadata_consistency_flags_mismatch(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            design_model_metadata_consistency_check,
        )

        bundle = CodeReviewBundle(
            review_context={
                "design_model": {
                    "hrf_model": "spm + derivative",
                    "temporal_derivative": True,
                    "autocorrelation_model": "ar1",
                    "prewhitening_method": "film",
                    "prewhitening_enabled": True,
                }
            },
            stats_metrics={
                "observed_hrf_model": "fir",
                "observed_autocorrelation_model": "ols",
                "observed_prewhitening_method": "ols",
                "observed_prewhitening_enabled": False,
                "design_matrix_temporal_derivative_count": 0,
            },
        )
        finding = design_model_metadata_consistency_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_DESIGN_MODEL_METADATA_MISMATCH"
        assert finding.severity == "error"
        assert finding.action == "block"
        assert finding.reason_tags == ["null_mismatch"]

    def test_design_model_metadata_consistency_allows_match(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            design_model_metadata_consistency_check,
        )

        bundle = CodeReviewBundle(
            review_context={
                "design_model": {
                    "hrf_model": "spm + derivative",
                    "temporal_derivative": True,
                    "autocorrelation_model": "ar(1)",
                    "prewhitening_method": "film",
                    "prewhitening_enabled": True,
                }
            },
            stats_metrics={
                "observed_hrf_model": "spm + derivative",
                "observed_autocorrelation_model": "ar1",
                "observed_prewhitening_method": "film",
                "observed_prewhitening_enabled": True,
                "design_matrix_temporal_derivative_count": 1,
            },
        )
        assert design_model_metadata_consistency_check(bundle) is None

    def test_design_matrix_confound_column_consistency_allows_present_aliases(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            design_matrix_confound_column_consistency_check,
        )

        bundle = CodeReviewBundle(
            review_context={
                "preprocessing": {
                    "confounds": ["motion", "gsr"],
                }
            },
            stats_metrics={
                "design_matrix_columns": [
                    "intercept",
                    "trans_x",
                    "rot_y",
                    "global_signal",
                ],
            },
        )
        assert design_matrix_confound_column_consistency_check(bundle) is None

    def test_correctness_rank_deficient(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            design_matrix_rank_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={"design_matrix_rank": 3, "design_matrix_ncols": 5}
        )
        finding = design_matrix_rank_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_DESIGN_MATRIX_RANK_DEFICIENT"
        assert finding.severity == "error"

    def test_correctness_rank_ok(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            design_matrix_rank_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={"design_matrix_rank": 5, "design_matrix_ncols": 5}
        )
        assert design_matrix_rank_check(bundle) is None

    def test_cross_file_n_subjects_mismatch(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            cross_file_n_subjects_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={"metadata_n_subjects": 30, "csv_n_rows": 25}
        )
        finding = cross_file_n_subjects_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CROSS_FILE_N_SUBJECTS"

    def test_contrast_dim_mismatch(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            contrast_vector_dim_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={"contrast_dims": 3, "design_matrix_ncols": 5}
        )
        finding = contrast_vector_dim_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CONTRAST_DIM_MISMATCH"

    def test_contrast_dim_ok(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            contrast_vector_dim_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={"contrast_dims": 5, "design_matrix_ncols": 5}
        )
        assert contrast_vector_dim_check(bundle) is None

    def test_effect_tstat_shape_mismatch(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            effect_tstat_shape_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={
                "effect_map_shape": [91, 109, 91],
                "tstat_map_shape": [91, 109, 92],
            }
        )
        finding = effect_tstat_shape_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_EFFECT_TSTAT_SHAPE_MISMATCH"

    def test_missing_metrics_returns_none(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            cross_file_n_subjects_check,
            design_matrix_confound_column_consistency_check,
            design_matrix_rank_check,
            design_model_metadata_consistency_check,
            multiple_comparison_metadata_consistency_check,
        )

        bundle = CodeReviewBundle(stats_metrics={})
        assert design_matrix_rank_check(bundle) is None
        assert cross_file_n_subjects_check(bundle) is None
        assert design_matrix_confound_column_consistency_check(bundle) is None
        assert multiple_comparison_metadata_consistency_check(bundle) is None
        assert design_model_metadata_consistency_check(bundle) is None


# ---------------------------------------------------------------------------
# Effect plausibility
# ---------------------------------------------------------------------------


class TestEffectPlausibility:
    def test_meta_analytic_spatial_plausibility_low(self):
        from brain_researcher.services.review.checks.effect_plausibility import (
            meta_analytic_spatial_plausibility_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={
                "meta_analytic_term": "working memory",
                "meta_analytic_spatial_corr": 0.03,
                "meta_analytic_voxels_compared": 2048,
            }
        )
        finding = meta_analytic_spatial_plausibility_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_META_ANALYTIC_SPATIAL_PLAUSIBILITY_LOW"
        assert finding.severity == "warn"

    def test_meta_analytic_spatial_plausibility_ok(self):
        from brain_researcher.services.review.checks.effect_plausibility import (
            meta_analytic_spatial_plausibility_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={
                "meta_analytic_term": "working memory",
                "meta_analytic_spatial_corr": 0.24,
            }
        )
        assert meta_analytic_spatial_plausibility_check(bundle) is None

    def test_effect_size_plausibility_flags_large_effect(self, monkeypatch):
        from brain_researcher.services.review.checks import effect_plausibility as ep

        _mock_prior = {
            "status": "ok",
            "source": "literature",
            "confidence_tier": "literature_text_mining",
            "priors": {
                "cohens_d": {
                    "median_abs_d": 0.5,
                    "p90_abs_d": 0.8,
                    "max_abs_d": 1.1,
                    "n_mentions": 20,
                }
            },
            "support": {
                "query": "working memory 2-back Cohen's d",
                "top_papers": [{"title": "Prior study on working memory"}],
            },
        }
        monkeypatch.setattr(
            ep, "infer_effect_size_priors_multi", lambda **kwargs: _mock_prior
        )
        monkeypatch.setattr(
            ep, "infer_effect_size_priors", lambda **kwargs: _mock_prior
        )

        bundle = CodeReviewBundle(
            stats_metrics={"cohens_d_max": 2.4},
            kg_context={"task": "working memory", "contrast": "2-back > rest"},
        )
        finding = ep.effect_size_plausibility_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_EFFECT_SIZE_PLAUSIBILITY_HIGH"
        assert finding.severity == "warn"
        assert any("working memory" in item for item in finding.kg_evidence)

    def test_effect_size_plausibility_ok_within_prior(self, monkeypatch):
        from brain_researcher.services.review.checks import effect_plausibility as ep

        _mock_prior = {
            "status": "ok",
            "source": "literature",
            "confidence_tier": "literature_text_mining",
            "priors": {
                "cohens_d": {
                    "median_abs_d": 0.5,
                    "p90_abs_d": 0.8,
                    "max_abs_d": 1.1,
                    "n_mentions": 20,
                }
            },
            "support": {},
        }
        monkeypatch.setattr(
            ep, "infer_effect_size_priors_multi", lambda **kwargs: _mock_prior
        )
        monkeypatch.setattr(
            ep, "infer_effect_size_priors", lambda **kwargs: _mock_prior
        )

        bundle = CodeReviewBundle(
            stats_metrics={"cohens_d_max": 1.4},
            kg_context={"task": "working memory", "contrast": "2-back > rest"},
        )
        assert ep.effect_size_plausibility_check(bundle) is None

    def test_effect_size_prior_helper_extracts_values(self, monkeypatch):
        from brain_researcher.core.literature import literature_priors as lp

        lp._cached_effect_size_priors.cache_clear()

        def fake_search(query, **kwargs):
            assert "Cohen's d" in query
            return {
                "status": "ok",
                "hits": [
                    {"title": "Study A", "text": "Cohen's d = 0.4", "snippet": ""},
                    {"title": "Study B", "text": "effect size = 0.8", "snippet": ""},
                    {
                        "title": "Study C",
                        "text": "standardized effect 1.2",
                        "snippet": "",
                    },
                ],
                "store": "mock-store",
                "model": "mock-model",
            }

        monkeypatch.setattr(lp, "search_gfs_auto", fake_search)
        payload = lp.infer_effect_size_priors(
            task="working memory", contrast="2-back > rest", top_k=3
        )

        summary = payload["priors"]["cohens_d"]
        assert payload["status"] == "ok"
        assert summary["n_mentions"] == 3
        assert summary["max_abs_d"] == 1.2
        assert summary["median_abs_d"] == 0.8


class TestStatsExtractorEffectPlausibility:
    def test_build_artifact_review_bundle_populates_kg_context(self, tmp_path):
        import json

        from brain_researcher.services.review.bundle_builder import (
            build_artifact_review_bundle,
        )

        run_payload = {
            "steps": [
                {
                    "tool_id": "glm_first_level",
                    "params": {
                        "task": "working memory",
                        "contrast_name": "2-back > rest",
                    },
                    "status": "succeeded",
                }
            ]
        }
        (tmp_path / "run.json").write_text(json.dumps(run_payload), encoding="utf-8")

        bundle = build_artifact_review_bundle("run-1", run_dir=tmp_path)
        assert bundle.kg_context["task"] == "working memory"
        assert bundle.kg_context["contrast"] == "2-back > rest"
        assert bundle.kg_context["analysis_family"] == "glm"

    def test_build_artifact_review_bundle_captures_external_review_contract(
        self, tmp_path
    ):
        import json

        from brain_researcher.services.review.bundle_builder import (
            build_artifact_review_bundle,
        )

        (tmp_path / "run.json").write_text(
            json.dumps(
                {
                    "steps": [
                        {
                            "tool_id": "external_analysis_summary",
                            "params": {"task": "fluid intelligence"},
                            "status": "succeeded",
                        }
                    ],
                    "review_contract": {
                        "scientific_review_profile": "predictive_model_review",
                        "scientific_completeness_checks": [
                            "target_declared",
                            "evaluation_protocol_declared",
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps(
                {
                    "target_column": "PMAT24_A_CR",
                    "n_folds": 10,
                }
            ),
            encoding="utf-8",
        )

        bundle = build_artifact_review_bundle("run-external-1", run_dir=tmp_path)
        assert bundle.observed_artifacts["review_contract"][
            "scientific_review_profile"
        ] == ("predictive_model_review")
        assert bundle.observed_artifacts["review_contract"][
            "scientific_completeness_checks"
        ] == [
            "target_declared",
            "evaluation_protocol_declared",
        ]
        assert (
            bundle.observed_artifacts["source_summary"]["target_column"]
            == "PMAT24_A_CR"
        )

    def test_build_artifact_review_bundle_captures_quote_grounded_artifacts(
        self, tmp_path
    ):
        import json

        from brain_researcher.services.review.bundle_builder import (
            build_artifact_review_bundle,
        )

        (tmp_path / "run.json").write_text(json.dumps({"steps": []}), encoding="utf-8")
        (tmp_path / "quote_grounded_evidence_items.json").write_text(
            json.dumps(
                [
                    {
                        "schema_version": "evidence-item-v1",
                        "evidence_id": "ev-1",
                        "type": "file",
                        "ref": "paper-1",
                        "evidence_provenance": "cross_study_inference",
                        "raw_data_available": False,
                        "direct_statistical_test": False,
                    }
                ]
            ),
            encoding="utf-8",
        )
        (tmp_path / "quote_grounded_claims.json").write_text(
            json.dumps(
                [
                    {
                        "schema_version": "claim-v1",
                        "claim_id": "claim-1",
                        "claim_text": "Right TPJ is stronger than left TPJ.",
                        "verdict": "supported",
                        "epistemic_confidence_tier": "high",
                        "evidence_provenance": "cross_study_inference",
                        "claim_scope": "cross_study",
                        "raw_data_available": False,
                        "direct_statistical_test": False,
                        "evidence_ids": ["ev-1"],
                    }
                ]
            ),
            encoding="utf-8",
        )

        bundle = build_artifact_review_bundle("run-qg-1", run_dir=tmp_path)
        assert (
            bundle.observed_artifacts["quote_grounded_claims"][0]["claim_id"]
            == "claim-1"
        )
        assert (
            bundle.observed_artifacts["quote_grounded_evidence_items"][0]["evidence_id"]
            == "ev-1"
        )

    def test_build_artifact_review_bundle_surfaces_claim_review_sidecars(
        self, tmp_path
    ):
        import json

        from brain_researcher.services.review.bundle_builder import (
            build_artifact_review_bundle,
        )

        (tmp_path / "run.json").write_text(json.dumps({"steps": []}), encoding="utf-8")
        (tmp_path / "claim_report.json").write_text(
            json.dumps(
                {
                    "schema_version": "claim-report-v1",
                    "report_id": "claim_report:run-sidecar-1",
                    "claims": [],
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "claim_update.json").write_text(
            json.dumps(
                [
                    {
                        "schema_version": "claim-update-v1",
                        "claim_id": "claim-1",
                        "action": "support",
                    }
                ]
            ),
            encoding="utf-8",
        )

        bundle = build_artifact_review_bundle("run-sidecar-1", run_dir=tmp_path)
        assert bundle.observed_artifacts["claim_report"]["report_id"] == (
            "claim_report:run-sidecar-1"
        )
        assert bundle.observed_artifacts["claim_update"][0]["claim_id"] == "claim-1"

    def test_build_artifact_review_bundle_canonicalizes_fc_statistical_method(
        self, tmp_path
    ):
        import json

        from brain_researcher.services.review.bundle_builder import (
            build_artifact_review_bundle,
        )

        (tmp_path / "run.json").write_text(
            json.dumps(
                {
                    "steps": [
                        {
                            "tool_id": "external_analysis_summary",
                            "params": {
                                "task": "fluid intelligence",
                                "statistical_method": "graph_transformer",
                            },
                            "status": "succeeded",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        bundle = build_artifact_review_bundle("run-external-method-1", run_dir=tmp_path)
        assert bundle.kg_context["statistical_method"] == "graph_transformer"

    def test_build_artifact_review_bundle_prefers_native_bundle_contracts(
        self, tmp_path
    ):
        import json

        from brain_researcher.services.review.bundle_builder import (
            build_artifact_review_bundle,
        )

        support_dir = tmp_path / ".bundle_support"
        support_dir.mkdir()
        (support_dir / "research_episode.json").write_text(
            json.dumps(
                {
                    "schema_version": "research-episode-v1",
                    "episode_id": "episode:native",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "research_episode.json").write_text(
            json.dumps(
                {
                    "schema_version": "research-episode-v1",
                    "episode_id": "episode:legacy-root",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"target_column": "legacy_target"}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-1",
                    "run_id": "run-native-1",
                    "state": "succeeded",
                    "steps": [
                        {
                            "tool_id": "embedding_autoresearch",
                            "params": {"task": "theory of mind"},
                            "step_id": "s1",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-1",
                    "files": {
                        "observation_json": "observation.json",
                        "research_episode_json": ".bundle_support/research_episode.json",
                    },
                    "analysis_manifest": {
                        "target_column": "native_target",
                        "classifier": "ridge",
                    },
                    "policy_snapshot": {
                        "source": "predictive_loop_controller",
                    },
                    "observation": {
                        "schema_version": "observation-v1",
                        "job_id": "run-native-1",
                        "run_id": "run-native-1",
                        "state": "succeeded",
                        "steps": [
                            {
                                "tool_id": "external_analysis_summary",
                                "params": {"task": "fluid intelligence"},
                                "step_id": "s1",
                            }
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )

        bundle = build_artifact_review_bundle("run-native-1", run_dir=tmp_path)
        assert (
            bundle.observed_artifacts["source_summary"]["target_column"]
            == "native_target"
        )
        assert (
            bundle.observed_artifacts["research_episode"]["episode_id"]
            == "episode:native"
        )
        assert (
            bundle.observed_artifacts["review_contract"]["contract_mode"]
            == "native_review_bundle"
        )
        assert (
            bundle.observed_artifacts["review_contract"]["scientific_review_profile"]
            == "predictive_model_review"
        )
        assert bundle.observed_artifacts["review_contract"][
            "scientific_completeness_checks"
        ] == [
            "random_seed_pinned",
            "target_declared",
            "evaluation_protocol_declared",
            "subject_alignment_declared",
            "split_metadata_declared",
            "null_model_declared",
            "preprocessing_choices_declared",
        ]

    def test_build_artifact_review_bundle_uses_native_source_summary_manifest_ref(
        self, tmp_path
    ):
        import json

        from brain_researcher.services.review.bundle_builder import (
            build_artifact_review_bundle,
        )

        support_dir = tmp_path / ".bundle_support"
        support_dir.mkdir()
        (support_dir / "source_summary.json").write_text(
            json.dumps(
                {
                    "target_column": "manifest_target",
                    "n_folds": 5,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"target_column": "legacy_target"}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-manifest-1",
                    "run_id": "run-native-manifest-1",
                    "state": "succeeded",
                    "steps": [
                        {
                            "tool_id": "external_analysis_summary",
                            "params": {"task": "fluid intelligence"},
                            "step_id": "s1",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-manifest-1",
                    "files": {
                        "observation_json": "observation.json",
                    },
                    "policy_snapshot": {
                        "source": "predictive_loop_controller",
                    },
                    "source_manifests": [
                        ".bundle_support/source_summary.json",
                    ],
                }
            ),
            encoding="utf-8",
        )

        bundle = build_artifact_review_bundle(
            "run-native-manifest-1",
            run_dir=tmp_path,
        )

        assert (
            bundle.observed_artifacts["source_summary"]["target_column"]
            == "manifest_target"
        )
        assert bundle.observed_artifacts["source_summary"]["n_folds"] == 5

    def test_build_completeness_checklist_uses_native_predictive_review_contract(
        self, tmp_path
    ):
        import json

        from brain_researcher.services.review.bundle_builder import (
            build_artifact_review_bundle,
        )
        from brain_researcher.services.review.checks.completeness import (
            build_completeness_checklist,
        )

        support_dir = tmp_path / ".bundle_support"
        support_dir.mkdir()
        (support_dir / "research_episode.json").write_text(
            json.dumps(
                {
                    "schema_version": "research-episode-v1",
                    "episode_id": "episode:native-predictive",
                    "estimand": "Predict PMAT24_A_CR from FC connectivity",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-predictive-1",
                    "run_id": "run-native-predictive-1",
                    "state": "succeeded",
                    "inputs_manifest_ref": "manifests/subject_manifest.json",
                    "steps": [
                        {
                            "tool_id": "external_analysis_summary",
                            "params": {"task": "fluid intelligence"},
                            "step_id": "s1",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "execution_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "execution-manifest-v1",
                    "parameters": {
                        "target_column": "PMAT24_A_CR",
                        "n_folds": 10,
                        "evaluation_protocol": "nested_cv",
                    },
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-predictive-1",
                    "files": {
                        "observation_json": "observation.json",
                        "execution_manifest_json": "execution_manifest.json",
                        "research_episode_json": ".bundle_support/research_episode.json",
                    },
                    "analysis_manifest": {
                        "target_column": "PMAT24_A_CR",
                        "n_folds": 10,
                        "split_manifest_path": "manifests/subject_manifest.json",
                        "cv_manifest_path": "manifests/fold_manifest.json",
                        "feature_selection_scope": "train_only",
                        "permutation_baseline_spec": "label_shuffle",
                    },
                    "policy_snapshot": {
                        "source": "predictive_loop_controller",
                    },
                    "source_manifests": [
                        "manifests/fold_manifest.json",
                    ],
                }
            ),
            encoding="utf-8",
        )

        bundle = build_artifact_review_bundle(
            "run-native-predictive-1",
            run_dir=tmp_path,
        )
        checklist = build_completeness_checklist(bundle)

        assert (
            bundle.observed_artifacts["review_contract"]["scientific_review_profile"]
            == "predictive_model_review"
        )
        assert set(checklist) == {
            "random_seed_pinned",
            "target_declared",
            "evaluation_protocol_declared",
            "subject_alignment_declared",
            "split_metadata_declared",
            "null_model_declared",
            "preprocessing_choices_declared",
        }
        assert checklist["random_seed_pinned"] is True
        assert checklist["target_declared"] is True
        assert checklist["evaluation_protocol_declared"] is True
        assert checklist["subject_alignment_declared"] is True
        assert checklist["split_metadata_declared"] is True
        assert checklist["null_model_declared"] is True
        assert checklist["preprocessing_choices_declared"] is True

    def test_build_artifact_review_bundle_uses_native_observation_steps_without_run_json(
        self, tmp_path
    ):
        import json

        from brain_researcher.services.review.bundle_builder import (
            build_artifact_review_bundle,
        )

        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-steps-1",
                    "run_id": "run-native-steps-1",
                    "state": "succeeded",
                    "steps": [
                        {
                            "tool_id": "tribe_predict",
                            "params": {
                                "task": "working memory",
                                "contrast_name": "2-back > rest",
                            },
                            "step_id": "s1",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-steps-1",
                    "files": {"observation_json": "observation.json"},
                }
            ),
            encoding="utf-8",
        )

        bundle = build_artifact_review_bundle("run-native-steps-1", run_dir=tmp_path)
        assert bundle.plan_steps[0]["tool"] == "tribe_predict"
        assert bundle.kg_context["task"] == "working memory"
        assert bundle.kg_context["contrast"] == "2-back > rest"
        assert bundle.kg_context["analysis_family"] == "tribe_prediction"

    def test_extract_meta_analytic_spatial_metrics(self, tmp_path, monkeypatch):
        import nibabel as nib
        import numpy as np

        from brain_researcher.services.review.stats_extractor import (
            _extract_meta_analytic_spatial_metrics,
        )

        run_payload = {
            "steps": [
                {
                    "tool": "glm_first_level",
                    "params": {"task": "working memory"},
                    "status": "succeeded",
                }
            ]
        }
        (tmp_path / "run.json").write_text(json.dumps(run_payload), encoding="utf-8")

        data = np.zeros((6, 6, 6), dtype=float)
        data[1:4, 1:4, 1:4] = np.arange(27, dtype=float).reshape(3, 3, 3)
        result_img = nib.Nifti1Image(data, np.eye(4))
        result_path = tmp_path / "sub-01_stat-z_statmap.nii.gz"
        nib.save(result_img, result_path)

        ref_img = nib.Nifti1Image(data.copy(), np.eye(4))

        def _fake_mapping(term: str):
            assert term == "working memory"
            return {"activation_maps": [ref_img]}

        monkeypatch.setattr(
            "brain_researcher.core.analysis.neurosynth_integration.get_neurosynth_mapping",
            _fake_mapping,
        )

        metrics = _extract_meta_analytic_spatial_metrics(tmp_path)
        assert metrics["meta_analytic_term"] == "working memory"
        assert metrics["meta_analytic_spatial_corr"] is not None
        assert metrics["meta_analytic_spatial_corr"] > 0.99
        assert metrics["meta_analytic_voxels_compared"] > 0

    def test_extract_meta_analytic_spatial_metrics_missing_task(self, tmp_path):
        from brain_researcher.services.review.stats_extractor import (
            _extract_meta_analytic_spatial_metrics,
        )

        (tmp_path / "run.json").write_text(json.dumps({"steps": []}), encoding="utf-8")
        metrics = _extract_meta_analytic_spatial_metrics(tmp_path)
        assert metrics["meta_analytic_term"] is None
        assert metrics["meta_analytic_spatial_corr"] is None

    def test_epistemic_claim_policy_check_flags_overclaim(self):
        from brain_researcher.services.review.checks.epistemic_integrity import (
            epistemic_claim_policy_check,
        )

        bundle = CodeReviewBundle(
            observed_artifacts={
                "quote_grounded_evidence_items": [
                    {
                        "schema_version": "evidence-item-v1",
                        "evidence_id": "ev-1",
                        "type": "file",
                        "ref": "paper-1",
                        "evidence_provenance": "cross_study_inference",
                        "raw_data_available": False,
                        "direct_statistical_test": False,
                    }
                ],
                "quote_grounded_claims": [
                    {
                        "schema_version": "claim-v1",
                        "claim_id": "claim-1",
                        "claim_text": "Right TPJ is stronger than left TPJ.",
                        "verdict": "supported",
                        "epistemic_confidence_tier": "high",
                        "evidence_provenance": "cross_study_inference",
                        "claim_scope": "cross_study",
                        "raw_data_available": False,
                        "direct_statistical_test": False,
                        "evidence_ids": ["ev-1"],
                    }
                ],
            }
        )

        finding = epistemic_claim_policy_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_EPISTEMIC_CLAIM_POLICY"
        assert finding.severity == "error"
        assert "uses verdict 'supported'" in finding.message

    def test_epistemic_claim_policy_check_allows_direct_support(self):
        from brain_researcher.services.review.checks.epistemic_integrity import (
            epistemic_claim_policy_check,
        )

        bundle = CodeReviewBundle(
            observed_artifacts={
                "quote_grounded_evidence_items": [
                    {
                        "schema_version": "evidence-item-v1",
                        "evidence_id": "ev-1",
                        "type": "artifact",
                        "ref": "analysis.json#/claims/0",
                        "evidence_provenance": "single_study_direct",
                        "raw_data_available": True,
                        "direct_statistical_test": True,
                    }
                ],
                "quote_grounded_claims": [
                    {
                        "schema_version": "claim-v1",
                        "claim_id": "claim-1",
                        "claim_text": "Condition A exceeds condition B in TPJ.",
                        "verdict": "supported",
                        "epistemic_confidence_tier": "high",
                        "evidence_ids": ["ev-1"],
                    }
                ],
            }
        )

        assert epistemic_claim_policy_check(bundle) is None

    def test_reverse_inference_risk_check_flags_region_to_process_claim(self):
        from brain_researcher.services.review.checks.claim_validity import (
            reverse_inference_risk_check,
        )

        bundle = CodeReviewBundle(
            observed_artifacts={
                "claim_report": {
                    "claims": [
                        {
                            "claim_text": "Amygdala activation indicates emotion processing.",
                        }
                    ]
                }
            }
        )

        finding = reverse_inference_risk_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_REVERSE_INFERENCE_RISK"
        assert finding.severity == "warn"

    def test_model_fit_mechanism_overreach_check_flags_equivalence_claim(self):
        from brain_researcher.services.review.checks.claim_validity import (
            model_fit_mechanism_overreach_check,
        )

        bundle = CodeReviewBundle(
            kg_context={"analysis_family": "neural_encoding_prediction"},
            observed_artifacts={
                "claim_report": {
                    "claims": [
                        {
                            "claim_text": "The best-fitting transformer layer proves the cortex uses the same representation.",
                        }
                    ]
                }
            },
        )

        finding = model_fit_mechanism_overreach_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_MODEL_FIT_MECHANISM_OVERREACH"
        assert finding.severity == "warn"

    def test_cross_study_coordinate_comparison_check_flags_group_difference_table(self):
        from brain_researcher.services.review.checks.epistemic_integrity import (
            cross_study_coordinate_comparison_check,
        )

        bundle = CodeReviewBundle(
            observed_artifacts={
                "quote_grounded_evidence_items": [
                    {
                        "schema_version": "evidence-item-v1",
                        "evidence_id": "ev-1",
                        "type": "file",
                        "ref": "paper-1",
                        "evidence_provenance": "cross_study_inference",
                        "raw_data_available": False,
                        "direct_statistical_test": False,
                    }
                ],
                "quote_grounded_claims": [
                    {
                        "schema_version": "claim-v1",
                        "claim_id": "claim-1",
                        "claim_text": "EA > EuA in TPJ for stranger trust.",
                        "verdict": "indirectly_supported",
                        "epistemic_confidence_tier": "low",
                        "evidence_ids": ["ev-1"],
                    }
                ],
                "source_summary": {
                    "coordinate_table": {
                        "columns": ["region", "mni_coordinates", "group_difference"],
                        "rows": [
                            {
                                "region": "TPJ",
                                "mni_coordinates": [54, -52, 22],
                                "group_difference": "EA > EuA",
                            }
                        ],
                    }
                },
            }
        )

        finding = cross_study_coordinate_comparison_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CROSS_STUDY_COORDINATE_COMPARISON"
        assert finding.severity == "error"
        assert "group-difference column" in finding.message

    def test_directional_claim_contradiction_check_flags_opposed_directions(self):
        from brain_researcher.services.review.checks.epistemic_integrity import (
            directional_claim_contradiction_check,
        )

        bundle = CodeReviewBundle(
            observed_artifacts={
                "quote_grounded_evidence_items": [
                    {
                        "schema_version": "evidence-item-v1",
                        "evidence_id": "ev-1",
                        "type": "file",
                        "ref": "doc-1",
                        "evidence_provenance": "cross_study_inference",
                        "raw_data_available": False,
                        "direct_statistical_test": False,
                    },
                    {
                        "schema_version": "evidence-item-v1",
                        "evidence_id": "ev-2",
                        "type": "file",
                        "ref": "doc-2",
                        "evidence_provenance": "cross_study_inference",
                        "raw_data_available": False,
                        "direct_statistical_test": False,
                    },
                ],
                "quote_grounded_claims": [
                    {
                        "schema_version": "claim-v1",
                        "claim_id": "claim-1",
                        "claim_text": "EuA > EA",
                        "verdict": "predicted",
                        "epistemic_confidence_tier": "low",
                        "evidence_ids": ["ev-1"],
                        "extra": {
                            "hypothesis_id": "H3",
                            "region": "TPJ",
                            "task": "stranger trust",
                        },
                    },
                    {
                        "schema_version": "claim-v1",
                        "claim_id": "claim-2",
                        "claim_text": "EA > EuA",
                        "verdict": "indirectly_supported",
                        "epistemic_confidence_tier": "low",
                        "evidence_ids": ["ev-2"],
                        "extra": {
                            "hypothesis_id": "H3",
                            "region": "TPJ",
                            "task": "stranger trust",
                        },
                    },
                ],
            }
        )

        finding = directional_claim_contradiction_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_DIRECTIONAL_CLAIM_CONTRADICTION"
        assert finding.severity == "warn"
        assert "eua > ea" in finding.message
        assert "ea > eua" in finding.message

    def test_distill_scientific_review_records_writes_claim_sidecars_for_overclaim(
        self, tmp_path
    ):
        from brain_researcher.core.contracts import (
            ClaimReportV1,
            ClaimUpdateV1,
            EvidenceGateVerdictV1,
        )
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        (tmp_path / "run.json").write_text(json.dumps({"steps": []}), encoding="utf-8")
        (tmp_path / "quote_grounded_evidence_items.json").write_text(
            json.dumps(
                [
                    {
                        "schema_version": "evidence-item-v1",
                        "evidence_id": "ev-1",
                        "type": "file",
                        "ref": "paper-1",
                        "evidence_provenance": "cross_study_inference",
                        "raw_data_available": False,
                        "direct_statistical_test": False,
                    }
                ]
            ),
            encoding="utf-8",
        )
        (tmp_path / "quote_grounded_claims.json").write_text(
            json.dumps(
                [
                    {
                        "schema_version": "claim-v1",
                        "claim_id": "claim-1",
                        "claim_text": "Right TPJ is stronger than left TPJ.",
                        "verdict": "supported",
                        "epistemic_confidence_tier": "high",
                        "evidence_provenance": "cross_study_inference",
                        "claim_scope": "cross_study",
                        "raw_data_available": False,
                        "direct_statistical_test": False,
                        "evidence_ids": ["ev-1"],
                    }
                ]
            ),
            encoding="utf-8",
        )
        verdict = distill_scientific_review_records(
            "run-overclaim-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        assert verdict.overall_decision == "stop_with_rationale"
        claim_report_payload = json.loads(
            (tmp_path / "claim_report.json").read_text(encoding="utf-8")
        )
        claim_report = ClaimReportV1.model_validate(claim_report_payload)
        assert claim_report.extra["claim_source"] == "quote_grounded_claims"
        assert claim_report.claims[0].verdict.value == "indirectly_supported"
        assert claim_report.claims[0].epistemic_confidence_tier.value == "low"
        assert (
            claim_report.claims[0].extra["epistemic_calibration"]["display_verdict"]
            == "consistent_with"
        )

        updates_payload = json.loads(
            (tmp_path / "claim_update.json").read_text(encoding="utf-8")
        )
        updates = [ClaimUpdateV1.model_validate(item) for item in updates_payload]
        assert updates[0].extra["epistemic_issues"]
        assert "REVIEW_EPISTEMIC_CLAIM_POLICY" in (updates[0].note or "")

        gate_payload = json.loads(
            (tmp_path / "evidence_gate.json").read_text(encoding="utf-8")
        )
        gate = EvidenceGateVerdictV1.model_validate(gate_payload)
        assert gate.decision == "stop"

    def test_distill_scientific_review_records_synthesizes_claim_sidecars_from_source_summary(
        self, tmp_path
    ):
        from brain_researcher.core.contracts import ClaimReportV1
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        (tmp_path / "run.json").write_text(json.dumps({"steps": []}), encoding="utf-8")
        (tmp_path / "source_summary.json").write_text(
            json.dumps(
                {
                    "claim_text": "Fluid intelligence can be predicted above chance.",
                    "claim_verdict": "suggestive",
                    "evidence_provenance": "cross_study_inference",
                    "epistemic_confidence_tier": "low",
                    "direct_statistical_test": False,
                    "raw_data_available": False,
                }
            ),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-source-summary-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        assert verdict.overall_decision == "diagnose"
        assert {finding.rule_id for finding in verdict.correctness.findings} == {
            "REVIEW_CLAIM_INFLATION"
        }
        claim_report_payload = json.loads(
            (tmp_path / "claim_report.json").read_text(encoding="utf-8")
        )
        claim_report = ClaimReportV1.model_validate(claim_report_payload)
        assert claim_report.extra["claim_source"] == "source_summary_synthesized"
        assert len(claim_report.claims) == 1
        updates_payload = json.loads(
            (tmp_path / "claim_update.json").read_text(encoding="utf-8")
        )
        assert updates_payload[0]["claim_id"] == "source_summary_claim"

    def test_distill_scientific_review_records_uses_native_review_context_for_neuroai_warnings(
        self, tmp_path
    ):
        from brain_researcher.core.contracts import ClaimReportV1
        from brain_researcher.services.review.bundle_builder import (
            build_artifact_review_bundle,
        )
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        review_context = {
            "schema_version": "review-context-v1",
            "split": {
                "split_unit": "story",
                "grouped_split_keys": ["story", "subject"],
                "required_group_keys": ["story", "subject"],
            },
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-neuroai-1",
                    "run_id": "run-native-neuroai-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-neuroai-1",
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "review_context": review_context,
                    "run_card": {"review_context": review_context},
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps(
                {
                    "claim_text": "Layer performance was suggestive.",
                    "claim_verdict": "suggestive",
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )

        bundle = build_artifact_review_bundle(
            "run-native-neuroai-1",
            run_dir=tmp_path,
        )
        assert (
            bundle.observed_artifacts["review_context"]["selection"]["best_layer"]
            == "layer-12"
        )
        assert (
            bundle.observed_artifacts["analysis_bundle"]["review_context"]
            == review_context
        )

        verdict = distill_scientific_review_records(
            "run-native-neuroai-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_NEUROAI_SELECTION_VALIDATION_GAP" in rule_ids
        saved_verdict = json.loads(
            (tmp_path / "scientific_review_verdict.json").read_text(encoding="utf-8")
        )
        saved_rule_ids = {
            finding["rule_id"] for finding in saved_verdict["correctness"]["findings"]
        }
        assert "REVIEW_NEUROAI_SELECTION_VALIDATION_GAP" in saved_rule_ids
        claim_report_payload = json.loads(
            (tmp_path / "claim_report.json").read_text(encoding="utf-8")
        )
        claim_report = ClaimReportV1.model_validate(claim_report_payload)
        assert (
            "REVIEW_NEUROAI_SELECTION_VALIDATION_GAP"
            in claim_report.extra["scientific_review"]["correctness_rule_ids"]
        )

    def test_distill_scientific_review_records_blocks_design_matrix_confound_mismatch(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        review_context = {
            "schema_version": "review-context-v1",
            "preprocessing": {
                "confound_columns": ["age", "site"],
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-design-confounds-1",
                    "run_id": "run-native-design-confounds-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-design-confounds-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "glm_pipeline"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "design_matrix.tsv").write_text(
            "intercept\tage\tsex\n1\t22\t0\n1\t31\t1\n1\t28\t0\n",
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-design-confounds-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_DESIGN_MATRIX_CONFOUND_COLUMNS_MISMATCH" in rule_ids
        assert verdict.correctness.decision == "block"
        # P0: the native distill path must now populate the shared metadata
        # fields derived from the three verdict cards.
        assert verdict.report_action == "revise_report"
        assert verdict.claim_strength is None
        assert verdict.validation_status.get("structural_correctness") == "failed"
        assert any(
            a.startswith(
                "Resolve blocking rule REVIEW_DESIGN_MATRIX_CONFOUND_COLUMNS_MISMATCH"
            )
            for a in verdict.required_next_actions
        )

    def test_distill_scientific_review_records_blocks_multiple_comparison_metadata_mismatch(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        review_context = {
            "schema_version": "review-context-v1",
            "statistical_inference": {
                "multiple_comparison_correction": "fdr",
                "correction_alpha": 0.05,
                "cluster_forming_threshold": 3.1,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-threshold-mismatch-1",
                    "run_id": "run-native-threshold-mismatch-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-threshold-mismatch-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "glm_pipeline"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "multiple_comparison_summary.json").write_text(
            json.dumps(
                {
                    "method": "bonferroni",
                    "alpha": 0.01,
                    "cluster_threshold": 2.3,
                }
            ),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-threshold-mismatch-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_MULTIPLE_COMPARISON_METADATA_MISMATCH" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_cluster_table_semantics_invalid(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        review_context = {
            "schema_version": "review-context-v1",
            "statistical_inference": {
                "cluster_table_path": "cluster_table.csv",
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-cluster-table-invalid-1",
                    "run_id": "run-native-cluster-table-invalid-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-cluster-table-invalid-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "glm_pipeline"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "cluster_table.csv").write_text(
            "label,notes\nmotor,robust\nvisual,secondary\n",
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-cluster-table-invalid-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_CLUSTER_TABLE_SEMANTICS_INVALID" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_correction_summary_numeric_mismatch(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        review_context = {
            "schema_version": "review-context-v1",
            "statistical_inference": {
                "correction_summary_path": "threshold_summary.json",
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-correction-summary-numeric-mismatch-1",
                    "run_id": "run-native-correction-summary-numeric-mismatch-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-correction-summary-numeric-mismatch-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "glm_pipeline"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "threshold_summary.json").write_text(
            json.dumps(
                {
                    "alpha": 1.2,
                    "n_tests": 10,
                    "rejected_count": 12,
                    "fraction_significant": 0.2,
                }
            ),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-correction-summary-numeric-mismatch-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_CORRECTION_SUMMARY_NUMERIC_MISMATCH" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_contrast_table_semantics_invalid(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        review_context = {
            "schema_version": "review-context-v1",
            "statistical_inference": {
                "contrast_table_path": "contrast_table.csv",
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps(
                {
                    "steps": [
                        {
                            "tool": "glm_first_level",
                            "params": {"contrast_name": "task > rest"},
                        }
                    ],
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-contrast-table-invalid-1",
                    "run_id": "run-native-contrast-table-invalid-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-contrast-table-invalid-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "glm_pipeline"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "design_matrix.csv").write_text(
            "intercept,task,motion\n1,0,0\n1,1,0.1\n",
            encoding="utf-8",
        )
        (tmp_path / "contrast_table.csv").write_text(
            "contrast_name,intercept,task,motion\n" "task > fixation,0,1,0\n",
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-contrast-table-invalid-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_CONTRAST_TABLE_SEMANTICS_INVALID" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_cluster_table_count_mismatch(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        review_context = {
            "schema_version": "review-context-v1",
            "statistical_inference": {
                "cluster_table_path": "cluster_table.csv",
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-cluster-count-mismatch-1",
                    "run_id": "run-native-cluster-count-mismatch-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-cluster-count-mismatch-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "glm_pipeline"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "threshold_summary.json").write_text(
            json.dumps(
                {
                    "n_clusters_found": 5,
                    "n_clusters_surviving": 3,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "cluster_table.csv").write_text(
            "cluster_id,cluster_size,p_fwe\n1,42,0.01\n2,18,0.03\n",
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-cluster-count-mismatch-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_CLUSTER_TABLE_COUNT_MISMATCH" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_peak_cluster_membership_invalid(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        review_context = {
            "schema_version": "review-context-v1",
            "statistical_inference": {
                "cluster_table_path": "cluster_table.csv",
                "peak_table_path": "peak_table.csv",
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-peak-cluster-membership-invalid-1",
                    "run_id": "run-native-peak-cluster-membership-invalid-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-peak-cluster-membership-invalid-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "glm_pipeline"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "cluster_table.csv").write_text(
            "cluster_id,cluster_size,p_fwe\n1,42,0.01\n2,18,0.03\n",
            encoding="utf-8",
        )
        (tmp_path / "peak_table.csv").write_text(
            "x,y,z,peak_z,cluster_id\n12,-8,50,5.1,1\n-24,-60,40,4.4,3\n",
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-peak-cluster-membership-invalid-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_PEAK_CLUSTER_MEMBERSHIP_INVALID" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_cluster_peak_cardinality_mismatch(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        review_context = {
            "schema_version": "review-context-v1",
            "statistical_inference": {
                "cluster_table_path": "cluster_table.csv",
                "peak_table_path": "peak_table.csv",
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-cluster-peak-cardinality-mismatch-1",
                    "run_id": "run-native-cluster-peak-cardinality-mismatch-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-cluster-peak-cardinality-mismatch-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "glm_pipeline"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "cluster_table.csv").write_text(
            "cluster_id,cluster_size,p_fwe\n1,42,0.01\n2,18,0.03\n",
            encoding="utf-8",
        )
        (tmp_path / "peak_table.csv").write_text(
            "x,y,z,peak_z,cluster_id\n12,-8,50,5.1,1\n",
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-cluster-peak-cardinality-mismatch-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_CLUSTER_PEAK_CARDINALITY_MISMATCH" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_peak_table_semantics_invalid(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        review_context = {
            "schema_version": "review-context-v1",
            "statistical_inference": {
                "peak_table_path": "peak_table.csv",
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-peak-table-invalid-1",
                    "run_id": "run-native-peak-table-invalid-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-peak-table-invalid-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "glm_pipeline"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "peak_table.csv").write_text(
            "cluster_id,peak_z\n1,5.1\n2,4.4\n",
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-peak-table-invalid-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_PEAK_TABLE_SEMANTICS_INVALID" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_design_model_metadata_mismatch(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        review_context = {
            "schema_version": "review-context-v1",
            "design_model": {
                "hrf_model": "spm + derivative",
                "temporal_derivative": True,
                "autocorrelation_model": "ar1",
                "prewhitening_method": "film",
                "prewhitening_enabled": True,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-design-model-mismatch-1",
                    "run_id": "run-native-design-model-mismatch-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-design-model-mismatch-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "glm_pipeline"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "first_level_summary.json").write_text(
            json.dumps(
                {
                    "hrf_model": "glover",
                    "noise_model": "ols",
                    "prewhitening_method": "ols",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "design_matrix.tsv").write_text(
            "task\tmotion\n1\t0.1\n0\t0.2\n",
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-design-model-mismatch-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_DESIGN_MODEL_METADATA_MISMATCH" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_manifest_partition_conflict(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "fold_id": 0,
                        "partition": "train",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                    {
                        "fold_id": 0,
                        "partition": "test",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                ]
            ),
            encoding="utf-8",
        )
        review_context = {
            "schema_version": "review-context-v1",
            "split": {
                "fold_manifest_path": "fold_manifest.json",
                "required_group_keys": ["story", "session", "subject"],
            },
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                "nested_cv": True,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-neuroai-conflict-1",
                    "run_id": "run-native-neuroai-conflict-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-neuroai-conflict-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-neuroai-conflict-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_NEUROAI_SPLIT_MANIFEST_PARTITION_CONFLICT" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_missing_manifest_group_keys(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "fold_id": 0,
                        "partition": "train",
                        "story": "s1",
                        "subject": "u1",
                    },
                    {
                        "fold_id": 0,
                        "partition": "test",
                        "story": "s2",
                        "subject": "u2",
                    },
                ]
            ),
            encoding="utf-8",
        )
        review_context = {
            "schema_version": "review-context-v1",
            "split": {
                "fold_manifest_path": "fold_manifest.json",
                "required_group_keys": ["story", "session", "subject"],
            },
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                "nested_cv": True,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-neuroai-missing-keys-1",
                    "run_id": "run-native-neuroai-missing-keys-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-neuroai-missing-keys-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-neuroai-missing-keys-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_NEUROAI_SPLIT_MANIFEST_MISSING_GROUP_KEYS" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_subject_manifest_coverage_gap(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        subject_manifest = tmp_path / "subject_manifest.tsv"
        subject_manifest.write_text(
            "participant_id\nu1\nu2\n",
            encoding="utf-8",
        )
        fold_manifest = tmp_path / "fold_manifest.json"
        fold_manifest.write_text(
            json.dumps(
                [
                    {"fold_id": 0, "partition": "train", "subject": "u1"},
                    {"fold_id": 0, "partition": "test", "subject": "u3"},
                ]
            ),
            encoding="utf-8",
        )
        review_context = {
            "schema_version": "review-context-v1",
            "split": {
                "subject_manifest_path": "subject_manifest.tsv",
                "fold_manifest_path": "fold_manifest.json",
            },
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                "nested_cv": True,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-neuroai-subject-gap-1",
                    "run_id": "run-native-neuroai-subject-gap-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-neuroai-subject-gap-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-neuroai-subject-gap-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_NEUROAI_SUBJECT_MANIFEST_COVERAGE" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_subject_intersection_coverage_gap(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        subject_intersection = tmp_path / "subject_intersection.tsv"
        subject_intersection.write_text(
            "participant_id\nu1\nu2\n",
            encoding="utf-8",
        )
        fold_manifest = tmp_path / "fold_manifest.json"
        fold_manifest.write_text(
            json.dumps(
                [
                    {"fold_id": 0, "partition": "train", "subject": "u1"},
                    {"fold_id": 0, "partition": "test", "subject": "u3"},
                ]
            ),
            encoding="utf-8",
        )
        review_context = {
            "schema_version": "review-context-v1",
            "split": {
                "subject_intersection_manifest_path": "subject_intersection.tsv",
                "fold_manifest_path": "fold_manifest.json",
            },
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                "nested_cv": True,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-neuroai-intersection-gap-1",
                    "run_id": "run-native-neuroai-intersection-gap-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-neuroai-intersection-gap-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-neuroai-intersection-gap-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_NEUROAI_SUBJECT_INTERSECTION_COVERAGE" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_subject_intersection_subset_conflict(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        subject_manifest = tmp_path / "subject_manifest.tsv"
        subject_manifest.write_text(
            "participant_id\nu1\nu2\n",
            encoding="utf-8",
        )
        subject_intersection = tmp_path / "subject_intersection.tsv"
        subject_intersection.write_text(
            "participant_id\nu1\nu3\n",
            encoding="utf-8",
        )
        review_context = {
            "schema_version": "review-context-v1",
            "split": {
                "subject_manifest_path": "subject_manifest.tsv",
                "subject_intersection_manifest_path": "subject_intersection.tsv",
            },
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                "nested_cv": True,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-neuroai-intersection-subset-1",
                    "run_id": "run-native-neuroai-intersection-subset-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-neuroai-intersection-subset-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-neuroai-intersection-subset-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_NEUROAI_SUBJECT_INTERSECTION_SUBSET_CONFLICT" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_subject_selection_source_coverage_gap(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        selection_source = tmp_path / "subjects.txt"
        selection_source.write_text("u1\nu2\n", encoding="utf-8")
        fold_manifest = tmp_path / "fold_manifest.json"
        fold_manifest.write_text(
            json.dumps(
                [
                    {"fold_id": 0, "partition": "train", "subject": "u1"},
                    {"fold_id": 0, "partition": "test", "subject": "u3"},
                ]
            ),
            encoding="utf-8",
        )
        review_context = {
            "schema_version": "review-context-v1",
            "split": {
                "subject_selection_source": "subjects.txt",
                "fold_manifest_path": "fold_manifest.json",
            },
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                "nested_cv": True,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-neuroai-selection-source-1",
                    "run_id": "run-native-neuroai-selection-source-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-neuroai-selection-source-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-neuroai-selection-source-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_NEUROAI_SUBJECT_SELECTION_SOURCE_COVERAGE" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_subject_manifest_selection_source_conflict(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        selection_source = tmp_path / "subjects.txt"
        selection_source.write_text("u1\nu2\n", encoding="utf-8")
        subject_manifest = tmp_path / "subject_manifest.tsv"
        subject_manifest.write_text(
            "participant_id\nu1\nu3\n",
            encoding="utf-8",
        )
        review_context = {
            "schema_version": "review-context-v1",
            "split": {
                "subject_selection_source": "subjects.txt",
                "subject_manifest_path": "subject_manifest.tsv",
            },
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                "nested_cv": True,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-neuroai-subject-manifest-source-1",
                    "run_id": "run-native-neuroai-subject-manifest-source-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-neuroai-subject-manifest-source-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-neuroai-subject-manifest-source-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_NEUROAI_SUBJECT_MANIFEST_SELECTION_SOURCE_CONFLICT" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_declared_subject_set_missing_subject_column(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        subject_manifest = tmp_path / "subject_manifest.tsv"
        subject_manifest.write_text(
            "sample_id\nu1\nu2\n",
            encoding="utf-8",
        )
        review_context = {
            "schema_version": "review-context-v1",
            "split": {
                "subject_manifest_path": "subject_manifest.tsv",
            },
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                "nested_cv": True,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-neuroai-subject-column-gap-1",
                    "run_id": "run-native-neuroai-subject-column-gap-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-neuroai-subject-column-gap-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-neuroai-subject-column-gap-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_NEUROAI_DECLARED_SUBJECT_SET_MISSING_SUBJECT_COLUMN" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_warns_on_review_context_mirror_conflict(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        analysis_review_context = {
            "schema_version": "review-context-v1",
            "reason_tags": ["predictive"],
            "split": {"split_unit": "subject"},
            "null_model": {"null_model_spec": "permutation_test"},
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                "nested_cv": True,
            },
        }
        source_review_context = {
            "schema_version": "review-context-v1",
            "reason_tags": ["predictive"],
            "split": {"split_unit": "story"},
            "null_model": {"null_model_spec": "permutation_test"},
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                "nested_cv": True,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": analysis_review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-neuroai-mirror-conflict-1",
                    "run_id": "run-native-neuroai-mirror-conflict-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-neuroai-mirror-conflict-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "review_context": analysis_review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": source_review_context}),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-neuroai-mirror-conflict-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_REVIEW_CONTEXT_MIRROR_CONFLICT" in rule_ids
        assert verdict.correctness.decision == "flag"

    def test_distill_scientific_review_records_warns_on_external_evidence_path_integrity(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        (tmp_path / "run.json").write_text(
            json.dumps(
                {
                    "run_id": "run-external-evidence-path-1",
                    "status": "succeeded",
                    "review_contract": {
                        "contract_mode": "external_review_bundle",
                    },
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-external-evidence-path-1",
                    "run_id": "run-external-evidence-path-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-external-evidence-path-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "external_artifact_adapter"},
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "extraction_report.json").write_text(
            json.dumps(
                {
                    "schema_version": "external-extraction-report-v1",
                    "adapter_name": "generic_prediction_summary",
                    "indexed_artifacts": ["artifacts/source/run_summary.json"],
                    "inferred_fields": [
                        {
                            "field": "task",
                            "value": "working memory",
                            "evidence_path": "missing_summary.json",
                        }
                    ],
                    "review_contract": {"contract_mode": "external_review_bundle"},
                }
            ),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-external-evidence-path-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_EXTERNAL_EVIDENCE_PATH_INTEGRITY" in rule_ids
        assert verdict.correctness.decision == "flag"

    def test_distill_scientific_review_records_blocks_nested_cv_outer_holdout_conflict(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "outer_fold": 0,
                        "fold_id": 0,
                        "partition": "train",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                    {
                        "outer_fold": 0,
                        "fold_id": 1,
                        "partition": "test",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                ]
            ),
            encoding="utf-8",
        )
        review_context = {
            "schema_version": "review-context-v1",
            "split": {
                "fold_manifest_path": "fold_manifest.json",
                "required_group_keys": ["story", "session", "subject"],
            },
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                "nested_cv": True,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-neuroai-nested-conflict-1",
                    "run_id": "run-native-neuroai-nested-conflict-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-neuroai-nested-conflict-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-neuroai-nested-conflict-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_NEUROAI_NESTED_CV_OUTER_HOLDOUT_CONFLICT" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_nested_cv_schema_missing_fold_keys(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {"fold_id": 0, "partition": "train", "subject": "u1"},
                    {"fold_id": 0, "partition": "test", "subject": "u2"},
                ]
            ),
            encoding="utf-8",
        )
        review_context = {
            "schema_version": "review-context-v1",
            "split": {
                "fold_manifest_path": "fold_manifest.json",
                "required_group_keys": ["subject"],
            },
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                "nested_cv": True,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-neuroai-nested-schema-1",
                    "run_id": "run-native-neuroai-nested-schema-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-neuroai-nested-schema-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-neuroai-nested-schema-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_NEUROAI_NESTED_CV_SCHEMA_MISSING_FOLD_KEYS" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_nested_cv_inner_partition_gap(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "outer_fold": 0,
                        "inner_fold": 0,
                        "partition": "train",
                        "subject": "u1",
                    },
                    {
                        "outer_fold": 0,
                        "partition": "test",
                        "subject": "u2",
                    },
                ]
            ),
            encoding="utf-8",
        )
        review_context = {
            "schema_version": "review-context-v1",
            "split": {
                "fold_manifest_path": "fold_manifest.json",
                "required_group_keys": ["subject"],
            },
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                "nested_cv": True,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-neuroai-inner-gap-1",
                    "run_id": "run-native-neuroai-inner-gap-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-neuroai-inner-gap-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-neuroai-inner-gap-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_NEUROAI_NESTED_CV_INNER_PARTITION_GAP" in rule_ids
        assert verdict.correctness.decision == "block"

    def test_distill_scientific_review_records_blocks_outer_missing_inner_resampling(
        self, tmp_path
    ):
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {"outer_fold": 0, "partition": "train", "subject": "u1"},
                    {"outer_fold": 0, "partition": "validation", "subject": "u2"},
                    {
                        "outer_fold": 0,
                        "partition": "test",
                        "inner_fold": 0,
                        "subject": "u3",
                    },
                ]
            ),
            encoding="utf-8",
        )
        review_context = {
            "schema_version": "review-context-v1",
            "split": {
                "fold_manifest_path": "fold_manifest.json",
                "required_group_keys": ["subject"],
            },
            "selection": {
                "best_layer": "layer-12",
                "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                "nested_cv": True,
            },
        }
        (tmp_path / "run.json").write_text(
            json.dumps({"steps": [], "review_context": review_context}),
            encoding="utf-8",
        )
        (tmp_path / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "run-native-neuroai-outer-missing-inner-1",
                    "run_id": "run-native-neuroai-outer-missing-inner-1",
                    "state": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "run_id": "run-native-neuroai-outer-missing-inner-1",
                    "run_dir": str(tmp_path),
                    "files": {"observation_json": "observation.json"},
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "review_context": review_context,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "source_summary.json").write_text(
            json.dumps({"review_context": review_context}),
            encoding="utf-8",
        )

        verdict = distill_scientific_review_records(
            "run-native-neuroai-outer-missing-inner-1",
            run_dir=tmp_path,
            use_judgment_critic=False,
            force_recompute=True,
        )

        rule_ids = {finding.rule_id for finding in verdict.correctness.findings}
        assert "REVIEW_NEUROAI_NESTED_CV_OUTER_MISSING_INNER_RESAMPLING" in rule_ids
        assert verdict.correctness.decision == "block"


# ---------------------------------------------------------------------------
# Completeness checklist
# ---------------------------------------------------------------------------


class TestCompleteness:
    def test_completeness_no_seed_for_stochastic(self):
        from brain_researcher.services.review.checks.completeness import (
            random_seed_pinned,
        )

        bundle = CodeReviewBundle(
            plan_steps=[{"tool": "ica", "params": {}, "step_id": "s1"}]
        )
        assert random_seed_pinned(bundle) is False

    def test_completeness_seed_pinned(self):
        from brain_researcher.services.review.checks.completeness import (
            random_seed_pinned,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {"tool": "ica", "params": {"random_state": 42}, "step_id": "s1"}
            ]
        )
        assert random_seed_pinned(bundle) is True

    def test_completeness_no_atlas_tool_na(self):
        from brain_researcher.services.review.checks.completeness import (
            atlas_version_pinned,
        )

        bundle = CodeReviewBundle(
            plan_steps=[{"tool": "run_glm", "params": {}, "step_id": "s1"}]
        )
        # No atlas tool — N/A → True
        assert atlas_version_pinned(bundle) is True

    def test_atlas_tool_without_version(self):
        from brain_researcher.services.review.checks.completeness import (
            atlas_version_pinned,
        )

        bundle = CodeReviewBundle(
            plan_steps=[{"tool": "parcellation_fetch", "params": {}, "step_id": "s1"}]
        )
        assert atlas_version_pinned(bundle) is False

    def test_atlas_tool_with_version(self):
        from brain_researcher.services.review.checks.completeness import (
            atlas_version_pinned,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "parcellation_fetch",
                    "params": {"atlas_version": "2018"},
                    "step_id": "s1",
                }
            ]
        )
        assert atlas_version_pinned(bundle) is True

    def test_atlas_version_requires_all_atlas_steps(self):
        from brain_researcher.services.review.checks.completeness import (
            atlas_version_pinned,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "parcellation_fetch",
                    "params": {"atlas_version": "2018"},
                    "step_id": "s1",
                },
                {"tool": "parcellation_fetch", "params": {}, "step_id": "s2"},
            ]
        )
        assert atlas_version_pinned(bundle) is False

    def test_ordering_rule_required_for_output_like_step(self):
        from brain_researcher.services.review.checks.completeness import (
            ordering_rule_declared,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "write_csv",
                    "params": {"output_csv": "results.csv"},
                    "step_id": "s1",
                }
            ]
        )
        assert ordering_rule_declared(bundle) is False

    def test_ordering_rule_detected_for_output_like_step(self):
        from brain_researcher.services.review.checks.completeness import (
            ordering_rule_declared,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "write_csv",
                    "params": {
                        "output_csv": "results.csv",
                        "sort_order": "participant_id",
                    },
                    "step_id": "s1",
                }
            ]
        )
        assert ordering_rule_declared(bundle) is True

    def test_build_completeness_checklist(self):
        from brain_researcher.services.review.checks.completeness import (
            build_completeness_checklist,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {"tool": "ica", "params": {"random_state": 42}, "step_id": "s1"},
                {
                    "tool": "parcellation_fetch",
                    "params": {"atlas_version": "2018"},
                    "step_id": "s2",
                },
            ]
        )
        checklist = build_completeness_checklist(bundle)
        assert checklist["random_seed_pinned"] is True
        assert checklist["atlas_version_pinned"] is True
        assert checklist["ordering_rule_declared"] is True  # N/A defaults True

    def test_build_completeness_checklist_uses_predictive_review_contract(self):
        from brain_researcher.services.review.checks.completeness import (
            build_completeness_checklist,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "external_analysis_summary",
                    "params": {
                        "task": "fluid intelligence",
                        "modality": "fmri",
                        "statistical_method": "graph_transformer",
                    },
                    "step_id": "s1",
                }
            ],
            observed_artifacts={
                "review_contract": {
                    "scientific_review_profile": "predictive_model_review",
                    "scientific_completeness_checks": [
                        "random_seed_pinned",
                        "target_declared",
                        "evaluation_protocol_declared",
                        "subject_alignment_declared",
                    ],
                },
                "source_summary": {
                    "target_column": "PMAT24_A_CR",
                    "n_folds": 10,
                    "subject_alignment_status": "verified_subject_list_file",
                    "subject_intersection_manifest_path": "/tmp/subjects.json",
                },
            },
            stats_metrics={
                "external_n_folds": 10,
                "external_mean_test_r2": 0.0375,
                "external_item_count": 326,
            },
            kg_context={"task": "fluid intelligence"},
        )
        checklist = build_completeness_checklist(bundle)
        assert set(checklist) == {
            "random_seed_pinned",
            "target_declared",
            "evaluation_protocol_declared",
            "subject_alignment_declared",
        }
        assert checklist["random_seed_pinned"] is True
        assert checklist["target_declared"] is True
        assert checklist["evaluation_protocol_declared"] is True
        assert checklist["subject_alignment_declared"] is True

    def test_build_completeness_checklist_accepts_manifest_backed_lanea_summary(self):
        from brain_researcher.services.review.checks.completeness import (
            build_completeness_checklist,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "external_analysis_summary",
                    "params": {
                        "task": "liu behavior factor",
                        "modality": "fmri",
                        "statistical_method": "ridge",
                    },
                    "step_id": "s1",
                }
            ],
            observed_artifacts={
                "review_contract": {
                    "scientific_review_profile": "predictive_model_review",
                    "scientific_completeness_checks": [
                        "target_declared",
                        "evaluation_protocol_declared",
                        "subject_alignment_declared",
                    ],
                },
                "source_summary": {
                    "target_name": "liu_behavior_factor_0",
                    "n_folds": 10,
                    "mean_proxy_score": 0.43,
                    "subject_manifest_path": "/tmp/manifests/subject_manifest.json",
                    "fold_manifest_path": "/tmp/manifests/fold_manifest.json",
                },
            },
            kg_context={"task": "liu behavior factor"},
        )

        checklist = build_completeness_checklist(bundle)
        assert checklist["target_declared"] is True
        assert checklist["evaluation_protocol_declared"] is True
        assert checklist["subject_alignment_declared"] is True

    def test_target_declared_prefers_research_episode_estimand(self):
        from brain_researcher.services.review.checks.completeness import (
            target_declared,
        )

        bundle = CodeReviewBundle(
            observed_artifacts={
                "research_episode": {
                    "schema_version": "research-episode-v1",
                    "episode_id": "episode:predictive-1",
                    "estimand": "Predict PMAT24_A_CR from FC connectivity",
                }
            }
        )

        assert target_declared(bundle) is True

    def test_evaluation_protocol_declared_prefers_execution_manifest_parameters(self):
        from brain_researcher.services.review.checks.completeness import (
            evaluation_protocol_declared,
        )

        bundle = CodeReviewBundle(
            observed_artifacts={
                "execution_manifest": {
                    "schema_version": "execution-manifest-v1",
                    "parameters": {
                        "n_folds": 10,
                        "evaluation_protocol": "nested_cv",
                    },
                }
            }
        )

        assert evaluation_protocol_declared(bundle) is True

    def test_subject_alignment_declared_prefers_native_manifest_refs(self):
        from brain_researcher.services.review.checks.completeness import (
            subject_alignment_declared,
        )

        bundle = CodeReviewBundle(
            observed_artifacts={
                "observation": {
                    "schema_version": "observation-v1",
                    "job_id": "job-align-1",
                    "state": "succeeded",
                    "inputs_manifest_ref": "manifests/subject_manifest.json",
                },
                "analysis_bundle": {
                    "schema_version": "analysis-bundle-v1",
                    "source_manifests": [
                        "manifests/fold_manifest.json",
                        "manifests/target_manifest.json",
                    ],
                    "files": {
                        "observation_json": "observation.json",
                        "execution_manifest_json": "execution_manifest.json",
                    },
                },
            }
        )

        assert subject_alignment_declared(bundle) is True

    def test_build_completeness_checklist_uses_profile_defaults(self):
        from brain_researcher.services.review.checks.completeness import (
            build_completeness_checklist,
        )

        bundle = CodeReviewBundle(
            review_context={
                "split": {"split_manifest_path": "manifests/subject_manifest.json"},
                "null_model": {"permutation_baseline_spec": "label_shuffle"},
                "preprocessing": {"feature_selection_scope": "train_only"},
            },
            observed_artifacts={
                "review_contract": {
                    "scientific_review_profile": "predictive_model_review",
                },
                "research_episode": {
                    "schema_version": "research-episode-v1",
                    "episode_id": "episode:predictive-defaults",
                    "estimand": "Predict PMAT24_A_CR from FC connectivity",
                },
                "execution_manifest": {
                    "schema_version": "execution-manifest-v1",
                    "parameters": {
                        "n_folds": 10,
                        "split_manifest_path": "manifests/subject_manifest.json",
                        "permutation_baseline_spec": "label_shuffle",
                        "feature_selection_scope": "train_only",
                    },
                },
                "observation": {
                    "schema_version": "observation-v1",
                    "job_id": "job-profile-defaults",
                    "state": "succeeded",
                    "inputs_manifest_ref": "manifests/subject_manifest.json",
                },
                "analysis_bundle": {
                    "schema_version": "analysis-bundle-v1",
                    "files": {
                        "observation_json": "observation.json",
                        "execution_manifest_json": "execution_manifest.json",
                    },
                },
            },
        )

        checklist = build_completeness_checklist(bundle)
        assert set(checklist) == {
            "random_seed_pinned",
            "target_declared",
            "evaluation_protocol_declared",
            "subject_alignment_declared",
            "split_metadata_declared",
            "null_model_declared",
            "preprocessing_choices_declared",
            "nested_cv_structure_declared",
            "subject_manifest_declared",
            "sensitivity_package_declared",
        }
        assert checklist["random_seed_pinned"] is True
        assert checklist["target_declared"] is True
        assert checklist["evaluation_protocol_declared"] is True
        assert checklist["subject_alignment_declared"] is True
        assert checklist["split_metadata_declared"] is True
        assert checklist["null_model_declared"] is True
        assert checklist["preprocessing_choices_declared"] is True

    def test_evaluation_protocol_declared_accepts_review_context_split_metadata(self):
        from brain_researcher.services.review.checks.completeness import (
            evaluation_protocol_declared,
        )

        bundle = CodeReviewBundle(
            review_context={
                "split": {
                    "split_unit": "subject",
                    "split_strategy_detail": "groupkfold",
                    "grouped_split_keys": ["subject"],
                }
            }
        )

        assert evaluation_protocol_declared(bundle) is True

    def test_predictive_review_context_metadata_check_accepts_nested_split_and_null_model(
        self,
    ):
        from brain_researcher.services.review.checks.review_context_validity import (
            predictive_review_context_metadata_check,
        )

        bundle = CodeReviewBundle(
            review_context={
                "reason_tags": ["predictive"],
                "split": {
                    "split_unit": "subject",
                    "train_test_independence": True,
                },
                "null_model": {
                    "null_model_spec": "permutation_test",
                    "permutation_baseline_spec": "label_shuffle",
                },
            },
            stats_metrics={
                "artifact_scientific_review_profile": "predictive_model_review"
            },
        )

        assert predictive_review_context_metadata_check(bundle) is None

    def test_predictive_review_context_metadata_check_flags_missing_null_model(self):
        from brain_researcher.services.review.checks.review_context_validity import (
            predictive_review_context_metadata_check,
        )

        bundle = CodeReviewBundle(
            review_context={
                "reason_tags": ["predictive"],
                "split": {"split_unit": "subject"},
            },
            stats_metrics={
                "artifact_scientific_review_profile": "predictive_model_review"
            },
        )

        finding = predictive_review_context_metadata_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_PREDICTIVE_REVIEW_CONTEXT_METADATA"
        assert "null_mismatch" in finding.reason_tags

    def test_review_context_leakage_circularity_flag_check_surfaces_reason_tags(self):
        from brain_researcher.services.review.checks.review_context_validity import (
            review_context_leakage_circularity_flag_check,
        )

        bundle = CodeReviewBundle(
            review_context={
                "reason_tags": ["leakage", "predictive"],
                "flags": ["circularity"],
            }
        )

        finding = review_context_leakage_circularity_flag_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_REVIEW_CONTEXT_LEAKAGE_CIRCULARITY"
        assert set(finding.reason_tags) == {"circularity", "leakage"}

    def test_review_context_mirror_conflict_check_warns_on_cross_artifact_drift(self):
        from brain_researcher.services.review.checks.review_context_validity import (
            review_context_mirror_conflict_check,
        )

        bundle = CodeReviewBundle(
            review_context={
                "reason_tags": ["predictive"],
                "split": {"split_unit": "subject"},
                "selection": {"best_model": "ridge"},
            },
            observed_artifacts={
                "analysis_bundle": {
                    "review_context": {
                        "split": {"split_unit": "subject"},
                        "selection": {"best_model": "ridge"},
                    }
                },
                "review_contract": {
                    "review_context": {
                        "split": {"split_unit": "story"},
                        "selection": {"best_model": "ridge"},
                    }
                },
            },
            stats_metrics={
                "artifact_scientific_review_profile": "predictive_model_review"
            },
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = review_context_mirror_conflict_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_REVIEW_CONTEXT_MIRROR_CONFLICT"
        assert finding.action == "warn"
        assert finding.severity == "warn"
        assert finding.reason_tags == ["low_reliability"]
        assert any("split.split_unit" in item for item in finding.kg_evidence)

    def test_external_evidence_path_integrity_check_warns_on_missing_staged_evidence(
        self,
    ):
        from brain_researcher.services.review.checks.review_context_validity import (
            external_evidence_path_integrity_check,
        )

        bundle = CodeReviewBundle(
            observed_artifacts={
                "analysis_bundle": {"run_dir": "/tmp/fake-external-run"},
                "review_contract": {"contract_mode": "external_review_bundle"},
                "extraction_report": {
                    "adapter_name": "generic_prediction_summary",
                    "indexed_artifacts": ["artifacts/source/run_summary.json"],
                    "inferred_fields": [
                        {
                            "field": "task",
                            "value": "working memory",
                            "evidence_path": "missing_summary.json",
                        }
                    ],
                },
            }
        )

        finding = external_evidence_path_integrity_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_EXTERNAL_EVIDENCE_PATH_INTEGRITY"
        assert finding.action == "warn"
        assert finding.severity == "warn"
        assert finding.reason_tags == ["low_reliability"]
        assert any("missing_evidence_paths" in item for item in finding.kg_evidence)

    def test_external_evidence_path_integrity_check_accepts_staged_source_evidence(
        self, tmp_path
    ):
        from brain_researcher.services.review.checks.review_context_validity import (
            external_evidence_path_integrity_check,
        )

        source_root = tmp_path / "artifacts" / "source"
        source_root.mkdir(parents=True)
        (source_root / "run_summary.json").write_text("{}", encoding="utf-8")

        bundle = CodeReviewBundle(
            observed_artifacts={
                "analysis_bundle": {"run_dir": str(tmp_path)},
                "review_contract": {"contract_mode": "external_review_bundle"},
                "extraction_report": {
                    "adapter_name": "generic_prediction_summary",
                    "indexed_artifacts": ["artifacts/source/run_summary.json"],
                    "inferred_fields": [
                        {
                            "field": "task",
                            "value": "working memory",
                            "evidence_path": "run_summary.json",
                        }
                    ],
                },
            }
        )

        assert external_evidence_path_integrity_check(bundle) is None


# ---------------------------------------------------------------------------
# Scientific verdict roll-up
# ---------------------------------------------------------------------------


class TestScientificVerdictRollUp:
    def test_scientific_verdict_proceed_on_clean(self):
        correctness = CorrectnessVerdict(decision="pass")
        judgment = JudgmentVerdict(decision="sound")
        completeness = CompletenessVerdict(
            decision="complete", checklist={"random_seed_pinned": True}
        )
        decision, rationale = roll_up_scientific_decision(
            correctness, judgment, completeness
        )
        assert decision == "proceed"

    def test_scientific_verdict_stop_on_block(self):
        correctness = CorrectnessVerdict(
            decision="block",
            findings=[
                ReviewFinding(
                    rule_id="REVIEW_DESIGN_MATRIX_RANK_DEFICIENT",
                    severity="error",
                    message="rank deficient",
                )
            ],
        )
        judgment = JudgmentVerdict(decision="sound")
        completeness = CompletenessVerdict(decision="complete")
        decision, _ = roll_up_scientific_decision(correctness, judgment, completeness)
        assert decision == "stop_with_rationale"

    def test_scientific_verdict_diagnose_on_unsound_judgment(self):
        correctness = CorrectnessVerdict(decision="pass")
        judgment = JudgmentVerdict(
            decision="unsound", estimand_complete=False, method_defensible=False
        )
        completeness = CompletenessVerdict(decision="complete")
        decision, _ = roll_up_scientific_decision(correctness, judgment, completeness)
        assert decision == "diagnose"

    def test_scientific_verdict_explore_more_on_incomplete(self):
        correctness = CorrectnessVerdict(decision="pass")
        judgment = JudgmentVerdict(decision="sound")
        completeness = CompletenessVerdict(
            decision="incomplete",
            checklist={"random_seed_pinned": False, "atlas_version_pinned": False},
        )
        decision, _ = roll_up_scientific_decision(correctness, judgment, completeness)
        assert decision == "explore_more"

    def test_scientific_verdict_explore_more_on_questionable_judgment(self):
        correctness = CorrectnessVerdict(decision="pass")
        judgment = JudgmentVerdict(
            decision="questionable", issues=["judgment_critic unavailable"]
        )
        completeness = CompletenessVerdict(decision="complete")
        decision, _ = roll_up_scientific_decision(correctness, judgment, completeness)
        assert decision == "explore_more"

    def test_scientific_verdict_diagnose_on_flag(self):
        correctness = CorrectnessVerdict(
            decision="flag",
            findings=[
                ReviewFinding(
                    rule_id="REVIEW_CONTRAST_DIM_MISMATCH",
                    severity="warn",
                    message="contrast dim mismatch",
                )
            ],
        )
        judgment = JudgmentVerdict(decision="sound")
        completeness = CompletenessVerdict(decision="complete")
        decision, _ = roll_up_scientific_decision(correctness, judgment, completeness)
        assert decision == "diagnose"


# ---------------------------------------------------------------------------
# Judgment critic
# ---------------------------------------------------------------------------


class TestJudgmentCritic:
    def test_judgment_prompt_mentions_sensitivity_and_construct_validity(self):
        from brain_researcher.services.review.judgment_critic import (
            _build_judgment_prompt,
        )

        prompt = _build_judgment_prompt(
            CodeReviewBundle(
                plan_steps=[],
                review_context={
                    "sensitivity": {"controversial_choices": ["gsr"]},
                    "construct_validity": {
                        "behavioral_imbalance": {
                            "reaction_time": "large_group_difference"
                        }
                    },
                },
            )
        )

        assert "controversial choices" in prompt
        assert "behavioral or alternative explanations" in prompt
        assert "reverse inference" in prompt
        assert "mechanistic equivalence" in prompt

    def test_judgment_critic_prefers_default_llm_model_env(self, monkeypatch):
        from brain_researcher.services.review import judgment_critic as jc

        calls: list[dict[str, object]] = []

        class FakeRouter:
            def route_chat(
                self,
                *,
                prompt,
                model_hint=None,
                provider_lock=None,
                task_type=None,
                strict_json=None,
            ):
                calls.append(
                    {
                        "prompt": prompt,
                        "model_hint": model_hint,
                        "provider_lock": provider_lock,
                        "task_type": task_type,
                        "strict_json": strict_json,
                    }
                )

                class _Result:
                    text = (
                        '{"decision":"sound","estimand_complete":true,'
                        '"method_defensible":true,"issues":[],"reviewer_questions":[]}'
                    )

                return _Result()

        monkeypatch.setenv("DEFAULT_LLM_MODEL", "gemini-2.5-flash")
        monkeypatch.delenv("SCIENTIFIC_REVIEW_JUDGMENT_MODEL", raising=False)
        monkeypatch.delenv("JUDGMENT_CRITIC_MODEL", raising=False)
        monkeypatch.setattr(jc, "LLMRouter", FakeRouter)

        verdict = jc.run_judgment_critic(CodeReviewBundle(plan_steps=[]))

        assert verdict.decision == "sound"
        assert calls and calls[0]["model_hint"] == "gemini-2.5-flash"
        assert calls[0]["provider_lock"] == "gemini"

    def test_judgment_critic_uses_llm_router(self, monkeypatch):
        from brain_researcher.services.review import judgment_critic as jc

        calls: list[dict[str, object]] = []

        class FakeRouter:
            def route_chat(
                self,
                *,
                prompt,
                model_hint=None,
                provider_lock=None,
                task_type=None,
                strict_json=None,
            ):
                calls.append(
                    {
                        "prompt": prompt,
                        "model_hint": model_hint,
                        "provider_lock": provider_lock,
                        "task_type": task_type,
                        "strict_json": strict_json,
                    }
                )

                class _Result:
                    text = (
                        "```json\n"
                        '{"decision":"questionable","estimand_complete":false,'
                        '"method_defensible":true,"issues":["missing atlas"],'
                        '"reviewer_questions":["Which atlas?"]}\n'
                        "```"
                    )

                return _Result()

        monkeypatch.setattr(jc, "LLMRouter", FakeRouter)

        verdict = jc.run_judgment_critic(CodeReviewBundle(plan_steps=[]))

        assert verdict.decision == "questionable"
        assert verdict.estimand_complete is False
        assert verdict.issues == ["missing atlas"]
        assert verdict.reviewer_questions == ["Which atlas?"]
        assert calls and calls[0]["strict_json"] is True
        assert calls[0]["task_type"] == "classification"
        assert calls[0]["provider_lock"] == "gemini"

    def test_judgment_critic_prefers_gemini_fallback_when_google_key_present(
        self, monkeypatch
    ):
        from brain_researcher.services.review import judgment_critic as jc

        calls: list[dict[str, object]] = []

        class FakeRouter:
            def route_chat(
                self,
                *,
                prompt,
                model_hint=None,
                provider_lock=None,
                task_type=None,
                strict_json=None,
            ):
                calls.append({"model_hint": model_hint, "provider_lock": provider_lock})

                class _Result:
                    text = (
                        '{"decision":"sound","estimand_complete":true,'
                        '"method_defensible":true,"issues":[],"reviewer_questions":[]}'
                    )

                return _Result()

        monkeypatch.delenv("DEFAULT_LLM_MODEL", raising=False)
        monkeypatch.delenv("SCIENTIFIC_REVIEW_JUDGMENT_MODEL", raising=False)
        monkeypatch.delenv("JUDGMENT_CRITIC_MODEL", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
        monkeypatch.setattr(jc, "LLMRouter", FakeRouter)

        verdict = jc.run_judgment_critic(CodeReviewBundle(plan_steps=[]))

        assert verdict.decision == "sound"
        assert calls and calls[0]["model_hint"] == "gemini-2.5-flash"
        assert calls[0]["provider_lock"] == "gemini"

    def test_judgment_critic_router_failure_is_questionable(self, monkeypatch):
        from brain_researcher.services.review import judgment_critic as jc

        class FailingRouter:
            def route_chat(
                self,
                *,
                prompt,
                model_hint=None,
                provider_lock=None,
                task_type=None,
                strict_json=None,
            ):
                raise RuntimeError("router unavailable")

        monkeypatch.setattr(jc, "LLMRouter", FailingRouter)

        verdict = jc.run_judgment_critic(CodeReviewBundle(plan_steps=[]))

        assert verdict.decision == "questionable"
        assert any("router unavailable" in issue for issue in verdict.issues)


# ---------------------------------------------------------------------------
# Cross-step assumption consistency
# ---------------------------------------------------------------------------


class TestCrossStepCompat:
    def test_bandpass_glm_drift_overlap_warns(self):
        from brain_researcher.services.review.checks.cross_step_compat import (
            bandpass_glm_drift_overlap,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "nilearn_clean_img",
                    "params": {"high_pass": 0.01},
                    "step_id": "s1",
                },
                {
                    "tool": "glm_first_level",
                    "params": {"high_pass": 0.01},
                    "step_id": "s2",
                },
            ]
        )
        finding = bandpass_glm_drift_overlap(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_BANDPASS_GLM_DRIFT_OVERLAP"

    def test_bandpass_glm_no_overlap_when_distant_freqs(self):
        from brain_researcher.services.review.checks.cross_step_compat import (
            bandpass_glm_drift_overlap,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "bandpass_filter",
                    "params": {"high_pass": 0.005},
                    "step_id": "s1",
                },
                {"tool": "fsl_feat", "params": {"high_pass": 0.02}, "step_id": "s2"},
            ]
        )
        # ratio = 0.02/0.005 = 4.0 > 2.0 → no overlap
        assert bandpass_glm_drift_overlap(bundle) is None

    def test_bandpass_glm_no_glm_returns_none(self):
        from brain_researcher.services.review.checks.cross_step_compat import (
            bandpass_glm_drift_overlap,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "nilearn_clean_img",
                    "params": {"high_pass": 0.01},
                    "step_id": "s1",
                },
            ]
        )
        assert bandpass_glm_drift_overlap(bundle) is None

    def test_xcpd_bandpass_tuple(self):
        from brain_researcher.services.review.checks.cross_step_compat import (
            bandpass_glm_drift_overlap,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "xcpd",
                    "params": {"bandpass_filter": [0.01, 0.1]},
                    "step_id": "s1",
                },
                {
                    "tool": "nilearn_first_level_model",
                    "params": {"high_pass": 0.01},
                    "step_id": "s2",
                },
            ]
        )
        finding = bandpass_glm_drift_overlap(bundle)
        assert finding is not None

    def test_preprocessing_stats_space_mismatch(self):
        from brain_researcher.services.review.checks.cross_step_compat import (
            preprocessing_stats_space_mismatch,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "fmriprep",
                    "params": {"output_space": "MNI152NLin2009cAsym"},
                    "step_id": "s1",
                },
                {
                    "tool": "extract_timeseries",
                    "params": {"atlas_space": "MNI152NLin6Asym"},
                    "step_id": "s2",
                },
            ]
        )
        finding = preprocessing_stats_space_mismatch(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_SPACE_MISMATCH_ACROSS_STEPS"

    def test_preprocessing_stats_space_match(self):
        from brain_researcher.services.review.checks.cross_step_compat import (
            preprocessing_stats_space_mismatch,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "fmriprep",
                    "params": {"output_space": "MNI152NLin2009cAsym"},
                    "step_id": "s1",
                },
                {
                    "tool": "glm_first_level",
                    "params": {"space": "MNI152NLin2009cAsym"},
                    "step_id": "s2",
                },
            ]
        )
        assert preprocessing_stats_space_mismatch(bundle) is None

    def test_bandpass_before_confound_warns(self):
        from brain_researcher.services.review.checks.cross_step_compat import (
            bandpass_before_confound_regression,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "bandpass_filter",
                    "params": {"high_pass": 0.01},
                    "step_id": "s1",
                },
                {"tool": "confound_regression", "params": {}, "step_id": "s2"},
            ]
        )
        finding = bandpass_before_confound_regression(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_BANDPASS_BEFORE_CONFOUND"

    def test_confound_before_bandpass_ok(self):
        from brain_researcher.services.review.checks.cross_step_compat import (
            bandpass_before_confound_regression,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {"tool": "confound_regression", "params": {}, "step_id": "s1"},
                {
                    "tool": "bandpass_filter",
                    "params": {"high_pass": 0.01},
                    "step_id": "s2",
                },
            ]
        )
        assert bandpass_before_confound_regression(bundle) is None

    def test_atlas_reg_space_mismatch(self):
        from brain_researcher.services.review.checks.cross_step_compat import (
            atlas_registration_space_mismatch,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "fsl_flirt",
                    "params": {"target_space": "MNI152NLin6Asym"},
                    "step_id": "s1",
                },
                {
                    "tool": "parcellation_fetch",
                    "params": {"atlas_space": "MNI152NLin2009cAsym"},
                    "step_id": "s2",
                },
            ]
        )
        finding = atlas_registration_space_mismatch(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_ATLAS_REG_SPACE_MISMATCH"

    def test_atlas_reg_space_match(self):
        from brain_researcher.services.review.checks.cross_step_compat import (
            atlas_registration_space_mismatch,
        )

        bundle = CodeReviewBundle(
            plan_steps=[
                {
                    "tool": "fsl_flirt",
                    "params": {"target_space": "MNI152NLin2009cAsym"},
                    "step_id": "s1",
                },
                {
                    "tool": "parcellation_fetch",
                    "params": {"atlas_space": "MNI152NLin2009cAsym"},
                    "step_id": "s2",
                },
            ]
        )
        assert atlas_registration_space_mismatch(bundle) is None

    def test_empty_plan_returns_none(self):
        from brain_researcher.services.review.checks.cross_step_compat import (
            atlas_registration_space_mismatch,
            bandpass_before_confound_regression,
            bandpass_glm_drift_overlap,
            preprocessing_stats_space_mismatch,
        )

        bundle = CodeReviewBundle(plan_steps=[])
        assert bandpass_glm_drift_overlap(bundle) is None
        assert preprocessing_stats_space_mismatch(bundle) is None
        assert bandpass_before_confound_regression(bundle) is None
        assert atlas_registration_space_mismatch(bundle) is None


# ---------------------------------------------------------------------------
# Design matrix numerical diagnostics
# ---------------------------------------------------------------------------


class TestConditionNumber:
    def test_condition_number_critical(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            condition_number_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={"design_matrix_condition_number": 50000}
        )
        finding = condition_number_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CONDITION_NUMBER_CRITICAL"
        assert finding.severity == "error"

    def test_condition_number_high(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            condition_number_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={"design_matrix_condition_number": 5000}
        )
        finding = condition_number_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CONDITION_NUMBER_HIGH"
        assert finding.severity == "warn"

    def test_condition_number_ok(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            condition_number_check,
        )

        bundle = CodeReviewBundle(stats_metrics={"design_matrix_condition_number": 100})
        assert condition_number_check(bundle) is None

    def test_condition_number_missing(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            condition_number_check,
        )

        bundle = CodeReviewBundle(stats_metrics={})
        assert condition_number_check(bundle) is None

    def test_contrast_estimability_false(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            contrast_estimability_check,
        )

        bundle = CodeReviewBundle(stats_metrics={"contrast_estimable": False})
        finding = contrast_estimability_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CONTRAST_NOT_ESTIMABLE"
        assert finding.severity == "error"

    def test_contrast_estimability_true(self):
        from brain_researcher.services.review.checks.artifact_structure import (
            contrast_estimability_check,
        )

        bundle = CodeReviewBundle(stats_metrics={"contrast_estimable": True})
        assert contrast_estimability_check(bundle) is None


# ---------------------------------------------------------------------------
# Correlation matrix validity
# ---------------------------------------------------------------------------


class TestCorrelationValidity:
    def test_corr_has_nan(self):
        from brain_researcher.services.review.checks.correlation_validity import (
            corr_has_nan_check,
        )

        bundle = CodeReviewBundle(stats_metrics={"corr_has_nan": True})
        finding = corr_has_nan_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CORR_HAS_NAN"

    def test_corr_not_symmetric(self):
        from brain_researcher.services.review.checks.correlation_validity import (
            corr_symmetric_check,
        )

        bundle = CodeReviewBundle(stats_metrics={"corr_symmetric": False})
        finding = corr_symmetric_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CORR_NOT_SYMMETRIC"

    def test_corr_diag_not_ones(self):
        from brain_researcher.services.review.checks.correlation_validity import (
            corr_diag_check,
        )

        bundle = CodeReviewBundle(stats_metrics={"corr_diag_all_ones": False})
        finding = corr_diag_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CORR_DIAG_NOT_ONES"
        assert finding.severity == "warn"

    def test_corr_out_of_range(self):
        from brain_researcher.services.review.checks.correlation_validity import (
            corr_range_check,
        )

        bundle = CodeReviewBundle(stats_metrics={"corr_range_valid": False})
        finding = corr_range_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CORR_OUT_OF_RANGE"

    def test_corr_not_psd(self):
        from brain_researcher.services.review.checks.correlation_validity import (
            corr_positive_semidefinite_check,
        )

        bundle = CodeReviewBundle(stats_metrics={"corr_positive_semidefinite": False})
        finding = corr_positive_semidefinite_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CORR_NOT_PSD"
        assert finding.severity == "warn"

    def test_corr_too_few_regions(self):
        from brain_researcher.services.review.checks.correlation_validity import (
            corr_region_count_check,
        )

        bundle = CodeReviewBundle(stats_metrics={"corr_n_regions": 1})
        finding = corr_region_count_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CORR_TOO_FEW_REGIONS"

    def test_corr_many_regions(self):
        from brain_researcher.services.review.checks.correlation_validity import (
            corr_region_count_check,
        )

        bundle = CodeReviewBundle(stats_metrics={"corr_n_regions": 1500})
        finding = corr_region_count_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CORR_MANY_REGIONS"
        assert finding.severity == "warn"

    def test_corr_all_valid(self):
        from brain_researcher.services.review.checks.correlation_validity import (
            corr_diag_check,
            corr_has_nan_check,
            corr_positive_semidefinite_check,
            corr_range_check,
            corr_region_count_check,
            corr_symmetric_check,
        )

        bundle = CodeReviewBundle(
            stats_metrics={
                "corr_n_regions": 100,
                "corr_symmetric": True,
                "corr_diag_all_ones": True,
                "corr_range_valid": True,
                "corr_positive_semidefinite": True,
                "corr_has_nan": False,
            }
        )
        assert corr_has_nan_check(bundle) is None
        assert corr_symmetric_check(bundle) is None
        assert corr_diag_check(bundle) is None
        assert corr_range_check(bundle) is None
        assert corr_positive_semidefinite_check(bundle) is None
        assert corr_region_count_check(bundle) is None

    def test_corr_missing_metrics(self):
        from brain_researcher.services.review.checks.correlation_validity import (
            corr_has_nan_check,
            corr_region_count_check,
            corr_symmetric_check,
        )

        bundle = CodeReviewBundle(stats_metrics={})
        assert corr_has_nan_check(bundle) is None
        assert corr_symmetric_check(bundle) is None
        assert corr_region_count_check(bundle) is None


# ---------------------------------------------------------------------------
# Stats extractor new metrics (integration tests with tmp_path)
# ---------------------------------------------------------------------------


class TestStatsExtractorNewMetrics:
    def test_extract_valid_correlation_matrix(self, tmp_path):
        import numpy as np

        from brain_researcher.services.review.stats_extractor import (
            _extract_correlation_matrix_metrics,
        )

        # Create a valid 10x10 correlation matrix
        rng = np.random.RandomState(42)
        A = rng.randn(50, 10)
        corr = np.corrcoef(A, rowvar=False)
        np.save(tmp_path / "connectivity_matrix.npy", corr)

        metrics = _extract_correlation_matrix_metrics(tmp_path)
        assert metrics["corr_n_regions"] == 10
        assert metrics["corr_symmetric"] is True
        assert metrics["corr_diag_all_ones"] is True
        assert metrics["corr_range_valid"] is True
        assert metrics["corr_positive_semidefinite"] is True
        assert metrics["corr_has_nan"] is False
        assert metrics["corr_condition_number"] is not None
        assert metrics["corr_min_eig"] is not None

    def test_extract_asymmetric_correlation_matrix(self, tmp_path):
        import numpy as np

        from brain_researcher.services.review.stats_extractor import (
            _extract_correlation_matrix_metrics,
        )

        matrix = np.eye(5)
        matrix[0, 1] = 0.5  # asymmetric: [0,1] != [1,0]
        np.save(tmp_path / "fc_matrix.npy", matrix)

        metrics = _extract_correlation_matrix_metrics(tmp_path)
        assert metrics["corr_symmetric"] is False

    def test_extract_correlation_matrix_stack(self, tmp_path):
        import numpy as np

        from brain_researcher.services.review.stats_extractor import (
            _extract_correlation_matrix_metrics,
        )

        stack = np.stack([np.eye(4), np.eye(4)])
        np.save(tmp_path / "connectivity_matrix.npy", stack)

        metrics = _extract_correlation_matrix_metrics(tmp_path)
        assert metrics["corr_n_regions"] == 4
        assert metrics["corr_symmetric"] is True
        assert metrics["corr_diag_all_ones"] is True
        assert metrics["corr_has_nan"] is False

    def test_extract_correlation_matrix_with_nan(self, tmp_path):
        import numpy as np

        from brain_researcher.services.review.stats_extractor import (
            _extract_correlation_matrix_metrics,
        )

        matrix = np.eye(5)
        matrix[0, 1] = float("nan")
        matrix[1, 0] = float("nan")
        np.save(tmp_path / "corr_matrix.npy", matrix)

        metrics = _extract_correlation_matrix_metrics(tmp_path)
        assert metrics["corr_has_nan"] is True

    def test_extract_correlation_matrix_missing(self, tmp_path):
        from brain_researcher.services.review.stats_extractor import (
            _extract_correlation_matrix_metrics,
        )

        metrics = _extract_correlation_matrix_metrics(tmp_path)
        assert metrics["corr_n_regions"] is None

    def test_extract_connectivity_contract_sidecar(self, tmp_path):
        from brain_researcher.services.review.stats_extractor import (
            extract_stats_from_run_dir,
        )

        contract = {
            "feature_contract": {
                "matrix_kind": "partial_correlation",
                "source_level": "raw_timeseries",
                "n_rois": 100,
                "effective_n_timepoints": 80,
                "precision_estimator": "EmpiricalCovariance",
                "precision_condition_number": 1e12,
                "min_eig": 1e-12,
                "transform_state": "fisher_z",
            }
        }
        (tmp_path / "feature_contract.json").write_text(
            json.dumps(contract),
            encoding="utf-8",
        )

        metrics = extract_stats_from_run_dir(tmp_path)
        assert metrics["corr_matrix_kind"] == "partial_correlation"
        assert metrics["connectivity_source_level"] == "raw_timeseries"
        assert metrics["corr_n_regions"] == 100
        assert metrics["corr_effective_n_timepoints"] == 80
        assert metrics["corr_precision_estimator"] == "EmpiricalCovariance"
        assert metrics["corr_precision_condition_number"] == 1e12
        assert metrics["corr_min_eig"] == 1e-12
        assert metrics["corr_transform_state"] == "fisher_z"

    def test_extract_condition_number_from_tsv(self, tmp_path):
        import numpy as np

        from brain_researcher.services.review.stats_extractor import (
            _extract_condition_number_metrics,
        )

        # Well-conditioned matrix
        matrix = np.column_stack(
            [
                np.ones(20),
                np.linspace(0, 1, 20),
                np.linspace(0, 1, 20) ** 2,
            ]
        )
        tsv = tmp_path / "design_matrix.tsv"
        header = "intercept\tlinear\tquadratic\n"
        rows = "\n".join("\t".join(f"{v:.6f}" for v in row) for row in matrix)
        tsv.write_text(header + rows)

        metrics = _extract_condition_number_metrics(tmp_path)
        assert metrics["design_matrix_condition_number"] is not None
        assert metrics["design_matrix_condition_number"] > 0

    def test_extract_condition_number_missing(self, tmp_path):
        from brain_researcher.services.review.stats_extractor import (
            _extract_condition_number_metrics,
        )

        metrics = _extract_condition_number_metrics(tmp_path)
        assert metrics["design_matrix_condition_number"] is None


# ---------------------------------------------------------------------------
# derive_verdict_metadata (shared helper powering native + autoresearch paths)
# ---------------------------------------------------------------------------


class TestDeriveVerdictMetadata:
    def _clean_cards(self):
        return (
            CorrectnessVerdict(decision="pass"),
            JudgmentVerdict(decision="sound"),
            CompletenessVerdict(decision="complete", checklist={}, missing_caveats=[]),
        )

    def test_proceed_all_clean_returns_contract_satisfied_and_write_report(self):
        from brain_researcher.core.contracts.scientific_review import (
            derive_verdict_metadata,
        )

        correctness, judgment, completeness = self._clean_cards()
        claim_strength, report_action, actions, status = derive_verdict_metadata(
            correctness, judgment, completeness, "proceed"
        )
        assert claim_strength == "contract_satisfied"
        assert report_action == "write_report"
        assert actions == []
        assert status["structural_correctness"] == "ok"
        assert status["scientific_judgment"] == "ok"
        assert status["declared_completeness"] == "ok"
        assert status["validation_evidence"] == "missing"
        assert status["replication_evidence"] == "missing"

    def test_block_returns_revise_report_and_no_claim_strength(self):
        from brain_researcher.core.contracts.scientific_review import (
            derive_verdict_metadata,
        )

        correctness = CorrectnessVerdict(
            decision="block",
            findings=[
                ReviewFinding(
                    rule_id="BLOCKER_X",
                    severity="error",
                    action="block",
                    message="hard block",
                    suggested_fix="fix it",
                )
            ],
        )
        _, judgment, completeness = self._clean_cards()
        claim_strength, report_action, actions, status = derive_verdict_metadata(
            correctness, judgment, completeness, "stop_with_rationale"
        )
        assert claim_strength is None
        assert report_action == "revise_report"
        assert any("Resolve blocking rule BLOCKER_X" in a for a in actions)
        assert status["structural_correctness"] == "failed"

    def test_explore_more_returns_continue_loop(self):
        from brain_researcher.core.contracts.scientific_review import (
            derive_verdict_metadata,
        )

        correctness, judgment, _ = self._clean_cards()
        completeness = CompletenessVerdict(
            decision="incomplete",
            checklist={"null_model_declared": False},
            missing_caveats=["null_model_declared not specified"],
        )
        claim_strength, report_action, actions, status = derive_verdict_metadata(
            correctness, judgment, completeness, "explore_more"
        )
        assert claim_strength is None
        assert report_action == "continue_loop"
        assert "Declare review_context field: null_model_declared" in actions
        assert status["declared_completeness"] == "missing"

    def test_unsound_judgment_adds_prepended_action(self):
        from brain_researcher.core.contracts.scientific_review import (
            derive_verdict_metadata,
        )

        correctness, _, completeness = self._clean_cards()
        judgment = JudgmentVerdict(
            decision="unsound",
            estimand_complete=False,
            method_defensible=False,
            issues=["model misspecified"],
        )
        claim_strength, report_action, actions, status = derive_verdict_metadata(
            correctness, judgment, completeness, "diagnose"
        )
        assert claim_strength is None
        # unsound should force revise_report even if overall decision is diagnose.
        assert report_action == "revise_report"
        assert actions[0].startswith("Judgment critic flagged method as unsound")
        assert status["scientific_judgment"] == "failed"

    def test_questionable_judgment_emits_reviewer_question_actions(self):
        from brain_researcher.core.contracts.scientific_review import (
            derive_verdict_metadata,
        )

        correctness, _, completeness = self._clean_cards()
        judgment = JudgmentVerdict(
            decision="questionable",
            reviewer_questions=[
                "Is the split subject-level?",
                "Is the baseline matched?",
                "Extra question that should be dropped",
            ],
        )
        _, report_action, actions, status = derive_verdict_metadata(
            correctness, judgment, completeness, "explore_more"
        )
        assert report_action == "continue_loop"
        q_actions = [a for a in actions if a.startswith("Answer reviewer question:")]
        assert len(q_actions) == 2
        assert "Is the split subject-level?" in q_actions[0]
        assert status["scientific_judgment"] == "missing"

    def test_incomplete_completeness_emits_declare_actions_capped_at_5(self):
        from brain_researcher.core.contracts.scientific_review import (
            derive_verdict_metadata,
        )

        correctness, judgment, _ = self._clean_cards()
        checklist = {f"k{i}": False for i in range(8)}
        completeness = CompletenessVerdict(
            decision="incomplete", checklist=checklist, missing_caveats=[]
        )
        _, _, actions, _ = derive_verdict_metadata(
            correctness, judgment, completeness, "explore_more"
        )
        declare_actions = [
            a for a in actions if a.startswith("Declare review_context field:")
        ]
        assert len(declare_actions) == 5

    def test_blocking_findings_emit_resolve_actions_capped_at_5(self):
        from brain_researcher.core.contracts.scientific_review import (
            derive_verdict_metadata,
        )

        findings = [
            ReviewFinding(
                rule_id=f"BLOCKER_{i}",
                severity="error",
                action="block",
                message=f"msg {i}",
            )
            for i in range(8)
        ]
        correctness = CorrectnessVerdict(decision="block", findings=findings)
        _, judgment, completeness = self._clean_cards()
        _, _, actions, _ = derive_verdict_metadata(
            correctness, judgment, completeness, "stop_with_rationale"
        )
        resolve = [a for a in actions if a.startswith("Resolve blocking rule")]
        assert len(resolve) == 5

    def test_validation_status_maps_reason_tags_to_failed(self):
        from brain_researcher.core.contracts.scientific_review import (
            derive_verdict_metadata,
        )

        correctness = CorrectnessVerdict(
            decision="block",
            findings=[
                ReviewFinding(
                    rule_id="LEAK_1",
                    severity="error",
                    action="block",
                    message="leakage detected",
                    reason_tags=["leakage", "null_mismatch"],
                ),
                ReviewFinding(
                    rule_id="FLAG_1",
                    severity="warn",
                    action="warn",
                    message="construct validity soft flag",
                    reason_tags=["construct_validity"],
                ),
            ],
        )
        _, judgment, completeness = self._clean_cards()
        _, _, _, status = derive_verdict_metadata(
            correctness, judgment, completeness, "stop_with_rationale"
        )
        assert status["issue:leakage"] == "failed"
        assert status["issue:null_mismatch"] == "failed"
        assert status["issue:construct_validity"] == "missing"

    def test_validation_evidence_flag_promotes_claim_strength_to_internally_supported(
        self,
    ):
        from brain_researcher.core.contracts.scientific_review import (
            derive_verdict_metadata,
        )

        correctness, judgment, completeness = self._clean_cards()
        claim_strength, _, _, status = derive_verdict_metadata(
            correctness,
            judgment,
            completeness,
            "proceed",
            scope="autoresearch_loop",
            validation_evidence_present=True,
            replication_evidence_present=False,
        )
        assert claim_strength == "internally_supported"
        assert status["validation_evidence"] == "ok"
        assert status["replication_evidence"] == "missing"

    def test_replication_evidence_flag_promotes_claim_strength_to_scientifically_convincing(
        self,
    ):
        from brain_researcher.core.contracts.scientific_review import (
            derive_verdict_metadata,
        )

        correctness, judgment, completeness = self._clean_cards()
        claim_strength, _, _, status = derive_verdict_metadata(
            correctness,
            judgment,
            completeness,
            "proceed",
            scope="autoresearch_loop",
            validation_evidence_present=True,
            replication_evidence_present=True,
        )
        assert claim_strength == "scientifically_convincing"
        assert status["validation_evidence"] == "ok"
        assert status["replication_evidence"] == "ok"
