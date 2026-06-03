from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.memory import (
    MemoryStore,
    build_canonical_claim_id,
    build_verification_claim_mapping,
    distill_run_records,
    summarize_claim_families,
)
from brain_researcher.services.memory.models import build_memory_record
from scripts.tools.etl import (
    build_claim_snapshot_substantive_breadth_pack as snapshot_module,
)


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_memory_store_round_trip_episodic_card(tmp_path):
    store = MemoryStore(run_root=tmp_path)

    write_resp = store.write(
        "episodic_run_memory",
        {
            "source_run_id": "run_epi_1",
            "task_description": "Evaluate HCP connectivity workflow",
            "task_type": "analysis",
            "dataset_refs": ["HCP"],
            "modality": ["fMRI-task"],
            "tool_sequence": ["extract_timeseries", "connectivity_matrix"],
            "status": "success",
            "output_summary": "Produced connectivity matrices for the pilot cohort.",
            "tags": ["connectivity", "hcp"],
        },
    )

    assert write_resp["ok"] is True
    card_id = write_resp["card_id"]

    get_resp = store.get(card_id)
    assert get_resp["ok"] is True
    assert get_resp["card"]["task_description"] == "Evaluate HCP connectivity workflow"

    search_resp = store.search(
        "hcp connectivity workflow",
        card_type="episodic_run_memory",
        filters={"dataset_ref": "HCP", "status": "success"},
        limit=5,
    )
    assert search_resp["ok"] is True
    assert search_resp["cards"]
    assert search_resp["cards"][0]["card_id"] == card_id
    assert search_resp["cards"][0]["score"] is not None
    assert search_resp["cards"][0]["score"] > 0


def test_build_memory_record_derives_nonzero_embedding_vector():
    record = build_memory_record(
        "episodic_run_memory",
        {
            "source_run_id": "run_epi_embed_1",
            "task_description": "Run run1 executed fsl.bet via mcp.",
            "status": "success",
            "output_summary": "Status=success",
            "what_worked": ["Executed tool sequence: fsl.bet."],
            "tags": ["success", "fsl.bet"],
        },
    )

    assert record.embedding_text
    assert any(value != 0.0 for value in record.embedding_vector)


def test_build_memory_record_supports_code_review_verdict():
    record = build_memory_record(
        "code_review_verdict",
        {
            "source_run_id": "run_review_1",
            "decision": "revise",
            "risk_level": "medium",
        },
    )

    assert record.card_type == "code_review_verdict"
    assert record.source_run_id == "run_review_1"


def test_memory_store_round_trip_code_review_verdict(tmp_path):
    store = MemoryStore(run_root=tmp_path)

    write_resp = store.write(
        "code_review_verdict",
        {
            "source_run_id": "run_review_store_1",
            "decision": "approve_with_warnings",
            "risk_level": "low",
            "workflow_id": "wf-demo",
        },
    )

    assert write_resp["ok"] is True
    card_id = write_resp["card_id"]

    get_resp = store.get(card_id)
    assert get_resp["ok"] is True
    assert get_resp["card"]["card_type"] == "code_review_verdict"
    assert get_resp["card"]["source_run_id"] == "run_review_store_1"


def test_build_canonical_claim_id_matches_snapshot_family_helper():
    kwargs = {
        "target_id": "concept:working_memory",
        "target_type": "Concept",
        "claim_text": "Working memory load robustly recruits dlPFC.",
        "polarity": "supports",
    }

    assert build_canonical_claim_id(**kwargs) == snapshot_module._canonical_claim_id(
        **kwargs
    )


def test_build_verification_claim_mapping_is_deterministic():
    mapping = build_verification_claim_mapping(
        hypothesis="DLPFC is involved in n-back",
        normalized_claim={
            "subject": {
                "kg_id": "region:dlpfc",
                "label": "DLPFC",
                "node_type": "Region",
            },
            "predicate": "supports",
            "object": {
                "kg_id": "task:nback",
                "label": "n-back",
                "node_type": "Task",
            },
        },
        verdict="supports",
    )
    repeated = build_verification_claim_mapping(
        hypothesis="DLPFC is involved in n-back",
        normalized_claim={
            "subject": {
                "kg_id": "region:dlpfc",
                "label": "DLPFC",
                "node_type": "Region",
            },
            "predicate": "supports",
            "object": {
                "kg_id": "task:nback",
                "label": "n-back",
                "node_type": "Task",
            },
        },
        verdict="supports",
    )

    assert mapping["canonical_claim_id"].startswith("canonical_claim:")
    assert mapping["stable_key"] == f"claim_memory:{mapping['canonical_claim_id']}"
    assert mapping["canonical_target_id"] == "region:dlpfc|supports|task:nback"
    assert mapping["canonical_claim_text"] == "DLPFC supports n-back"
    assert mapping["target_ids"][0] == mapping["canonical_target_id"]
    assert mapping == repeated


