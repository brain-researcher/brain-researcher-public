#!/usr/bin/env python3
"""Rescore an existing tool-selection real-trace run without rerunning agents."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval.summarize_tool_selection_model_matrix import (
    build_summary,
    markdown_report,
    write_csv,
    write_json,
)
from scripts.eval.tool_selection_capability_pilot import (
    load_tasks,
    parse_events,
    score_task,
)

DEFAULT_TASKS = (
    ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "capability_pilot"
    / "microtooling_capability_pilot.v1.jsonl"
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _actions_for_episode(episode_dir: Path) -> list[dict[str, Any]]:
    stdout_path = episode_dir / "stdout.jsonl"
    if stdout_path.exists():
        return parse_events(read_jsonl(stdout_path))
    return read_jsonl(episode_dir / "parsed_actions.jsonl")


def _records_from_episodes(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    episodes_dir = run_dir / "episodes"
    for record_path in sorted(episodes_dir.glob("*/*/record.json")):
        try:
            record = read_json(record_path)
        except json.JSONDecodeError:
            continue
        condition = record_path.parent.parent.name
        task_id = record_path.parent.name
        if not isinstance(record, dict):
            continue
        record.setdefault("condition_id", condition)
        record.setdefault("task_id", task_id)
        records.append(record)
    return records


def _load_or_synthesize_run_summary(
    run_dir: Path,
    *,
    tasks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    summary_path = run_dir / "run_summary.json"
    if summary_path.exists():
        return read_json(summary_path)

    records = _records_from_episodes(run_dir)
    conditions = sorted(
        {
            str(record.get("condition_id") or "")
            for record in records
            if str(record.get("condition_id") or "")
        }
    )
    run_summary = {
        "schema_version": "br.tool_selection_real_trace_run_summary.synthetic.v1",
        "synthetic": True,
        "reason": "run_summary_missing; synthesized from episode record.json files",
        "conditions": conditions,
        "tasks": sorted(tasks),
        "stop_after_actions": 3,
        "records": records,
    }
    summary_path.write_text(
        json.dumps(run_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return run_summary


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_summary_outputs(run_dir: Path, score_rows_path: Path, prefix: str) -> dict[str, Any]:
    summary = build_summary(run_dir, score_rows_path)
    write_json(run_dir / f"{prefix}_summary.json", summary)
    write_json(run_dir / f"{prefix}_audit.json", summary["audit"])
    write_csv(
        run_dir / f"{prefix}_condition_summary.csv",
        summary["condition_summary"],
        fieldnames=list(summary["condition_summary"][0].keys())
        if summary["condition_summary"]
        else [],
    )
    write_csv(
        run_dir / f"{prefix}_pair_summary.csv",
        summary["pair_summary"],
        fieldnames=list(summary["pair_summary"][0].keys())
        if summary["pair_summary"]
        else [],
    )
    write_csv(
        run_dir / f"{prefix}_task_summary.csv",
        summary["task_summary"],
        fieldnames=list(summary["task_summary"][0].keys()) if summary["task_summary"] else [],
    )
    write_csv(
        run_dir / f"{prefix}_task_condition_rows.csv",
        summary["task_condition_rows"],
        fieldnames=list(summary["task_condition_rows"][0].keys())
        if summary["task_condition_rows"]
        else [],
    )
    (run_dir / f"{prefix}_summary.md").write_text(
        markdown_report(
            run_dir=run_dir,
            audit=summary["audit"],
            condition_rows=summary["condition_summary"],
            pair_rows=summary["pair_summary"],
            task_rows=summary["task_summary"],
        ),
        encoding="utf-8",
    )
    return summary


def rescore_run(run_dir: Path, tasks_jsonl: Path, output_name: str) -> dict[str, Any]:
    tasks = {str(task["task_id"]): task for task in load_tasks(tasks_jsonl)}
    run_summary = _load_or_synthesize_run_summary(run_dir, tasks=tasks)
    max_actions = int(run_summary.get("stop_after_actions") or 3)
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for record in run_summary.get("records") or []:
        if not isinstance(record, dict):
            continue
        condition = str(record.get("condition_id") or "")
        task_id = str(record.get("task_id") or "")
        task = tasks.get(task_id)
        episode_dir = run_dir / "episodes" / condition / task_id
        actions_path = episode_dir / "stdout.jsonl"
        if not actions_path.exists():
            actions_path = episode_dir / "parsed_actions.jsonl"
        if task is None:
            skipped.append({"condition": condition, "task_id": task_id, "reason": "missing_task"})
            continue
        if not actions_path.exists():
            skipped.append(
                {"condition": condition, "task_id": task_id, "reason": "missing_actions"}
            )
            continue
        actions = _actions_for_episode(episode_dir)
        rows.append(
            score_task(
                task,
                actions,
                condition=condition,
                max_actions=max_actions,
            )
        )

    score_rows_path = run_dir / output_name
    write_jsonl(score_rows_path, rows)
    prefix = output_name.removesuffix(".jsonl").removeprefix("score_rows_")
    summary = write_summary_outputs(run_dir, score_rows_path, prefix)
    return {
        "schema_version": "br.tool_selection_rescore.v1",
        "run_dir": str(run_dir),
        "tasks_jsonl": str(tasks_jsonl),
        "score_rows_path": str(score_rows_path),
        "output_prefix": prefix,
        "rows": len(rows),
        "skipped": skipped,
        "audit": summary["audit"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--tasks-jsonl", type=Path, default=DEFAULT_TASKS)
    parser.add_argument(
        "--output-name",
        default="score_rows_rescored_template_fix_v1.jsonl",
        help="Output score rows filename inside run_dir.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = rescore_run(
        run_dir=args.run_dir.resolve(),
        tasks_jsonl=args.tasks_jsonl.resolve(),
        output_name=args.output_name,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
