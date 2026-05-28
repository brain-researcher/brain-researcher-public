from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_researcher.autoresearch.scorer_contract import (
    ScoreMutationError,
    run_guarded_scorer_command,
    score_discovery_closed_loop,
    score_predictive_weak_targets,
)


def test_score_predictive_weak_targets_uses_explicit_ledger(tmp_path: Path) -> None:
    ledger_path = tmp_path / "experiments.jsonl"
    rows = [
        {
            "phase": "phase9_weak_target_term_discovery",
            "config": {
                "target": "PicSeq_Unadj",
                "hyperparameters": {"term_index": 11},
            },
            "scores": {"gold_r2": 0.02},
            "tags": [],
        },
        {
            "phase": "phase9_weak_target_term_discovery",
            "config": {
                "target": "PicSeq_Unadj",
                "hyperparameters": {"term_index": 12, "replicate_id": "r1"},
            },
            "scores": {"gold_r2": 0.03},
            "tags": [],
        },
        {
            "phase": "phase9_weak_target_term_discovery",
            "config": {
                "target": "PicSeq_Unadj",
                "hyperparameters": {"term_index": 13},
            },
            "scores": {"gold_r2": 0.0},
            "tags": ["label-shuffle-control"],
        },
        {
            "phase": "phase9_weak_target_term_discovery",
            "config": {
                "target": "ListSort_Unadj",
                "hyperparameters": {"term_index": 21},
            },
            "scores": {"gold_r2": 0.01},
            "tags": [],
        },
        {
            "phase": "phase9_weak_target_term_discovery",
            "config": {
                "target": "ListSort_Unadj",
                "hyperparameters": {"term_index": 22},
            },
            "scores": {"gold_r2": 0.0},
            "tags": ["label-shuffle-control"],
        },
    ]
    ledger_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    result = score_predictive_weak_targets(
        ledger_path,
        min_nulls=1,
        min_replicates=0,
    )

    assert result.scorer_name == "predictive_weak_targets"
    assert result.payload["contract_satisfied"] is True
    assert result.payload["target_scores"]["PicSeq_Unadj"] == pytest.approx(0.03)
    assert result.payload["exploratory_term_counts"]["PicSeq_Unadj"] == 2


def test_score_discovery_closed_loop_uses_explicit_checkpoint_paths(tmp_path: Path) -> None:
    loop_root = tmp_path / "closed_loop_001"
    loop_root.mkdir()
    state_path = loop_root / "research_state.json"
    state_path.write_text(
        json.dumps(
            {
                "branches": [
                    {
                        "branch_id": "tom",
                        "status": "frozen",
                        "decision": "freeze",
                        "evidence": {"best_score": 3.0},
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    checkpoint_path = loop_root / "closed_loop_checkpoint.json"
    checkpoint_path.write_text(
        json.dumps({"rounds": [{"state_path": str(state_path)}]}, indent=2),
        encoding="utf-8",
    )
    kg_log = tmp_path / "tribe_kg_call_log.jsonl"
    kg_log.write_text(
        json.dumps({"branch_id": "tom", "injection_point": 1}) + "\n"
        + json.dumps({"branch_id": "tom", "injection_point": 3}) + "\n"
        + json.dumps({"branch_id": "tom", "injection_point": 4}) + "\n",
        encoding="utf-8",
    )
    ledger = tmp_path / "tribe_hypothesis_ledger.jsonl"
    ledger.write_text(
        json.dumps(
            {"kg_support_level": "weak", "kg_call_ids": ["kg1", "kg2"]}
        )
        + "\n",
        encoding="utf-8",
    )

    result = score_discovery_closed_loop(
        checkpoint_path,
        kg_log_path=kg_log,
        ledger_path=ledger,
        expected_branches=("tom",),
    )

    assert result.payload["n_branches_seen"] == 1
    assert result.payload["score_B"] == pytest.approx(1.0)
    assert result.payload["n_novel_hypotheses"] == 1


def test_run_guarded_scorer_command_detects_side_effects(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    tracked = root / "tracked.json"
    tracked.write_text(json.dumps({"value": 1}), encoding="utf-8")

    with pytest.raises(ScoreMutationError):
        run_guarded_scorer_command(
            (
                "python",
                "-c",
                (
                    "from pathlib import Path; "
                    f"Path(r'{tracked}').write_text('{{\"value\": 2}}', encoding='utf-8'); "
                    "print('{\"score\": 1.0}')"
                ),
            ),
            mutation_roots=(root,),
        )
