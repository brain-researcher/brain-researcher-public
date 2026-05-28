from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_idea_mining_failure_taxonomy_pack as build_module
from scripts.tools.etl import evaluate_idea_mining_failure_probes as eval_module


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_evaluate_idea_mining_failure_probe_flags_degenerate_transfer_case(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "pack"
    build_module.main(["--output-dir", str(output_dir)])

    cards_json = tmp_path / "cards.json"
    _write_json(
        cards_json,
        [
            {
                "card_id": "card:1",
                "title": "Penn Word Memory OOD hypothesis",
                "hypothesis": (
                    "Representations supporting decoding in Penn Word Memory Test "
                    "may transfer to Penn Facial Memory Test because both depend on "
                    "a shared latent mechanism."
                ),
                "kg_verification": {"verdict": "supported", "confidence": 0.7},
                "minimal_discriminating_test": "Train on Penn Word Memory Test, test on Penn Facial Memory Test.",
                "falsifier_hint": "Reject if cross-condition performance stays at control levels.",
                "provenance": {
                    "seed_kg_id": "concept:attention",
                    "candidate_kg_id": "concept:penn_facial_memory",
                    "relation_hint": "ASSOCIATED_WITH",
                },
            }
        ],
    )

    result_json = tmp_path / "result.json"
    exit_code = eval_module.main(
        [
            "--probes-jsonl",
            str(output_dir / "idea_mining_failure_regression_probes_v1.jsonl"),
            "--probe-id",
            "IMR-01",
            "--cards-json",
            str(cards_json),
            "--output-json",
            str(result_json),
        ]
    )
    assert exit_code == 0

    result = json.loads(result_json.read_text(encoding="utf-8"))
    assert result["status"] == "fail"
    assert "SC-1" in result["failure_layers_triggered"]
    assert "TA-1" in result["failure_layers_triggered"]
    assert "TD-1" in result["failure_layers_triggered"]
    assert "LV-1" in result["failure_layers_triggered"]
    assert "population_comparator" in result["missing_required_roles"]
    assert result["template_hits"]
    assert result["candidate_family_hits"]


def test_evaluate_idea_mining_failure_probe_allows_zero_card_fail_closed(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "pack"
    build_module.main(["--output-dir", str(output_dir)])

    cards_json = tmp_path / "cards.json"
    _write_json(cards_json, [])

    result_json = tmp_path / "result.json"
    exit_code = eval_module.main(
        [
            "--probes-jsonl",
            str(output_dir / "idea_mining_failure_regression_probes_v1.jsonl"),
            "--probe-id",
            "IMR-02",
            "--cards-json",
            str(cards_json),
            "--output-json",
            str(result_json),
        ]
    )
    assert exit_code == 0

    result = json.loads(result_json.read_text(encoding="utf-8"))
    assert result["status"] == "pass_zero_card"
    assert result["zero_card_pass_closed"] is True
    assert result["cards_total"] == 0
