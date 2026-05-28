from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.review.autoresearch_sequel_planner import (
    build_candidate_lines,
    build_closeout_card,
    generate_sequel_planning_artifacts,
)


def test_generate_sequel_planning_artifacts_selects_blind_replication(tmp_path: Path) -> None:
    workspace = tmp_path / "autoresearch_closeout_line_20260418_000000"
    outputs = workspace / "outputs"
    outputs.mkdir(parents=True)

    final_report = """# Final Report

## 2. Primary analysis

| Component | fold_mean_r | ref_mean_r | ref_best_r | hit_mean | hit_best |
|-----------|------------:|-----------:|-----------:|:--------:|:--------:|
| ICA_Cognition | 0.3786 | 0.215 | 0.420 | yes | no |
| ICA_TobaccoUse | 0.2641 | 0.143 | 0.357 | yes | no |
| ICA_PersonalityEmotion | 0.1191 | 0.084 | 0.245 | yes | no |
| ICA_IllicitDrugUse | 0.0200 | 0.010 | 0.199 | yes | no |
| ICA_MentalHealth | 0.1296 | 0.014 | 0.174 | yes | no |

- `run_alternate_parcellation_or_gsr_sensitivity`: **out of dataset scope for this line**
- `run_external_cohort_replication`: **out of dataset scope for this line**
- **validation_missing:** alternate_parcellation_or_gsr_sensitivity, external_cohort_replication
"""
    (outputs / "final_report.md").write_text(final_report, encoding="utf-8")

    verdict = {
        "overall_decision": "proceed",
        "report_action": "write_report",
        "claim_strength": "internally_supported",
        "rationale": "accepted closeout",
        "judgment": {"judgment_status": "parse_failed"},
        "validation_status": {
            "replication_evidence": "missing",
            "validation:alternate_parcellation_or_gsr": "mentioned_only",
            "validation:external_cohort_replication": "mentioned_only",
        },
    }
    (outputs / "autoresearch_scientific_review_verdict.json").write_text(
        json.dumps(verdict), encoding="utf-8"
    )

    line_state = {
        "line_type": "closeout",
        "status": "completed",
        "last_latest_summary": {
            "iteration": 39,
            "action_type": "final_report",
            "aggregate_mean_r": 0.182277,
        },
    }
    (workspace / "line_state.json").write_text(json.dumps(line_state), encoding="utf-8")

    # Existing sequel lines should be detected and deprioritized.
    (tmp_path / "autoresearch_data_scaling_line_20260417_230951").mkdir()
    (tmp_path / "autoresearch_generalization_line_20260418_000000").mkdir()

    presets = {
        "blind_replication": {
            "loaded_modules": ["base"],
            "forbidden_modules": ["representation_scaling"],
            "training_backend": "cpu_local",
            "success_criterion": "attempt_blind_reference_reproduction",
        },
        "representation_scaling": {
            "loaded_modules": ["base", "representation_scaling"],
            "forbidden_modules": ["foundation_transfer"],
            "training_backend": "cpu_local",
            "success_criterion": "test_representation_expansions",
        },
        "data_scaling": {
            "loaded_modules": ["base", "data_scaling"],
            "forbidden_modules": [],
            "training_backend": "cpu_local",
            "success_criterion": "estimate_sample_size_scaling",
        },
        "generalization": {
            "loaded_modules": ["base", "generalization", "robustness"],
            "forbidden_modules": ["foundation_transfer"],
            "training_backend": "cpu_local",
            "success_criterion": "stress_test_generalization_axes",
        },
        "model_scaling": {
            "loaded_modules": ["base", "model_scaling"],
            "forbidden_modules": [],
            "training_backend": "gpu_local",
            "success_criterion": "find_capacity_crossover",
        },
        "foundation_transfer": {
            "loaded_modules": ["base", "foundation_transfer"],
            "forbidden_modules": [],
            "training_backend": "gpu_local",
            "success_criterion": "test_pretrained_transfer",
        },
    }

    closeout_card = build_closeout_card(workspace, line_state=line_state)
    assert closeout_card["confirmed_wins"] == ["ICA_Cognition", "ICA_TobaccoUse"]
    assert "ICA_IllicitDrugUse" in closeout_card["weak_or_null_components"]
    assert "no_blind_replication_baseline" in closeout_card["demo_gaps"]

    candidate_lines = build_candidate_lines(
        closeout_card,
        module_presets=presets,
        workspace_root=tmp_path,
    )
    assert candidate_lines["selected_candidate_id"] == "blind_replication_baseline"

    generalization = next(
        item
        for item in candidate_lines["candidates"]
        if item["candidate_id"] == "generalization_axes_followup"
    )
    assert generalization["status"] == "already_exists"

    result = generate_sequel_planning_artifacts(
        workspace,
        line_state=line_state,
        module_presets=presets,
        workspace_root=tmp_path,
    )
    assert result["selected_candidate_id"] == "blind_replication_baseline"
    assert (outputs / "closeout_card.json").exists()
    assert (outputs / "candidate_lines.json").exists()
    assert (outputs / "line_spec.json").exists()
