from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.tools.etl import (
    build_idea_mining_failure_taxonomy_pack as build_failure_pack,
    run_idea_mining_replay_pack as replay_module,
)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_replay_runner_surfaces_failure_layers_for_probe(monkeypatch, tmp_path):
    failure_pack_dir = tmp_path / "failure_pack"
    failure_pack_dir.mkdir()
    build_failure_pack.main(["--output-dir", str(failure_pack_dir)])

    examples = [
        {
            "run_spec_id": "degenerate_transfer",
            "seed_id": "concept:attention",
            "query": "Does default mode network suppression differ with aging?",
            "workflow_id": "workflow_hypothesis_candidate_cards",
            "candidate_lane_mode": "broad",
            "controller_mode": "legacy",
            "top_k": 5,
            "n_samples": 1,
            "failure_probe_id": "IMR-01",
        }
    ]
    examples_path = tmp_path / "examples.jsonl"
    _write_jsonl(examples_path, examples)

    manifest = {
        "replay_pack_id": "idea_mining_failure_probe_replay_test",
        "workflow_id": "workflow_hypothesis_candidate_cards",
        "examples_jsonl": str(examples_path),
        "failure_regression_manifest_json": str(
            failure_pack_dir / "idea_mining_failure_regression_manifest_v1.json"
        ),
    }
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    class _FakeToolResult:
        def __init__(self, data: dict[str, Any]):
            self.status = "success"
            self.error = None
            self.data = data

    def _fake_execute_tool(tool_id: str, params: dict[str, Any], emit_execution_pack: bool = False):
        del tool_id, emit_execution_pack
        return _FakeToolResult(
            {
                "workflow": "workflow_hypothesis_candidate_cards",
                "steps": {
                    "verify_sampled_hypotheses": {},
                    "ood_sampling": {},
                    "leverage": {},
                },
                "_spec": dict(params),
            }
        )

    def _fake_build_cards(workflow_result: dict[str, Any], *, query: str, top_n: int = 1):
        del workflow_result, query, top_n
        return [
            {
                "card_id": "card:degenerate_transfer",
                "title": "Penn Transfer Hypothesis",
                "hypothesis": (
                    "Representations in Penn Word Memory may transfer to Penn Facial Memory "
                    "because they share a latent mechanism."
                ),
                "minimal_discriminating_test": (
                    "Train on Penn Word Memory, test on Penn Facial Memory to see if values diverge."
                ),
                "falsifier_hint": "Reject if cross-task performance remains unchanged.",
                "kg_verification": {"verdict": "supported", "confidence": 0.7},
                "provenance": {
                    "seed_kg_id": "concept:attention",
                    "candidate_kg_id": "concept:penn_facial_memory",
                    "relation_hint": "ASSOCIATED_WITH",
                },
            }
        ]

    failure_layers_captured: list[list[dict[str, Any]]] = []

    def _fake_evaluate_probe_cards(probe: dict[str, Any], cards: list[dict[str, Any]]):
        del probe
        failure_layers_captured.append(cards)
        return {
            "failure_layers_triggered": ["SC-1", "TA-1", "TD-1", "LV-1"],
            "status": "fail",
            "cards_total": len(cards),
            "label": "IMR-01",
            "checks": {
                "query_role_coverage": False,
                "anchor_family_alignment": False,
                "candidate_family_restriction": False,
                "template_family_rejection": False,
                "allow_zero_card_fail_closed": False,
            },
        }

    monkeypatch.setattr(
        replay_module,
        "execute_tool",
        _fake_execute_tool,
    )
    monkeypatch.setattr(
        replay_module,
        "build_candidate_cards_from_workflow_result",
        _fake_build_cards,
    )
    monkeypatch.setattr(
        replay_module,
        "evaluate_probe_cards",
        _fake_evaluate_probe_cards,
    )

    output_dir = tmp_path / "out"
    exit_code = replay_module.main(
        ["--manifest-json", str(manifest_path), "--output-dir", str(output_dir)]
    )
    assert exit_code == 0
    assert failure_layers_captured, "failure probe evaluation should run"

    log_files = replay_module._log_file_names(manifest["replay_pack_id"])
    routing_rows = _load_jsonl(output_dir / log_files["routing_decisions"])
    codified_rows = _load_jsonl(output_dir / log_files["codified_failures"])

    expected_layers = {"SC-1", "TA-1", "TD-1", "LV-1"}
    assert routing_rows, "routing logs should exist"
    for row in routing_rows:
        assert set(row.get("failure_layers_triggered", [])) == expected_layers

    assert codified_rows, "codified failure log should mirror the failure layers"
    assert {row.get("failure_pattern_id") for row in codified_rows} >= expected_layers
