#!/usr/bin/env python3
"""Build a v4->v5 reroute audit pack for task-panel packages."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build.build_task_panel_ingest_package import _route_task_lane_candidate


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-v4", type=Path, required=True)
    parser.add_argument("--package-v5", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--focus-label",
        action="append",
        dest="focus_labels",
        default=[],
        help="Case-insensitive label to highlight in the audit output. Can be repeated.",
    )
    return parser.parse_args()


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            yield json.loads(raw)


def _record_key(row: dict[str, Any]) -> str:
    paper_id = str((row.get("paper") or {}).get("id") or "").strip()
    claim_id = str((row.get("claim") or {}).get("id") or "").strip()
    run_id = str((row.get("run") or {}).get("run_id") or "").strip()
    if paper_id and claim_id and run_id:
        return "::".join([paper_id, claim_id, run_id])
    target = row.get("target") or {}
    target = target if isinstance(target, dict) else {}
    original_id = str(target.get("original_id") or "").strip()
    target_id = str(target.get("id") or "").strip()
    return "::".join([paper_id, claim_id, run_id, original_id or target_id])


def _route_label(row: dict[str, Any]) -> str:
    task_panel = dict((row.get("normalization") or {}).get("task_panel") or {})
    return str(
        task_panel.get("family_match_input_label")
        or (row.get("target") or {}).get("label")
        or ""
    ).strip()


def _normalize_focus_label(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _audit_row(row: dict[str, Any], *, focus_labels: set[str]) -> dict[str, Any]:
    label = _route_label(row)
    route_probe = dict(row)
    route_probe["source_label"] = label
    route = _route_task_lane_candidate(
        row=route_probe,
        source_labels_by_id={},
        task_matcher=None,
    )
    target = row.get("target") or {}
    target = target if isinstance(target, dict) else {}
    paper = row.get("paper") or {}
    paper = paper if isinstance(paper, dict) else {}
    task_panel = dict((row.get("normalization") or {}).get("task_panel") or {})
    onvoc = dict((row.get("normalization") or {}).get("onvoc") or {})

    return {
        "paper_id": str(paper.get("id") or "").strip(),
        "paper_title": str(paper.get("title") or "").strip(),
        "claim_id": str((row.get("claim") or {}).get("id") or "").strip(),
        "run_id": str((row.get("run") or {}).get("run_id") or "").strip(),
        "audit_label": label,
        "focus_label_match": _normalize_focus_label(label) in focus_labels,
        "target_id_v4": str(target.get("id") or "").strip(),
        "target_label_v4": str(target.get("label") or "").strip(),
        "target_original_id_v4": str(target.get("original_id") or "").strip(),
        "onvoc_id": str(target.get("onvoc_id") or onvoc.get("onvoc_id") or "").strip(),
        "onvoc_label": str(
            target.get("onvoc_label") or onvoc.get("onvoc_label") or ""
        ).strip(),
        "family_id_v4": str(task_panel.get("family_id") or "").strip(),
        "subfamily_id_v4": str(task_panel.get("subfamily_id") or "").strip(),
        "family_match_method_v4": str(task_panel.get("family_match_method") or "").strip(),
        "router_reason_probe": route.reason,
        "router_label_type_probe": route.label_type,
        "router_input_label_probe": route.input_label,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "paper_id",
        "claim_id",
        "run_id",
        "audit_label",
        "focus_label_match",
        "target_id_v4",
        "target_label_v4",
        "onvoc_id",
        "onvoc_label",
        "family_id_v4",
        "subfamily_id_v4",
        "family_match_method_v4",
        "router_reason_probe",
        "router_label_type_probe",
        "paper_title",
    ]
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(columns) + "\n")
        for row in rows:
            handle.write(
                "\t".join(str(row.get(column, "")).replace("\t", " ") for column in columns)
                + "\n"
            )


def main() -> int:
    args = parse_args()
    package_v4 = args.package_v4.resolve()
    package_v5 = args.package_v5.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    v4_records_path = package_v4 / "task_panel_records.jsonl"
    v5_records_path = package_v5 / "task_panel_records.jsonl"
    if not v4_records_path.exists():
        raise SystemExit(f"Missing v4 task_panel_records.jsonl: {v4_records_path}")
    if not v5_records_path.exists():
        raise SystemExit(f"Missing v5 task_panel_records.jsonl: {v5_records_path}")

    v4_rows = list(_iter_jsonl(v4_records_path))
    v5_keys = {_record_key(row) for row in _iter_jsonl(v5_records_path)}
    focus_labels = {_normalize_focus_label(label) for label in args.focus_labels}

    dropped_rows = [
        _audit_row(row, focus_labels=focus_labels)
        for row in v4_rows
        if _record_key(row) not in v5_keys
    ]

    dropped_label_counts = Counter(row["audit_label"] for row in dropped_rows if row["audit_label"])
    focus_counter = Counter(
        row["audit_label"]
        for row in dropped_rows
        if row.get("focus_label_match") and row.get("audit_label")
    )
    router_reason_counts = Counter(row["router_reason_probe"] for row in dropped_rows)

    summary = {
        "generated_at": _utc_now_iso(),
        "package_v4": str(package_v4),
        "package_v5": str(package_v5),
        "records_v4": len(v4_rows),
        "records_v5": len(v5_keys),
        "records_dropped": len(dropped_rows),
        "focus_labels": sorted(focus_labels),
        "top_dropped_labels": dropped_label_counts.most_common(50),
        "focus_label_counts": focus_counter.most_common(),
        "router_reason_counts": router_reason_counts.most_common(),
        "artifacts": {
            "audit_pack_jsonl": str(output_dir / "reroute_audit_pack.jsonl"),
            "audit_pack_tsv": str(output_dir / "reroute_audit_pack.tsv"),
            "summary_json": str(output_dir / "reroute_audit_summary.json"),
        },
    }

    _write_jsonl(output_dir / "reroute_audit_pack.jsonl", dropped_rows)
    _write_tsv(output_dir / "reroute_audit_pack.tsv", dropped_rows)
    (output_dir / "reroute_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
