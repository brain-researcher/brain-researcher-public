from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from brain_researcher.services.neurokg.etl.loaders.gabriel_loader import (
    GabrielMeasurementLoader,
)


class MockDB:
    def __init__(self) -> None:
        self._node_store: dict[str, tuple[str, dict]] = {}
        self.nodes: list[tuple[str, str, dict]] = []
        self.relationships: list[tuple[str, str, str, dict]] = []

    def create_node(self, labels, properties=None, node_id=None, auto_commit=True):
        del auto_commit
        label = labels[0] if isinstance(labels, list) else labels
        node_id = node_id or properties.get("id") or f"{label}:{len(self.nodes) + 1}"
        props = dict(properties or {})
        props.setdefault("id", node_id)
        self._node_store[node_id] = (label, props)
        self.nodes = [
            (stored_label, stored_id, dict(stored_props))
            for stored_id, (stored_label, stored_props) in self._node_store.items()
        ]
        return node_id

    def create_relationship(
        self,
        source,
        target,
        rel_type,
        properties=None,
        auto_commit=True,
    ):
        del auto_commit
        if source not in self._node_store or target not in self._node_store:
            return False
        self.relationships.append((source, target, rel_type, dict(properties or {})))
        return True

    def find_nodes(self, labels=None, properties=None):
        if isinstance(labels, str):
            labels = [labels]
        filters = dict(properties or {})
        matches: list[tuple[str, dict]] = []
        for node_id, (label, props) in self._node_store.items():
            if labels and label not in labels:
                continue
            if any(props.get(key) != value for key, value in filters.items()):
                continue
            matches.append((node_id, dict(props)))
        return matches

    def execute_query(self, query: str, params=None):
        query_l = str(query).lower()
        params = dict(params or {})

        if "publication" in query_l and "pmid" in params:
            lookup_pmid = str(params.get("pmid") or "").strip()
            if not lookup_pmid:
                return []
            rows = []
            for node_id, (label, props) in self._node_store.items():
                if label != "Publication":
                    continue
                pmid = str(props.get("pmid") or "").strip()
                if pmid == lookup_pmid:
                    rows.append({"id": node_id})
            return rows

        if "publication" in query_l and "doi" in params:
            lookup_doi = str(params.get("doi") or "").strip().lower()
            if not lookup_doi:
                return []
            rows = []
            for node_id, (label, props) in self._node_store.items():
                if label != "Publication":
                    continue
                doi = str(props.get("doi") or "").strip().lower()
                if doi == lookup_doi:
                    rows.append({"id": node_id})
            return rows

        lookup_name = str(params.get("name") or "").strip().lower()
        if not lookup_name:
            return []
        rows = []
        for node_id, (label, props) in self._node_store.items():
            if label != "Region":
                continue
            name = str(props.get("name") or "").strip().lower()
            if name != lookup_name:
                continue
            rows.append({"id": node_id, "source": props.get("source")})
        return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _accepted_record(
    *,
    run_id: str,
    paper_id: str,
    title: str,
    target_id: str = "concept:working_memory",
    target_label: str = "Working memory",
) -> dict:
    return {
        "run": {
            "run_id": run_id,
            "tool": "extract",
            "model": "gpt-5",
            "prompt_hash": "phash",
            "template_hash": "thash",
            "raw_response_path": f"/tmp/{run_id}.jsonl",
            "loader_version": "v1",
            "timestamp": "2026-02-24T00:00:00Z",
        },
        "paper": {
            "id": paper_id,
            "title": title,
            "year": 2024,
        },
        "target": {
            "type": "Concept",
            "id": target_id,
            "label": target_label,
        },
        "claim": {
            "text": f"{target_label} increases dlPFC activity",
            "polarity": "supports",
        },
        "evidence": {
            "quote": "We observed significant dlPFC activation during the n-back task.",
            "section": "results",
            "char_start": 10,
            "char_end": 80,
            "has_statistical_detail": True,
            "locatable": True,
            "direct_quote": True,
        },
        "signals": {
            "mention_frequency": 5,
            "max_frequency": 5,
            "title_hit": True,
            "abstract_hit": True,
            "semantic_similarity": 0.95,
            "ontology_match": True,
            "context_overlap": 0.8,
            "modal_density": 0.1,
            "statistical_density": 0.9,
            "assertive_verb_ratio": 0.8,
            "preregistration": True,
            "threshold_correction_reported": True,
            "sample_size_adequacy": 0.9,
            "roi_definition_clear": True,
            "open_data_or_code": True,
        },
    }


