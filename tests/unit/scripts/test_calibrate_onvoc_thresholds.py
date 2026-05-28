from __future__ import annotations

import json
from pathlib import Path

from scripts.calibrate_onvoc_thresholds import (
    calibrate,
    evaluate_thresholds,
    load_mapping_rows,
    run_grid,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def test_evaluate_thresholds_counts_acceptance(tmp_path: Path) -> None:
    mapping_rows = tmp_path / "mapping_rows.jsonl"
    _write_jsonl(
        mapping_rows,
        [
            {
                "status": "mapped",
                "reason": "lexical_candidate",
                "onvoc_id": "ONVOC_1",
                "score": 0.90,
                "top1_score": 0.90,
                "top2_score": 0.70,
            },
            {
                "status": "below_threshold",
                "reason": "below_threshold",
                "onvoc_id": "ONVOC_2",
                "score": 0.79,
                "top1_score": 0.79,
                "top2_score": 0.60,
            },
            {
                "status": "ambiguous",
                "reason": "margin_too_small",
                "onvoc_id": "ONVOC_3",
                "score": 0.85,
                "top1_score": 0.85,
                "top2_score": 0.84,
            },
            {
                "status": "unmatched",
                "reason": "no_candidate",
            },
        ],
    )

    rows = load_mapping_rows(mapping_rows)
    strict = evaluate_thresholds(rows, min_score=0.82, margin_min=0.04)
    assert strict["accepted"] == 1
    assert strict["rejected_no_candidate"] == 1
    assert strict["rejected_below_score"] >= 1
    assert strict["rejected_margin"] >= 1

    relaxed = evaluate_thresholds(rows, min_score=0.78, margin_min=0.00)
    assert relaxed["accepted"] == 3
    assert relaxed["accepted"] > strict["accepted"]


def test_calibrate_writes_summary_and_selects_best(tmp_path: Path) -> None:
    mapping_rows = tmp_path / "mapping_rows.jsonl"
    _write_jsonl(
        mapping_rows,
        [
            {
                "status": "mapped",
                "reason": "lexical_candidate",
                "onvoc_id": "ONVOC_A",
                "score": 0.91,
                "top1_score": 0.91,
                "top2_score": 0.80,
            },
            {
                "status": "below_threshold",
                "reason": "below_threshold",
                "onvoc_id": "ONVOC_B",
                "score": 0.79,
                "top1_score": 0.79,
                "top2_score": 0.60,
            },
        ],
    )

    rows = load_mapping_rows(mapping_rows)
    top = run_grid(rows, min_scores=[0.82, 0.78], margins=[0.04, 0.00], top_n=4)
    assert top
    assert top[0]["accepted"] >= top[-1]["accepted"]

    output = tmp_path / "summary.json"
    payload = calibrate(
        mapping_rows_path=mapping_rows,
        output_path=output,
        min_scores=[0.82, 0.78],
        margins=[0.04, 0.00],
        top_n=4,
    )

    assert output.exists()
    assert payload["baseline"]["accepted"] == 1
    assert payload["best"]["accepted"] >= payload["baseline"]["accepted"]
    assert "accepted_delta" in payload["delta_vs_baseline"]
