from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SEED_ROWS: list[dict[str, Any]] = [
    {
        "seed_id": "concept:attention",
        "node_type": "Concept",
        "query": "attention",
        "role": "control",
        "why": "Stable mixed concept control from v1 replay and bounded claim artifacts.",
        "expected_use": "low_drift_control",
    },
    {
        "seed_id": "concept:reward_learning",
        "node_type": "Concept",
        "query": "reward learning",
        "role": "control",
        "why": "Repo-known strict-vs-broad discriminator retained as a positive control for candidate-lane sensitivity.",
        "expected_use": "delta_positive_control",
    },
    {
        "seed_id": "neurostore_task:uxtq96MkGKbV:fmri:0",
        "node_type": "Task",
        "query": "social attention task",
        "role": "control",
        "why": "Previously validated live workflow seed; kept as task-level control.",
        "expected_use": "task_control",
    },
    {
        "seed_id": "concept:amyloid",
        "node_type": "Concept",
        "query": "amyloid biomarker",
        "role": "candidate_sensitive",
        "why": "Live candidate-only concept target from benchmark_final_tail_candidate_only bucket.",
        "expected_use": "broad_strict_probe",
    },
    {
        "seed_id": "concept:striatal_reward_sensitivity",
        "node_type": "Concept",
        "query": "striatal reward sensitivity",
        "role": "candidate_sensitive",
        "why": "Live candidate-only concept target from benchmark_final_tail_candidate_only bucket.",
        "expected_use": "broad_strict_probe",
    },
    {
        "seed_id": "concept:serotonin_1a_receptor_binding",
        "node_type": "Concept",
        "query": "serotonin 1A receptor binding",
        "role": "candidate_sensitive",
        "why": "Live candidate-only biomarker target from benchmark_terminal_candidate_only bucket.",
        "expected_use": "broad_strict_probe",
    },
    {
        "seed_id": "task:response_inhibition",
        "node_type": "Task",
        "query": "response inhibition",
        "role": "candidate_sensitive",
        "why": "Live candidate-only task target from benchmark_terminal_candidate_only bucket.",
        "expected_use": "broad_strict_probe",
    },
    {
        "seed_id": "task:risky_decision_making",
        "node_type": "Task",
        "query": "risky decision making",
        "role": "candidate_sensitive",
        "why": "Live candidate-only task target from benchmark_terminal_candidate_only bucket.",
        "expected_use": "broad_strict_probe",
    },
]

DROPPED_V1_SEEDS: list[dict[str, str]] = [
    {
        "seed_id": "ds:openneuro:ds000114",
        "reason": "Dataset seed produced anonymous element-id candidates and no broad/strict delta.",
    },
    {
        "seed_id": "neurostore_task:8KxjduL9yMvK:behavioral:0",
        "reason": "Acoustic attention task produced only insufficient-evidence bridge cards in v1 replay.",
    },
    {
        "seed_id": "neurostore_task:8GUWT4kpDKww:fmri:0",
        "reason": "Follow-up task anchor did not surface candidate-lane-sensitive divergence in v1 replay.",
    },
]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(dict(row), sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize idea-mining seed set v2 and replay pack v2.")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    seed_rows = [
        {
            "schema_version": "idea-mining-seed-set-v2",
            **row,
        }
        for row in SEED_ROWS
    ]
    summary = {
        "schema_version": "idea-mining-seed-set-v2-summary",
        "rows_total": len(seed_rows),
        "candidate_sensitive_total": sum(1 for row in seed_rows if row["role"] == "candidate_sensitive"),
        "control_total": sum(1 for row in seed_rows if row["role"] == "control"),
        "dropped_v1_seeds": DROPPED_V1_SEEDS,
    }
    examples: list[dict[str, Any]] = []
    for row in seed_rows:
        for mode in ("broad", "strict"):
            examples.append(
                {
                    "schema_version": "idea-mining-replay-example-v2",
                    "replay_pack_id": "idea_mining_replay_pack_v2_20260314",
                    "run_spec_id": f"{row['seed_id'].replace(':', '_')}_{mode}",
                    "seed_id": row["seed_id"],
                    "query": row["query"],
                    "workflow_id": "workflow_hypothesis_candidate_cards",
                    "candidate_lane_mode": mode,
                    "controller_mode": "legacy",
                    "top_k": 5,
                    "n_samples": 2,
                    "expected_checks": [
                        "workflow_success",
                        "cards_generated",
                        "verifier_mode_surface",
                        "broad_vs_strict_delta",
                    ],
                }
            )

    manifest = {
        "schema_version": "idea-mining-replay-pack-v2",
        "replay_pack_id": "idea_mining_replay_pack_v2_20260314",
        "seed_set_ref": str(output_dir / "idea_mining_seed_set_v2.jsonl"),
        "workflow_id": "workflow_hypothesis_candidate_cards",
        "controller_mode": "legacy",
        "candidate_lane_modes": ["broad", "strict"],
        "examples_jsonl": str(output_dir / "idea_mining_replay_pack_v2_examples.jsonl"),
        "checks": [
            "workflow_success",
            "seed_resolution",
            "cards_generated",
            "verifier_mode_surface",
            "broad_vs_strict_delta",
            "fallback_or_degraded_flag",
        ],
    }
    replay_summary = {
        "schema_version": "idea-mining-replay-pack-v2-summary",
        "seed_rows_total": len(seed_rows),
        "run_specs_total": len(examples),
        "candidate_sensitive_seed_ids": [
            row["seed_id"] for row in seed_rows if row["role"] == "candidate_sensitive"
        ],
    }

    _write_jsonl(output_dir / "idea_mining_seed_set_v2.jsonl", seed_rows)
    _write_json(output_dir / "idea_mining_seed_set_v2_summary.json", summary)
    _write_jsonl(output_dir / "idea_mining_replay_pack_v2_examples.jsonl", examples)
    _write_json(output_dir / "idea_mining_replay_pack_v2_manifest.json", manifest)
    _write_json(output_dir / "idea_mining_replay_pack_v2_summary.json", replay_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
