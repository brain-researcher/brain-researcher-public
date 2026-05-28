from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_task_panel_reroute_audit_pack import main


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_task_panel_reroute_audit_pack_outputs_dropped_rows(
    tmp_path: Path, monkeypatch
) -> None:
    v4 = tmp_path / "v4"
    v5 = tmp_path / "v5"
    out = tmp_path / "audit"

    _write_jsonl(
        v4 / "task_panel_records.jsonl",
        [
            {
                "paper": {"id": "pmid:1", "title": "Attention paper"},
                "claim": {"id": "claim:1"},
                "run": {"run_id": "run:1"},
                "target": {
                    "id": "task:onvoc:onvoc_1",
                    "label": "Cognitive Inhibition",
                    "original_id": "concept:attention",
                },
                "normalization": {
                    "task_panel": {
                        "family_match_input_label": "attention",
                        "family_id": "",
                        "subfamily_id": "",
                    },
                    "onvoc": {"onvoc_id": "ONVOC_1", "onvoc_label": "Cognitive Inhibition"},
                },
            },
            {
                "paper": {"id": "pmid:2", "title": "Reading paper"},
                "claim": {"id": "claim:2"},
                "run": {"run_id": "run:2"},
                "target": {
                    "id": "task:onvoc:onvoc_2",
                    "label": "Reading Comprehension",
                    "original_id": "concept:word_reading",
                },
                "normalization": {
                    "task_panel": {
                        "family_match_input_label": "word reading",
                        "family_id": "tf_language",
                        "subfamily_id": "sf_reading",
                    },
                    "onvoc": {
                        "onvoc_id": "ONVOC_2",
                        "onvoc_label": "Reading Comprehension",
                    },
                },
            },
        ],
    )
    _write_jsonl(
        v5 / "task_panel_records.jsonl",
        [
            {
                "paper": {"id": "pmid:2", "title": "Reading paper"},
                "claim": {"id": "claim:2"},
                "run": {"run_id": "run:2"},
                "target": {"id": "task:subfamily:sf_reading", "label": "Reading"},
                "normalization": {
                    "task_panel": {
                        "family_match_input_label": "word reading",
                        "family_id": "tf_language",
                        "subfamily_id": "sf_reading",
                    }
                },
            }
        ],
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "build_task_panel_reroute_audit_pack.py",
            "--package-v4",
            str(v4),
            "--package-v5",
            str(v5),
            "--output-dir",
            str(out),
            "--focus-label",
            "attention",
        ],
    )
    assert main() == 0

    summary = json.loads((out / "reroute_audit_summary.json").read_text(encoding="utf-8"))
    assert summary["records_dropped"] == 1
    assert summary["focus_label_counts"] == [["attention", 1]]

    rows = [
        json.loads(line)
        for line in (out / "reroute_audit_pack.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["audit_label"] == "attention"
    assert rows[0]["router_reason_probe"] == "router_generic_construct"