def _rejected_record(*, run_id: str, paper_id: str, title: str) -> dict:
    return {
        "run": {
            "run_id": run_id,
            "tool": "extract",
            "model": "gpt-5",
            "prompt_hash": "phash2",
            "template_hash": "thash2",
            "raw_response_path": f"/tmp/{run_id}.jsonl",
        },
        "paper": {"id": paper_id, "title": title},
        "target": {"type": "Concept", "label": "Executive function"},
        "claim": {"text": "Potential trend", "polarity": "uncertain"},
        "evidence": {"quote": "Possibly related.", "section": "discussion"},
        "signals": {
            "mention_frequency": 1,
            "max_frequency": 5,
            "semantic_similarity": 0.2,
            "ontology_match": False,
            "context_overlap": 0.1,
            "modal_density": 0.9,
            "statistical_density": 0.1,
            "assertive_verb_ratio": 0.1,
            "sample_size_adequacy": 0.1,
        },
    }


def _balanced_only_record(*, run_id: str, paper_id: str, title: str) -> dict:
    """Record tuned to pass balanced gate but fail high_precision gate."""

    return {
        "run": {
            "run_id": run_id,
            "tool": "extract",
            "model": "gpt-5",
            "prompt_hash": "phash-balanced",
            "template_hash": "thash-balanced",
            "raw_response_path": f"/tmp/{run_id}.jsonl",
            "loader_version": "v1",
            "timestamp": "2026-02-24T00:00:00Z",
        },
        "paper": {
            "id": paper_id,
            "title": title,
            "year": 2025,
        },
        "target": {
            "type": "Concept",
            "id": "concept:attention",
            "label": "Attention",
        },
        "claim": {
            "text": "Attention was associated with moderate prefrontal effects.",
            "polarity": "supports",
        },
        "evidence": {
            "quote": "Results suggested moderate attention-related activation.",
            "section": "results",
            "char_start": 10,
            "char_end": 70,
            "has_statistical_detail": False,
            "locatable": True,
            "direct_quote": True,
        },
        "signals": {
            "mention_frequency": 3,
            "max_frequency": 5,
            "title_hit": False,
            "abstract_hit": False,
            "semantic_similarity": 0.75,
            "ontology_match": True,
            "context_overlap": 0.60,
            "modal_density": 0.45,
            "statistical_density": 0.65,
            "assertive_verb_ratio": 0.65,
            "preregistration": False,
            "threshold_correction_reported": True,
            "sample_size_adequacy": 0.20,
            "roi_definition_clear": True,
            "open_data_or_code": False,
        },
    }


def _marginal_only_record(*, run_id: str, paper_id: str, title: str) -> dict:
    """Record tuned to pass balanced_marginal but fail balanced."""

    return {
        "run": {
            "run_id": run_id,
            "tool": "extract",
            "model": "gpt-5",
            "prompt_hash": "phash-marginal",
            "template_hash": "thash-marginal",
            "raw_response_path": f"/tmp/{run_id}.jsonl",
            "loader_version": "v1",
            "timestamp": "2026-02-24T00:00:00Z",
        },
        "paper": {
            "id": paper_id,
            "title": title,
            "year": 2025,
        },
        "target": {
            "type": "Concept",
            "id": "concept:reward_processing",
            "label": "Reward Processing",
        },
        "claim": {
            "text": "Reward processing was moderately associated with activation.",
            "polarity": "supports",
            "claim_strength": 0.52,
        },
        "evidence": {
            "quote": "Results indicated moderate reward-related activation.",
            "section": "results",
            "char_start": 20,
            "char_end": 74,
            "has_statistical_detail": True,
            "locatable": True,
            "direct_quote": True,
            "evidence_quality": "high",
            "evidence_quality_score": 0.70,
        },
        "mapping": {
            "mapping_confidence": 0.80,
            "mapping_type": "exact",
        },
        "signals": {
            "mention_strength": 0.57,
            "mapping_confidence": 0.80,
            "claim_strength": 0.52,
            "method_rigor": 0.365,
        },
    }


