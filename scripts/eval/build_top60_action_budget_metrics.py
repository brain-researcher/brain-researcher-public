#!/usr/bin/env python3
"""Build Top60 action-budget metrics from real tool-calling trajectories.

This is different from the exact-routing top-k evaluator.  Exact top-k metrics
score a ranked shortlist.  These action-budget metrics rescore the first k
non-neutral actions that actually appeared in each agent trajectory.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval.tool_selection_capability_pilot import load_tasks, parse_events, score_task


DEFAULT_TASKS = (
    ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "capability_pilot"
    / "microtooling_top60_plus_br_20260514.jsonl"
)
DEFAULT_RUNS_DIR = (
    ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "capability_pilot"
    / "real_trace_runs"
)
DEFAULT_OUT_DIR = ROOT / "benchmarks" / "tool_routing_validation"
DEFAULT_EXISTING_AGG = (
    DEFAULT_OUT_DIR / "TOOL_SELECTION_TOP60_PLUS_BR_MODEL_METRIC_BREAKDOWN_20260514.json"
)
DEFAULT_BUDGETS = (1, 3, 5)

MODEL_ORDER = [
    ("Codex", "codex_cli_gpt55"),
    ("Claude", "claude_code_opus47"),
    ("Gemini", "opencode_gemini_pro"),
    ("GLM-5.1", "opencode_glm51"),
    ("DeepSeek", "opencode_deepseek_v4_pro"),
    ("Kimi", "opencode_kimi_k25"),
    ("Qwen", "opencode_qwen36_plus"),
]
MODEL_BY_KEY = {model_key: model for model, model_key in MODEL_ORDER}
MODE_ORDER = ("without_br", "with_br")

QUALITY_METRICS = [
    ("capability_score", "Capability"),
    ("correct_rate", "Correct route/tool"),
    ("execution_handoff_score", "Handoff score"),
]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def condition_to_model_mode(condition: str) -> tuple[str, str, str] | None:
    if condition.endswith("_with_br"):
        mode = "with_br"
        model_key = condition.removesuffix("_with_br")
    elif condition.endswith("_without_br"):
        mode = "without_br"
        model_key = condition.removesuffix("_without_br")
    else:
        return None
    model = MODEL_BY_KEY.get(model_key)
    if model is None:
        return None
    return model, model_key, mode


def num(value: Any, *, default: float = -1.0) -> float:
    return float(value) if isinstance(value, int | float) else default


def candidate_quality(
    scored_by_budget: Mapping[int, Mapping[str, Any]],
    source_file: Path,
    *,
    episode_status: str | None = None,
    episode_returncode: int | None = None,
) -> tuple[Any, ...]:
    row = scored_by_budget[max(scored_by_budget)]
    source_name = source_file.name
    source_preference = 0
    if "score_rows_rescored_execution_handoff_v1" in source_name:
        source_preference = 4
    elif "score_rows_health_rescore" in source_name:
        source_preference = 3
    elif "score_rows_rescored_stdout_parser_v3" in source_name:
        source_preference = 2
    elif source_name == "score_rows.jsonl":
        source_preference = 1

    # Prefer episodes whose underlying trajectory terminated cleanly.
    #
    # Acceptable terminations:
    #   - status=succeeded rc=0: agent finished on its own.
    #   - status=captured_stop rc in {0, -15}: runner cleanly stopped after the
    #     action budget was reached (opencode/codex use SIGTERM=15, claude_code
    #     uses graceful close so rc=0). These are normal benchmark stops, not
    #     external kills.
    #
    # Unacceptable (clean_finish=0):
    #   - status=captured_stop rc=143: SIGTERM mid-trajectory often from a
    #     5h rate-limit kill or runaway action loop (Claude-side artifact).
    #   - status=captured_stop rc=1: agent crash.
    #   - status=timed_out rc=-9: hit wall-clock timeout.
    #   - status=failed: provider/account-limit, fatal API error.
    clean_finish = 0
    if episode_status == "succeeded" and episode_returncode in (0, None):
        clean_finish = 2
    elif episode_status == "captured_stop" and episode_returncode in (0, -15, None):
        clean_finish = 1
    # Anything else stays at 0.

    return (
        clean_finish,
        0 if row.get("no_action") else 1,
        0 if row.get("needs_human_adjudication") else 1,
        1 if row.get("correct") else 0,
        num(row.get("capability_score")),
        num(row.get("trace_required_call_coverage")),
        num(row.get("execution_handoff_score")),
        0 if row.get("trap_fall") else 1,
        num(row.get("parse_confidence")),
        num(row.get("n_selected_non_neutral_actions")),
        source_preference,
    )


def clean_actions(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    actions = row.get("selected_actions") or []
    out = []
    for action in actions:
        if isinstance(action, Mapping):
            out.append(dict(action))
    return out


def actions_for_candidate(source_file: Path, row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Load original parsed episode actions, falling back to score-row actions.

    Prefers a fresh re-parse of ``stdout.jsonl`` so that parser improvements
    (e.g. alias-import resolution, Skill-args capability extraction) take
    effect on archived runs without regenerating ``parsed_actions.jsonl``.
    Falls back to the cached ``parsed_actions.jsonl`` and then the score-row
    projection for episodes where ``stdout.jsonl`` is unavailable.
    """

    condition = str(row.get("condition") or "")
    task_id = str(row.get("task_id") or "")
    episode_dir = source_file.parent / "episodes" / condition / task_id
    stdout_path = episode_dir / "stdout.jsonl"
    if stdout_path.exists():
        return parse_events(read_jsonl(stdout_path))
    parsed_actions = episode_dir / "parsed_actions.jsonl"
    if parsed_actions.exists():
        return read_jsonl(parsed_actions)
    return clean_actions(row)