def test_summarize_claim_families_groups_paraphrases_under_shared_canonical_family():
    mapping = build_verification_claim_mapping(
        hypothesis="DLPFC is involved in n-back",
        normalized_claim={
            "subject": {
                "kg_id": "region:dlpfc",
                "label": "DLPFC",
                "node_type": "Region",
            },
            "predicate": "supports",
            "object": {
                "kg_id": "task:nback",
                "label": "n-back",
                "node_type": "Task",
            },
        },
        verdict="supports",
    )

    summary = summarize_claim_families(
        [
            {
                "claim_text": "DLPFC supports n-back",
                "claim_type": "verification",
                "claim_polarity": "supports",
                "target_ids": [mapping["canonical_target_id"], "region:dlpfc"],
                "canonical_claim_id": mapping["canonical_claim_id"],
                "canonical_target_id": mapping["canonical_target_id"],
                "source_run_ids": ["run:1"],
            },
            {
                "claim_text": "n-back engages DLPFC",
                "claim_type": "verification",
                "claim_polarity": "supports",
                "target_ids": [mapping["canonical_target_id"], "task:nback"],
                "tags": [
                    f"canonical_claim_id:{mapping['canonical_claim_id']}",
                    f"canonical_target_id:{mapping['canonical_target_id']}",
                ],
                "source_run_ids": ["run:2"],
            },
        ]
    )

    assert summary["n_claim_families"] == 1
    assert summary["n_target_families"] == 1
    dominant_family = summary["dominant_claim_family"]
    assert dominant_family["canonical_claim_id"] == mapping["canonical_claim_id"]
    assert dominant_family["canonical_target_id"] == mapping["canonical_target_id"]
    assert dominant_family["n_cards"] == 2


def test_claim_cards_merge_evidence_and_emit_relation_events(tmp_path):
    store = MemoryStore(run_root=tmp_path)

    first = store.write(
        "claim_memory",
        {
            "source_run_ids": ["run_claim_1"],
            "claim_text": "Amygdala activation increases during the task.",
            "claim_type": "observation",
            "claim_polarity": "supports",
            "target_ids": ["region:amygdala"],
            "supporting_evidence": [
                {
                    "run_id": "run_claim_1",
                    "claim_id": "claim:amygdala:1",
                    "paper_id": "paper:1",
                    "target_id": "region:amygdala",
                    "polarity": "supports",
                    "source_ref": "result.json#/claims/0",
                    "description": "Primary result supports the increase.",
                }
            ],
            "tags": ["amygdala", "task"],
        },
    )
    second = store.write(
        "claim_memory",
        {
            "source_run_ids": ["run_claim_2"],
            "claim_text": "Amygdala activation decreases during the task.",
            "claim_type": "observation",
            "claim_polarity": "refutes",
            "target_ids": ["region:amygdala"],
            "conflicting_evidence": [
                {
                    "run_id": "run_claim_2",
                    "claim_id": "claim:amygdala:2",
                    "paper_id": "paper:2",
                    "target_id": "region:amygdala",
                    "polarity": "refutes",
                    "source_ref": "result.json#/claims/1",
                    "description": "Replication run points the other way.",
                }
            ],
            "tags": ["amygdala", "task"],
        },
    )

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["relation_events"]
    assert any(
        event["relation_type"] == "contradicts" for event in second["relation_events"]
    )

    relation_search = store.search(
        "",
        card_type="claim_relation_event",
        filters={"relation_type": "contradicts"},
        limit=10,
    )
    assert relation_search["ok"] is True
    assert relation_search["cards"]


def test_distill_run_records_extracts_episodic_and_claim_cards(tmp_path):
    run_dir = tmp_path / "runs" / "run_distill_1"
    _write_json(
        run_dir / "run.json",
        {
            "run_id": "run_distill_1",
            "created_at": "2026-04-04T00:00:00Z",
            "status": "succeeded",
            "dry_run": False,
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_id": "claim_extraction",
                    "params": {"dataset_ref": "HCP"},
                    "status": "succeeded",
                    "result_path": "outputs/claims.json",
                }
            ],
        },
    )
    _write_json(
        run_dir / "provenance.json",
        {
            "run_id": "run_distill_1",
            "route": "tool_execute",
            "request": {"dataset_ref": "HCP", "modality": "fMRI-task"},
        },
    )
    _write_json(
        run_dir / "session_snapshot.json",
        {
            "session_id": "session-1",
            "goal": "Extract explicit amygdala claims",
            "done": ["persisted claim extraction output"],
            "open": ["review contradicting replication"],
            "next_command": "compare the conflicting claim family",
        },
    )
    _write_json(
        run_dir / "outputs" / "claims.json",
        [
            {
                "run": {"run_id": "gabriel-run-1"},
                "paper": {"id": "paper:alpha"},
                "target": {"id": "region:amygdala", "type": "Region"},
                "mapping": {"canonical_id": "region:amygdala"},
                "claim": {
                    "id": "claim:alpha",
                    "text": "Amygdala activation increases during reward anticipation.",
                    "polarity": "supports",
                    "claim_strength": 0.9,
                    "kind": "observation",
                },
                "evidence": {
                    "quote": "Amygdala activation increases...",
                    "section": "title",
                },
                "variables": {"evidence_quality_score": 0.8},
            }
        ],
    )

    distilled = distill_run_records("run_distill_1", run_dir=run_dir)
    assert distilled.episodic_card is not None
    assert (
        distilled.episodic_card.task_description == "Extract explicit amygdala claims"
    )
    assert distilled.claim_cards
    assert distilled.claim_cards[0].claim_text.startswith(
        "Amygdala activation increases"
    )
    assert distilled.claim_cards[0].supporting_evidence
    assert distilled.claim_cards[0].stable_key.startswith(
        "claim_memory:canonical_claim:"
    )


