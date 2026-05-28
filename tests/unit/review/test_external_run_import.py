from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.review.distill_review import distill_review_records
from brain_researcher.services.review.external_run_import import (
    ExternalRunImportSpec,
    build_imported_run_record,
    stage_external_run,
    stage_external_run_in_mcp_store,
)
from brain_researcher.services.review.native_review_contract import (
    build_native_review_contract,
)
from brain_researcher.services.review.stats_extractor import extract_stats_from_run_dir


def _write_fitlins_multiverse_fixture(root: Path, *, workflow_layout: bool) -> None:
    variants = [
        {
            "model_id": "mv001",
            "variant_id": "canonical_24mot_128",
            "hrf": "canonical",
            "hrf_basis": "spm",
            "confounds": "24mot",
            "high_pass": 128,
        },
        {
            "model_id": "mv002",
            "variant_id": "fir_gsr_100",
            "hrf": "fir",
            "hrf_basis": "fir",
            "confounds": "24mot_gsr",
            "high_pass": 100,
        },
    ]
    run_manifest = {
        "run_id": "fitlins-multiverse-source",
        "dataset_id": "ds000114",
        "task": "linebisection",
        "seed": 13,
        "k": 2,
        "runtime": "slurm",
        "analysis_level": "run",
        "execute": True,
        "variants": [
            {
                "model_id": row["model_id"],
                "variant_id": row["variant_id"],
                "decision_points": {
                    "hrf": row["hrf"],
                    "hrf_basis": row["hrf_basis"],
                    "confounds": row["confounds"],
                    "high_pass": row["high_pass"],
                },
                "status": "success",
            }
            for row in variants
        ],
    }
    spec_manifest = {
        "dataset_id": "ds000114",
        "task": "linebisection",
        "variants": variants,
    }
    robustness_payload = {
        "summary_path": (
            "fitlins/yeo17_summary.csv" if workflow_layout else "yeo17_summary.csv"
        ),
        "edges_path": (
            "fitlins/yeo17_edges.csv" if workflow_layout else "yeo17_edges.csv"
        ),
        "variants": variants,
        "contrasts": {
            "cue": {
                "n_variants": 2,
                "pairwise_corr_mean": 0.81,
                "pairwise_corr_min": 0.81,
                "top_regions_by_abs_mean": [
                    {
                        "region_id": "yeo17:03",
                        "region_name": "DefaultA",
                        "mean": 0.42,
                        "std": 0.05,
                        "sign_consistency": 1.0,
                    }
                ],
            }
        },
        "effect_size": {
            "cue": {
                "n_variants": 2,
                "pairwise_corr_mean": 0.77,
                "pairwise_corr_min": 0.77,
                "top_regions_by_abs_mean": [],
            }
        },
        "notes": {"warp_to_yeo_space": False},
    }
    summary_csv = "\n".join(
        [
            "model_id,variant_id,contrast,metric,region_id,value",
            "mv001,canonical_24mot_128,cue,mean_z,yeo17:03,0.4",
            "mv002,fir_gsr_100,cue,mean_z,yeo17:03,0.44",
            "mv001,canonical_24mot_128,cue,mean_z,yeo17:11,0.1",
            "mv002,fir_gsr_100,cue,mean_z,yeo17:11,0.12",
        ]
    )

    if workflow_layout:
        (root / "run_manifest.json").write_text(
            json.dumps(run_manifest),
            encoding="utf-8",
        )
        (root / "specs").mkdir(parents=True, exist_ok=True)
        (root / "specs" / "multiverse_manifest.json").write_text(
            json.dumps(spec_manifest),
            encoding="utf-8",
        )
        fitlins_dir = root / "fitlins"
        fitlins_dir.mkdir(parents=True, exist_ok=True)
        (fitlins_dir / "yeo17_summary.csv").write_text(summary_csv, encoding="utf-8")
        (fitlins_dir / "robustness_yeo17.json").write_text(
            json.dumps(robustness_payload),
            encoding="utf-8",
        )
        (fitlins_dir / "robustness_yeo17.md").write_text(
            "# Robustness\n",
            encoding="utf-8",
        )
        return

    (root / "multiverse_manifest.json").write_text(
        json.dumps(spec_manifest),
        encoding="utf-8",
    )
    (root / "yeo17_summary.csv").write_text(summary_csv, encoding="utf-8")
    (root / "robustness_yeo17.json").write_text(
        json.dumps(robustness_payload),
        encoding="utf-8",
    )
    (root / "robustness_yeo17.md").write_text("# Robustness\n", encoding="utf-8")


def test_build_imported_run_record_synthesizes_step_params(tmp_path: Path) -> None:
    spec = ExternalRunImportSpec(
        run_id="tribe-encoding-001",
        tool_id="glm_first_level",
        task="working memory",
        contrast_name="2-back > rest",
        dataset_id="ds000001",
        modality="fmri",
    )

    record = build_imported_run_record(tmp_path, spec)

    assert record["run_id"] == "tribe-encoding-001"
    assert record["status"] == "succeeded"
    assert len(record["steps"]) == 1
    step = record["steps"][0]
    assert step["tool_id"] == "glm_first_level"
    assert step["params"]["task"] == "working memory"
    assert step["params"]["contrast_name"] == "2-back > rest"
    assert step["params"]["dataset_id"] == "ds000001"
    assert step["params"]["modality"] == "fmri"


