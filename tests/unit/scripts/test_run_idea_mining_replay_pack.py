from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import run_idea_mining_replay_pack as module


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _summary_path(output_dir: Path, replay_pack_id: str) -> Path:
    return output_dir / f"{replay_pack_id}_run_summary.json"


def test_run_idea_mining_replay_pack_populates_logs(tmp_path: Path, monkeypatch) -> None:
    examples_jsonl = tmp_path / "examples.jsonl"
    manifest_json = tmp_path / "manifest.json"
    output_dir = tmp_path / "out"

    _write_jsonl(
        examples_jsonl,
        [
            {
                "run_spec_id": "seed_a_broad",
                "seed_id": "concept:attention",
                "query": "attention",
                "workflow_id": "workflow_hypothesis_candidate_cards",
                "candidate_lane_mode": "broad",
                "controller_mode": "legacy",
                "top_k": 5,
                "n_samples": 1,
            },
            {
                "run_spec_id": "seed_a_strict",
                "seed_id": "concept:attention",
                "query": "attention",
                "workflow_id": "workflow_hypothesis_candidate_cards",
                "candidate_lane_mode": "strict",
                "controller_mode": "legacy",
                "top_k": 5,
                "n_samples": 1,
            },
        ],
    )
    _write_json(
        manifest_json,
        {
            "replay_pack_id": "idea_mining_replay_pack_v1_20260314",
            "workflow_id": "workflow_hypothesis_candidate_cards",
            "examples_jsonl": str(examples_jsonl),
        },
    )

    class _FakeResult:
        def __init__(self, data: dict[str, object]):
            self.status = "success"
            self.error = None
            self.data = data

    def _fake_execute_tool(tool_id: str, params: dict[str, object], emit_execution_pack: bool = False):
        del tool_id, emit_execution_pack
        return _FakeResult(
            {
                "workflow": "workflow_hypothesis_candidate_cards",
                "steps": {"verify_sampled_hypotheses": {}, "ood_sampling": {}, "leverage": {}},
                "_spec": dict(params),
            }
        )

    def _fake_build_cards(workflow_result: dict[str, object], *, query: str, top_n: int = 1):
        del query, top_n
        spec = workflow_result["_spec"]
        mode = spec["candidate_lane_mode"]
        verdict = "supported" if mode == "broad" else "insufficient_evidence"
        return [
            {
                "card_id": f"card:{mode}",
                "title": f"{mode} card",
                "hypothesis": "Attention may couple with Candidate A under constrained settings.",
                "kg_verification": {"verdict": verdict, "confidence": 0.7},
                "minimal_discriminating_test": "Compare anchor vs candidate under a bounded task.",
                "falsifier_hint": "Reject if no stable difference appears for anchor vs candidate.",
                "provenance": {
                    "source_workflow": "workflow_hypothesis_candidate_cards",
                    "seed_kg_id": "concept:attention",
                    "candidate_kg_id": "concept:candidate_a",
                    "relation_hint": "ASSOCIATED_WITH",
                    "novelty_score": 0.8,
                    "ood_score": 0.7,
                    "sampled_hypothesis_verification": {
                        "candidate_lane_mode": mode,
                        "candidate_lane_filtered": 1 if mode == "strict" else 0,
                        "verification_error": None,
                        "kg_verification": {"verdict": verdict, "confidence": 0.7},
                    },
                },
            }
        ]

    monkeypatch.setattr(module, "execute_tool", _fake_execute_tool)
    monkeypatch.setattr(module, "build_candidate_cards_from_workflow_result", _fake_build_cards)

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
        for line in (output_dir / "candidate_card_review_rows.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(review_rows) == 2
    assert {row["candidate_lane_mode"] for row in review_rows} == {"broad", "strict"}
    assert any(row["paired_broad_strict_delta"] for row in review_rows)
    assert all(row["scores"]["provenance_integrity"] >= 2 for row in review_rows)
    assert all(row["scores"]["discriminating_testability"] >= 2 for row in review_rows)

    routing_rows = [
        json.loads(line)
        for line in (output_dir / "candidate_card_routing_decisions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    routes = {row["candidate_card_id"]: row["route"] for row in routing_rows}
    assert routes["card:broad"] == "hold_for_refinement"
    assert routes["card:strict"] in {"retire_from_candidate_pack", "hold_for_refinement", "codify_failure_pattern"}

    summary = json.loads(
        _summary_path(output_dir, "idea_mining_replay_pack_v1_20260314").read_text(encoding="utf-8")
    )
    assert summary["runs_total"] == 2
    assert summary["candidate_cards_total"] == 2
    assert summary["pair_counts"]["pairs_total"] == 1
    assert summary["pair_counts"]["pairs_with_delta"] == 1
    assert summary["seeds_with_meaningful_delta"] == ["concept:attention"]


def test_run_idea_mining_replay_pack_codifies_repeated_failure_pattern(
    tmp_path: Path,
    monkeypatch,
) -> None:
    examples_jsonl = tmp_path / "examples.jsonl"
    manifest_json = tmp_path / "manifest.json"
    output_dir = tmp_path / "out"

    _write_jsonl(
        examples_jsonl,
        [
            {
                "run_spec_id": "seed_a_broad",
                "seed_id": "concept:attention",
                "query": "attention",
                "workflow_id": "workflow_hypothesis_candidate_cards",
                "candidate_lane_mode": "broad",
                "controller_mode": "legacy",
                "top_k": 5,
                "n_samples": 1,
            },
            {
                "run_spec_id": "seed_b_broad",
                "seed_id": "concept:working_memory",
                "query": "working memory",
                "workflow_id": "workflow_hypothesis_candidate_cards",
                "candidate_lane_mode": "broad",
                "controller_mode": "legacy",
                "top_k": 5,
                "n_samples": 1,
            },
        ],
    )
    _write_json(
        manifest_json,
        {
            "replay_pack_id": "idea_mining_replay_pack_v1_20260314",
            "workflow_id": "workflow_hypothesis_candidate_cards",
            "examples_jsonl": str(examples_jsonl),
        },
    )

    class _FakeResult:
        def __init__(self, data: dict[str, object]):
            self.status = "success"
            self.error = None
            self.data = data

    def _fake_execute_tool(tool_id: str, params: dict[str, object], emit_execution_pack: bool = False):
        del tool_id, emit_execution_pack
        return _FakeResult({"workflow": "workflow_hypothesis_candidate_cards", "steps": {}, "_spec": dict(params)})

    def _fake_build_cards(workflow_result: dict[str, object], *, query: str, top_n: int = 1):
        del query, top_n
        spec = workflow_result["_spec"]
        return [
            {
                "card_id": f"card:{spec['seed_kg_ids'][0]}",
                "title": "Generic OOD hypothesis",
                "hypothesis": "Seed may show out-of-distribution coupling with candidate node.",
                "kg_verification": {},
                "minimal_discriminating_test": "",
                "falsifier_hint": "",
                "provenance": {
                    "source_workflow": "workflow_hypothesis_candidate_cards",
                    "seed_kg_id": spec["seed_kg_ids"][0],
                    "candidate_kg_id": "",
                    "relation_hint": "",
                    "sampled_hypothesis_verification": {
                        "candidate_lane_mode": "broad",
                        "candidate_lane_filtered": 0,
                        "verification_error": "fallback",
                        "kg_verification": {},
                    },
                },
            }
        ]

    monkeypatch.setattr(module, "execute_tool", _fake_execute_tool)
    monkeypatch.setattr(module, "build_candidate_cards_from_workflow_result", _fake_build_cards)

    exit_code = module.main(
        [
            "--manifest-json",
            str(manifest_json),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    routing_rows = [
        json.loads(line)
        for line in (output_dir / "candidate_card_routing_decisions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["route"] for row in routing_rows} == {"codify_failure_pattern"}

    codified_rows = [
        json.loads(line)
        for line in (output_dir / "candidate_card_codified_failures.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(codified_rows) >= 1
    assert any(row["failure_pattern_id"] == "fallback_overconfidence_repeats" for row in codified_rows)


def test_run_idea_mining_replay_pack_can_reuse_precomputed_run_results(
    tmp_path: Path,
) -> None:
    manifest_json = tmp_path / "manifest.json"
    run_results_jsonl = tmp_path / "run_results.jsonl"
    output_dir = tmp_path / "out"

    _write_json(
        manifest_json,
        {
            "replay_pack_id": "idea_mining_replay_pack_v1_20260314",
            "workflow_id": "workflow_hypothesis_candidate_cards",
            "examples_jsonl": str(tmp_path / "unused.jsonl"),
        },
    )
    _write_jsonl(
        run_results_jsonl,
        [
            {
                "run_spec_id": "seed_a_broad",
                "seed_id": "concept:attention",
                "query": "attention",
                "candidate_lane_mode": "broad",
                "tool_status": "success",
                "tool_error": None,
                "cards": [
                    {
                        "card_id": "card:broad",
                        "title": "broad card",
                        "hypothesis": "Attention may couple with Candidate A under constrained settings.",
                        "kg_verification": {"verdict": "supported", "confidence": 0.7},
                        "minimal_discriminating_test": "Compare anchor vs candidate under a bounded task.",
                        "falsifier_hint": "Reject if no stable difference appears for anchor vs candidate.",
                        "provenance": {
                            "source_workflow": "workflow_hypothesis_candidate_cards",
                            "seed_kg_id": "concept:attention",
                            "candidate_kg_id": "concept:candidate_a",
                            "relation_hint": "ASSOCIATED_WITH",
                            "novelty_score": 0.8,
                            "ood_score": 0.7,
                            "sampled_hypothesis_verification": {
                                "candidate_lane_mode": "broad",
                                "candidate_lane_filtered": 0,
                                "verification_error": None,
                                "kg_verification": {"verdict": "supported", "confidence": 0.7},
                            },
                        },
                    }
                ],
                "raw_path": str(tmp_path / "raw_a.json"),
                "workflow": "workflow_hypothesis_candidate_cards",
                "steps_present": ["leverage", "ood_sampling", "verify_sampled_hypotheses"],
            }
        ],
    )

    exit_code = module.main(
        [
            "--manifest-json",
            str(manifest_json),
            "--output-dir",
            str(output_dir),
            "--reuse-run-results-jsonl",
            str(run_results_jsonl),
        ]
    )
    assert exit_code == 0

    summary = json.loads(
        _summary_path(output_dir, "idea_mining_replay_pack_v1_20260314").read_text(encoding="utf-8")
    )
    assert summary["runs_total"] == 1
    assert summary["candidate_cards_total"] == 1


def test_run_idea_mining_replay_pack_uses_manifest_specific_result_names(
    tmp_path: Path,
) -> None:
    manifest_json = tmp_path / "manifest.json"
    run_results_jsonl = tmp_path / "run_results.jsonl"
    output_dir = tmp_path / "out"

    replay_pack_id = "idea_mining_replay_pack_v2_20260314"
    _write_json(
        manifest_json,
        {
            "replay_pack_id": replay_pack_id,
            "workflow_id": "workflow_hypothesis_candidate_cards",
            "examples_jsonl": str(tmp_path / "unused.jsonl"),
        },
    )
    _write_jsonl(
        run_results_jsonl,
        [
            {
                "run_spec_id": "seed_a_broad",
                "seed_id": "concept:attention",
                "query": "attention",
                "candidate_lane_mode": "broad",
                "tool_status": "success",
                "tool_error": None,
                "cards": [],
                "raw_path": str(tmp_path / "raw_a.json"),
                "workflow": "workflow_hypothesis_candidate_cards",
                "steps_present": [],
            }
        ],
    )

    exit_code = module.main(
        [
            "--manifest-json",
            str(manifest_json),
            "--output-dir",
            str(output_dir),
            "--reuse-run-results-jsonl",
            str(run_results_jsonl),
        ]
    )
    assert exit_code == 0
    assert (output_dir / f"{replay_pack_id}_run_summary.json").exists()
    assert (output_dir / f"{replay_pack_id}_results.jsonl").exists()
    assert (output_dir / "idea_mining_outcome_ledger_v2.jsonl").exists()
    assert (output_dir / "idea_mining_failure_probe_run_evaluations.jsonl").exists()