def score_candidate(
    *,
    task: Mapping[str, Any],
    actions: Sequence[Mapping[str, Any]],
    condition: str,
    budgets: Sequence[int],
) -> dict[int, dict[str, Any]]:
    return {
        budget: score_task(task, actions, condition=condition, max_actions=budget)
        for budget in budgets
    }


def collect_best_cells(
    *,
    tasks_by_id: Mapping[str, Mapping[str, Any]],
    runs_dir: Path,
    budgets: Sequence[int],
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[str, int]]:
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    source_counts: dict[str, int] = defaultdict(int)
    candidate_files = sorted(runs_dir.glob("*/score_rows*.jsonl"))
    for source_file in candidate_files:
        source_run = source_file.parent.name
        for row in read_jsonl(source_file):
            task_id = str(row.get("task_id") or "")
            task = tasks_by_id.get(task_id)
            parsed_condition = condition_to_model_mode(str(row.get("condition") or ""))
            if task is None or parsed_condition is None:
                continue
            model, model_key, mode = parsed_condition
            actions = actions_for_candidate(source_file, row)
            try:
                scored = score_candidate(
                    task=task,
                    actions=actions,
                    condition=str(row.get("condition") or ""),
                    budgets=budgets,
                )
            except Exception:
                continue
            # Pull the episode's terminal status so the picker can avoid
            # SIGTERM-truncated trajectories when a clean rerun exists.
            condition_str = str(row.get("condition") or "")
            episode_dir = source_file.parent / "episodes" / condition_str / task_id
            episode_status: str | None = None
            episode_returncode: int | None = None
            record_path = episode_dir / "record.json"
            if record_path.exists():
                try:
                    rec = json.loads(record_path.read_text(encoding="utf-8"))
                    if isinstance(rec, dict):
                        episode_status = rec.get("status")
                        rc = rec.get("returncode")
                        if isinstance(rc, int):
                            episode_returncode = rc
                except (json.JSONDecodeError, OSError):
                    pass
            key = (model, mode, task_id)
            candidate = {
                "model": model,
                "model_key": model_key,
                "mode": mode,
                "task_id": task_id,
                "source_run": source_run,
                "source_file": str(source_file.relative_to(ROOT)),
                "episode_status": episode_status,
                "episode_returncode": episode_returncode,
                "scores": scored,
                "quality": candidate_quality(
                    scored,
                    source_file,
                    episode_status=episode_status,
                    episode_returncode=episode_returncode,
                ),
            }
            if key not in best or candidate["quality"] > best[key]["quality"]:
                best[key] = candidate
    for cell in best.values():
        source_counts[str(cell["source_run"])] += 1
    return best, dict(sorted(source_counts.items()))


