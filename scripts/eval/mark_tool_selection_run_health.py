#!/usr/bin/env python3
"""Mark tool-selection real-trace runs as clean or degraded.

This is a run-health layer only. It does not judge whether selected tools are
scientifically correct; it checks whether the trace matrix is complete and
usable for scoring.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_ROOT = (
    ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "capability_pilot"
    / "real_trace_runs"
)
DEFAULT_OUT_DIR = ROOT / "benchmarks" / "tool_routing_validation"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def count_jsonl(path: Path) -> int | None:
    if not path.exists():
        return None
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def latest_summary(run_dir: Path) -> tuple[Path | None, dict[str, Any] | None]:
    candidates = sorted(run_dir.glob("*_summary.json"))
    if not candidates:
        return None, None
    preferred = [
        path
        for path in candidates
        if path.name.startswith("comprehensive_model_matrix_current")
        or path.name.startswith("health_rescore")
        or path.name.startswith("rescored_stdout_parser_v3")
        or path.name.startswith("comprehensive_parser_v3")
    ]
    path = max(preferred or candidates, key=lambda item: item.stat().st_mtime)
    try:
        return path, read_json(path)
    except Exception:
        return path, None


def status_counts(records: list[Mapping[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get("status") or "unknown") for row in records).items()))


def run_health(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "run_summary.json"
    if not summary_path.exists():
        return {
            "run": run_dir.name,
            "run_dir": str(run_dir),
            "health_status": "degraded",
            "degraded": True,
            "degraded_reasons": ["run_summary_missing"],
            "expected_record_count": 0,
            "observed_record_count": 0,
            "scored_record_count": None,
            "status_counts": {},
            "missing_condition_task_pairs": [],
            "zero_parsed_action_count": 0,
        }
    run_summary = read_json(summary_path)
    records = [row for row in run_summary.get("records") or [] if isinstance(row, Mapping)]
    conditions = list(run_summary.get("conditions") or [])
    tasks = list(run_summary.get("tasks") or [])
    expected_record_count = len(conditions) * len(tasks)
    observed_pairs = {
        (str(row.get("condition_id") or ""), str(row.get("task_id") or ""))
        for row in records
    }
    expected_pairs = {
        (str(condition), str(task_id))
        for condition in conditions
        for task_id in tasks
    }
    missing_pairs = sorted(expected_pairs - observed_pairs)
    duplicate_count = max(0, len(records) - len(observed_pairs))

    score_rows_count = count_jsonl(run_dir / "score_rows.jsonl")
    summary_file, summary = latest_summary(run_dir)
    audit = (summary or {}).get("audit") if isinstance(summary, dict) else {}
    audit_scored = audit.get("scored_record_count") if isinstance(audit, dict) else None
    scored_candidates = [
        int(value)
        for value in (score_rows_count, audit_scored)
        if isinstance(value, int)
    ]
    scored_record_count = max(scored_candidates) if scored_candidates else None

    statuses = status_counts(records)
    failed_count = statuses.get("failed", 0)
    timed_out_count = statuses.get("timed_out", 0)
    json_error_count = sum(1 for row in records if row.get("json_error_event"))
    parsed_action_record_count = sum(
        1 for row in records if row.get("parsed_action_count") is not None
    )
    zero_parsed_action_count = sum(
        1 for row in records if int(row.get("parsed_action_count") or 0) == 0
    )

    reasons: list[str] = []
    if expected_record_count and len(records) != expected_record_count:
        reasons.append("incomplete_condition_task_matrix")
    if missing_pairs:
        reasons.append("missing_condition_task_pairs")
    if duplicate_count:
        reasons.append("duplicate_condition_task_records")
    if scored_record_count is None:
        reasons.append("score_rows_missing")
    elif scored_record_count != len(records):
        reasons.append("score_coverage_incomplete")
    if failed_count:
        reasons.append("failed_records_present")
    if timed_out_count:
        reasons.append("timed_out_records_present")
    if json_error_count:
        reasons.append("json_error_records_present")
    if parsed_action_record_count != len(records):
        reasons.append("parsed_action_metadata_incomplete")

    degraded = bool(reasons)
    return {
        "run": run_dir.name,
        "run_dir": str(run_dir),
        "health_status": "degraded" if degraded else "clean",
        "degraded": degraded,
        "degraded_reasons": reasons,
        "expected_record_count": expected_record_count,
        "observed_record_count": len(records),
        "scored_record_count": scored_record_count,
        "score_rows_path": str(run_dir / "score_rows.jsonl")
        if score_rows_count is not None
        else None,
        "summary_source": str(summary_file) if summary_file else None,
        "condition_count": len(conditions),
        "task_count": len(tasks),
        "status_counts": statuses,
        "failed_count": failed_count,
        "timed_out_count": timed_out_count,
        "json_error_count": json_error_count,
        "parsed_action_record_count": parsed_action_record_count,
        "zero_parsed_action_count": zero_parsed_action_count,
        "duplicate_condition_task_records": duplicate_count,
        "missing_condition_task_pairs": [
            {"condition": condition, "task_id": task_id}
            for condition, task_id in missing_pairs
        ],
    }


def write_markdown(path: Path, rows: list[dict[str, Any]], created_at: str) -> None:
    clean = [row for row in rows if not row["degraded"]]
    degraded = [row for row in rows if row["degraded"]]
    lines = [
        "# Tool-Selection Run Health",
        "",
        f"Generated: `{created_at}`",
        "",
        "Scope: run-health only. This does not score scientific correctness.",
        "",
        f"- Clean runs: {len(clean)}",
        f"- Degraded runs: {len(degraded)}",
        "",
        "## Degraded Runs",
        "",
        "| Run | Records | Scored | Status | Reasons | Missing pairs | Zero parsed |",
        "| --- | ---: | ---: | --- | --- | ---: | ---: |",
    ]
    for row in degraded:
        lines.append(
            "| {run} | {observed}/{expected} | {scored} | `{status}` | `{reasons}` | {missing} | {zero} |".format(
                run=row["run"],
                observed=row["observed_record_count"],
                expected=row["expected_record_count"],
                scored=row.get("scored_record_count"),
                status=json.dumps(row["status_counts"], sort_keys=True),
                reasons=", ".join(row["degraded_reasons"]),
                missing=len(row["missing_condition_task_pairs"]),
                zero=row["zero_parsed_action_count"],
            )
        )
    lines.extend(
        [
            "",
            "## Clean Runs",
            "",
            "| Run | Records | Scored | Status | Zero parsed |",
            "| --- | ---: | ---: | --- | ---: |",
        ]
    )
    for row in clean:
        lines.append(
            "| {run} | {observed}/{expected} | {scored} | `{status}` | {zero} |".format(
                run=row["run"],
                observed=row["observed_record_count"],
                expected=row["expected_record_count"],
                scored=row.get("scored_record_count"),
                status=json.dumps(row["status_counts"], sort_keys=True),
                zero=row["zero_parsed_action_count"],
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--prefix", default="TOOL_SELECTION_RUN_HEALTH")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = [
        run_health(run_dir)
        for run_dir in sorted(args.run_root.iterdir())
        if run_dir.is_dir()
    ]
    payload = {
        "schema_version": "br.tool_selection_run_health.v1",
        "created_at": created_at,
        "run_root": str(args.run_root),
        "clean_count": sum(1 for row in rows if not row["degraded"]),
        "degraded_count": sum(1 for row in rows if row["degraded"]),
        "runs": rows,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    json_path = args.out_dir / f"{args.prefix}_{stamp}.json"
    md_path = args.out_dir / f"{args.prefix}_{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(md_path, rows, created_at)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), **{k: payload[k] for k in ("clean_count", "degraded_count")}}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