def test_distill_run_records_enriches_episodic_card_from_failed_step_log(tmp_path):
    run_dir = tmp_path / "runs" / "run_distill_failed_step_log"
    _write_json(
        run_dir / "run.json",
        {
            "run_id": "run_distill_failed_step_log",
            "created_at": "2026-04-04T00:00:00Z",
            "status": "failed",
            "dry_run": False,
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_id": "pipeline.search",
                    "status": "failed",
                }
            ],
        },
    )
    _write_json(
        run_dir / "provenance.json",
        {
            "run_id": "run_distill_failed_step_log",
            "route": "tool_execute",
            "request": {"tool_id": "pipeline.search"},
        },
    )
    _write_json(
        run_dir / "observation.json",
        {"artifacts": [], "violations": [], "run_card": {"tools": []}},
    )
    _write_json(run_dir / "analysis_bundle.json", {"schema_version": "analysis-bundle-v1"})
    _write_json(
        run_dir / "logs" / "step-01-s1.json",
        {
            "status": "failed",
            "error": "File or directory not found: /tmp/f.npy",
            "metadata": {
                "tool_name": "pipeline.search",
                "error_type": "FileNotFoundError",
                "error_category": "filesystem",
            },
            "data": {"policy_issues": ["missing input file"]},
        },
    )

    distilled = distill_run_records(
        "run_distill_failed_step_log",
        run_dir=run_dir,
    )

    assert distilled.episodic_card is not None
    card = distilled.episodic_card
    assert card.failure_mode == (
        "pipeline.search failed [FileNotFoundError/filesystem]: "
        "File or directory not found: /tmp/f.npy"
    )
    assert any("pipeline.search failed" in item for item in card.what_failed)
    assert card.quality_indicators["step_log_count"] == 1
    assert card.quality_indicators["failed_log_count"] == 1
    assert "logs/step-01-s1.json" in card.provenance_refs


def test_distill_run_records_uses_success_step_log_for_output_summary(tmp_path):
    run_dir = tmp_path / "runs" / "run_distill_success_step_log"
    _write_json(
        run_dir / "run.json",
        {
            "run_id": "run_distill_success_step_log",
            "created_at": "2026-04-04T00:00:00Z",
            "status": "succeeded",
            "dry_run": False,
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_id": "task_to_concept_mapping",
                    "status": "succeeded",
                }
            ],
        },
    )
    _write_json(
        run_dir / "provenance.json",
        {
            "run_id": "run_distill_success_step_log",
            "route": "tool_execute",
            "request": {"tool_id": "task_to_concept_mapping"},
        },
    )
    _write_json(
        run_dir / "observation.json",
        {"artifacts": [], "violations": [], "run_card": {"tools": []}},
    )
    _write_json(run_dir / "analysis_bundle.json", {"schema_version": "analysis-bundle-v1"})
    _write_json(
        run_dir / "logs" / "step-01-s1.json",
        {
            "status": "success",
            "metadata": {"tool": "task_to_concept_mapping"},
            "data": {
                "task_name": "Monetary Incentive Delay",
                "matched_task": "monetary incentive delay",
                "concepts": ["reward anticipation", "salience"],
            },
        },
    )

    distilled = distill_run_records(
        "run_distill_success_step_log",
        run_dir=run_dir,
    )

    assert distilled.episodic_card is not None
    card = distilled.episodic_card
    assert card.output_summary == (
        "task_to_concept_mapping succeeded "
        "(task_name=Monetary Incentive Delay; matched_task=monetary incentive delay; "
        "concepts=2 items)."
    )
    assert card.what_worked[0] == card.output_summary
    assert card.quality_indicators["successful_log_count"] == 1