def known_mean(values: Sequence[Any]) -> tuple[float | None, int]:
    nums = [float(value) for value in values if isinstance(value, int | float)]
    return (mean(nums), len(nums)) if nums else (None, 0)


def metric_value(row: Mapping[str, Any], metric: str) -> float | None:
    if metric == "correct_rate":
        return 1.0 if row.get("correct") else 0.0
    value = row.get(metric)
    return float(value) if isinstance(value, int | float) else None


def first_budget(cell: Mapping[str, Any], predicate) -> int | None:
    for budget in sorted(cell["scores"]):
        if predicate(cell["scores"][budget]):
            return budget
    return None


def build_outputs(
    *,
    cells: Mapping[tuple[str, str, str], Mapping[str, Any]],
    tasks_by_id: Mapping[str, Mapping[str, Any]],
    budgets: Sequence[int],
    source_counts: Mapping[str, int],
    existing_agg: Path,
) -> dict[str, Any]:
    row_budget_rows: list[dict[str, Any]] = []
    for (model, mode, task_id), cell in sorted(cells.items()):
        for budget in budgets:
            score = cell["scores"][budget]
            row_budget_rows.append(
                {
                    "model": model,
                    "model_key": cell["model_key"],
                    "mode": mode,
                    "task_id": task_id,
                    "budget": budget,
                    "capability_score": metric_value(score, "capability_score"),
                    "correct": bool(score.get("correct")),
                    "correct_rate": metric_value(score, "correct_rate"),
                    "execution_handoff_score": metric_value(
                        score, "execution_handoff_score"
                    ),
                    "first_task_relevant_action_index": score.get(
                        "first_task_relevant_action_index"
                    ),
                    "n_selected_non_neutral_actions": score.get(
                        "n_selected_non_neutral_actions"
                    ),
                    "source_run": cell["source_run"],
                    "source_file": cell["source_file"],
                }
            )

    long_rows: list[dict[str, Any]] = []
    for model, model_key in MODEL_ORDER:
        for mode in MODE_ORDER:
            matching = [
                cell
                for (cell_model, cell_mode, _), cell in cells.items()
                if cell_model == model and cell_mode == mode
            ]
            for budget in budgets:
                budget_scores = [cell["scores"][budget] for cell in matching]
                for metric, metric_label in QUALITY_METRICS:
                    value, known_n = known_mean(
                        [metric_value(row, metric) for row in budget_scores]
                    )
                    long_rows.append(
                        {
                            "model": model,
                            "model_key": model_key,
                            "mode": mode,
                            "budget": budget,
                            "metric": metric,
                            "metric_label": metric_label,
                            "value": value,
                            "plot_value": 0.0 if value is None else value,
                            "known_n": known_n,
                            "expected_n": len(tasks_by_id),
                            "observed_n": len(matching),
                        }
                    )
            first_correct, n_first_correct = known_mean(
                [
                    first_budget(cell, lambda row: bool(row.get("correct")))
                    for cell in matching
                ]
            )
            first_full_cap, n_first_full_cap = known_mean(
                [
                    first_budget(
                        cell,
                        lambda row: metric_value(row, "capability_score") == 1.0,
                    )
                    for cell in matching
                ]
            )
            first_handoff, n_first_handoff = known_mean(
                [
                    first_budget(
                        cell,
                        lambda row: row.get("execution_handoff_ok") is True,
                    )
                    for cell in matching
                ]
            )
            for metric, metric_label, value, known_n in (
                (
                    "first_correct_budget",
                    "First correct budget",
                    first_correct,
                    n_first_correct,
                ),
                (
                    "first_full_capability_budget",
                    "First full-capability budget",
                    first_full_cap,
                    n_first_full_cap,
                ),
                (
                    "first_handoff_pass_budget",
                    "First handoff-pass budget",
                    first_handoff,
                    n_first_handoff,
                ),
            ):
                normalized = None if value is None else max(0.0, min(1.0, 1.0 - ((value - 1.0) / 2.0)))
                long_rows.append(
                    {
                        "model": model,
                        "model_key": model_key,
                        "mode": mode,
                        "budget": "",
                        "metric": metric,
                        "metric_label": metric_label,
                        "value": value,
                        "plot_value": 0.0 if normalized is None else normalized,
                        "known_n": known_n,
                        "expected_n": len(tasks_by_id),
                        "observed_n": len(matching),
                    }
                )

    validation = validate_against_existing(long_rows, existing_agg)
    return {
        "schema_version": "tool-selection-top60-action-budget-metrics-v1",
        "task_file": str(DEFAULT_TASKS.relative_to(ROOT)),
        "runs_dir": str(DEFAULT_RUNS_DIR.relative_to(ROOT)),
        "budgets": list(budgets),
        "n_tasks": len(tasks_by_id),
        "expected_cells": len(tasks_by_id) * len(MODEL_ORDER) * len(MODE_ORDER),
        "observed_cells": len(cells),
        "source_run_counts": source_counts,
        "quality_metrics": [
            {"metric": metric, "label": label} for metric, label in QUALITY_METRICS
        ],
        "long_rows": long_rows,
        "row_budget_rows": row_budget_rows,
        "validation_against_existing_top60_at_budget_3": validation,
    }


