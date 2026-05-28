from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.review.autoresearch_bundle_builder import (
    build_autoresearch_review_bundle,
)
from brain_researcher.services.review.autoresearch_line_workspace import (
    load_autoresearch_line_state,
    resolve_autoresearch_workspace_layout,
)


def _write_minimal_workspace(root: Path) -> None:
    (root / "outputs").mkdir(parents=True, exist_ok=True)
    (root / "runner_logs").mkdir(parents=True, exist_ok=True)
    (root / "reference_parent_closeout").mkdir(parents=True, exist_ok=True)
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
        "config": {"model": "Ridge", "terms": ["cov"]},
        "results": {"aggregate_mean_r": 0.12, "coverage_fraction": 0.8},
        "self_critique": {"verdict": "ADVANCE"},
    }
    (root / "experiments.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")


def test_resolve_autoresearch_workspace_layout_detects_standard_paths(
    tmp_path: Path,
) -> None:
    _write_minimal_workspace(tmp_path)

    layout = resolve_autoresearch_workspace_layout(tmp_path)

    assert layout.root_dir == str(tmp_path.resolve())
    assert layout.final_report_path.endswith("outputs/final_report.md")
    assert any(
        path.endswith("reference_parent_closeout") for path in layout.reference_dirs
    )
    assert any(path.endswith("predict.py") for path in layout.entrypoint_paths)
    assert any(path.endswith("runner_logs") for path in layout.existing_paths)


def test_load_autoresearch_line_state_coerces_legacy_payload(tmp_path: Path) -> None:
    payload = {
        "schema_version": "liu_component_line_state_v0",
        "line_type": "data_scaling",
        "status": "active",
        "workspace": str(tmp_path),
        "budget_envelope": {
            "max_runner_turns": 12,
            "max_wallclock_hours": 8,
            "max_extension_turns": 2,
            "max_consecutive_no_growth": 3,
        },
        "pending_directive": {
            "directive_type": "budget_grace_turn",
            "source": "controller",
            "must_address_this_turn": True,
            "message": "write synthesis before another run",
        },
        "loaded_modules": ["base", "data_scaling"],
        "forbidden_modules": ["generalization"],
        "training_backend": "cpu_local",
        "success_criterion": "estimate_sample_size_and_reliability_scaling_behavior",
        "last_latest_summary": {
            "iteration": 12,
            "action_type": "diagnostic",
            "model": "PerComponentTermsTopKByComponentRidge",
            "metric": "cov+dcorr",
            "coverage_fraction": 1.0,
            "aggregate_mean_r": 0.1899,
            "verdict": "DIAGNOSE",
        },
        "controller_note": "legacy payload should survive in extra",
    }
    (tmp_path / "line_state.json").write_text(json.dumps(payload), encoding="utf-8")

    state = load_autoresearch_line_state(tmp_path)

    assert state is not None
    assert state.schema_version == "autoresearch-line-state-v1"
    assert state.source_schema_version == "liu_component_line_state_v0"
    assert state.line_type == "data_scaling"
    assert state.budget_envelope is not None
    assert state.budget_envelope.max_runner_turns == 12
    assert state.pending_directive is not None
    assert state.pending_directive.directive_type == "budget_grace_turn"
    assert state.last_latest_summary is not None
    assert state.last_latest_summary.aggregate_mean_r == 0.1899
    assert state.extra["controller_note"] == "legacy payload should survive in extra"


def test_autoresearch_review_bundle_reads_generic_line_metadata(tmp_path: Path) -> None:
    _write_minimal_workspace(tmp_path)
    (tmp_path / "line_state.json").write_text(
        json.dumps(
            {
                "schema_version": "liu_component_line_state_v0",
                "line_type": "foundation_transfer",
                "status": "completed",
                "workspace": str(tmp_path),
                "parent_workspace": "/tmp/parent_line",
                "reference_workspace": "/tmp/reference_line",
                "loaded_modules": ["base", "foundation_transfer"],
                "forbidden_modules": ["generalization"],
                "training_backend": "gpu_local",
                "success_criterion": "determine_whether_pretrained_embeddings_beat_the_baseline",
            }
        ),
        encoding="utf-8",
    )

    bundle = build_autoresearch_review_bundle(tmp_path)

    assert bundle.logs_dir == str((tmp_path / "runner_logs").resolve())
    assert (
        bundle.review_context["line_state_schema_version"]
        == "liu_component_line_state_v0"
    )
    assert bundle.review_context["workspace_layout_schema_version"] == (
        "autoresearch-workspace-layout-v1"
    )
    assert bundle.review_context["line_type"] == "foundation_transfer"
    assert bundle.review_context["line_status"] == "completed"
    assert bundle.review_context["parent_workspace"] == "/tmp/parent_line"
    assert bundle.review_context["reference_workspace"] == "/tmp/reference_line"
    assert bundle.review_context["loaded_modules"] == ["base", "foundation_transfer"]



def test_autoresearch_review_bundle_reads_legacy_top_level_metrics(tmp_path: Path) -> None:
    (tmp_path / "outputs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runner_logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "predict.py").write_text(
        "def get_config():\n    return {}\n", encoding="utf-8"
    )
    (tmp_path / "run.py").write_text("print('run')\n", encoding="utf-8")
    (tmp_path / "outputs" / "final_report.md").write_text(
        "# Final Report\n", encoding="utf-8"
    )
    row = {
        "iteration": 4,
        "action_type": "diagnostic",
        "model": "Ridge_ensemble_mean_4terms",
        "metric": "ensemble_cov+prec_LW+dcorr+spearman",
        "aggregate_mean_r": 0.175848,
        "coverage_fraction": 1.0,
        "n_hit_mean": 5,
        "verdict": "ADVANCE",
        "per_component": [
            {
                "component": "ICA_Cognition",
                "fold_mean_r": 0.385344,
                "reference_mean_r": 0.215,
                "reference_best_r": 0.42,
                "hit_mean": True,
                "hit_best": False,
            },
            {
                "component": "ICA_TobaccoUse",
                "fold_mean_r": 0.227241,
                "reference_mean_r": 0.143,
                "reference_best_r": 0.357,
                "hit_mean": True,
                "hit_best": False,
            },
        ],
    }
    (tmp_path / "experiments.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )

    bundle = build_autoresearch_review_bundle(tmp_path)

    assert bundle.latest_summary is not None
    assert bundle.latest_summary.aggregate_mean_r == 0.175848
    assert bundle.best_summary is not None
    assert bundle.best_summary.aggregate_mean_r == 0.175848
    assert bundle.latest_summary.model == "Ridge_ensemble_mean_4terms"
    assert bundle.latest_summary.fc_metric == "ensemble_cov+prec_LW+dcorr+spearman"
    cognition = next(
        item for item in bundle.component_summaries if item.component == "ICA_Cognition"
    )
    assert cognition.best_fold_mean_r == 0.385344
    assert cognition.ever_hit_mean is True