def test_build_native_review_contract_enriches_review_context_from_bundle(
    tmp_path: Path,
) -> None:
    bundle = {
        "schema_version": "analysis-bundle-v1",
        "analysis_manifest": {
            "split_manifest_path": "artifacts/split/split_manifest.json",
            "subject_manifest_path": "artifacts/split/subject_manifest.tsv",
            "fold_manifest_path": "artifacts/split/fold_manifest.json",
            "target_manifest_path": "artifacts/split/targets.json",
            "covariate_manifest_path": "artifacts/split/covariates.tsv",
            "subject_intersection_manifest_path": "artifacts/split/subject_intersection.tsv",
            "subject_selection_source": "subject_ids.tsv",
            "label_shuffle_seed": 1234,
            "reference_subject_count": 42,
            "n_folds": 5,
            "required_group_keys": ["story", "session", "subject_id"],
            "feature_strategy": "atlas_roi",
            "confounds": ["motion", "wm_csf"],
            "best_model": "semantic-encoder",
            "model_candidates": ["semantic-encoder", "phonetic-baseline"],
            "layer_candidates": ["layer-3", "layer-7"],
            "selection_accounting": {"nested_cv": True},
            "multiple_comparison_correction": "fdr",
            "correction_alpha": 0.05,
            "cluster_forming_threshold": 3.1,
            "height_control": "fpr",
            "sensitivity_requirements": ["gsr_on_off"],
            "reaction_time_difference": "large_group_difference",
            "controlled_covariates": ["reaction_time"],
            "matrix_kind": "partial_correlation",
            "source_level": "raw_timeseries",
            "n_rois": 100,
            "effective_n_timepoints": 80,
            "precision_estimator": "EmpiricalCovariance",
            "precision_condition_number": 1e12,
            "min_eig": 1e-12,
            "transform_state": "fisher_z",
            "label_permutation_null": {
                "status": "ok",
                "pipeline_scope": "full_pipeline",
                "cv_scope": "outer_train_fold_label_shuffle",
                "n_permutations": 1000,
                "verdict": "pass",
            },
        },
        "run_card": {
            "parameters": {
                "split_strategy": "subject-wise",
                "grouped_split_keys": ["subject_id"],
                "selection_scope": "validation_fold",
                "train_test_independence": "subject-disjoint",
                "permutation_test": True,
                "n_permutations": 1000,
                "permutation_seed": 17,
            }
        },
        "provenance": {"request": {"analysis_manifest_path": "analysis_manifest.json"}},
    }

    contract = build_native_review_contract(
        bundle,
        observation={"run_card": {"parameters": {"evaluation_strategy": "holdout"}}},
        execution_manifest={
            "parameters": {
                "resampling_method": "permutation",
                "n_permutations": 1000,
                "permutation_seed": 17,
                "exchangeability_blocks": ["subject_id"],
                "hrf_model": "spm + derivative",
                "noise_model": "ar1",
                "serial_correlation_correction": "film",
                "prewhitening_enabled": True,
                "high_pass": 0.01,
                "drift_model": "cosine",
            }
        },
    )

    review_context = contract["review_context"]
    assert review_context["split"]["split_strategy_detail"] == "subject-wise"
    assert review_context["split"]["grouped_split_keys"] == ["subject_id"]
    assert review_context["split"]["required_group_keys"] == [
        "story",
        "session",
        "subject_id",
    ]
    assert (
        review_context["split"]["subject_manifest_path"]
        == "artifacts/split/subject_manifest.tsv"
    )
    assert (
        review_context["split"]["fold_manifest_path"]
        == "artifacts/split/fold_manifest.json"
    )
    assert review_context["selection"]["best_model"] == "semantic-encoder"
    assert review_context["selection"]["selection_scope"] == "validation_fold"
    assert review_context["selection"]["model_candidates"] == [
        "semantic-encoder",
        "phonetic-baseline",
    ]
    assert review_context["selection"]["layer_candidates"] == [
        "layer-3",
        "layer-7",
    ]
    assert review_context["selection"]["selection_accounting"] == {"nested_cv": True}
    assert review_context["selection"]["multiple_comparison_correction"] == "fdr"
    assert review_context["preprocessing"]["feature_selection_scope"] == "atlas_roi"
    assert review_context["preprocessing"]["confound_regression_scope"] == [
        "motion",
        "wm_csf",
    ]
    assert review_context["feature_contract"]["matrix_kind"] == "partial_correlation"
    assert review_context["feature_contract"]["source_level"] == "raw_timeseries"
    assert review_context["feature_contract"]["n_rois"] == 100
    assert review_context["feature_contract"]["effective_n_timepoints"] == 80
    assert (
        review_context["feature_contract"]["precision_estimator"]
        == "EmpiricalCovariance"
    )
    assert review_context["feature_contract"]["precision_condition_number"] == 1e12
    assert review_context["feature_contract"]["min_eig"] == 1e-12
    assert review_context["feature_contract"]["transform_state"] == "fisher_z"
    assert review_context["review_probes"]["label_permutation_null"] == {
        "status": "ok",
        "pipeline_scope": "full_pipeline",
        "cv_scope": "outer_train_fold_label_shuffle",
        "n_permutations": 1000,
        "verdict": "pass",
    }
    assert (
        review_context["statistical_inference"]["multiple_comparison_correction"]
        == "fdr"
    )
    assert review_context["statistical_inference"]["correction_alpha"] == 0.05
    assert review_context["statistical_inference"]["cluster_forming_threshold"] == 3.1
    assert review_context["statistical_inference"]["height_control"] == "fpr"
    assert review_context["design_model"]["hrf_model"] == "spm + derivative"
    assert review_context["design_model"]["autocorrelation_model"] == "ar1"
    assert review_context["design_model"]["serial_correlation_correction"] == "film"
    assert review_context["design_model"]["prewhitening_enabled"] is True
    assert review_context["design_model"]["high_pass_cutoff"] == 0.01
    assert review_context["design_model"]["drift_model"] == "cosine"
    assert review_context["sensitivity"]["sensitivity_requirements"] == ["gsr_on_off"]
    assert review_context["construct_validity"]["behavioral_imbalance"] == {
        "reaction_time": "large_group_difference"
    }
    assert review_context["construct_validity"]["controlled_covariates"] == [
        "reaction_time"
    ]
    assert review_context["null_model"]["null_model_spec"] == {
        "resampling_method": "permutation",
        "permutation_test": True,
        "n_permutations": 1000,
        "permutation_seed": 17,
        "exchangeability_blocks": ["subject_id"],
    }
    assert review_context["provenance"]["provenance_tier"] == "multi_source"
    assert (
        "bundle.analysis_manifest"
        in review_context["provenance"]["evidence_provenance"]
    )
    assert (
        "execution_manifest.parameters"
        in review_context["provenance"]["evidence_provenance"]
    )


