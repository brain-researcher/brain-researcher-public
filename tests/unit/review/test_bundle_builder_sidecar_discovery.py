"""Unit tests for review-sidecar discovery in bundle_builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_researcher.services.review.bundle_builder import (
    _discover_review_sidecars,
    _extract_review_context,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.unit
def test_discover_review_sidecars_picks_up_feature_contract(tmp_path: Path):
    feature_contract = {
        "matrix_kind": "partial_correlation",
        "n_rois": 100,
        "n_timepoints": 80,
        "precision_estimator": "EmpiricalCovariance",
        "regularization": "unregularized",
    }
    _write_json(tmp_path / "outputs" / "feature_contract.json", feature_contract)

    discovered = _discover_review_sidecars(tmp_path)

    assert discovered["feature_contract"]["matrix_kind"] == "partial_correlation"
    assert discovered["feature_contract"]["n_rois"] == 100


@pytest.mark.unit
def test_discover_review_sidecars_picks_up_label_permutation_null(tmp_path: Path):
    probe = {
        "status": "ok",
        "pipeline_scope": "full_pipeline",
        "generated_by": "br_full_pipeline_permutation_harness",
        "input_scope": "workflow_invocation",
        "pipeline_invocation_sha256": "workflow-digest",
        "n_permutations": 1000,
        "verdict": "null_indistinguishable",
    }
    _write_json(
        tmp_path / "step-01" / "review_probes" / "label_permutation_null.json",
        probe,
    )

    discovered = _discover_review_sidecars(tmp_path)

    label_probe = discovered["review_probes"]["label_permutation_null"]
    assert label_probe["pipeline_scope"] == "full_pipeline"
    assert label_probe["generated_by"] == "br_full_pipeline_permutation_harness"


@pytest.mark.unit
def test_discover_review_sidecars_prefers_trusted_full_pipeline_probe(
    tmp_path: Path,
):
    feature_matrix_probe = {
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
    }
    _write_json(
        tmp_path / "step-01" / "review_probes" / "label_permutation_null.json",
        feature_matrix_probe,
    )
    _write_json(
        tmp_path / "step-02" / "review_probes" / "label_permutation_null.json",
        trusted_probe,
    )

    discovered = _discover_review_sidecars(tmp_path)

    label_probe = discovered["review_probes"]["label_permutation_null"]
    assert label_probe["pipeline_scope"] == "full_pipeline"
    assert label_probe["n_permutations"] == 100


@pytest.mark.unit
def test_extract_review_context_merges_sidecars_into_null_model():
    observed = {
        "review_context": {
            "claim_contract": {"confirmatory_or_exploratory": "confirmatory"},
        },
        "feature_contract": {
            "matrix_kind": "partial_correlation",
            "n_rois": 100,
            "n_timepoints": 60,
        },
        "review_probes": {
            "label_permutation_null": {
                "pipeline_scope": "full_pipeline",
                "verdict": "null_indistinguishable",
            }
        },
    }

    context = _extract_review_context(observed)

    assert context["feature_contract"]["matrix_kind"] == "partial_correlation"
    assert context["review_probes"]["label_permutation_null"]["pipeline_scope"] == (
        "full_pipeline"
    )
    assert context["null_model"]["permutation_null"]["pipeline_scope"] == (
        "full_pipeline"
    )


@pytest.mark.unit
def test_discover_review_sidecars_ignores_unrelated_label_permutation_files(
    tmp_path: Path,
):
    # File named correctly but not under review_probes/ should be ignored
    _write_json(
        tmp_path / "label_permutation_null.json",
        {"pipeline_scope": "full_pipeline"},
    )

    discovered = _discover_review_sidecars(tmp_path)
    assert "review_probes" not in discovered