def test_distill_run_records_surfaces_execution_and_manifest_metadata(tmp_path):
    run_dir = tmp_path / "runs" / "run_distill_execution_manifest"
    _write_json(
        run_dir / "run.json",
        {
            "run_id": "run_distill_execution_manifest",
            "created_at": "2026-04-04T00:00:00Z",
            "status": "succeeded",
            "dry_run": False,
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_id": "query_neuromaps",
                    "status": "succeeded",
                }
            ],
        },
    )
    _write_json(
        run_dir / "provenance.json",
        {
            "run_id": "run_distill_execution_manifest",
            "route": "tool_execute",
            "request": {"tool_id": "query_neuromaps"},
        },
    )
    _write_json(
        run_dir / "observation.json",
        {
            "artifacts": [],
            "violations": [],
            "run_card": {
                "tools": [],
                "execution": {
                    "provider": "local",
                    "model": "gpt-5.4",
                    "selected_tool": "query_neuromaps",
                    "tool_mode": "mcp",
                    "transport": "streamable-http",
                    "dry_run": False,
                },
            },
        },
    )
    _write_json(
        run_dir / "analysis_bundle.json",
        {
            "schema_version": "analysis-bundle-v1",
            "file_manifest": [
                {
                    "role": "observation",
                    "path": "observation.json",
                    "checksum_status": "ok",
                },
                {
                    "role": "result",
                    "path": "logs/step-01-s1.json",
                    "checksum_status": "ok",
                },
            ],
        },
    )
    _write_json(
        run_dir / "execution_manifest.json",
        {
            "steps": [
                {"step_id": "step-1", "tool_id": "query_neuromaps"},
                {"step_id": "step-2", "tool_id": "fetch_atlas"},
            ]
        },
    )

    distilled = distill_run_records(
        "run_distill_execution_manifest",
        run_dir=run_dir,
    )

    assert distilled.episodic_card is not None
    card = distilled.episodic_card
    assert card.key_parameters["execution"] == {
        "provider": "local",
        "model": "gpt-5.4",
        "selected_tool": "query_neuromaps",
        "tool_mode": "mcp",
        "transport": "streamable-http",
        "dry_run": False,
    }
    assert card.quality_indicators["file_manifest_count"] == 2
    assert card.quality_indicators["verified_checksum_count"] == 2
    assert card.quality_indicators["execution_manifest_step_count"] == 2
    assert card.quality_indicators["selected_tool"] == "query_neuromaps"
    assert card.quality_indicators["execution_provider"] == "local"
    assert "execution_manifest.json" in card.provenance_refs
    assert any("Captured 2 manifest entries with 2 verified checksums." in item for item in card.what_worked)


def test_distill_run_records_surfaces_trajectory_and_research_notes(tmp_path):
    run_dir = tmp_path / "runs" / "run_distill_research_notes"
    _write_json(
        run_dir / "run.json",
        {
            "run_id": "run_distill_research_notes",
            "created_at": "2026-04-04T00:00:00Z",
            "status": "succeeded",
            "dry_run": False,
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_id": "query_neuromaps",
                    "status": "succeeded",
                }
            ],
        },
    )
    _write_json(
        run_dir / "provenance.json",
        {
            "run_id": "run_distill_research_notes",
            "route": "tool_execute",
            "request": {"tool_id": "query_neuromaps"},
        },
    )
    _write_json(
        run_dir / "observation.json",
        {"artifacts": [], "violations": [], "run_card": {"tools": []}},
    )
    _write_json(run_dir / "analysis_bundle.json", {"schema_version": "analysis-bundle-v1"})
    _write_json(
        run_dir / "trajectory.json",
        {
            "steps": [
                {"step_id": 1, "source": "user", "message": "Find reusable prod signals"},
                {
                    "step_id": 2,
                    "source": "assistant",
                    "message": "I will inspect generic execution bundles.",
                },
            ]
        },
    )
    _write_json(
        run_dir / "session_snapshot.json",
        {
            "session_id": "sess-research-notes",
            "tags": ["memory-audit", "prod-runs"],
            "source_client": "codex",
        },
    )
    _write_jsonl(
        run_dir / "research_events.jsonl",
        [
            {
                "kind": "start",
                "content": "Audit generic prod runs for reusable memory signals.",
            },
            {
                "kind": "note",
                "content": (
                    "Found reusable tool-result summaries in generic execution bundles."
                ),
                "tags": ["tool-result", "generic-runs"],
            },
            {
                "kind": "note",
                "content": "Trajectory captured both user and assistant turns.",
                "tags": ["trajectory", "generic-runs"],
            },
        ],
    )

    distilled = distill_run_records(
        "run_distill_research_notes",
        run_dir=run_dir,
    )

    assert distilled.episodic_card is not None
    card = distilled.episodic_card
    assert (
        card.task_description == "Audit generic prod runs for reusable memory signals."
    )
    assert (
        card.output_summary
        == "Found reusable tool-result summaries in generic execution bundles."
    )
    assert card.key_parameters["trajectory"] == {
        "step_count": 2,
        "sources": ["user", "assistant"],
    }
    assert card.quality_indicators["trajectory_step_count"] == 2
    assert card.quality_indicators["research_note_count"] == 2
    assert card.what_worked[:2] == [
        "Found reusable tool-result summaries in generic execution bundles.",
        "Trajectory captured both user and assistant turns.",
    ]
    assert "memory-audit" in card.tags
    assert "prod-runs" in card.tags
    assert "source_client:codex" in card.tags
    assert "tool-result" in card.tags
    assert "trajectory" in card.tags
    assert "trajectory.json" in card.provenance_refs
    assert "research_events.jsonl" in card.provenance_refs


