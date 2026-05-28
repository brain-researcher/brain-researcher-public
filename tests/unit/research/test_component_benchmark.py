from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_researcher.research.predictive.component_benchmark import (
    compute_component_line_score,
    load_component_manifest,
    validate_component_csv,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_validate_component_csv_accepts_manifest_targets(tmp_path: Path) -> None:
    manifest_path = _write_json(
        tmp_path / "manifest.json",
        {
            "benchmark_name": "liu_component_autoresearch",
            "subject_id_column": "Subject",
            "targets": [
                {
                    "target_column": "ICA_Cognition",
                    "display_name": "Cognition",
                    "reference_mean_r": 0.215,
                    "reference_best_r": 0.42,
                },
                {
                    "target_column": "ICA_MentalHealth",
                    "display_name": "Mental Health",
                    "reference_mean_r": 0.014,
                    "reference_best_r": 0.174,
                },
            ],
        },
    )
    csv_path = tmp_path / "components.csv"
    csv_path.write_text(
        "Subject,ICA_Cognition,ICA_MentalHealth\n1001,1.2,0.4\n1002,0.9,0.1\n",
        encoding="utf-8",
    )

    manifest = load_component_manifest(manifest_path)
    summary = validate_component_csv(csv_path, manifest)

    assert summary["row_count"] == 2
    assert summary["subject_id_column"] == "Subject"
    assert summary["target_columns"] == ["ICA_Cognition", "ICA_MentalHealth"]


def test_validate_component_csv_rejects_missing_columns(tmp_path: Path) -> None:
    manifest_path = _write_json(
        tmp_path / "manifest.json",
        {
            "benchmark_name": "liu_component_autoresearch",
            "subject_id_column": "Subject",
            "targets": [
                {
                    "target_column": "ICA_Cognition",
                    "display_name": "Cognition",
                    "reference_mean_r": 0.215,
                    "reference_best_r": 0.42,
                }
            ],
        },
    )
    csv_path = tmp_path / "components.csv"
    csv_path.write_text("Subject,WrongColumn\n1001,1.2\n", encoding="utf-8")

    manifest = load_component_manifest(manifest_path)
    with pytest.raises(ValueError, match="Missing required columns"):
        validate_component_csv(csv_path, manifest)


def test_compute_component_line_score_uses_gold_r_and_manifest_targets(tmp_path: Path) -> None:
    manifest = {
        "benchmark_name": "liu_component_autoresearch",
        "subject_id_column": "Subject",
        "phase_name": "phase_liu_component_reproduction",
        "targets": [
            {
                "target_column": "ICA_Cognition",
                "display_name": "Cognition",
                "reference_mean_r": 0.215,
                "reference_best_r": 0.42,
            },
            {
                "target_column": "ICA_TobaccoUse",
                "display_name": "Tobacco Use",
                "reference_mean_r": 0.143,
                "reference_best_r": 0.357,
            },
        ],
    }
    ledger_path = tmp_path / "experiments.jsonl"
    rows = [
        {
            "phase": "phase_liu_component_reproduction",
            "run_id": "run_cog_01",
            "config": {"target": "ICA_Cognition"},
            "scores": {
                "primary_metric_name": "10fold_cv_r2",
                "gold_r": 0.30,
                "gold_r2": 0.09,
            },
        },
        {
            "phase": "phase_liu_component_reproduction",
            "run_id": "run_tob_01",
            "config": {"target": "ICA_TobaccoUse"},
            "scores": {
                "primary_metric_name": "10fold_cv_r2",
                "gold_r": 0.10,
                "gold_r2": 0.01,
            },
        },
        {
            "phase": "other_phase",
            "run_id": "ignored_run",
            "config": {"target": "ICA_Cognition"},
            "scores": {"primary_metric_name": "10fold_cv_r2", "gold_r": 0.99, "gold_r2": 0.98},
        },
    ]
    ledger_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    payload = compute_component_line_score(ledger_path, manifest)

    assert payload["coverage_fraction"] == 1.0
    assert payload["contract_satisfied"] is True
    assert payload["target_summaries"][0]["best_gold_r"] == 0.3
    assert payload["target_summaries"][0]["ratio_vs_mean_reference"] == round(0.30 / 0.215, 4)
    assert payload["target_summaries"][1]["best_run_id"] == "run_tob_01"
    assert payload["score"] > 0
