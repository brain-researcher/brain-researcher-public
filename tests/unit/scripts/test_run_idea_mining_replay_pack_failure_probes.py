from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_idea_mining_failure_taxonomy_pack as pack_module
from scripts.tools.etl import run_idea_mining_replay_pack as module


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_run_idea_mining_replay_pack_emits_failure_layers_for_probe_eval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pack_dir = tmp_path / "failure_pack"
    pack_module.main(["--output-dir", str(pack_dir)])

    examples_jsonl = tmp_path / "examples.jsonl"
    manifest_json = tmp_path / "manifest.json"
    output_dir = tmp_path / "out"

    _write_jsonl(
        examples_jsonl,
        [
            {
                "run_spec_id": "dmn_aging_broad",
                "seed_id": "concept:default_mode_network",
                "query": (
                    "Does default mode network suppression during working memory tasks "
                    "differ between younger and older adults?"
                ),
                "workflow_id": "workflow_hypothesis_candidate_cards",
                "candidate_lane_mode": "broad",
                "controller_mode": "legacy",
                "top_k": 5,
                "n_samples": 1,
                "failure_probe_id": "IMR-01",
            }
        ],
    )
    _write_json(
        manifest_json,
        {
            "replay_pack_id": "idea_mining_replay_pack_v1_20260316_failure_probe",
            "workflow_id": "workflow_hypothesis_candidate_cards",
            "examples_jsonl": str(examples_jsonl),
            "failure_regression_manifest_json": str(
                pack_dir / "idea_mining_failure_regression_manifest_v1.json"
            ),
        },
    )

    class _FakeResult:
        def __init__(self, data: dict[str, object]):
            self.status = "success"
            self.error = None
            self.data = data

    def _fake_execute_tool(
        tool_id: str,
        params: dict[str, object],
        emit_execution_pack: bool = False,
    ):
        del tool_id, emit_execution_pack
        return _FakeResult(
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

    def _fake_build_cards(
        workflow_result: dict[str, object],
        *,
        query: str,
        top_n: int = 1,
    ):
        del workflow_result, query, top_n
        return [
            {
                "card_id": "card:degenerate_transfer",
                "title": "Penn Word Memory OOD hypothesis",
                "hypothesis": (
                    "Representations supporting decoding in Penn Word Memory Test "
                    "may transfer to Penn Facial Memory Test because both depend on "
                    "a shared latent mechanism."
                ),
                "kg_verification": {"verdict": "supported", "confidence": 0.7},
                "minimal_discriminating_test": (
                    "Train on Penn Word Memory Test, test on Penn Facial Memory Test."
                ),
                "falsifier_hint": (
                    "Reject if cross-condition performance stays at control levels."
                ),
                "provenance": {
                    "source_workflow": "workflow_hypothesis_candidate_cards",
                    "seed_kg_id": "concept:default_mode_network",
                    "candidate_kg_id": "concept:penn_facial_memory",
                    "relation_hint": "ASSOCIATED_WITH",
                    "sampled_hypothesis_verification": {
                        "candidate_lane_mode": "broad",
                        "candidate_lane_filtered": 0,
                        "verification_error": None,
                        "kg_verification": {
                            "verdict": "supported",
                            "confidence": 0.7,
                        },
                    },
                },
            }
        ]

    monkeypatch.setattr(module, "execute_tool", _fake_execute_tool)
    monkeypatch.setattr(
        module,
        "build_candidate_cards_from_workflow_result",
        _fake_build_cards,
    )

    exit_code = module.main(
        [
            "--manifest-json",
            str(manifest_json),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    review_rows = [
        json.loads(line)
        for line in (output_dir / "candidate_card_review_rows.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(review_rows) == 1
    review_row = review_rows[0]
    assert review_row["failure_probe_id"] == "IMR-01"
    assert review_row["failure_probe_status"] == "fail"
    assert set(review_row["failure_layers_triggered"]) == {
        "SC-1",
        "TA-1",
        "TD-1",
        "LV-1",
    }

    routing_rows = [
        json.loads(line)
        for line in (output_dir / "candidate_card_routing_decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(routing_rows) == 1
    routing_row = routing_rows[0]
    assert routing_row["route"] == "codify_failure_pattern"
    assert set(routing_row["failure_layers_triggered"]) == {
        "SC-1",
        "TA-1",
        "TD-1",
        "LV-1",
    }

    codified_rows = [
        json.loads(line)
        for line in (output_dir / "candidate_card_codified_failures.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert {row["failure_pattern_id"] for row in codified_rows} >= {
        "SC-1",
        "TA-1",
        "TD-1",
        "LV-1",
    }
    assert all(row["classification"] == "failure_layer" for row in codified_rows)

    summary = json.loads(
        (
            output_dir / "idea_mining_replay_pack_v1_20260316_failure_probe_run_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert summary["failure_layer_counts"]["SC-1"] == 1
    assert summary["failure_probe_status_counts"]["fail"] == 1


def test_run_idea_mining_replay_pack_emits_run_level_zero_card_fail_closed_log(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pack_dir = tmp_path / "failure_pack"
    pack_module.main(["--output-dir", str(pack_dir)])

    examples_jsonl = tmp_path / "examples.jsonl"
    manifest_json = tmp_path / "manifest.json"
    output_dir = tmp_path / "out"

    _write_jsonl(
        examples_jsonl,
        [
            {
                "run_spec_id": "visual_decoding_broad",
                "seed_id": "concept:visual_decoding",
                "query": (
                    "Can fMRI-based neural decoding accurately reconstruct visual "
                    "image representations across different visual cortex regions?"
                ),
                "workflow_id": "workflow_hypothesis_candidate_cards",
                "candidate_lane_mode": "broad",
                "controller_mode": "legacy",
                "top_k": 5,
                "n_samples": 1,
                "failure_probe_id": "IMR-02",
            }
        ],
    )
    _write_json(
        manifest_json,
        {
            "replay_pack_id": "idea_mining_replay_pack_v1_20260317_zero_card",
            "workflow_id": "workflow_hypothesis_candidate_cards",
            "examples_jsonl": str(examples_jsonl),
            "failure_regression_manifest_json": str(
                pack_dir / "idea_mining_failure_regression_manifest_v1.json"
            ),
        },
    )

    class _FakeResult:
        def __init__(self, data: dict[str, object]):
            self.status = "success"
            self.error = None
            self.data = data

    def _fake_execute_tool(
        tool_id: str,
        params: dict[str, object],
        emit_execution_pack: bool = False,
    ):
        del tool_id, emit_execution_pack
        return _FakeResult(
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

    def _fake_build_cards(
        workflow_result: dict[str, object],
        *,
        query: str,
        top_n: int = 1,
    ):
        del workflow_result, query, top_n
        return []

    monkeypatch.setattr(module, "execute_tool", _fake_execute_tool)
    monkeypatch.setattr(
        module,
        "build_candidate_cards_from_workflow_result",
        _fake_build_cards,
    )

    exit_code = module.main(
        [
            "--manifest-json",
            str(manifest_json),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    review_rows = _load_jsonl(output_dir / "candidate_card_review_rows.jsonl")
    assert review_rows == []

    probe_run_rows = _load_jsonl(
        output_dir / "idea_mining_failure_probe_run_evaluations.jsonl"
    )
    assert len(probe_run_rows) == 1
    probe_run = probe_run_rows[0]
    assert probe_run["replay_pack_id"] == "idea_mining_replay_pack_v1_20260317_zero_card"
    assert probe_run["failure_probe_id"] == "IMR-02"
    assert probe_run["failure_probe_status"] == "pass_zero_card"
    assert probe_run["zero_card_pass_closed"] is True
    assert probe_run["cards_total"] == 0
    assert probe_run["failure_layers_triggered"] == ["SC-1"]

    summary = json.loads(
        (
            output_dir / "idea_mining_replay_pack_v1_20260317_zero_card_run_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert summary["failure_probe_runs_total"] == 1
    assert summary["failure_probe_status_counts"]["pass_zero_card"] == 1
    assert summary["failure_probe_run_layer_counts"]["SC-1"] == 1
    assert summary["zero_card_pass_closed_runs"] == 1