def _kg_task_panel_record(
    *,
    run_id: str,
    paper_id: str,
    title: str,
    mapping_confidence: float,
    target_id: str = "task:onvoc:onvoc_9990003",
    target_label: str = "Response Inhibition",
) -> dict:
    """Record tuned for task-panel ingest from KGGEN ONVOC outputs."""

    return {
        "run": {
            "run_id": run_id,
            "tool": "kggen",
            "model": "gemini-2.5-flash",
            "prompt_hash": "phash-task-panel",
            "template_hash": "thash-task-panel",
            "raw_response_path": f"/tmp/{run_id}.jsonl",
            "loader_version": "kggen-adapter/v1",
            "timestamp": "2026-02-25T00:00:00Z",
        },
        "paper": {
            "id": paper_id,
            "title": title,
            "year": 2025,
        },
        "target": {
            "type": "Task",
            "id": target_id,
            "label": target_label,
        },
        "mapping": {
            "canonical_id": target_id,
            "mapping_type": "synonym",
            "mapping_confidence": mapping_confidence,
            "onvoc_id": "ONVOC_9990003",
            "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990003",
        },
        "claim": {
            "text": "Response inhibition engages frontoparietal control.",
            "polarity": "supports",
        },
        "evidence": {
            "quote": "Task-related association was observed.",
            "section": "discussion",
            "char_start": 5,
            "char_end": 41,
            "has_statistical_detail": False,
            "locatable": False,
            "direct_quote": False,
        },
        "signals": {
            "mention_strength": 0.34,
            "mapping_confidence": mapping_confidence,
            "claim_strength": 0.42,
            "method_rigor": 0.12,
            "evidence_quality": "low",
            "evidence_quality_score": 0.30,
        },
    }


def test_gabriel_loader_applies_gate_and_writes_review_queue(tmp_path: Path) -> None:
    input_path = tmp_path / "measurements.jsonl"
    review_queue_path = tmp_path / "review_queue.jsonl"

    accepted = _accepted_record(
        run_id="run-good",
        paper_id="pmid:123",
        title="Working memory study",
    )
    rejected = _rejected_record(
        run_id="run-bad",
        paper_id="pmid:456",
        title="Ambiguous claim",
    )

    _write_jsonl(input_path, [accepted, rejected])

    db = MockDB()
    loader = GabrielMeasurementLoader(
        db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_path),
            "loader_version": "test-loader/v1",
        },
    )

    stats = loader.load(mode="spine")

    assert stats["records_total"] == 2
    assert stats["records_accepted"] == 1
    assert stats["records_rejected"] == 1
    assert stats["review_queue_items"] == 1
    assert stats["nodes_created"] >= 5
    assert stats["relationships_created"] >= 5

    node_labels = {label for label, _, _ in db.nodes}
    assert "MeasurementRun" in node_labels
    assert "Claim" in node_labels
    assert "EvidenceSpan" in node_labels

    rel_types = {rel_type for _, _, rel_type, _ in db.relationships}
    assert "MENTIONS" in rel_types
    assert "REPORTS_CLAIM" in rel_types
    assert "SUPPORTS" in rel_types
    assert "GENERATED" in rel_types

    review_lines = review_queue_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(review_lines) == 1
    queued = json.loads(review_lines[0])
    assert queued["reasons"]
    assert "mapping_confidence_below_threshold" in queued["reasons"]