def validate_against_existing(
    long_rows: Sequence[Mapping[str, Any]],
    existing_agg: Path,
) -> dict[str, Any]:
    if not existing_agg.exists():
        return {"available": False}
    existing = json.loads(existing_agg.read_text(encoding="utf-8"))
    by_key = {
        (row["model"], row["mode"], row["metric"]): row
        for row in long_rows
        if row.get("budget") == 3
    }
    metric_map = {
        "capability_score": "capability_score",
        "correct_rate": "correct_rate",
        "execution_handoff_score": "execution_handoff_score",
    }
    comparisons = []
    for row in existing.get("mode_rows") or []:
        for metric in metric_map:
            current_value = row.get(metric)
            action_row = by_key.get((row["model"], row["mode"], metric))
            action_value = action_row.get("value") if action_row else None
            if isinstance(current_value, int | float) and isinstance(action_value, int | float):
                diff = float(action_value) - float(current_value)
            elif current_value is None and action_value is None:
                diff = None
            else:
                diff = None
            comparisons.append(
                {
                    "model": row["model"],
                    "mode": row["mode"],
                    "metric": metric,
                    "existing_value": current_value,
                    "action_budget_value_at_3": action_value,
                    "diff": diff,
                    "action_known_n": action_row.get("known_n") if action_row else 0,
                }
            )
    numeric_diffs = [abs(item["diff"]) for item in comparisons if isinstance(item["diff"], float)]
    return {
        "available": True,
        "note": "Action-budget @3 is recomputed from selected trajectory actions; it may differ from the previously published merged aggregate when a different duplicate trajectory wins the best-row merge.",
        "max_abs_numeric_diff": max(numeric_diffs) if numeric_diffs else None,
        "mean_abs_numeric_diff": mean(numeric_diffs) if numeric_diffs else None,
        "comparisons": comparisons,
    }


