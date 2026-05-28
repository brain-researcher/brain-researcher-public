"""Sidecar discovery and review_context wiring for autoresearch bundles."""

from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.review.autoresearch_bundle_builder import (
    _discover_autoresearch_review_sidecars,
    _is_trusted_full_pipeline_probe,
    build_autoresearch_review_bundle,
)


def _seed_minimal_workspace(root: Path) -> None:
    (root / "outputs").mkdir(parents=True, exist_ok=True)
    (root / "runner_logs").mkdir(parents=True, exist_ok=True)
    (root / "loop_body_prompt.md").write_text("# loop\n", encoding="utf-8")
    (root / "predict.py").write_text(
        "def get_config():\n    return {}\n", encoding="utf-8"
    )
    (root / "run.py").write_text("print('run')\n", encoding="utf-8")
    (root / "outputs" / "final_report.md").write_text(
        "# Final Report\n", encoding="utf-8"
    )
    row = {
        "iteration": 1,
        "action_type": "baseline_replicate",
        "config": {"model": "Ridge"},
        "results": {"aggregate_mean_r": 0.12, "coverage_fraction": 0.8},
        "self_critique": {"verdict": "ADVANCE"},
    }
    (root / "experiments.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_discover_autoresearch_review_sidecars_picks_up_feature_contract(
    tmp_path: Path,
) -> None:
    _seed_minimal_workspace(tmp_path)
    _write_json(
        tmp_path / "outputs" / "step01" / "feature_contract.json",
        {
            "matrix_kind": "partial_correlation",
            "n_rois": 100,
            "n_timepoints": 80,
            "precision_estimator": "EmpiricalCovariance",
        },
    )

    discovered = _discover_autoresearch_review_sidecars(
        tmp_path, tmp_path / "outputs", tmp_path / "runner_logs"
    )

    assert discovered["feature_contract"]["matrix_kind"] == "partial_correlation"
    assert discovered["feature_contract"]["n_rois"] == 100


def test_discover_autoresearch_review_sidecars_prefers_trusted_probe(
    tmp_path: Path,
) -> None:
    _seed_minimal_workspace(tmp_path)
    untrusted_probe = {
        "status": "ok",
        "pipeline_scope": "feature_matrix_only",
        "generated_by": "permutation_testing_tool",
        "input_scope": "feature_matrix",
        "n_permutations": 5000,
    }
    trusted_probe = {
        "status": "ok",
        "pipeline_scope": "full_pipeline",
        "generated_by": "br_full_pipeline_permutation_harness",
        "input_scope": "workflow_invocation",
        "pipeline_invocation_sha256": "workflow-digest",
        "n_permutations": 100,
        "verdict": "null_indistinguishable",
    }
    _write_json(
        tmp_path / "outputs" / "step01" / "review_probes" / "label_permutation_null.json",
        untrusted_probe,
    )
    _write_json(
        tmp_path / "runner_logs" / "step02" / "review_probes" / "label_permutation_null.json",
        trusted_probe,
    )

    discovered = _discover_autoresearch_review_sidecars(
        tmp_path, tmp_path / "outputs", tmp_path / "runner_logs"
    )

    label_probe = discovered["label_permutation_null"]
    assert label_probe["generated_by"] == "br_full_pipeline_permutation_harness"
    assert _is_trusted_full_pipeline_probe(label_probe)
    assert label_probe["n_permutations"] == 100


def test_build_autoresearch_review_bundle_injects_sidecars_into_review_context(
    tmp_path: Path,
) -> None:
    _seed_minimal_workspace(tmp_path)
    _write_json(
        tmp_path / "outputs" / "step01" / "feature_contract.json",
        {
            "matrix_kind": "correlation",
            "n_rois": 200,
            "n_timepoints": 240,
        },
    )
    probe = {
        "status": "ok",
        "pipeline_scope": "full_pipeline",
        "generated_by": "br_full_pipeline_permutation_harness",
        "input_scope": "workflow_invocation",
        "pipeline_invocation_sha256": "abc123",
        "n_permutations": 1000,
        "verdict": "null_indistinguishable",
    }
    _write_json(
        tmp_path / "outputs" / "step02" / "review_probes" / "label_permutation_null.json",
        probe,
    )

    bundle = build_autoresearch_review_bundle(tmp_path)

    ctx = bundle.review_context
    assert ctx["feature_contract"]["matrix_kind"] == "correlation"
    assert ctx["feature_contract"]["n_rois"] == 200
    assert ctx["review_probes"]["label_permutation_null"]["verdict"] == (
        "null_indistinguishable"
    )
    # Mirror into null_model so the existing predictive-diagnostics check finds it
    assert ctx["null_model"]["permutation_null"]["pipeline_scope"] == "full_pipeline"


def test_build_autoresearch_review_bundle_handles_missing_sidecars(
    tmp_path: Path,
) -> None:
    _seed_minimal_workspace(tmp_path)

    bundle = build_autoresearch_review_bundle(tmp_path)

    ctx = bundle.review_context
    assert "feature_contract" not in ctx
    assert "review_probes" not in ctx
