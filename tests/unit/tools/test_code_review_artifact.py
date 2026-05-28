"""Unit tests for the artifact-time code review layer (Phase 2)."""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from brain_researcher.core.contracts.code_review import (
    CodeReviewBundle,
)
from brain_researcher.services.review.rule_engine import ReviewRuleEngine
from brain_researcher.services.review.stats_extractor import (
    _extract_scorecard_snapshot,
    extract_stats_from_run_dir,
)
from brain_researcher.services.review.verdict_builder import produce_verdict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine() -> ReviewRuleEngine:
    rules_path = Path(__file__).resolve().parents[3] / "configs" / "review_rules.yaml"
    return ReviewRuleEngine.from_yaml(rules_path)


def _artifact_bundle(**kwargs) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=[],
        stats_metrics=kwargs.get("stats_metrics", {}),
        scorecard_snapshot=kwargs.get("scorecard_snapshot", {}),
    )


# ---------------------------------------------------------------------------
# stats_extractor tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extract_stats_returns_empty_dict_on_empty_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics = extract_stats_from_run_dir(Path(tmpdir))
    assert isinstance(metrics, dict)
    # All values should be None or absent — no crashes
    for v in metrics.values():
        assert v is None


@pytest.mark.unit
def test_extract_motion_metrics_from_confounds_tsv():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        # Create a minimal confounds TSV
        confounds = run_dir / "sub-01_desc-confounds_timeseries.tsv"
        with confounds.open("w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["framewise_displacement"], delimiter="\t"
            )
            writer.writeheader()
            for fd in [0.1, 0.2, 0.6, 0.8, 0.15]:  # 2 > 0.5mm
                writer.writerow({"framewise_displacement": fd})

        metrics = extract_stats_from_run_dir(run_dir)

    expected_mean = (0.1 + 0.2 + 0.6 + 0.8 + 0.15) / 5
    assert metrics["mean_fd"] == pytest.approx(expected_mean, rel=1e-3)
    assert metrics["scrubbing_fraction"] == pytest.approx(0.4, abs=0.01)  # 2/5
    assert metrics["max_fd"] == pytest.approx(0.8, abs=0.001)


@pytest.mark.unit
def test_extract_glm_metrics_from_summary_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        summary = run_dir / "group_glm_summary.json"
        summary.write_text(
            json.dumps(
                {
                    "r_squared": 0.42,
                    "cohens_d_max": 1.8,
                    "n_subjects": 30,
                }
            )
        )
        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["r_squared"] == pytest.approx(0.42)
    assert metrics["cohens_d_max"] == pytest.approx(1.8)
    assert metrics["n_subjects"] == pytest.approx(30)


@pytest.mark.unit
def test_extract_design_matrix_metrics_from_csv():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        design = run_dir / "design_matrix.csv"
        design.write_text(
            "intercept,task,double_task\n1,0,0\n1,1,2\n1,0,0\n1,1,2\n",
            encoding="utf-8",
        )

        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["design_matrix_ncols"] == 3
    assert metrics["design_matrix_rank"] == 2
    assert metrics["design_matrix_columns"] == ["intercept", "task", "double_task"]


@pytest.mark.unit
def test_extract_thresholding_metrics_from_summary_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        summary = run_dir / "multiple_comparison_summary.json"
        summary.write_text(
            json.dumps(
                {
                    "method": "fdr_bh",
                    "alpha": 0.05,
                    "n_tests": 1000,
                    "significant_voxels": 42,
                    "cluster_threshold": 3.1,
                    "height_control": "fpr",
                }
            ),
            encoding="utf-8",
        )

        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["observed_multiple_comparison_correction"] == "fdr_bh"
    assert metrics["observed_multiple_comparison_alpha"] == pytest.approx(0.05)
    assert metrics["observed_multiple_comparison_n_tests"] == 1000
    assert metrics["observed_multiple_comparison_rejected_count"] == 42
    assert metrics["observed_cluster_forming_threshold"] == pytest.approx(3.1)
    assert metrics["observed_height_control"] == "fpr"
    assert metrics["observed_n_clusters_found"] is None
    assert metrics["observed_n_clusters_surviving"] is None