def markdown_report(payload: Mapping[str, Any]) -> str:
    validation = payload["validation_against_existing_top60_at_budget_3"]
    lines = [
        "# Top60 Action-Budget Metrics",
        "",
        f"Task file: `{payload['task_file']}`",
        f"Observed cells: `{payload['observed_cells']}/{payload['expected_cells']}`",
        f"Budgets: `{payload['budgets']}`",
        "",
        "These metrics are trajectory action-budget scores, not exact ranked top-k scores.",
        "They rescore each selected trajectory using the first k non-neutral actions.",
        "",
        "## Metrics",
        "",
        "- `Capability@k`: mean capability coverage after k non-neutral actions.",
        "- `Correct route/tool@k`: exact task success under the capability scorer after k actions.",
        "- `Handoff score@k`: execution handoff score where available.",
        "",
        "## Validation",
        "",
        f"- Existing aggregate comparison available: `{validation.get('available')}`",
        f"- Max abs numeric diff at @3: `{validation.get('max_abs_numeric_diff')}`",
        f"- Mean abs numeric diff at @3: `{validation.get('mean_abs_numeric_diff')}`",
        "",
        "## Outputs",
        "",
        "- `TOOL_SELECTION_TOP60_ACTION_BUDGET_METRICS_20260514.json`",
        "- `TOOL_SELECTION_TOP60_ACTION_BUDGET_METRICS_LONG_20260514.csv`",
        "- `TOOL_SELECTION_TOP60_ACTION_BUDGET_ROWS_20260514.csv`",
    ]
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-jsonl", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--existing-aggregate", type=Path, default=DEFAULT_EXISTING_AGG)
    parser.add_argument("--budgets", type=int, nargs="+", default=list(DEFAULT_BUDGETS))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    budgets = tuple(sorted(set(args.budgets)))
    tasks = {str(task["task_id"]): task for task in load_tasks(args.tasks_jsonl)}
    cells, source_counts = collect_best_cells(
        tasks_by_id=tasks,
        runs_dir=args.runs_dir,
        budgets=budgets,
    )
    payload = build_outputs(
        cells=cells,
        tasks_by_id=tasks,
        budgets=budgets,
        source_counts=source_counts,
        existing_agg=args.existing_aggregate,
    )
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "TOOL_SELECTION_TOP60_ACTION_BUDGET_METRICS_20260514.json"
    long_csv = out_dir / "TOOL_SELECTION_TOP60_ACTION_BUDGET_METRICS_LONG_20260514.csv"
    row_csv = out_dir / "TOOL_SELECTION_TOP60_ACTION_BUDGET_ROWS_20260514.csv"
    md_path = out_dir / "TOOL_SELECTION_TOP60_ACTION_BUDGET_METRICS_20260514.md"
    write_json(json_path, payload)
    write_csv(
        long_csv,
        payload["long_rows"],
        fieldnames=[
            "model",
            "model_key",
            "mode",
            "budget",
            "metric",
            "metric_label",
            "value",
            "plot_value",
            "known_n",
            "expected_n",
            "observed_n",
        ],
    )
    write_csv(
        row_csv,
        payload["row_budget_rows"],
        fieldnames=[
            "model",
            "model_key",
            "mode",
            "task_id",
            "budget",
            "capability_score",
            "correct",
            "correct_rate",
            "execution_handoff_score",
            "first_task_relevant_action_index",
            "n_selected_non_neutral_actions",
            "source_run",
            "source_file",
        ],
    )
    md_path.write_text(markdown_report(payload), encoding="utf-8")
    print(json.dumps({
        "json": str(json_path),
        "long_csv": str(long_csv),
        "row_csv": str(row_csv),
        "observed_cells": payload["observed_cells"],
        "expected_cells": payload["expected_cells"],
        "max_abs_diff_at_3": payload["validation_against_existing_top60_at_budget_3"].get(
            "max_abs_numeric_diff"
        ),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
