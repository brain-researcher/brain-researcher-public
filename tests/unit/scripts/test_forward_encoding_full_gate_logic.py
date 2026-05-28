"""Unit tests for scripts/analysis/run_forward_encoding_full.py gate logic."""

from __future__ import annotations

from scripts.analysis.run_forward_encoding_full import EvalSummary, compute_gate_decision


def test_gate_go_when_same_mode_passes_both_thresholds() -> None:
    modes = {
        "residual_lowrank32": EvalSummary(
            n_eval=63,
            mean_r_model=0.10,
            mean_r_baseline=0.09,
            mean_delta=-0.001,
            win_rate=0.56,
        ),
        "residual_voxel": EvalSummary(
            n_eval=63,
            mean_r_model=0.095,
            mean_r_baseline=0.096,
            mean_delta=-0.0015,
            win_rate=0.50,
        ),
    }

    gate = compute_gate_decision(
        modes,
        delta_threshold=-0.002,
        win_rate_threshold=0.55,
    )

    assert gate["decision"] == "go"
    assert gate["pass_joint_modes"] == ["residual_lowrank32"]
    assert gate["split_evidence"] is False


def test_gate_conditional_go_with_split_evidence() -> None:
    modes = {
        "residual_lowrank32": EvalSummary(
            n_eval=63,
            mean_r_model=0.095,
            mean_r_baseline=0.096,
            mean_delta=-0.001,
            win_rate=0.51,
        ),
        "abs_voxel": EvalSummary(
            n_eval=63,
            mean_r_model=0.085,
            mean_r_baseline=0.098,
            mean_delta=-0.013,
            win_rate=0.56,
        ),
    }

    gate = compute_gate_decision(
        modes,
        delta_threshold=-0.002,
        win_rate_threshold=0.55,
    )

    assert gate["decision"] == "conditional_go"
    assert gate["pass_delta_modes"] == ["residual_lowrank32"]
    assert gate["pass_win_modes"] == ["abs_voxel"]
    assert gate["pass_joint_modes"] == []
    assert gate["split_evidence"] is True