def test_distill_run_records_extracts_claim_from_candidate_card_normalized_claim(
    tmp_path,
):
    run_dir = tmp_path / "runs" / "run_distill_candidate_normalized"
    normalized_claim = {
        "subject": {
            "kg_id": "region:dlpfc",
            "label": "DLPFC",
            "node_type": "Region",
        },
        "predicate": "supports",
        "object": {
            "kg_id": "task:nback",
            "label": "n-back",
            "node_type": "Task",
        },
    }
    _write_json(
        run_dir / "run.json",
        {
            "run_id": "run_distill_candidate_normalized",
            "created_at": "2026-04-04T00:00:00Z",
            "status": "succeeded",
            "dry_run": False,
            "steps": [
                {
                    "step_id": "candidate-cards",
                    "tool_id": "kg_hypothesis_candidate_cards",
                    "status": "succeeded",
                    "result_path": "artifacts/candidate_cards_result.json",
                }
            ],
        },
    )
    _write_json(
        run_dir / "artifacts" / "candidate_cards_result.json",
        {
            "candidate_cards": [
                {
                    "card_id": "cand_norm_01",
                    "hypothesis": "DLPFC may support n-back performance.",
                    "testable_hypothesis": "DLPFC supports n-back performance.",
                    "evidence_summary": "Independent evidence supports the mapping.",
                    "kg_verification": {
                        "verdict": "supported",
                        "normalized_claim": normalized_claim,
                    },
                    "provenance": {
                        "avg_confidence": 0.82,
                        "avg_evidence_quality": 0.74,
                        "supporting_paper_ids": ["paper:nback:1"],
                    },
                }
            ]
        },
    )

    distilled = distill_run_records(
        "run_distill_candidate_normalized",
        run_dir=run_dir,
    )

    mapping = build_verification_claim_mapping(
        hypothesis="DLPFC supports n-back performance.",
        normalized_claim=normalized_claim,
        verdict="supported",
    )

    assert len(distilled.claim_cards) == 1
    claim = distilled.claim_cards[0]
    assert claim.claim_text == "DLPFC supports n-back performance."
    assert claim.claim_type == "verification"
    assert claim.claim_polarity == "supports"
    assert claim.target_ids == mapping["target_ids"]
    assert f"canonical_claim_id:{mapping['canonical_claim_id']}" in claim.tags
    assert claim.supporting_evidence
    assert claim.supporting_evidence[0].paper_id == "paper:nback:1"
    assert claim.supporting_evidence[0].description == (
        "Independent evidence supports the mapping."
    )


def test_distill_run_records_extracts_claim_from_candidate_card_provenance_ids(
    tmp_path,
):
    run_dir = tmp_path / "runs" / "run_distill_candidate_provenance_ids"
    _write_json(
        run_dir / "run.json",
        {
            "run_id": "run_distill_candidate_provenance_ids",
            "created_at": "2026-04-04T00:00:00Z",
            "status": "succeeded",
            "dry_run": False,
            "steps": [
                {
                    "step_id": "candidate-cards",
                    "tool_id": "kg_hypothesis_candidate_cards",
                    "status": "succeeded",
                    "result_path": "artifacts/candidate_cards_result.json",
                }
            ],
        },
    )
    _write_json(
        run_dir / "artifacts" / "candidate_cards_result.json",
        {
            "candidate_cards": [
                {
                    "card_id": "cand_prop_01",
                    "hypothesis": "Posterior cingulate may modulate episodic retrieval.",
                    "testable_hypothesis": (
                        "Posterior cingulate modulates episodic retrieval."
                    ),
                    "minimal_discriminating_test": (
                        "Contrast retrieval against a matched perceptual control task."
                    ),
                    "provenance": {
                        "seed_kg_id": "region:pcc",
                        "candidate_kg_id": "task:episodic_retrieval",
                        "relation_hint": "modulates",
                        "avg_confidence": 0.56,
                        "avg_evidence_quality": 0.41,
                    },
                }
            ]
        },
    )

    distilled = distill_run_records(
        "run_distill_candidate_provenance_ids",
        run_dir=run_dir,
    )

    assert len(distilled.claim_cards) == 1
    claim = distilled.claim_cards[0]
    assert claim.claim_text == "Posterior cingulate modulates episodic retrieval."
    assert claim.claim_type == "candidate_hypothesis"
    assert claim.claim_polarity is None
    assert claim.target_ids == [
        "region:pcc|modulates|task:episodic_retrieval",
        "region:pcc",
        "task:episodic_retrieval",
    ]
    assert "candidate_card" in claim.analytic_conditions
    assert claim.supporting_evidence == []
    assert claim.conflicting_evidence == []