def test_stage_external_run_reuses_existing_bundle_files(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "analysis_bundle.json").write_text(
        json.dumps({"ok": True}),
        encoding="utf-8",
    )
    (source_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": "old-run",
                "steps": [
                    {
                        "tool_id": "glm_first_level",
                        "params": {"task": "nback"},
                        "status": "succeeded",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    destination = tmp_path / "staged-run"
    spec = ExternalRunImportSpec(
        run_id="tribe-encoding-002",
        contrast_name="2-back > rest",
    )
    result = stage_external_run(source_dir, destination, spec=spec)

    assert result.reused_root_files == ["analysis_bundle.json"]
    assert (destination / "artifacts" / "source").is_dir()
    assert (destination / "analysis_bundle.json").is_symlink()
    assert (destination / "artifacts" / "source" / "analysis_bundle.json").is_symlink()

    staged_run = json.loads((destination / "run.json").read_text(encoding="utf-8"))
    assert staged_run["run_id"] == "tribe-encoding-002"
    assert staged_run["steps"][0]["params"]["task"] == "nback"
    assert staged_run["steps"][0]["params"]["contrast_name"] == "2-back > rest"


def test_stage_external_run_in_mcp_store_dry_run_uses_runs_subdir(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "glm_summary.json").write_text("{}", encoding="utf-8")

    spec = ExternalRunImportSpec(run_id="tribe-encoding-003")
    result = stage_external_run_in_mcp_store(
        source_dir,
        spec=spec,
        run_root=tmp_path / "mcp_runs",
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.run_dir.endswith("mcp_runs/runs/tribe-encoding-003")
    assert not (tmp_path / "mcp_runs" / "runs" / "tribe-encoding-003").exists()


def test_stage_external_run_enriches_generic_analysis_review_context(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "generic_analysis"
    source_dir.mkdir()
    (tmp_path / "experiments.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "run_id": "generic-analysis-001",
                        "config": {
                            "target": "working memory",
                            "hyperparameters": {
                                "fold_count": 5,
                                "subject_selection_source": "subject_ids.tsv",
                                "label_shuffle_seed": 7,
                                "subject_intersection_manifest_path": "artifacts/split/subject_intersection.tsv",
                            },
                        },
                        "frozen_spec": {
                            "subject_manifest_path": "artifacts/split/subject_manifest.tsv",
                            "fold_manifest_path": "artifacts/split/fold_manifest.json",
                            "target_manifest_path": "artifacts/split/targets.json",
                            "covariate_manifest_path": "artifacts/split/covariates.tsv",
                            "data_manifest_path": "artifacts/split/data_manifest.json",
                        },
                        "scores": {"primary_metric_name": "mean_test_r2"},
                    }
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (source_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "generic-analysis-001",
                "analysis_dir": str(source_dir),
                "run_root": str(tmp_path),
                "n_rows": 16,
                "target_column": "memory_score",
                "feature_strategy": "atlas_roi",
                "split_unit": "tr",
                "split_strategy": "random_tr_split",
                "grouped_split_keys": ["subject"],
                "required_group_keys": ["story", "session", "subject"],
                "grouping_required": True,
                "best_model": "semantic-encoder",
                "model_candidates": ["semantic-encoder", "phonetic-baseline"],
                "layer_candidates": ["layer-3", "layer-7", "layer-12"],
                "selection_scope": "validation_fold",
                "selection_accounting": {"nested_cv": True},
                "multiple_comparison_correction": "fdr",
                "confounds": ["motion", "gsr"],
                "sensitivity_requirements": ["gsr_on_off"],
                "reaction_time_difference": "large_group_difference",
                "behavioral_covariates": ["reaction_time"],
                "subject_alignment_status": "disjoint",
                "permutation_test": True,
                "n_permutations": 1000,
                "permutation_seed": 17,
            }
        ),
        encoding="utf-8",
    )

    destination = tmp_path / "generic-analysis-run"
    stage_external_run(
        source_dir,
        destination,
        spec=ExternalRunImportSpec(run_id="generic-analysis-001"),
    )

    run_record = json.loads((destination / "run.json").read_text(encoding="utf-8"))
    review_context = run_record["review_context"]
    assert (
        run_record["review_contract"]["scientific_review_profile"]
        == "predictive_model_review"
    )
    assert run_record["review_contract"]["scientific_completeness_checks"] == [
        "random_seed_pinned",
        "target_declared",
        "evaluation_protocol_declared",
        "subject_alignment_declared",
        "split_metadata_declared",
        "null_model_declared",
        "preprocessing_choices_declared",
    ]
    assert (
        review_context["split"]["fold_manifest_path"]
        == "artifacts/split/fold_manifest.json"
    )
    assert (
        review_context["split"]["subject_manifest_path"]
        == "artifacts/split/subject_manifest.tsv"
    )
    assert review_context["split"]["subject_selection_source"] == "subject_ids.tsv"
    assert review_context["split"]["split_unit"] == "tr"
    assert review_context["split"]["required_group_keys"] == [
        "story",
        "session",
        "subject",
    ]
    assert review_context["selection"]["best_model"] == "semantic-encoder"
    assert review_context["selection"]["selection_scope"] == "validation_fold"
    assert review_context["selection"]["model_candidates"] == [
        "semantic-encoder",
        "phonetic-baseline",
    ]
    assert review_context["selection"]["layer_candidates"] == [
        "layer-3",
        "layer-7",
        "layer-12",
    ]
    assert review_context["selection"]["selection_accounting"] == {"nested_cv": True}
    assert review_context["selection"]["multiple_comparison_correction"] == "fdr"
    assert review_context["preprocessing"]["feature_selection_scope"] == "atlas_roi"
    assert review_context["preprocessing"]["confounds"] == ["motion", "gsr"]
    assert review_context["sensitivity"]["sensitivity_requirements"] == ["gsr_on_off"]
    assert review_context["construct_validity"]["behavioral_imbalance"] == {
        "reaction_time": "large_group_difference"
    }
    assert review_context["construct_validity"]["controlled_covariates"] == [
        "reaction_time"
    ]
    assert review_context["null_model"]["null_model_spec"] == {
        "permutation_test": True,
        "n_permutations": 1000,
        "permutation_seed": 17,
    }
    assert review_context["provenance"]["provenance_tier"] == "multi_source"
    assert "source_summary" in review_context["provenance"]["evidence_provenance"]
    assert "provenance_updates" in review_context["provenance"]["evidence_provenance"]

    analysis_bundle = json.loads(
        (destination / "analysis_bundle.json").read_text(encoding="utf-8")
    )
    assert (
        analysis_bundle["review_context"]["split"]["target_manifest_path"]
        == "artifacts/split/targets.json"
    )


def test_stage_external_run_synthesizes_tribe_prediction_bundle(tmp_path: Path) -> None:
    source_dir = tmp_path / "tribe_prediction"
    source_dir.mkdir()
    (source_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "checkpoint_dir": "facebook/tribev2",
                "checkpoint_name": "best.ckpt",
                "device": "cuda",
                "n_success": 2,
                "n_failures": 0,
                "split_unit": "tr",
                "split_strategy": "random_tr_split",
                "grouped_split_keys": ["story", "session", "subject"],
                "required_group_keys": ["story", "session", "subject"],
                "best_layer": "layer-12",
                "layer_candidates": ["layer-3", "layer-7", "layer-12"],
                "selection_accounting": {"nested_cv": True},
                "per_task_requested_item_count": {
                    "ibc_tom_story_question_round5": 2,
                },
            }
        ),
        encoding="utf-8",
    )
    (source_dir / "manifest_index.json").write_text(
        json.dumps(
            {
                "wave": "targeted_round5_tom",
                "tasks": [
                    {
                        "task_id": "ibc_tom_story_question_round5",
                        "preferred_tribe_input": "text",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (source_dir / "embedding_rows.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "task_id": "ibc_tom_story_question_round5",
                        "item_id": "story-1",
                        "condition": "belief_story",
                        "segment_count": 17,
                        "n_vertices": 20484,
                        "surface_space": "fsaverage5",
                    }
                ),
                json.dumps(
                    {
                        "task_id": "ibc_tom_story_question_round5",
                        "item_id": "story-2",
                        "condition": "physical_story",
                        "segment_count": 15,
                        "n_vertices": 20484,
                        "surface_space": "fsaverage5",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (source_dir / "failures.jsonl").write_text("", encoding="utf-8")
    (source_dir / "embeddings_matrix.npy").write_bytes(b"npy")

    destination = tmp_path / "staged-run"
    result = stage_external_run(
        source_dir,
        destination,
        spec=ExternalRunImportSpec(run_id="tribe-encoding-tribe"),
    )

    assert result.adapter_name == "tribe_prediction"
    assert (destination / "observation.json").exists()
    assert (destination / "analysis_bundle.json").exists()
    assert (destination / "artifact_manifest.json").exists()
    assert (destination / "source_summary.json").exists()
    assert (destination / "extraction_report.json").exists()

    run_record = json.loads((destination / "run.json").read_text(encoding="utf-8"))
    assert run_record["steps"][0]["tool_id"] == "tribe_predict"
    assert run_record["steps"][0]["params"]["task"] == "theory of mind"
    assert run_record["steps"][0]["params"]["modality"] == "fmri"
    assert run_record["review_contract"]["contract_mode"] == "external_review_bundle"
    assert run_record["review_context"]["schema_version"] == "review-context-v1"
    assert "split" in run_record["review_context"]
    assert "null_model" in run_record["review_context"]
    assert (
        run_record["review_contract"]["review_context"]["schema_version"]
        == "review-context-v1"
    )
    assert run_record["review_context"]["split"]["split_unit"] == "tr"
    assert run_record["review_context"]["split"]["required_group_keys"] == [
        "story",
        "session",
        "subject",
    ]
    assert run_record["review_context"]["selection"]["best_layer"] == "layer-12"
    assert run_record["review_context"]["selection"]["layer_candidates"] == [
        "layer-3",
        "layer-7",
        "layer-12",
    ]
    assert run_record["review_context"]["selection"]["selection_accounting"] == {
        "nested_cv": True
    }

    observation = json.loads(
        (destination / "observation.json").read_text(encoding="utf-8")
    )
    assert observation["diagnostics_summary"]["n_items"] == 2

    analysis_bundle = json.loads(
        (destination / "analysis_bundle.json").read_text(encoding="utf-8")
    )
    assert analysis_bundle["review_context"]["schema_version"] == "review-context-v1"

    metrics = extract_stats_from_run_dir(destination)
    assert metrics["tribe_item_count"] == 2
    assert metrics["tribe_task_count"] == 1
    assert metrics["tribe_surface_vertices"] == 20484

    review = distill_review_records(
        "tribe-encoding-tribe", run_dir=destination, force_recompute=True
    )
    assert review.verdict is not None
    assert review.verdict.decision in {"approve", "approve_with_warnings"}
    assert "REVIEW_ARTIFACT_COMPLETENESS_LOW" not in {
        finding.rule_id for finding in review.verdict.findings
    }


def test_stage_external_run_synthesizes_tribe_analysis_bundle(tmp_path: Path) -> None:
    source_dir = tmp_path / "tribe_analysis"
    source_dir.mkdir()
    (source_dir / "summary.json").write_text(
        json.dumps(
            {
                "analysis_dir": str(source_dir),
                "run_root": "/tmp/upstream-run",
                "n_rows": 16,
                "embedding_shape": [16, 20484],
                "n_contrast_findings": 2,
                "split_unit": "tr",
                "split_strategy": "random_tr_split",
                "grouped_split_keys": ["story", "session"],
                "required_group_keys": ["story", "session", "subject"],
                "best_layer": "layer-12",
                "layer_candidates": ["layer-3", "layer-7", "layer-12"],
                "selection_accounting": {"nested_cv": True},
                "source_run_summary": {
                    "per_task_requested_item_count": {
                        "ibc_tom_story_question_round5": 8,
                    }
                },
                "ranked_candidate_ids": [
                    {
                        "candidate_type": "contrast",
                        "label": "belief_vs_physical_story_question_block",
                        "score": 2.03,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (source_dir / "pca_summary.json").write_text(
        json.dumps({"n_components": 8, "explained_variance_ratio": [0.47, 0.28]}),
        encoding="utf-8",
    )
    (source_dir / "roi_atlas_summary.json").write_text(
        json.dumps({"atlas_name": "destrieux_surface_fsaverage5", "n_rois": 150}),
        encoding="utf-8",
    )
    (source_dir / "ranked_candidates.jsonl").write_text("{}", encoding="utf-8")
    (source_dir / "contrast_findings.jsonl").write_text("{}", encoding="utf-8")

    destination = tmp_path / "analysis-run"
    result = stage_external_run(
        source_dir,
        destination,
        spec=ExternalRunImportSpec(run_id="tribe-analysis-001"),
    )

    assert result.adapter_name == "tribe_embedding_analysis"
    run_record = json.loads((destination / "run.json").read_text(encoding="utf-8"))
    assert run_record["steps"][0]["tool_id"] == "embedding_autoresearch"
    assert run_record["steps"][0]["params"]["task"] == "theory of mind"
    assert (
        run_record["steps"][0]["params"]["contrast_name"]
        == "belief_vs_physical_story_question_block"
    )
    assert run_record["review_context"]["split"]["required_group_keys"] == [
        "story",
        "session",
        "subject",
    ]
    assert run_record["review_context"]["selection"]["best_layer"] == "layer-12"
    assert run_record["review_context"]["selection"]["layer_candidates"] == [
        "layer-3",
        "layer-7",
        "layer-12",
    ]
    assert run_record["review_context"]["selection"]["selection_accounting"] == {
        "nested_cv": True
    }

    metrics = extract_stats_from_run_dir(destination)
    assert metrics["tribe_item_count"] == 16
    assert metrics["tribe_embedding_dim"] == 20484
    assert metrics["tribe_pca_top1_variance"] == 0.47
    assert metrics["tribe_roi_count"] == 150


def test_stage_external_run_can_force_generic_prediction_adapter(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "generic_prediction"
    source_dir.mkdir()
    (source_dir / "threshold_summary.json").write_text(
        json.dumps({"n_clusters_surviving": 2}),
        encoding="utf-8",
    )
    (source_dir / "correction_summary.json").write_text(
        json.dumps({"method": "fdr", "alpha": 0.05}),
        encoding="utf-8",
    )
    (source_dir / "design_matrix.csv").write_text(
        "intercept,task\n1,0\n1,1\n",
        encoding="utf-8",
    )
    (source_dir / "contrast_table.csv").write_text(
        "contrast_name,intercept,task\nmain_effect,0,1\n",
        encoding="utf-8",
    )
    (source_dir / "cluster_table.csv").write_text(
        "cluster_id,cluster_size,p_fwe\n1,42,0.01\n2,18,0.03\n",
        encoding="utf-8",
    )
    (source_dir / "peak_table.csv").write_text(
        "x,y,z,peak_z,cluster_id\n12,-8,50,5.1,1\n-24,-60,40,4.4,2\n",
        encoding="utf-8",
    )
    (source_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "tool_id": "custom_predictor",
                "task": "reward task",
                "n_success": 3,
                "n_failures": 1,
                "modality": "fmri",
                "statistical_method": "custom_prediction",
                "split_unit": "story",
                "split_strategy": "leave_one_story_out",
                "grouped_split_keys": ["story", "subject"],
                "required_group_keys": ["story", "subject"],
                "best_model": "semantic-encoder",
                "model_candidates": ["semantic-encoder", "acoustic-baseline"],
                "selection_scope": "validation_fold",
                "selection_accounting": {"nested_cv": True},
                "multiple_comparison_correction": "fdr",
                "correction_alpha": 0.05,
                "cluster_threshold": 2.3,
                "correction_summary_path": "correction_summary.json",
                "hrf_model": "spm",
                "noise_model": "ar1",
                "serial_correlation_correction": "film",
                "prewhitening_enabled": True,
                "threshold_summary_path": "threshold_summary.json",
                "design_matrix_path": "design_matrix.csv",
                "contrast_table_path": "contrast_table.csv",
                "cluster_table_path": "cluster_table.csv",
                "peak_table_path": "peak_table.csv",
            }
        ),
        encoding="utf-8",
    )

    destination = tmp_path / "generic-prediction-run"
    result = stage_external_run(
        source_dir,
        destination,
        spec=ExternalRunImportSpec(run_id="generic-prediction-001"),
        adapter_preference="generic_prediction_summary",
    )

    assert result.adapter_name == "generic_prediction_summary"
    run_record = json.loads((destination / "run.json").read_text(encoding="utf-8"))
    assert run_record["steps"][0]["tool_id"] == "custom_predictor"
    assert run_record["steps"][0]["params"]["task"] == "reward"
    assert run_record["review_context"]["split"]["split_unit"] == "story"
    assert run_record["review_context"]["split"]["required_group_keys"] == [
        "story",
        "subject",
    ]
    assert run_record["review_context"]["selection"]["best_model"] == "semantic-encoder"
    assert run_record["review_context"]["selection"]["model_candidates"] == [
        "semantic-encoder",
        "acoustic-baseline",
    ]
    assert (
        run_record["review_context"]["selection"]["selection_scope"]
        == "validation_fold"
    )
    assert run_record["review_context"]["selection"]["selection_accounting"] == {
        "nested_cv": True
    }
    assert (
        run_record["review_context"]["statistical_inference"][
            "multiple_comparison_correction"
        ]
        == "fdr"
    )
    assert (
        run_record["review_context"]["statistical_inference"]["correction_alpha"]
        == 0.05
    )
    assert (
        run_record["review_context"]["statistical_inference"][
            "cluster_forming_threshold"
        ]
        == 2.3
    )
    assert run_record["review_context"]["design_model"]["hrf_model"] == "spm"
    assert (
        run_record["review_context"]["design_model"]["autocorrelation_model"] == "ar1"
    )
    assert (
        run_record["review_context"]["design_model"]["serial_correlation_correction"]
        == "film"
    )
    assert run_record["review_context"]["design_model"]["prewhitening_enabled"] is True
    metrics = extract_stats_from_run_dir(destination)
    assert metrics["external_item_count"] == 4
    assert metrics["external_failure_rate"] == 0.25
    analysis_bundle = json.loads(
        (destination / "analysis_bundle.json").read_text(encoding="utf-8")
    )
    observation = json.loads(
        (destination / "observation.json").read_text(encoding="utf-8")
    )
    assert (
        analysis_bundle["files"]["correction_summary_json"]
        == "artifacts/source/correction_summary.json"
    )
    assert (
        analysis_bundle["files"]["threshold_summary_json"]
        == "artifacts/source/threshold_summary.json"
    )
    assert (
        analysis_bundle["files"]["design_matrix"]
        == "artifacts/source/design_matrix.csv"
    )
    assert (
        analysis_bundle["files"]["contrast_table"]
        == "artifacts/source/contrast_table.csv"
    )
    assert (
        analysis_bundle["files"]["cluster_table"]
        == "artifacts/source/cluster_table.csv"
    )
    assert analysis_bundle["files"]["peak_table"] == "artifacts/source/peak_table.csv"
    assert (
        observation["files"]["correction_summary_json"]
        == "artifacts/source/correction_summary.json"
    )
    assert (
        observation["files"]["threshold_summary_json"]
        == "artifacts/source/threshold_summary.json"
    )
    assert observation["files"]["design_matrix"] == "artifacts/source/design_matrix.csv"
    assert (
        observation["files"]["contrast_table"] == "artifacts/source/contrast_table.csv"
    )
    assert observation["files"]["cluster_table"] == "artifacts/source/cluster_table.csv"
    assert observation["files"]["peak_table"] == "artifacts/source/peak_table.csv"


def test_stage_external_run_can_force_generic_analysis_adapter(tmp_path: Path) -> None:
    source_dir = tmp_path / "generic_analysis"
    source_dir.mkdir()
    (source_dir / "summary.json").write_text(
        json.dumps(
            {
                "tool_id": "custom_analysis",
                "task": "language localizer",
                "contrast_name": "sentences_vs_nonwords",
                "n_rows": 24,
                "embedding_shape": [24, 1024],
                "statistical_method": "custom_analysis_method",
            }
        ),
        encoding="utf-8",
    )

    destination = tmp_path / "generic-analysis-run"
    result = stage_external_run(
        source_dir,
        destination,
        spec=ExternalRunImportSpec(run_id="generic-analysis-001"),
        adapter_preference="generic_analysis_summary",
    )

    assert result.adapter_name == "generic_analysis_summary"
    run_record = json.loads((destination / "run.json").read_text(encoding="utf-8"))
    assert run_record["steps"][0]["tool_id"] == "custom_analysis"
    assert run_record["steps"][0]["params"]["task"] == "language"
    metrics = extract_stats_from_run_dir(destination)
    assert metrics["external_item_count"] == 24
    assert metrics["external_embedding_dim"] == 1024


def test_stage_external_run_autodetects_fitlins_multiverse_workflow_root(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "fitlins_multiverse"
    source_dir.mkdir()
    _write_fitlins_multiverse_fixture(source_dir, workflow_layout=True)

    destination = tmp_path / "fitlins-multiverse-run"
    result = stage_external_run(
        source_dir,
        destination,
        spec=ExternalRunImportSpec(run_id="fitlins-multiverse-import-001"),
    )

    assert result.adapter_name == "fitlins_multiverse"
    run_record = json.loads((destination / "run.json").read_text(encoding="utf-8"))
    assert run_record["steps"][0]["tool_id"] == "fitlins_multiverse_external"
    assert run_record["steps"][0]["params"]["task"] == "linebisection"
    assert run_record["steps"][0]["params"]["contrast_name"] == "cue"
    assert run_record["review_contract"]["scientific_completeness_checks"] == [
        "random_seed_pinned",
        "atlas_version_pinned",
        "sensitivity_package_declared",
    ]
    assert run_record["review_context"]["selection"]["model_candidates"] == [
        "mv001",
        "mv002",
    ]
    assert run_record["review_context"]["selection"]["candidate_count"] == 2
    assert run_record["review_context"]["sensitivity"]["controversial_choices"] == [
        "confounds",
        "gsr",
        "high_pass",
        "hrf",
    ]
    assert run_record["review_context"]["sensitivity"]["sensitivity_requirements"] == [
        "gsr_on_off",
        "high-pass sensitivity",
        "hrf robustness",
    ]
    assert run_record["review_context"]["sensitivity"]["robustness_checks"] == [
        "cue: pairwise_corr_mean=0.810"
    ]

    analysis_bundle = json.loads(
        (destination / "analysis_bundle.json").read_text(encoding="utf-8")
    )
    assert analysis_bundle["analysis_manifest"]["dataset_id"] == "ds000114"
    assert analysis_bundle["analysis_manifest"]["n_variants"] == 2
    assert analysis_bundle["analysis_manifest"]["top_contrast"] == "cue"
    assert "artifacts/source/run_manifest.json" in {
        artifact["path"] for artifact in analysis_bundle["artifacts"]
    }
    assert "artifacts/source/fitlins/robustness_yeo17.json" in {
        artifact["path"] for artifact in analysis_bundle["artifacts"]
    }


def test_stage_external_run_autodetects_fitlins_multiverse_runonly_root(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "fitlins_multiverse_runonly"
    source_dir.mkdir()
    _write_fitlins_multiverse_fixture(source_dir, workflow_layout=False)

    destination = tmp_path / "fitlins-multiverse-runonly-import"
    result = stage_external_run(
        source_dir,
        destination,
        spec=ExternalRunImportSpec(run_id="fitlins-multiverse-import-002"),
    )

    assert result.adapter_name == "fitlins_multiverse"
    run_record = json.loads((destination / "run.json").read_text(encoding="utf-8"))
    assert run_record["steps"][0]["params"]["task"] == "linebisection"
    assert run_record["steps"][0]["params"]["contrast_name"] == "cue"

    observation = json.loads(
        (destination / "observation.json").read_text(encoding="utf-8")
    )
    assert (
        observation["run_card"]["parameters"]["statistical_method"]
        == "fitlins_multiverse"
    )
    assert observation["diagnostics_summary"]["n_variants"] == 2

    analysis_bundle = json.loads(
        (destination / "analysis_bundle.json").read_text(encoding="utf-8")
    )
    assert (
        analysis_bundle["analysis_manifest"]["spec_manifest_path"]
        == "multiverse_manifest.json"
    )
    assert (
        analysis_bundle["analysis_manifest"]["robustness_json_path"]
        == "robustness_yeo17.json"
    )
    assert (
        analysis_bundle["analysis_manifest"]["yeo17_summary_path"]
        == "yeo17_summary.csv"
    )
    assert "artifacts/source/multiverse_manifest.json" in {
        artifact["path"] for artifact in analysis_bundle["artifacts"]
    }
    assert "artifacts/source/robustness_yeo17.json" in {
        artifact["path"] for artifact in analysis_bundle["artifacts"]
    }


def test_stage_external_run_can_import_single_file_fc_metric_summary(
    tmp_path: Path,
) -> None:
    source_file = (
        tmp_path
        / "banghcp_phase8_rawtarget_pmat24_a_cr_graph_transformer_termiu_term014_nocov_verified_n325.json"
    )
    source_file.write_text(
        json.dumps(
            {
                "run_id": "banghcp_phase8_rawtarget_pmat24_a_cr_graph_transformer_termiu_term014_nocov_verified_n325",
                "classifier": "graph_transformer",
                "target_column": "PMAT24_A_CR",
                "term_name": "prec_EmpiricalCovariance",
                "feature_strategy": "upstream_term_i_iu_middle80qcod",
                "reference_subject_count": 326,
                "fold_results": [
                    {
                        "fold_id": 1,
                        "train_r2": 0.12,
                        "test_r2": 0.03,
                        "test_pearson_r": 0.21,
                        "train_size": 292,
                        "test_size": 33,
                    },
                    {
                        "fold_id": 2,
                        "train_r2": 0.1,
                        "test_r2": -0.01,
                        "test_pearson_r": 0.18,
                        "train_size": 293,
                        "test_size": 32,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    destination = tmp_path / "fc-metric-run"
    result = stage_external_run(
        source_file,
        destination,
        spec=ExternalRunImportSpec(run_id="fc-metric-001"),
        adapter_preference="generic_analysis_summary",
    )

    assert result.adapter_name == "generic_analysis_summary"
    assert (destination / "artifacts" / "source" / source_file.name).exists()

    run_record = json.loads((destination / "run.json").read_text(encoding="utf-8"))
    assert run_record["steps"][0]["tool_id"] == "external_analysis_summary"
    assert run_record["steps"][0]["params"]["task"] == "fluid intelligence"
    assert run_record["steps"][0]["params"]["modality"] == "fmri"
    assert run_record["steps"][0]["params"]["statistical_method"] == "graph_transformer"

    metrics = extract_stats_from_run_dir(destination)
    assert metrics["external_item_count"] == 326
    assert metrics["external_n_folds"] == 2
    assert metrics["external_mean_train_r2"] == 0.11
    assert metrics["external_mean_test_r2"] == 0.01
    assert metrics["external_mean_test_pearson_r"] == 0.195
    assert metrics["r_squared"] == 0.01
    assert metrics["n_subjects"] == 326


def test_stage_external_run_lanea_metric_summary_uses_experiment_registry(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "predictive-project"
    metrics_dir = project_root / "artifacts" / "metrics"
    manifests_dir = project_root / "manifests"
    metrics_dir.mkdir(parents=True)
    manifests_dir.mkdir(parents=True)
    subject_manifest = manifests_dir / "subject_manifest.json"
    fold_manifest = manifests_dir / "fold_manifest.json"
    target_manifest = manifests_dir / "target_manifest.json"
    covariate_manifest = manifests_dir / "covariate_manifest.json"
    data_manifest = manifests_dir / "data_manifest.json"
    subject_intersection_manifest = (
        manifests_dir / "subject_intersection_liu_behavior_factor_0.json"
    )
    subject_ids_file = manifests_dir / "subjects_reinder326_recovered.txt"
    for path in (
        subject_manifest,
        fold_manifest,
        target_manifest,
        covariate_manifest,
        data_manifest,
        subject_intersection_manifest,
    ):
        path.write_text(json.dumps({"ok": True, "path": path.name}), encoding="utf-8")
    subject_ids_file.write_text("100001\n100002\n", encoding="utf-8")
    source_file = (
        metrics_dir / "banghcp_laneA_derivative_replay_ridge_feat0_term132.json"
    )
    source_file.write_text(
        json.dumps(
            {
                "run_id": "banghcp_laneA_derivative_replay_ridge_feat0_term132",
                "classifier": "ridge",
                "target_name": "liu_behavior_factor_0",
                "term_name": "plv_multitaper_mean_fs-1_fmin-0_fmax-0-25",
                "selection_mode": "best_term_for_classifier_feature",
                "proxy_fold_scores": [0.4, 0.5, 0.6],
                "proxy_mean_score": 0.5,
                "notes": "Lane A derivative replay using upstream nested-CV scores.",
            }
        ),
        encoding="utf-8",
    )
    (project_root / "experiments.jsonl").write_text(
        json.dumps(
            {
                "run_id": "banghcp_laneA_derivative_replay_ridge_feat0_term132",
                "frozen_spec": {
                    "subject_manifest_path": str(subject_manifest),
                    "fold_manifest_path": str(fold_manifest),
                    "target_manifest_path": str(target_manifest),
                    "covariate_manifest_path": str(covariate_manifest),
                    "data_manifest_path": str(data_manifest),
                },
                "config": {
                    "target": "liu_behavior_factor_0",
                    "feature_strategy": "upstream_qcod_middle_80_vectorized_upper_triangle",
                    "hyperparameters": {
                        "fold_count": 10,
                        "subject_ids_file": str(subject_ids_file),
                        "subject_intersection_manifest_path": str(
                            subject_intersection_manifest
                        ),
                    },
                },
                "scores": {
                    "primary_metric_name": "gold_proxy_1_minus_distance_correlation",
                    "gold_r": 0.5,
                },
                "data_diagnostics": {"subject_count": 326},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    destination = tmp_path / "fc-lanea-run"
    result = stage_external_run(
        source_file,
        destination,
        spec=ExternalRunImportSpec(run_id="fc-lanea-001"),
        adapter_preference="generic_analysis_summary",
    )

    assert result.adapter_name == "generic_analysis_summary"
    assert (
        destination / "artifacts" / "source" / "context" / "experiments.jsonl"
    ).exists()
    assert (
        destination / "artifacts" / "source" / "context" / subject_manifest.name
    ).exists()
    assert (
        destination / "artifacts" / "source" / "context" / fold_manifest.name
    ).exists()
    assert (
        destination / "artifacts" / "source" / "context" / target_manifest.name
    ).exists()
    assert (
        destination / "artifacts" / "source" / "context" / covariate_manifest.name
    ).exists()
    assert (
        destination / "artifacts" / "source" / "context" / data_manifest.name
    ).exists()
    assert (
        destination
        / "artifacts"
        / "source"
        / "context"
        / subject_intersection_manifest.name
    ).exists()
    assert (
        destination / "artifacts" / "source" / "context" / subject_ids_file.name
    ).exists()
    source_summary = json.loads(
        (destination / "source_summary.json").read_text(encoding="utf-8")
    )
    assert source_summary["n_folds"] == 10
    assert source_summary["mean_proxy_score"] == 0.5
    assert source_summary["subject_manifest_path"] == str(subject_manifest)
    assert source_summary["fold_manifest_path"] == str(fold_manifest)
    assert source_summary["covariate_manifest_path"] == str(covariate_manifest)
    assert source_summary["subject_ids_file"] == str(subject_ids_file)
    assert source_summary["reference_subject_count"] == 326
    extraction_report = json.loads(
        (destination / "extraction_report.json").read_text(encoding="utf-8")
    )
    assert (
        "artifacts/source/context/experiments.jsonl"
        in extraction_report["indexed_artifacts"]
    )
    assert (
        f"artifacts/source/context/{subject_manifest.name}"
        in extraction_report["indexed_artifacts"]
    )
    assert (
        f"artifacts/source/context/{subject_intersection_manifest.name}"
        in extraction_report["indexed_artifacts"]
    )
    assert (
        f"artifacts/source/context/{covariate_manifest.name}"
        in extraction_report["indexed_artifacts"]
    )
    assert (
        f"artifacts/source/context/{subject_ids_file.name}"
        in extraction_report["indexed_artifacts"]
    )

    metrics = extract_stats_from_run_dir(destination)
    assert metrics["external_item_count"] == 326
    assert metrics["external_n_folds"] == 10
    assert metrics["n_subjects"] == 326