def test_gabriel_loader_persists_assumptions_and_replication_edges(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "measurements.jsonl"
    review_queue_path = tmp_path / "review_queue.jsonl"

    record = _accepted_record(
        run_id="run-wow",
        paper_id="pmid:999",
        title="Failed replication of a structural prior claim",
    )
    record["claim"].update(
        {
            "kind": "failed_replication",
            "related_claim_id": "claim:prior_structural_prior",
            "relation_mode": "direct",
            "main_assumption_text": "Structural topology is sufficient prior for behavior-level prediction.",
            "assumption_type": "sufficiency",
            "assumption_scope": "systems_neuroscience",
            "defaultness_score": 0.92,
            "challengeability_score": 0.81,
            "assumption_confidence": 0.88,
            "assumption_status": "challenged",
        }
    )
    _write_jsonl(input_path, [record])

    db = MockDB()
    db.create_node(
        "Claim",
        {
            "text": "Structural topology is sufficient prior for behavior-level prediction.",
            "paper_id": "pmid:111",
            "claim_kind": "claim",
            "claim_polarity": "supports",
            "claim_strength": 0.75,
            "method_rigor": 0.80,
            "provenance_completeness": 1.0,
            "source": "gabriel",
        },
        node_id="claim:prior_structural_prior",
    )

    loader = GabrielMeasurementLoader(
        db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_path),
            "loader_version": "test-loader/v1",
        },
    )

    stats = loader.load(mode="spine")

    assert stats["records_total"] == 1
    assert stats["records_accepted"] == 1

    assumption_nodes = [props for label, _, props in db.nodes if label == "Assumption"]
    assert len(assumption_nodes) == 1
    assert (
        assumption_nodes[0]["text"]
        == "Structural topology is sufficient prior for behavior-level prediction."
    )
    assert assumption_nodes[0]["status"] == "challenged"

    claim_nodes = [props for label, _, props in db.nodes if label == "Claim"]
    current_claim = next(
        props for props in claim_nodes if props["paper_id"] == "pmid:999"
    )
    assert current_claim["claim_kind"] == "failed_replication"
    assert current_claim["related_claim_id"] == "claim:prior_structural_prior"
    assert current_claim["main_assumption_text"].startswith("Structural topology")

    rel_types = {rel_type for _, _, rel_type, _ in db.relationships}
    assert "ASSUMES" in rel_types
    assert "CHALLENGES_ASSUMPTION" in rel_types
    assert "FAILED_REPLICATION_OF" in rel_types

    failed_replication_edges = [
        edge for edge in db.relationships if edge[2] == "FAILED_REPLICATION_OF"
    ]
    assert failed_replication_edges
    assert failed_replication_edges[0][1] == "claim:prior_structural_prior"
    assert failed_replication_edges[0][3]["replication_type"] == "direct"


def test_gabriel_loader_supports_input_path_glob_and_per_file_stats(
    tmp_path: Path,
) -> None:
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    review_queue_path = tmp_path / "review_queue.jsonl"

    shard_one = shard_dir / "part-0001.jsonl"
    shard_two = shard_dir / "part-0002.jsonl"
    _write_jsonl(
        shard_one,
        [
            _accepted_record(
                run_id="run-shard-1",
                paper_id="pmid:1001",
                title="Shard one accepted",
            )
        ],
    )
    _write_jsonl(
        shard_two,
        [
            _rejected_record(
                run_id="run-shard-2",
                paper_id="pmid:1002",
                title="Shard two rejected",
            )
        ],
    )

    db = MockDB()
    loader = GabrielMeasurementLoader(
        db,
        config={
            "input_path_glob": str(shard_dir / "part-*.jsonl"),
            "review_queue_path": str(review_queue_path),
            "loader_version": "test-loader/v2",
        },
    )

    stats = loader.load(mode="spine")

    assert stats["files_discovered"] == 2
    assert stats["files_processed"] == 2
    assert stats["files_failed"] == 0
    assert stats["records_total"] == 2
    assert stats["records_accepted"] == 1
    assert stats["records_rejected"] == 1
    assert stats["review_queue_items"] == 1
    assert stats["input_paths"] == [str(shard_one), str(shard_two)]

    per_file = stats["per_file"]
    assert per_file[str(shard_one)]["records_total"] == 1
    assert per_file[str(shard_one)]["records_accepted"] == 1
    assert per_file[str(shard_one)]["records_rejected"] == 0
    assert per_file[str(shard_two)]["records_total"] == 1
    assert per_file[str(shard_two)]["records_accepted"] == 0
    assert per_file[str(shard_two)]["records_rejected"] == 1