def test_distill_run_records_extracts_claim_from_candidate_card_provenance_labels(
    tmp_path,
):
    run_dir = tmp_path / "runs" / "run_distill_candidate_provenance_labels"
    _write_json(
        run_dir / "run.json",
        {
            "run_id": "run_distill_candidate_provenance_labels",
            "created_at": "2026-04-04T00:00:00Z",
            "status": "succeeded",
            "dry_run": False,
            "steps": [
                {
                    "step_id": "hot-load",
                    "tool_id": "hypothesis_hot_load_research",
                    "status": "succeeded",
                    "result_path": "artifacts/hypothesis_hot_load.result.json",
                }
            ],
        },
    )
    _write_json(
        run_dir / "artifacts" / "hypothesis_hot_load.result.json",
        {
            "candidate_cards": [
                {
                    "card_id": "cand_label_01",
                    "hypothesis": (
                        "dmPFC may coordinate social inference under uncertainty."
                    ),
                    "title": "social inference bridge",
                    "provenance": {
                        "top_subjects": [
                            {
                                "kg_id": "region:dmpfc",
                                "label": "dmPFC",
                                "node_type": "Region",
                            }
                        ],
                        "object_label": "social inference",
                        "top_predicates": ["engages"],
                        "avg_confidence": 0.63,
                        "avg_evidence_quality": 0.52,
                    },
                }
            ]
        },
    )

    distilled = distill_run_records(
        "run_distill_candidate_provenance_labels",
        run_dir=run_dir,
    )

    assert len(distilled.claim_cards) == 1
    claim = distilled.claim_cards[0]
    assert claim.claim_text == "dmPFC may coordinate social inference under uncertainty."
    assert claim.claim_type == "candidate_hypothesis"
    assert claim.target_ids[0] == "region:dmpfc|engages|candidate_object:social_inference"
    assert "region:dmpfc" in claim.target_ids
    assert "candidate_object:social_inference" in claim.target_ids
    assert "predicate:engages" in claim.tags


def test_distill_run_records_keeps_insufficient_evidence_candidate_neutral(tmp_path):
    run_dir = tmp_path / "runs" / "run_distill_candidate_insufficient"
    _write_json(
        run_dir / "run.json",
        {
            "run_id": "run_distill_candidate_insufficient",
            "created_at": "2026-04-04T00:00:00Z",
            "status": "succeeded",
            "dry_run": False,
            "steps": [
                {
                    "step_id": "hot-load",
                    "tool_id": "hypothesis_hot_load_research",
                    "status": "succeeded",
                    "result_path": "artifacts/hypothesis_hot_load.result.json",
                }
            ],
        },
    )
    _write_json(
        run_dir / "artifacts" / "hypothesis_hot_load.result.json",
        {
            "candidate_cards": [
                {
                    "card_id": "cand_insufficient_01",
                    "hypothesis": (
                        "Cognitive control may explain transfer outside the source task."
                    ),
                    "kg_verification": {
                        "verdict": "insufficient_evidence",
                        "normalized_claim": {
                            "subject": {
                                "kg_id": "concept:cognitive_control",
                                "label": "cognitive control",
                                "node_type": "Concept",
                            },
                            "predicate": "related_to",
                            "object": {
                                "kg_id": "task:transfer",
                                "label": "transfer",
                                "node_type": "Task",
                            },
                        },
                    },
                    "provenance": {
                        "avg_confidence": 0.31,
                        "avg_evidence_quality": 0.28,
                    },
                }
            ]
        },
    )

    distilled = distill_run_records(
        "run_distill_candidate_insufficient",
        run_dir=run_dir,
    )

    assert len(distilled.claim_cards) == 1
    claim = distilled.claim_cards[0]
    assert claim.claim_polarity == "insufficient_evidence"
    assert claim.supporting_evidence == []
    assert claim.conflicting_evidence == []


