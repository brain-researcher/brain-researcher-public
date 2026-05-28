from __future__ import annotations

import json
from pathlib import Path

from scripts.neurometabench_v1.layer_a_model_adapters import adapt_model_outputs


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_decision_records_jsonl_normalizes_layer_a_prediction(tmp_path: Path) -> None:
    source = tmp_path / "decisions.jsonl"
    output = tmp_path / "predictions.jsonl"
    _write_jsonl(
        source,
        [
            {
                "pmid": "11",
                "decision": "include",
                "reason": "Matches whole-brain fMRI criteria.",
                "evidence_spans": [{"text": "whole-brain fMRI task"}],
                "criterion_hits": [{"criterion_id": "inc_whole_brain"}],
                "confidence": "0.8",
                "system": "source_model",
                "execution_mode": "reasoning_only",
            },
            {
                "study_pmid": "12",
                "decision": "exclude",
                "rationale": "ROI-only analysis.",
                "criterion_ids": ["exc_roi_only"],
                "confidence": 0.2,
                "system": "source_model",
                "execution_mode": "reasoning_only",
            },
        ],
    )

    summary = adapt_model_outputs(
        source,
        output,
        input_format="decision_records_jsonl",
        system="codex_reasoning",
        case_id="neurometabench:123",
        meta_pmid="123",
        candidate_source="mixed_pool",
    )
    rows = _read_jsonl(output)

    assert summary["n_predictions"] == 1
    assert rows[0]["case_id"] == "neurometabench:123"
    assert rows[0]["meta_pmid"] == "123"
    assert rows[0]["system"] == "codex_reasoning"
    assert rows[0]["execution_mode"] == "reasoning_only"
    assert rows[0]["included_pmids"] == ["11"]
    assert rows[0]["predicted_pmids"] == ["11"]
    assert rows[0]["ranked_pmids"] == ["11", "12"]
    assert rows[0]["candidate_source"] == "mixed_pool"
    assert rows[0]["decision_records"][0]["criterion_ids"] == ["inc_whole_brain"]
    assert rows[0]["decision_records"][0]["evidence_spans"] == ["whole-brain fMRI task"]
    assert rows[0]["decision_records"][0]["confidence"] == 0.8
    assert rows[0]["decision_records"][1]["decision"] == "exclude"
    assert rows[0]["provenance"]["adapter"] == "neurometabench_v1_layer_a_model_adapter"
    assert rows[0]["provenance"]["system"] == "codex_reasoning"
    assert rows[0]["provenance"]["input_path"] == str(source)
    assert rows[0]["provenance"]["execution_mode"] == "reasoning_only"
    assert rows[0]["provenance"]["source_systems"] == ["source_model"]


def test_prediction_jsonl_passthrough_adds_adapter_provenance(tmp_path: Path) -> None:
    source = tmp_path / "normalized.jsonl"
    output = tmp_path / "wrapped.jsonl"
    _write_jsonl(
        source,
        [
            {
                "case_id": "neurometabench:456",
                "meta_pmid": "456",
                "system": "source_agent",
                "ranked_pmids": [{"pmid": "21"}, {"pmid": "22"}],
                "predicted_pmids": ["21"],
                "provenance": {"source_artifact": "agent_report"},
            }
        ],
    )

    summary = adapt_model_outputs(
        source,
        output,
        input_format="prediction_jsonl",
        system="claude_coding_agent",
        execution_mode="coding_agent",
        candidate_source="closed_world",
    )
    rows = _read_jsonl(output)

    assert summary["effective_input_format"] == "prediction_jsonl"
    assert rows[0]["system"] == "claude_coding_agent"
    assert rows[0]["included_pmids"] == ["21"]
    assert rows[0]["predicted_pmids"] == ["21"]
    assert rows[0]["ranked_pmids"] == ["21", "22"]
    assert rows[0]["decision_records"] == []
    assert rows[0]["candidate_source"] == "closed_world"
    assert rows[0]["provenance"]["source_artifact"] == "agent_report"
    assert rows[0]["provenance"]["source_systems"] == ["source_agent"]
    assert rows[0]["provenance"]["input_format"] == "prediction_jsonl"
    assert rows[0]["provenance"]["execution_mode"] == "coding_agent"


def test_run_bundle_prefers_first_evaluable_prediction_file(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    predictions = bundle / "predictions.jsonl"
    screening = bundle / "screening_decisions.jsonl"
    output = tmp_path / "bundle_predictions.jsonl"
    _write_jsonl(
        predictions,
        [
            {
                "case_id": "neurometabench:789",
                "meta_pmid": "789",
                "ranked_pmids": ["31", "32"],
                "included_pmids": ["31"],
            }
        ],
    )
    _write_jsonl(screening, [{"pmid": "99", "decision": "include"}])

    summary = adapt_model_outputs(
        bundle,
        output,
        input_format="run_bundle",
        system="gemini_agent",
        execution_mode="coding_agent",
    )
    rows = _read_jsonl(output)

    assert summary["effective_input"] == str(predictions)
    assert summary["effective_input_format"] == "prediction_jsonl"
    assert rows[0]["included_pmids"] == ["31"]
    assert rows[0]["predicted_pmids"] == ["31"]
    assert rows[0]["ranked_pmids"] == ["31", "32"]
    assert rows[0]["provenance"]["input_format"] == "run_bundle"
    assert rows[0]["provenance"]["selected_input_path"] == str(predictions)
    assert rows[0]["provenance"]["selected_input_format"] == "prediction_jsonl"


def test_prediction_jsonl_candidate_pmids_are_ranked_not_included(
    tmp_path: Path,
) -> None:
    source = tmp_path / "candidate_only.jsonl"
    output = tmp_path / "wrapped.jsonl"
    _write_jsonl(
        source,
        [
            {
                "case_id": "neurometabench:999",
                "meta_pmid": "999",
                "candidate_pmids": ["41", "42"],
            }
        ],
    )

    adapt_model_outputs(
        source,
        output,
        input_format="prediction_jsonl",
        system="retrieval_candidate_pool",
        execution_mode="candidate_generation",
    )
    rows = _read_jsonl(output)

    assert rows[0]["ranked_pmids"] == ["41", "42"]
    assert rows[0]["included_pmids"] == []
    assert rows[0]["predicted_pmids"] == []