def test_gabriel_loader_writes_checkpoint_status_per_shard(tmp_path: Path) -> None:
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    review_queue_path = tmp_path / "review_queue.jsonl"
    checkpoint_path = tmp_path / "gabriel_checkpoint.json"

    shard_one = shard_dir / "part-0001.jsonl"
    shard_two = shard_dir / "part-0002.jsonl"
    _write_jsonl(
        shard_one,
        [
            _accepted_record(
                run_id="run-checkpoint-1",
                paper_id="pmid:2001",
                title="Checkpoint shard one",
            )
        ],
    )
    _write_jsonl(
        shard_two,
        [
            _accepted_record(
                run_id="run-checkpoint-2",
                paper_id="pmid:2002",
                title="Checkpoint shard two",
                target_id="concept:attention",
                target_label="Attention",
            )
        ],
    )

    db = MockDB()
    loader = GabrielMeasurementLoader(
        db,
        config={
            "input_path_glob": str(shard_dir / "part-*.jsonl"),
            "review_queue_path": str(review_queue_path),
            "ingest_checkpoint_path": str(checkpoint_path),
            "quality_profile": "balanced",
        },
    )

    stats = loader.load(mode="spine")

    assert stats["ingest_checkpoint_path"] == str(checkpoint_path)
    assert checkpoint_path.exists()

    checkpoint_payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint_payload["source"] == "gabriel"
    assert checkpoint_payload["mode"] == "spine"
    assert checkpoint_payload["quality_profile"] == "balanced"

    files = checkpoint_payload["files"]
    assert set(files) == {str(shard_one.resolve()), str(shard_two.resolve())}
    for shard in (shard_one, shard_two):
        entry = files[str(shard.resolve())]
        assert entry["status"] == "completed"
        assert entry["input_path"] == str(shard)
        assert entry["started_at"]
        assert entry["finished_at"]
        assert entry["stats"]["records_total"] == 1
        assert entry["stats"]["records_accepted"] == 1


def test_gabriel_loader_emits_heartbeat_logs(tmp_path: Path, caplog) -> None:
    input_path = tmp_path / "heartbeat_record.jsonl"
    review_queue_path = tmp_path / "review_heartbeat.jsonl"
    accepted = _accepted_record(
        run_id="run-heartbeat-1",
        paper_id="pmid:8101",
        title="Heartbeat accepted",
    )
    rejected = _rejected_record(
        run_id="run-heartbeat-2",
        paper_id="pmid:8102",
        title="Heartbeat rejected",
    )
    _write_jsonl(input_path, [accepted, rejected])

    db = MockDB()
    loader = GabrielMeasurementLoader(
        db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_path),
            "quality_profile": "balanced",
            "progress_log_every": 1,
        },
    )

    with caplog.at_level(logging.INFO):
        loader.load(mode="spine")

    heartbeat_logs = [
        record
        for record in caplog.records
        if "event=ingest_heartbeat" in record.getMessage()
    ]
    assert heartbeat_logs


def test_gabriel_loader_emits_stall_warning_for_long_inactivity(
    tmp_path: Path,
    caplog,
) -> None:
    input_path = tmp_path / "stall_record.jsonl"
    review_queue_path = tmp_path / "review_stall.jsonl"
    _write_jsonl(
        input_path,
        [
            _accepted_record(
                run_id="run-stall",
                paper_id="pmid:8201",
                title="Stall warning candidate",
            )
        ],
    )

    db = MockDB()
    loader = GabrielMeasurementLoader(
        db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_path),
            "quality_profile": "balanced",
            "progress_log_every": 100,
            "stall_warn_seconds": 1,
        },
    )
    original_ingest_record = loader._ingest_record

    def _slow_ingest_record(record, variables):
        time.sleep(2.2)
        return original_ingest_record(record, variables)

    loader._ingest_record = _slow_ingest_record  # type: ignore[assignment]

    with caplog.at_level(logging.WARNING):
        loader.load(mode="spine")

    stall_logs = [
        record
        for record in caplog.records
        if "event=ingest_stall_warning" in record.getMessage()
    ]
    assert stall_logs