@pytest.mark.unit
def test_extract_thresholding_metrics_reads_cluster_counts():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        summary = run_dir / "threshold_summary.json"
        summary.write_text(
            json.dumps(
                {
                    "method": "cluster",
                    "n_clusters_found": 5,
                    "n_clusters_surviving": 3,
                }
            ),
            encoding="utf-8",
        )

        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["observed_n_clusters_found"] == 5
    assert metrics["observed_n_clusters_surviving"] == 3


@pytest.mark.unit
def test_extract_design_model_metrics_from_glm_summary_and_design_matrix():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        (run_dir / "first_level_summary.json").write_text(
            json.dumps(
                {
                    "hrf_model": "spm + derivative",
                    "noise_model": "ar1",
                    "high_pass": 0.01,
                    "drift_model": "cosine",
                    "tr": 2.0,
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "design_matrix.csv").write_text(
            "task,task_derivative,task_dispersion,motion\n1,0,0,0.1\n0,1,0,0.2\n",
            encoding="utf-8",
        )

        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["observed_hrf_model"] == "spm + derivative"
    assert metrics["observed_autocorrelation_model"] == "ar1"
    assert metrics["observed_high_pass_cutoff"] == pytest.approx(0.01)
    assert metrics["observed_drift_model"] == "cosine"
    assert metrics["observed_tr"] == pytest.approx(2.0)
    assert metrics["design_matrix_temporal_derivative_count"] == 1
    assert metrics["design_matrix_dispersion_derivative_count"] == 1


@pytest.mark.unit
def test_extract_cluster_peak_table_metrics_from_csv():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        (run_dir / "run.json").write_text(
            json.dumps(
                {
                    "review_context": {
                        "statistical_inference": {
                            "cluster_table_path": "cluster_table.csv",
                            "peak_table_path": "peak_table.csv",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "cluster_table.csv").write_text(
            "cluster_id,cluster_size,p_fwe,max_z\n1,42,0.01,5.1\n2,18,0.03,4.4\n",
            encoding="utf-8",
        )
        (run_dir / "peak_table.csv").write_text(
            "x,y,z,peak_z,cluster_id\n12,-8,50,5.1,1\n-24,-60,40,4.4,2\n",
            encoding="utf-8",
        )

        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["observed_cluster_table_rows"] == 2
    assert metrics["observed_cluster_table_has_cluster_size"] is True
    assert metrics["observed_cluster_table_has_significance"] is True
    assert metrics["observed_cluster_table_has_stat"] is True
    assert metrics["observed_cluster_table_cluster_ids"] == ["1", "2"]
    assert metrics["observed_cluster_table_duplicate_cluster_ids"] is False
    assert metrics["observed_peak_table_rows"] == 2
    assert metrics["observed_peak_table_has_coordinates"] is True
    assert metrics["observed_peak_table_has_stat"] is True
    assert metrics["observed_peak_table_cluster_ids"] == ["1", "2"]
    assert metrics["observed_peak_table_rows_missing_cluster_id"] == 0


@pytest.mark.unit
def test_extract_design_model_metrics_reads_prewhitening_from_fsf():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        (run_dir / "design.fsf").write_text(
            'set fmri(prewhiten_yn) 1\n',
            encoding="utf-8",
        )

        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["observed_prewhitening_enabled"] is True
    assert metrics["observed_prewhitening_method"] == "film"
    assert metrics["observed_serial_correlation_correction"] == "film"


@pytest.mark.unit
def test_extract_contrast_dims_from_run_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        (run_dir / "run.json").write_text(
            json.dumps(
                {
                    "steps": [
                        {
                            "tool_id": "glm_first_level",
                            "params": {"contrasts": {"task_effect": [0, 1, 0]}},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["contrast_dims"] == 3


@pytest.mark.unit
def test_extract_contrast_dims_prefers_native_observation_steps():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        (run_dir / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "job-native-contrast",
                    "run_id": "run-native-contrast",
                    "state": "succeeded",
                    "steps": [
                        {
                            "tool_id": "glm_first_level",
                            "params": {"contrast_vector": [1, 0, -1, 0]},
                            "status": "succeeded",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "execution_manifest.json").write_text("{}", encoding="utf-8")
        (run_dir / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "generated_at": "2026-04-10T00:00:00Z",
                    "files": {
                        "observation_json": "observation.json",
                        "execution_manifest_json": "execution_manifest.json",
                    },
                }
            ),
            encoding="utf-8",
        )

        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["contrast_dims"] == 4


@pytest.mark.unit
def test_extract_contrast_table_metrics_from_csv():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        (run_dir / "run.json").write_text(
            json.dumps(
                {
                    "review_context": {
                        "statistical_inference": {
                            "contrast_table_path": "contrast_table.csv",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "contrast_table.csv").write_text(
            "contrast_name,intercept,task,motion\n"
            "task_effect,0,1,0\n"
            "task_vs_motion,0,1,-1\n",
            encoding="utf-8",
        )

        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["observed_contrast_table_rows"] == 2
    assert metrics["observed_contrast_table_has_contrast_name"] is True
    assert metrics["observed_contrast_table_rows_missing_contrast_name"] == 0
    assert metrics["observed_contrast_table_names"] == [
        "task_effect",
        "task_vs_motion",
    ]
    assert metrics["observed_contrast_table_vector_lengths"] == [3]
    assert metrics["observed_contrast_table_rows_with_vector"] == 2


@pytest.mark.unit
def test_extract_cross_file_row_metrics():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        summary = run_dir / "group_glm_summary.json"
        summary.write_text(json.dumps({"n_subjects": 3}), encoding="utf-8")
        results = run_dir / "group_results.csv"
        results.write_text(
            "subject_id,value\nsub-01,0.1\nsub-02,0.2\n", encoding="utf-8"
        )

        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["metadata_n_subjects"] == pytest.approx(3)
    assert metrics["csv_n_rows"] == 2


@pytest.mark.unit
def test_extract_effect_and_tstat_map_shapes():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        effect_img = nib.Nifti1Image(np.zeros((10, 11, 12), dtype=float), np.eye(4))
        tstat_img = nib.Nifti1Image(np.zeros((10, 11, 12), dtype=float), np.eye(4))
        nib.save(effect_img, run_dir / "task_effect_map.nii.gz")
        nib.save(tstat_img, run_dir / "task_t_map.nii.gz")

        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["effect_map_shape"] == [10, 11, 12]
    assert metrics["tstat_map_shape"] == [10, 11, 12]


@pytest.mark.unit
def test_extract_qc_metrics_from_qc_report_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        qc_report = run_dir / "qc_report.json"
        qc_report.write_text(
            json.dumps(
                {
                    "total_subjects": 40,
                    "flagged": 8,
                }
            )
        )
        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["flag_rate"] == pytest.approx(0.2, abs=0.001)
    assert metrics["total_subjects"] == pytest.approx(40)


@pytest.mark.unit
def test_scorecard_snapshot_from_run_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        run_json = run_dir / "run.json"
        run_json.write_text(
            json.dumps(
                {
                    "steps": [
                        {"status": "succeeded"},
                        {"status": "succeeded"},
                        {"status": "failed"},
                    ]
                }
            )
        )
        snapshot = _extract_scorecard_snapshot(run_dir)

    assert snapshot["steps_total"] == 3
    assert snapshot["steps_succeeded"] == 2
    assert snapshot["steps_failed"] == 1
    assert snapshot["step_success_rate"] == pytest.approx(2 / 3, abs=0.001)


@pytest.mark.unit
def test_scorecard_snapshot_uses_external_review_contract():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        (run_dir / "run.json").write_text(
            json.dumps(
                {
                    "steps": [{"status": "succeeded"}],
                    "review_contract": {
                        "contract_mode": "external_review_bundle",
                        "required_root_artifacts": [
                            "run.json",
                            "provenance.json",
                            "observation.json",
                            "analysis_bundle.json",
                        ],
                        "recommended_root_artifacts": [
                            "artifact_manifest.json",
                            "source_summary.json",
                            "extraction_report.json",
                            "trace.jsonl",
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )
        for name in [
            "provenance.json",
            "observation.json",
            "analysis_bundle.json",
            "artifact_manifest.json",
            "source_summary.json",
            "extraction_report.json",
        ]:
            (run_dir / name).write_text("{}", encoding="utf-8")

        snapshot = _extract_scorecard_snapshot(run_dir)

    assert snapshot["artifact_completeness_ratio"] == pytest.approx(1.0, abs=0.001)
    assert snapshot["artifact_recommended_coverage_ratio"] == pytest.approx(
        0.75, abs=0.001
    )
    assert snapshot["artifact_minimal_reviewable"] is True
    assert snapshot["artifact_review_tier"] == "review_bundle_ready"
    assert snapshot["artifact_contract_mode"] == "external_review_bundle"


@pytest.mark.unit
def test_extract_external_summary_metrics_prefers_native_analysis_manifest():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        (run_dir / "source_summary.json").write_text(
            json.dumps({"n_items": 3, "mean_test_r2": 0.11}),
            encoding="utf-8",
        )
        (run_dir / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "generated_at": "2026-04-10T00:00:00Z",
                    "analysis_manifest": {
                        "n_items": 7,
                        "mean_test_r2": 0.61,
                        "mean_test_pearson_r": 0.44,
                    },
                    "files": {"observation_json": "observation.json"},
                }
            ),
            encoding="utf-8",
        )

        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["external_item_count"] == 7
    assert metrics["external_mean_test_r2"] == pytest.approx(0.61)
    assert metrics["external_mean_test_pearson_r"] == pytest.approx(0.44)


@pytest.mark.unit
def test_extract_external_summary_metrics_prefers_native_source_manifest_ref():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        nested = run_dir / "artifacts"
        nested.mkdir()
        (run_dir / "source_summary.json").write_text(
            json.dumps({"n_items": 3, "mean_test_r2": 0.11}),
            encoding="utf-8",
        )
        (nested / "source_summary.json").write_text(
            json.dumps(
                {
                    "n_items": 9,
                    "mean_test_r2": 0.73,
                    "mean_test_pearson_r": 0.52,
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "generated_at": "2026-04-10T00:00:00Z",
                    "source_manifests": ["artifacts/source_summary.json"],
                    "files": {"observation_json": "observation.json"},
                }
            ),
            encoding="utf-8",
        )

        metrics = extract_stats_from_run_dir(run_dir)

    assert metrics["external_item_count"] == 9
    assert metrics["external_mean_test_r2"] == pytest.approx(0.73)
    assert metrics["external_mean_test_pearson_r"] == pytest.approx(0.52)


@pytest.mark.unit
def test_scorecard_snapshot_prefers_native_bundle_contract():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        (run_dir / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "job-native-scorecard",
                    "run_id": "run-native-scorecard",
                    "state": "succeeded",
                    "steps": [
                        {"tool_id": "tribe_predict", "status": "succeeded"},
                        {"tool_id": "tribe_predict", "status": "failed"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "execution_manifest.json").write_text("{}", encoding="utf-8")
        (run_dir / "claim_report.json").write_text("{}", encoding="utf-8")
        (run_dir / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "generated_at": "2026-04-10T00:00:00Z",
                    "files": {
                        "observation_json": "observation.json",
                        "execution_manifest_json": "execution_manifest.json",
                        "claim_report_json": "claim_report.json",
                    },
                }
            ),
            encoding="utf-8",
        )

        snapshot = _extract_scorecard_snapshot(run_dir)

    assert snapshot["steps_total"] == 2
    assert snapshot["steps_succeeded"] == 1
    assert snapshot["steps_failed"] == 1
    assert snapshot["artifact_completeness_ratio"] == pytest.approx(1.0, abs=0.001)
    assert snapshot["artifact_recommended_coverage_ratio"] == pytest.approx(
        1.0, abs=0.001
    )
    assert snapshot["artifact_review_tier"] == "trace_complete"
    assert snapshot["artifact_contract_mode"] == "native_review_bundle"


@pytest.mark.unit
def test_scorecard_snapshot_surfaces_native_predictive_review_contract():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        (run_dir / "observation.json").write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "job-native-predictive-scorecard",
                    "run_id": "run-native-predictive-scorecard",
                    "state": "succeeded",
                    "steps": [
                        {
                            "tool_id": "external_analysis_summary",
                            "params": {"task": "fluid intelligence"},
                            "status": "succeeded",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "execution_manifest.json").write_text(
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
        (run_dir / "claim_report.json").write_text("{}", encoding="utf-8")
        (run_dir / "analysis_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "analysis-bundle-v1",
                    "generated_at": "2026-04-10T00:00:00Z",
                    "policy_snapshot": {"source": "predictive_loop_controller"},
                    "analysis_manifest": {
                        "target_column": "PMAT24_A_CR",
                        "classifier": "ridge",
                        "n_folds": 10,
                    },
                    "files": {
                        "observation_json": "observation.json",
                        "execution_manifest_json": "execution_manifest.json",
                        "claim_report_json": "claim_report.json",
                    },
                }
            ),
            encoding="utf-8",
        )

        snapshot = _extract_scorecard_snapshot(run_dir)

    assert snapshot["artifact_contract_mode"] == "native_review_bundle"
    assert snapshot["artifact_review_tier"] == "trace_complete"
    assert snapshot["artifact_scientific_review_profile"] == "predictive_model_review"
    assert snapshot["artifact_scientific_completeness_checks"] == [
        "random_seed_pinned",
        "target_declared",
        "evaluation_protocol_declared",
        "subject_alignment_declared",
        "split_metadata_declared",
        "null_model_declared",
        "preprocessing_choices_declared",
    ]


# ---------------------------------------------------------------------------
# Artifact-time rule evaluation tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_high_mean_fd_produces_warning():
    engine = _make_engine()
    bundle = _artifact_bundle(stats_metrics={"mean_fd": 0.7})
    verdict = produce_verdict(bundle, engine=engine)
    assert verdict.decision == "approve_with_warnings"
    rule_ids = [f.rule_id for f in verdict.findings]
    assert "REVIEW_MEAN_FD_HIGH" in rule_ids


@pytest.mark.unit
def test_high_scrubbing_rate_blocks():
    engine = _make_engine()
    bundle = _artifact_bundle(stats_metrics={"scrubbing_fraction": 0.35})
    verdict = produce_verdict(bundle, engine=engine)
    assert verdict.decision == "block"
    rule_ids = [f.rule_id for f in verdict.findings]
    assert "REVIEW_SCRUBBING_RATE_HIGH" in rule_ids


@pytest.mark.unit
def test_low_r_squared_warns():
    engine = _make_engine()
    bundle = _artifact_bundle(stats_metrics={"r_squared": 0.04})
    verdict = produce_verdict(bundle, engine=engine)
    rule_ids = [f.rule_id for f in verdict.findings]
    assert "REVIEW_R2_TOO_LOW" in rule_ids


@pytest.mark.unit
def test_effect_size_oob_warns():
    engine = _make_engine()
    bundle = _artifact_bundle(stats_metrics={"cohens_d_max": 4.5})
    verdict = produce_verdict(bundle, engine=engine)
    rule_ids = [f.rule_id for f in verdict.findings]
    assert "REVIEW_EFFECT_SIZE_OOB" in rule_ids


@pytest.mark.unit
def test_zero_flag_rate_warns():
    engine = _make_engine()
    bundle = _artifact_bundle(stats_metrics={"flag_rate": 0.0})
    verdict = produce_verdict(bundle, engine=engine)
    rule_ids = [f.rule_id for f in verdict.findings]
    assert "REVIEW_QC_FLAG_RATE_ZERO" in rule_ids


@pytest.mark.unit
def test_low_artifact_completeness_blocks():
    engine = _make_engine()
    bundle = _artifact_bundle(scorecard_snapshot={"artifact_completeness_ratio": 0.4})
    verdict = produce_verdict(bundle, engine=engine)
    assert verdict.decision == "block"
    rule_ids = [f.rule_id for f in verdict.findings]
    assert "REVIEW_ARTIFACT_COMPLETENESS_LOW" in rule_ids


@pytest.mark.unit
def test_failed_steps_blocks():
    engine = _make_engine()
    bundle = _artifact_bundle(
        scorecard_snapshot={
            "step_success_rate": 0.75,
            "steps_failed": 1,
            "steps_total": 4,
        }
    )
    verdict = produce_verdict(bundle, engine=engine)
    assert verdict.decision == "block"
    rule_ids = [f.rule_id for f in verdict.findings]
    assert "REVIEW_STEP_SUCCESS_RATE_LOW" in rule_ids


@pytest.mark.unit
def test_clean_artifact_bundle_approves():
    engine = _make_engine()
    bundle = _artifact_bundle(
        stats_metrics={
            "mean_fd": 0.2,
            "scrubbing_fraction": 0.05,
            "r_squared": 0.45,
            "cohens_d_max": 1.2,
            "flag_rate": 0.1,
        },
        scorecard_snapshot={
            "artifact_completeness_ratio": 1.0,
            "step_success_rate": 1.0,
            "steps_total": 4,
            "steps_failed": 0,
        },
    )
    verdict = produce_verdict(bundle, engine=engine)
    assert verdict.decision == "approve"
    assert verdict.findings == []


# ---------------------------------------------------------------------------
# run_code_review MCP tool (with synthetic run dir)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_code_review_on_synthetic_run(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    # Build a synthetic run dir with known artifacts
    run_dir = tmp_path / "run_test123"
    run_dir.mkdir()

    # Minimal run.json — all steps succeeded
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "status": "succeeded",
                "steps": [
                    {"tool_id": "fmriprep", "status": "succeeded"},
                    {"tool_id": "glm_first_level", "status": "succeeded"},
                ],
            }
        )
    )
    # Mark standard artifacts as present
    for fname in [
        "observation.json",
        "analysis_bundle.json",
        "provenance.json",
        "trace.jsonl",
    ]:
        (run_dir / fname).write_text("{}")

    # High-motion confounds — should trigger REVIEW_MEAN_FD_HIGH
    confounds = run_dir / "sub-01_desc-confounds_timeseries.tsv"
    with confounds.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["framewise_displacement"], delimiter="\t"
        )
        writer.writeheader()
        for fd in [0.6, 0.7, 0.8, 0.9, 1.0]:
            writer.writerow({"framewise_displacement": fd})

    # Patch _find_run_dir in the distill module (where bundle_builder imports it from)
    monkeypatch.setattr(
        "brain_researcher.services.memory.distill._find_run_dir",
        lambda run_id, run_dir=None: run_dir or (tmp_path / f"run_{run_id}"),
    )

    result = srv.run_code_review("test123", workflow_id=None)

    assert result.get("ok") is True
    assert result.get("decision") in {
        "approve",
        "approve_with_warnings",
        "revise",
        "block",
    }
    # High FD should trigger a finding
    rule_ids = [f["rule_id"] for f in result.get("findings", [])]
    assert "REVIEW_MEAN_FD_HIGH" in rule_ids


@pytest.mark.unit
def test_distill_review_records_flags_epistemic_overclaim(tmp_path, monkeypatch):
    from brain_researcher.services.review.distill_review import distill_review_records

    run_dir = tmp_path / "run_epistemic"
    run_dir.mkdir()

    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "status": "succeeded",
                "steps": [
                    {"tool_id": "external_analysis_summary", "status": "succeeded"}
                ],
                "review_contract": {
                    "contract_mode": "external_review_bundle",
                    "required_root_artifacts": [
                        "run.json",
                        "quote_grounded_evidence_items.json",
                        "quote_grounded_claims.json",
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "quote_grounded_evidence_items.json").write_text(
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
    (run_dir / "quote_grounded_claims.json").write_text(
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

    monkeypatch.setattr(
        "brain_researcher.services.memory.distill._find_run_dir",
        lambda run_id, run_dir=None: run_dir or (tmp_path / f"run_{run_id}"),
    )

    review = distill_review_records("epistemic", run_dir=run_dir, force_recompute=True)

    assert review.warnings == []
    assert review.verdict is not None
    assert review.verdict.decision == "revise"
    assert review.verdict.risk_level == "high"
    assert [f.rule_id for f in review.verdict.findings] == [
        "REVIEW_EPISTEMIC_CLAIM_POLICY"
    ]
    assert "uses verdict 'supported'" in review.verdict.findings[0].message
