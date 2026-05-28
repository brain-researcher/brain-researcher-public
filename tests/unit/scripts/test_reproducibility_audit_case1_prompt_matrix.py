from __future__ import annotations

from pathlib import Path

from scripts.reproducibility_audit import run_case1_layer_b_prompt_variant_matrix as module


def test_isolation_scan_ignores_prior_output_exclusion_globs(tmp_path: Path) -> None:
    run_dir = tmp_path / "current_run"
    episode_dir = run_dir / "episodes" / "condition" / "layer_b_30793072"
    episode_dir.mkdir(parents=True)
    (episode_dir / "stdout.txt").write_text(
        "rg -n \"ALE\" benchmarks scripts "
        "-g '!benchmarks/neurometabench/experiments/agent_condition_matrix/**/producer_outputs/**'\n",
        encoding="utf-8",
    )
    (episode_dir / "stderr.txt").write_text("", encoding="utf-8")

    result = module.scan_episode_isolation(
        run_dir=run_dir,
        records=[{"condition_id": "condition", "episode_dir": str(episode_dir)}],
    )

    assert result["status"] == "clean"
    assert result["prior_experiment_hit_count"] == 0


def test_isolation_scan_flags_actual_prior_output_reference(tmp_path: Path) -> None:
    run_dir = tmp_path / "current_run"
    episode_dir = run_dir / "episodes" / "condition" / "layer_b_30793072"
    episode_dir.mkdir(parents=True)
    (episode_dir / "stdout.txt").write_text(
        "Reading benchmarks/neurometabench/experiments/agent_condition_matrix/"
        "old_run/producer_outputs/condition/layer_b_30793072/coordinate_table.csv\n",
        encoding="utf-8",
    )
    (episode_dir / "stderr.txt").write_text("", encoding="utf-8")

    result = module.scan_episode_isolation(
        run_dir=run_dir,
        records=[{"condition_id": "condition", "episode_dir": str(episode_dir)}],
    )

    assert result["status"] == "warning"
    assert result["prior_experiment_hit_count"] == 1