def test_gabriel_loader_balanced_profile_increases_recall(tmp_path: Path) -> None:
    input_path = tmp_path / "balanced_record.jsonl"
    review_queue_hp = tmp_path / "review_hp.jsonl"
    review_queue_bal = tmp_path / "review_balanced.jsonl"
    candidate = _balanced_only_record(
        run_id="run-balanced-only",
        paper_id="pmid:3001",
        title="Attention effects with moderate confidence",
    )
    _write_jsonl(input_path, [candidate])

    strict_db = MockDB()
    strict_loader = GabrielMeasurementLoader(
        strict_db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_hp),
            "quality_profile": "high_precision",
        },
    )
    strict_stats = strict_loader.load(mode="spine")
    assert strict_stats["records_accepted"] == 0
    assert strict_stats["records_rejected"] == 1

    balanced_db = MockDB()
    balanced_loader = GabrielMeasurementLoader(
        balanced_db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_bal),
            "quality_profile": "balanced",
        },
    )
    balanced_stats = balanced_loader.load(mode="spine")
    assert balanced_stats["records_accepted"] == 1
    assert balanced_stats["records_rejected"] == 0


def test_gabriel_loader_balanced_marginal_profile_accepts_near_threshold_records(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "marginal_record.jsonl"
    review_queue_bal = tmp_path / "review_balanced.jsonl"
    review_queue_marginal = tmp_path / "review_balanced_marginal.jsonl"
    candidate = _marginal_only_record(
        run_id="run-marginal-only",
        paper_id="pmid:3002",
        title="Reward processing with near-threshold support",
    )
    _write_jsonl(input_path, [candidate])

    balanced_db = MockDB()
    balanced_loader = GabrielMeasurementLoader(
        balanced_db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_bal),
            "quality_profile": "balanced",
        },
    )
    balanced_stats = balanced_loader.load(mode="spine")
    assert balanced_stats["records_accepted"] == 0
    assert balanced_stats["records_rejected"] == 1

    marginal_db = MockDB()
    marginal_loader = GabrielMeasurementLoader(
        marginal_db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_marginal),
            "quality_profile": "balanced_marginal",
        },
    )
    marginal_stats = marginal_loader.load(mode="spine")
    assert marginal_stats["records_accepted"] == 1
    assert marginal_stats["records_rejected"] == 0


def test_gabriel_loader_kg_task_panel_profile_accepts_task_panel_candidates(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "kg_task_panel_record.jsonl"
    review_queue_balanced = tmp_path / "review_balanced.jsonl"
    review_queue_task_panel = tmp_path / "review_kg_task_panel.jsonl"
    candidate = _kg_task_panel_record(
        run_id="run-task-panel-accept",
        paper_id="pmid:3101",
        title="Response inhibition task panel candidate",
        mapping_confidence=0.84,
    )
    _write_jsonl(input_path, [candidate])

    balanced_db = MockDB()
    balanced_loader = GabrielMeasurementLoader(
        balanced_db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_balanced),
            "quality_profile": "balanced",
        },
    )
    balanced_stats = balanced_loader.load(mode="spine")
    assert balanced_stats["records_accepted"] == 0
    assert balanced_stats["records_rejected"] == 1

    task_panel_db = MockDB()
    task_panel_loader = GabrielMeasurementLoader(
        task_panel_db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_task_panel),
            "quality_profile": "kg_task_panel",
        },
    )
    task_panel_stats = task_panel_loader.load(mode="spine")
    assert task_panel_stats["quality_profile"] == "kg_task_panel"
    assert task_panel_stats["records_accepted"] == 1
    assert task_panel_stats["records_rejected"] == 0