def test_distill_run_records_applies_claim_update_as_conflicting_evidence(tmp_path):
    run_dir = tmp_path / "runs" / "run_distill_claim_update_weaken"
    normalized_claim = {
        "subject": {
            "kg_id": "region:dlpfc",
            "label": "DLPFC",
            "node_type": "Region",
        },
        "predicate": "supports",
        "object": {
            "kg_id": "task:nback",
            "label": "n-back",
            "node_type": "Task",
        },
    }
    mapping = build_verification_claim_mapping(
        hypothesis="DLPFC supports n-back performance.",
        normalized_claim=normalized_claim,
        verdict="supported",
    )
    _write_json(
        run_dir / "run.json",
        {
            "run_id": "run_distill_claim_update_weaken",
            "created_at": "2026-04-04T00:00:00Z",
            "status": "succeeded",
            "dry_run": False,
            "steps": [
                {
                    "step_id": "candidate-cards",
                    "tool_id": "kg_hypothesis_candidate_cards",
                    "status": "succeeded",
                    "result_path": "artifacts/candidate_cards_result.json",
                }
            ],
        },
    )
    _write_json(
        run_dir / "artifacts" / "candidate_cards_result.json",
        {
            "candidate_cards": [
                {
                    "card_id": "cand_norm_01",
                    "hypothesis": "DLPFC may support n-back performance.",
                    "testable_hypothesis": "DLPFC supports n-back performance.",
                    "evidence_summary": "Independent evidence supports the mapping.",
                    "kg_verification": {
                        "verdict": "supported",
                        "normalized_claim": normalized_claim,
                    },
                    "provenance": {
                        "avg_confidence": 0.82,
                        "avg_evidence_quality": 0.74,
                        "supporting_paper_ids": ["paper:nback:1"],
                    },
                }
            ]
        },
    )
    _write_json(
        run_dir / "claim_update.json",
        [
            {
                "schema_version": "claim-update-v1",
                "claim_id": "cand_norm_01",
                "canonical_claim_id": mapping["canonical_claim_id"],
                "action": "weaken",
                "note": "Scientific review flagged this claim as indirect evidence only.",
                "updated_at": "2026-04-10T19:00:00Z",
            }
        ],
    )

    distilled = distill_run_records(
        "run_distill_claim_update_weaken",
        run_dir=run_dir,
    )

    assert len(distilled.claim_cards) == 1
    claim = distilled.claim_cards[0]
    assert "claim_update:weaken" in claim.analytic_conditions
    assert claim.conflicting_evidence
    assert claim.conflicting_evidence[0].source_ref == "claim_update.json[0]"
    assert claim.conflicting_evidence[0].claim_id == mapping["canonical_claim_id"]
    assert claim.extra["claim_updates"][0]["action"] == "weaken"
    assert claim.extra["claim_updates"][0]["source_ref"] == "claim_update.json[0]"
    assert claim.extra["claim_updates"][0]["applied_role"] == "direct"
    assert (
        claim.extra["claim_updates"][0]["update"]["note"]
        == "Scientific review flagged this claim as indirect evidence only."
    )


def test_distill_run_records_marks_superseded_claim_from_claim_update(tmp_path):
    run_dir = tmp_path / "runs" / "run_distill_claim_update_supersede"
    _write_json(
        run_dir / "run.json",
        {
            "run_id": "run_distill_claim_update_supersede",
            "created_at": "2026-04-04T00:00:00Z",
            "status": "succeeded",
            "dry_run": False,
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_id": "claim_extraction",
                    "status": "succeeded",
                    "result_path": "outputs/claims.json",
                }
            ],
        },
    )
    _write_json(
        run_dir / "outputs" / "claims.json",
        [
            {
                "run": {"run_id": "gabriel-run-old"},
                "target": {"id": "region:amygdala", "type": "Region"},
                "mapping": {"canonical_id": "region:amygdala"},
                "claim": {
                    "id": "claim:old",
                    "text": "Amygdala activation increases during reward anticipation.",
                    "polarity": "supports",
                    "claim_strength": 0.9,
                    "kind": "observation",
                },
                "variables": {"evidence_quality_score": 0.8},
            },
            {
                "run": {"run_id": "gabriel-run-new"},
                "target": {"id": "region:amygdala", "type": "Region"},
                "mapping": {"canonical_id": "region:amygdala"},
                "claim": {
                    "id": "claim:new",
                    "text": "Amygdala activation increases only under reward uncertainty.",
                    "polarity": "supports",
                    "claim_strength": 0.7,
                    "kind": "observation",
                },
                "variables": {"evidence_quality_score": 0.75},
            },
        ],
    )
    _write_json(
        run_dir / "claim_update.json",
        [
            {
                "schema_version": "claim-update-v1",
                "claim_id": "claim:new",
                "action": "supersede",
                "supersedes_claim_id": "claim:old",
                "note": "The broader legacy claim is superseded by the more specific uncertainty-conditioned version.",
                "updated_at": "2026-04-10T19:00:00Z",
            }
        ],
    )

    distilled = distill_run_records(
        "run_distill_claim_update_supersede",
        run_dir=run_dir,
    )

    old_claim = next(
        claim
        for claim in distilled.claim_cards
        if any(evidence.claim_id == "claim:old" for evidence in claim.supporting_evidence)
    )
    new_claim = next(
        claim
        for claim in distilled.claim_cards
        if any(evidence.claim_id == "claim:new" for evidence in claim.supporting_evidence)
    )
    assert old_claim.status == "superseded"
    assert old_claim.superseded_by == "claim:new"
    assert old_claim.extra["claim_updates"][0]["action"] == "supersede"
    assert old_claim.extra["claim_updates"][0]["applied_role"] == "superseded_target"
    assert new_claim.related_claims
    assert new_claim.related_claims[0].relation == "supersedes"
    assert new_claim.extra["claim_updates"][0]["action"] == "supersede"
    assert new_claim.extra["claim_updates"][0]["applied_role"] == "direct"


