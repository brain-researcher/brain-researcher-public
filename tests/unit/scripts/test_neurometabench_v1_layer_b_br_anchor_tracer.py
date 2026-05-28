from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.neurometabench_v1.layer_b_br_anchor_tracer import (
    trace_case_br_anchors,
    validate_br_reconciliation_anchors,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_br_anchor_tracer_marks_consumed_provenance_report_and_artifact(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "layer_b_123_reward"
    _write_json(
        case_dir / "provenance_manifest.json",
        {
            "br_calls_made": [
                {
                    "tool": "mcp__brain_researcher_prod__kg_search_nodes",
                    "purpose": "audit PMID 12345678 reward source asset",
                    "result": "PMID 12345678 appears in reward.json",
                    "changed_bundle": True,
                }
            ],
        },
    )
    _write_csv(
        case_dir / "included_studies.csv",
        [{"study_id": "study-1", "study_pmid": "12345678", "source_asset": "reward.json"}],
    )
    (case_dir / "spatial_report.md").write_text(
        "BR audit confirmed PMID 12345678 in reward.json.", encoding="utf-8"
    )

    payload = trace_case_br_anchors(case_dir)

    written = json.loads((case_dir / "br_anchor_trace.json").read_text(encoding="utf-8"))
    assert written == payload
    assert payload["summary"]["br_call_count"] == 1
    assert payload["summary"]["retrieved_or_audited_anchor_present"] is True
    assert payload["summary"]["artifact_or_report_consumes_br_result"] is True
    assert payload["summary"]["br_effective_use_pass"] is True
    anchor = payload["anchors"][0]
    assert anchor["consumed_by_provenance"] is True
    assert anchor["consumed_by_report"] is True
    assert anchor["consumed_by_artifact"] is True


def test_br_anchor_tracer_reads_episode_stdout_jsonl(tmp_path: Path) -> None:
    case_dir = tmp_path / "layer_b_123_reward"
    case_dir.mkdir()
    _write_json(case_dir / "provenance_manifest.json", {"br_calls_made": []})
    (case_dir / "spatial_report.md").write_text(
        "No actionable BR evidence was consumed.", encoding="utf-8"
    )
    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    (episode_dir / "stdout.txt").write_text(
        json.dumps(
            {
                "type": "tool_use",
                "name": "mcp__brain_researcher_prod__kg_search_nodes",
                "input": "audit case route",
                "output": "No actionable BR evidence",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    payload = trace_case_br_anchors(case_dir, episode_dir=episode_dir)

    assert payload["summary"]["br_call_count"] == 1
    assert payload["anchors"][0]["source"] == "stdout_jsonl"
    assert payload["summary"]["retrieved_or_audited_anchor_present"] is True
    assert payload["summary"]["n_consumed_by_report"] == 1


def test_br_anchor_tracer_treats_details_and_impact_as_audit_anchor(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "layer_b_123_reward"
    _write_json(
        case_dir / "provenance_manifest.json",
        {
            "br_calls_made": [
                {
                    "tool": "brain-researcher-local_plan_preflight",
                    "details": "Used to classify PMID 12345678 and audit local assets.",
                    "impact": "Confirmed no automatic study-set reconciliation was needed.",
                }
            ],
        },
    )
    _write_csv(
        case_dir / "included_studies.csv",
        [{"study_id": "study-1", "study_pmid": "12345678"}],
    )
    (case_dir / "spatial_report.md").write_text(
        "BR preflight classified PMID 12345678 and confirmed no automatic study-set "
        "reconciliation was needed.",
        encoding="utf-8",
    )

    payload = trace_case_br_anchors(case_dir)

    assert payload["summary"]["br_call_count"] == 1
    assert payload["summary"]["retrieved_or_audited_anchor_present"] is True
    assert payload["summary"]["artifact_or_report_consumes_br_result"] is True
    assert payload["summary"]["br_effective_use_pass"] is True
    assert "classify PMID 12345678" in payload["anchors"][0]["purpose"]
    assert "no automatic study-set reconciliation" in payload["anchors"][0]["result_summary"]


def test_br_anchor_tracer_trusts_explicit_br_calls_with_generic_tool_name(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "layer_b_123_reward"
    _write_json(
        case_dir / "provenance_manifest.json",
        {
            "br_calls": [
                {
                    "tool": "plan_preflight",
                    "purpose": "BR-assisted preflight for PMID 12345678",
                    "outcome": "classified as structured-coordinate reproduction",
                    "changed_bundle": False,
                }
            ],
        },
    )
    (case_dir / "spatial_report.md").write_text(
        "BR-assisted preflight classified PMID 12345678 as "
        "structured-coordinate reproduction.",
        encoding="utf-8",
    )

    payload = trace_case_br_anchors(case_dir)

    assert payload["summary"]["br_call_count"] == 1
    assert payload["summary"]["retrieved_or_audited_anchor_present"] is True
    assert payload["summary"]["artifact_or_report_consumes_br_result"] is True
    assert payload["summary"]["br_effective_use_pass"] is True
    assert payload["anchors"][0]["tool"] == "plan_preflight"
    assert "structured-coordinate" in payload["anchors"][0]["result_summary"]


def test_br_anchor_tracer_handles_no_br_calls(tmp_path: Path) -> None:
    case_dir = tmp_path / "layer_b_123_reward"
    _write_json(case_dir / "provenance_manifest.json", {"commands_executed": ["python run.py"]})

    payload = trace_case_br_anchors(case_dir)

    assert payload["anchors"] == []
    assert payload["summary"]["br_call_count"] == 0
    assert payload["summary"]["br_effective_use_pass"] is False


def test_br_reconciliation_anchor_contract_validates_consumed_canonical_value(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "layer_b_123_reward"
    _write_csv(
        case_dir / "included_studies.csv",
        [{"study_id": "study-1", "study_pmid": "12345678", "source_asset": "reward.json"}],
    )
    (case_dir / "spatial_report.md").write_text(
        "BR audit reconciled study-1 to PMID 12345678.", encoding="utf-8"
    )
    _write_json(
        case_dir / "br_reconciliation_anchors.json",
        {
            "anchors": [
                {
                    "anchor_id": "br:001",
                    "purpose": "study_id_reconciliation",
                    "target_artifact": "included_studies.csv",
                    "target_field": "study_pmid",
                    "study_id": "study-1",
                    "canonical_value": "12345678",
                    "evidence_source": "BR MCP",
                    "evidence_summary": "Matched local study to PMID 12345678.",
                    "confidence": "high",
                    "changed_bundle": True,
                }
            ]
        },
    )

    validation = validate_br_reconciliation_anchors(case_dir)
    payload = trace_case_br_anchors(case_dir)

    assert validation["pass"] is True
    assert validation["n_valid_anchors"] == 1
    assert validation["n_consumed"] == 1
    assert payload["summary"]["br_reconciliation_anchor_pass"] is True
    assert payload["summary"]["br_reconciliation_anchor_count"] == 1
    assert payload["summary"]["br_effective_use_pass"] is True


def test_br_reconciliation_anchor_contract_rejects_bad_field_and_unconsumed_change(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "layer_b_123_reward"
    _write_csv(case_dir / "included_studies.csv", [{"study_id": "study-1"}])
    _write_json(
        case_dir / "br_reconciliation_anchors.json",
        {
            "anchors": [
                {
                    "target_artifact": "included_studies.csv",
                    "target_field": "pmid",
                    "canonical_value": "12345678",
                    "evidence_source": "BR MCP",
                    "evidence_summary": "Matched local study to PMID 12345678.",
                    "changed_bundle": True,
                }
            ]
        },
    )

    validation = validate_br_reconciliation_anchors(case_dir)

    assert validation["pass"] is False
    assert validation["n_valid_target_fields"] == 0
    assert "invalid_target_field:pmid" in validation["invalid_reasons"]
    assert "changed_bundle_anchor_not_consumed" in validation["invalid_reasons"]