def test_gabriel_loader_kg_task_panel_profile_rejects_low_mapping_confidence(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "kg_task_panel_low_mapping.jsonl"
    review_queue_path = tmp_path / "review_kg_task_panel_low_mapping.jsonl"
    candidate = _kg_task_panel_record(
        run_id="run-task-panel-reject",
        paper_id="pmid:3102",
        title="Task panel candidate with weak ONVOC mapping",
        mapping_confidence=0.80,
    )
    _write_jsonl(input_path, [candidate])

    db = MockDB()
    loader = GabrielMeasurementLoader(
        db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_path),
            "quality_profile": "kg_task_panel",
        },
    )
    stats = loader.load(mode="spine")

    assert stats["quality_profile"] == "kg_task_panel"
    assert stats["records_accepted"] == 0
    assert stats["records_rejected"] == 1
    assert stats["review_queue_items"] == 1

    review_lines = review_queue_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(review_lines) == 1
    queued = json.loads(review_lines[0])
    assert "mapping_confidence_below_threshold" in queued["reasons"]


def test_gabriel_loader_kg_task_panel_preserves_exact_subfamily_target_id(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "kg_task_panel_exact_subfamily.jsonl"
    review_queue_path = tmp_path / "review_kg_task_panel_exact_subfamily.jsonl"
    candidate = _kg_task_panel_record(
        run_id="run-task-panel-subfamily",
        paper_id="pmid:3103",
        title="Semantic localizer task panel candidate",
        mapping_confidence=0.91,
        target_id="task:subfamily:sf_semantic_processing",
        target_label="Semantics",
    )
    _write_jsonl(input_path, [candidate])

    db = MockDB()
    db.create_node(
        "Task",
        {
            "name": "Semantics",
            "source": "legacy",
        },
        node_id="task:onvoc:onvoc_legacy_semantics",
    )

    loader = GabrielMeasurementLoader(
        db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_path),
            "quality_profile": "kg_task_panel",
        },
    )
    stats = loader.load(mode="spine")

    assert stats["records_accepted"] == 1
    assert "task:subfamily:sf_semantic_processing" in db._node_store
    claim_targets = [
        props.get("target_id")
        for label, _node_id, props in db.nodes
        if label == "Claim"
    ]
    assert claim_targets == ["task:subfamily:sf_semantic_processing"]
    assert not any(
        source == "pmid:3103"
        and target == "task:onvoc:onvoc_legacy_semantics"
        and rel_type == "MENTIONS"
        for source, target, rel_type, _props in db.relationships
    )
    assert any(
        source == "pmid:3103"
        and target == "task:subfamily:sf_semantic_processing"
        and rel_type == "MENTIONS"
        for source, target, rel_type, _props in db.relationships
    )
    assert stats["review_queue_items"] == 0


def test_gabriel_loader_region_upsert_merges_by_unique_name(tmp_path: Path) -> None:
    input_path = tmp_path / "region_record.jsonl"
    review_queue_path = tmp_path / "review_region.jsonl"

    region_record = _accepted_record(
        run_id="run-region-upsert",
        paper_id="pmid:9001",
        title="dlPFC working memory effect",
        target_id="region:dorsolateral_prefrontal_cortex",
        target_label="dorsolateral prefrontal cortex",
    )
    region_record["target"]["type"] = "Region"
    _write_jsonl(input_path, [region_record])

    db = MockDB()
    existing_region_id = "existing-region-id"
    db.create_node(
        "Region",
        {"name": "dorsolateral prefrontal cortex", "atlas": "unknown"},
        node_id=existing_region_id,
    )

    loader = GabrielMeasurementLoader(
        db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_path),
            "quality_profile": "kg_bootstrap",
            "create_missing_targets": True,
        },
    )
    stats = loader.load(mode="spine")

    assert stats["records_accepted"] == 1
    # No duplicate Region node should be created for the same unique name.
    region_nodes = [node for node in db.nodes if node[0] == "Region"]
    assert len(region_nodes) == 1
    assert region_nodes[0][1] == existing_region_id

    mention_edges = [rel for rel in db.relationships if rel[2] == "MENTIONS_REGION"]
    assert len(mention_edges) == 1
    assert mention_edges[0][1] == existing_region_id