def test_memory_store_preserves_superseded_claim_status_on_merge(tmp_path):
    store = MemoryStore(run_root=tmp_path)

    first = store.write(
        "claim_memory",
        {
            "stable_key": "claim_memory:claim:old",
            "source_run_ids": ["run_claim_1"],
            "claim_text": "Amygdala activation increases during reward anticipation.",
            "claim_type": "observation",
            "claim_polarity": "supports",
            "target_ids": ["region:amygdala"],
            "status": "active",
        },
    )
    assert first["ok"] is True

    second = store.write(
        "claim_memory",
        {
            "stable_key": "claim_memory:claim:old",
            "source_run_ids": ["run_claim_2"],
            "claim_text": "Amygdala activation increases during reward anticipation.",
            "claim_type": "observation",
            "claim_polarity": "supports",
            "target_ids": ["region:amygdala"],
            "status": "superseded",
            "superseded_by": "claim:new",
            "extra": {
                "claim_updates": [
                    {
                        "action": "supersede",
                        "run_id": "run_claim_2",
                        "source_ref": "claim_update.json[0]",
                        "applied_role": "superseded_target",
                        "update": {
                            "action": "supersede",
                            "claim_id": "claim:new",
                            "supersedes_claim_id": "claim:old",
                        },
                    }
                ]
            },
        },
    )
    assert second["ok"] is True

    get_resp = store.get(first["card_id"])
    assert get_resp["ok"] is True
    assert get_resp["card"]["status"] == "superseded"
    assert get_resp["card"]["superseded_by"] == "claim:new"
    assert get_resp["card"]["extra"]["claim_updates"][0]["action"] == "supersede"
    assert (
        get_resp["card"]["extra"]["claim_updates"][0]["applied_role"]
        == "superseded_target"
    )


def test_persist_mcp_run_bundle_writes_memory_cards(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.mcp import runstore

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "_run_roots_for_read", lambda: [tmp_path])
    srv._ensure_dirs()

    run_dir = tmp_path / "runs" / "run_hook_1"
    _write_json(
        run_dir / "run.json",
        {
            "run_id": "run_hook_1",
            "created_at": "2026-04-04T00:00:00Z",
            "status": "succeeded",
            "dry_run": False,
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_id": "claim_extraction",
                    "params": {},
                    "status": "succeeded",
                    "result_path": "outputs/claims.json",
                }
            ],
        },
    )
    _write_json(
        run_dir / "outputs" / "claims.json",
        [
            {
                "claim_id": "claim:hook:1",
                "claim_text": "Default mode network connectivity decreases with age.",
                "target_id": "concept:default_mode_network",
                "target_type": "Concept",
                "polarity": "supports",
                "paper_id": "paper:hook",
                "evidence_quality_score": 0.6,
            }
        ],
    )

    srv._persist_mcp_run_bundle("run_hook_1", run_dir=run_dir)

    search_resp = srv.memory_search(
        query="default mode network age",
        card_type="claim_memory",
        filters={"target_id": "concept:default_mode_network"},
        limit=5,
    )
    assert search_resp["ok"] is True
    assert search_resp["cards"]


def test_memory_tools_surface_claim_update_summary_and_filters(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.mcp import runstore

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)

    store = MemoryStore(run_root=tmp_path)
    write_resp = store.write(
        "claim_memory",
        {
            "stable_key": "claim_memory:claim:tool-surface",
            "source_run_ids": ["run_claim_tool_surface"],
            "claim_text": "DLPFC support for n-back is weaker than initially stated.",
            "claim_type": "verification",
            "claim_polarity": "supports",
            "target_ids": ["region:dlpfc|supports|task:nback"],
            "extra": {
                "claim_updates": [
                    {
                        "action": "weaken",
                        "claim_id": "claim:tool-surface",
                        "canonical_claim_id": "canonical_claim:dlpfc_nback",
                        "updated_at": "2026-04-10T19:00:00Z",
                        "source_ref": "claim_update.json[0]",
                        "applied_role": "direct",
                    }
                ]
            },
        },
    )
    assert write_resp["ok"] is True

    search_resp = srv.memory_search(
        query="dlpfc n-back weaker",
        card_type="claim_memory",
        filters={"claim_update_action": "weaken"},
        limit=5,
    )
    assert search_resp["ok"] is True
    assert search_resp["count"] == 1
    card = search_resp["cards"][0]
    assert card["claim_update_count"] == 1
    assert card["claim_update_actions"] == ["weaken"]
    assert card["claim_update_roles"] == ["direct"]
    assert card["latest_claim_update_at"] == "2026-04-10T19:00:00Z"

    get_resp = srv.memory_get(write_resp["card_id"])
    assert get_resp["ok"] is True
    assert get_resp["card"]["claim_update_actions"] == ["weaken"]
    assert get_resp["card"]["extra"]["claim_updates"][0]["source_ref"] == "claim_update.json[0]"
