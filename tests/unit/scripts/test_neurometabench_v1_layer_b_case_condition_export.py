from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.neurometabench_v1 import export_layer_b_case_condition_rows as module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_export_rows_joins_episode_records_to_v2_metrics(tmp_path: Path) -> None:
    run_dir = tmp_path / "layer_b_full"
    _write_jsonl(
        run_dir / "episode_records.jsonl",
        [
            {
                "condition_id": "opencode_gemini_pro_with_br_required",
                "br_mode": "with_br_required",
                "runner": "opencode",
                "model_target": "google/gemini-3.1-pro-preview",
                "status": "succeeded",
                "returncode": 0,
                "json_error_event": False,
                "tool_calls": 4,
                "retry_count": 0,
                "wall_time_s": 12.5,
                "started_at": "start",
                "ended_at": "end",
                "meta_pmids": ["123"],
                "producer_output_dir": str(run_dir / "producer_outputs" / "condition"),
                "episode_dir": str(run_dir / "episodes" / "condition" / "layer_b_123"),
            },
            {
                "condition_id": "opencode_gemini_pro_without_br",
                "br_mode": "without_br",
                "runner": "opencode",
                "model_target": "google/gemini-3.1-pro-preview",
                "status": "timed_out",
                "returncode": None,
                "json_error_event": False,
                "tool_calls": 0,
                "retry_count": 0,
                "wall_time_s": 1800.0,
                "started_at": "start",
                "ended_at": "end",
                "meta_pmids": ["456"],
                "producer_output_dir": str(run_dir / "producer_outputs" / "condition"),
                "episode_dir": str(run_dir / "episodes" / "condition" / "layer_b_456"),
            },
        ],
    )
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {"meta_pmid": "123", "case_id": "neurometabench:123", "topic": "Reward"},
            {"meta_pmid": "456", "case_id": "neurometabench:456", "topic": "Emotion"},
        ],
    )
    conditions_path = tmp_path / "conditions.jsonl"
    _write_jsonl(
        conditions_path,
        [
            {
                "record_type": "condition",
                "condition_id": "opencode_gemini_pro_with_br_required",
                "br_mode": "with_br_required",
            },
            {
                "record_type": "condition",
                "condition_id": "opencode_gemini_pro_without_br",
                "br_mode": "without_br",
            },
        ],
    )
    comparison_summary = tmp_path / "summary.json"
    _write_json(
        comparison_summary,
        {
            "conditions": [
                {
                    "name": "opencode_gemini_pro_with_br_required",
                    "cases": [
                        {
                            "condition": "opencode_gemini_pro_with_br_required",
                            "case_id": "neurometabench:123",
                            "meta_pmid": "123",
                            "topic": "Reward",
                            "case_dir": str(run_dir / "producer_outputs" / "condition" / "layer_b_123_reward"),
                            "status": "evaluable",
                            "status_reasons": [],
                            "map_generated": True,
                            "n_coordinate_rows": 10,
                            "n_included_studies": 3,
                            "split_half_status": "computed",
                            "spatial_metrics": {
                                "split_half_z_map": {
                                    "pearson_union_positive": 0.9,
                                    "dice_top5_positive": 0.7,
                                }
                            },
                            "control_comparison": {
                                "all_maps_exact_match": False,
                                "coordinate_table_exact_match": False,
                                "included_studies_exact_match": True,
                            },
                            "metric_layers": {
                                "metric_contract": {
                                    "study_set_f1": {"precision": 1.0, "recall": 0.5, "f1": 0.666666},
                                    "local_study_set_f1": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
                                    "coordinate_extraction_agreement": {"precision": 0.8, "recall": 0.8, "f1": 0.8},
                                    "coordinate_canonical_f1": {"precision": 0.9, "recall": 0.9, "f1": 0.9},
                                    "ale_map_spatial_correlation": {"value": 0.95},
                                    "dice_top5": {"value": 0.75},
                                    "exact_match_to_pure_nimare": {
                                        "all_maps": False,
                                        "coordinate_table": False,
                                        "included_studies": True,
                                    },
                                    "map_generated": {"value": True},
                                    "coordinate_rows": {"value": 10},
                                    "study_rows": {"value": 3},
                                    "pmid_study_reconciliation": {
                                        "local_identifier_coverage": 1.0,
                                        "public_identifier_coverage": 0.5,
                                        "source_provenance_coverage": 0.25,
                                        "sample_size_coverage": 0.75,
                                    },
                                    "br_reconciliation_anchors": {
                                        "present": True,
                                        "n_anchors": 1,
                                        "n_valid_anchors": 1,
                                        "n_consumed": 1,
                                        "n_changed_bundle": 1,
                                        "n_changed_consumed": 1,
                                        "pass": True,
                                    },
                                    "provenance_completeness": {
                                        "score": 1.0,
                                        "br_call_count": 2,
                                    },
                                    "claim_consistency": {"score": 1.0},
                                    "failure_diagnosis_quality": {"score": None},
                                },
                                "deterministic_artifact": {"map_generated": True},
                                "normalization": {
                                    "coordinate_table": {
                                        "coordinate_parseability": 1.0
                                    },
                                    "included_studies": {
                                        "public_identifier_coverage": 0.8,
                                        "source_provenance_coverage": 0.6,
                                    },
                                    "normalization_delta": {"n_repairs": 4},
                                },
                                "br_relevant_audit": {
                                    "br_anchor_trace": {
                                        "br_call_count": 2,
                                        "retrieved_or_audited_anchor_present": True,
                                        "artifact_or_report_consumes_br_result": True,
                                        "br_effective_use_pass": True,
                                        "br_reconciliation_anchor_present": True,
                                        "br_reconciliation_anchor_count": 1,
                                        "br_reconciliation_anchor_valid_count": 1,
                                        "br_reconciliation_anchor_consumed_count": 1,
                                        "br_reconciliation_anchor_changed_count": 1,
                                        "br_reconciliation_anchor_changed_consumed_count": 1,
                                        "br_reconciliation_anchor_pass": True,
                                    }
                                },
                            },
                        }
                    ],
                }
            ]
        },
    )

    output_csv = tmp_path / "rows.csv"
    rows = module.export_rows(
        run_dir=run_dir,
        comparison_summary=comparison_summary,
        output_csv=output_csv,
        cases_path=cases_path,
        conditions_path=conditions_path,
    )

    written = _read_csv(output_csv)
    assert rows == written
    assert len(written) == 2
    scored = written[0]
    missing = written[1]
    assert scored["condition"] == "opencode_gemini_pro_with_br_required"
    assert scored["br_condition"] == "with_br"
    assert scored["system_key"] == "opencode_gemini_pro"
    assert scored["scored"] == "true"
    assert scored["correct"] == "true"
    assert scored["local_study_set_f1"] == "1.0"
    assert scored["coordinate_canonical_f1"] == "0.9"
    assert scored["br_call_count"] == "2"
    assert scored["br_trace_effective_use_pass"] == "true"
    assert scored["br_reconciliation_anchor_pass"] == "true"
    assert scored["br_reconciliation_anchor_count"] == "1"
    assert scored["normalization_repairs"] == "4"
    assert '"coordinate_canonical_f1"' in scored["metric_contract"]

    assert missing["condition"] == "opencode_gemini_pro_without_br"
    assert missing["br_condition"] == "without_br"
    assert missing["scored"] == "false"
    assert missing["evaluator_discovered"] == "false"
    assert missing["correct"] == "false"
    assert missing["topic"] == "Emotion"