def test_gabriel_loader_region_upsert_merges_case_insensitive_name(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "region_case_record.jsonl"
    review_queue_path = tmp_path / "review_region_case.jsonl"

    region_record = _accepted_record(
        run_id="run-region-case-upsert",
        paper_id="pmid:9002",
        title="PFC control effect",
        target_id="region:prefrontal_cortex",
        target_label="prefrontal cortex",
    )
    region_record["target"]["type"] = "Region"
    _write_jsonl(input_path, [region_record])

    db = MockDB()
    existing_region_id = "r_pfc"
    db.create_node(
        "Region",
        {"name": "Prefrontal Cortex", "atlas": "legacy", "source": "curated"},
        node_id=existing_region_id,
    )

    loader = GabrielMeasurementLoader(
        db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_path),
            "quality_profile": "kg_bootstrap",
            "create_missing_targets": True,
        },
    )
    stats = loader.load(mode="spine")

    assert stats["records_accepted"] == 1
    region_nodes = [node for node in db.nodes if node[0] == "Region"]
    assert len(region_nodes) == 1
    assert region_nodes[0][1] == existing_region_id

    mention_edges = [rel for rel in db.relationships if rel[2] == "MENTIONS_REGION"]
    assert len(mention_edges) == 1
    assert mention_edges[0][1] == existing_region_id


def test_gabriel_loader_publication_upsert_reuses_existing_pmid(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "pub_record.jsonl"
    review_queue_path = tmp_path / "review_pub.jsonl"

    record = _accepted_record(
        run_id="run-publication-upsert",
        paper_id="paper:new-id-for-existing-pmid",
        title="Working memory replication",
    )
    record["paper"]["pmid"] = "12345678"
    record["paper"]["doi"] = "10.1234/example-doi"
    _write_jsonl(input_path, [record])

    db = MockDB()
    existing_pub_id = "pub_existing_12345678"
    db.create_node(
        "Publication",
        {"pmid": "12345678", "title": "Existing publication"},
        node_id=existing_pub_id,
    )

    loader = GabrielMeasurementLoader(
        db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_path),
            "quality_profile": "kg_bootstrap",
            "create_missing_targets": True,
        },
    )
    stats = loader.load(mode="spine")

    assert stats["records_accepted"] == 1
    publication_nodes = [node for node in db.nodes if node[0] == "Publication"]
    assert len(publication_nodes) == 1
    assert publication_nodes[0][1] == existing_pub_id

    mention_edges = [rel for rel in db.relationships if rel[2] == "MENTIONS"]
    assert len(mention_edges) == 1
    assert mention_edges[0][0] == existing_pub_id


def test_gabriel_loader_publication_upsert_reuses_existing_numeric_pmid(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "pub_record_numeric_pmid.jsonl"
    review_queue_path = tmp_path / "review_pub_numeric_pmid.jsonl"

    record = _accepted_record(
        run_id="run-publication-upsert-numeric-pmid",
        paper_id="paper:new-id-for-existing-numeric-pmid",
        title="Working memory replication numeric pmid",
    )
    # Incoming record carries PMID as text while existing DB value may be numeric.
    record["paper"]["pmid"] = "12345678"
    _write_jsonl(input_path, [record])

    db = MockDB()
    existing_pub_id = "pub_existing_numeric_12345678"
    db.create_node(
        "Publication",
        {"pmid": 12345678, "title": "Existing publication numeric pmid"},
        node_id=existing_pub_id,
    )

    loader = GabrielMeasurementLoader(
        db,
        config={
            "input_path": str(input_path),
            "review_queue_path": str(review_queue_path),
            "quality_profile": "kg_bootstrap",
            "create_missing_targets": True,
        },
    )
    stats = loader.load(mode="spine")

    assert stats["records_accepted"] == 1
    publication_nodes = [node for node in db.nodes if node[0] == "Publication"]
    assert len(publication_nodes) == 1
    assert publication_nodes[0][1] == existing_pub_id

    mention_edges = [rel for rel in db.relationships if rel[2] == "MENTIONS"]
    assert len(mention_edges) == 1
    assert mention_edges[0][0] == existing_pub_id
