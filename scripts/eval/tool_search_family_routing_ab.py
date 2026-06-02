#!/usr/bin/env python3
"""A/B evaluate legacy vs family-card MCP tool_search routing.

This is a measurement harness only. It does not change
BR_TOOL_FAMILY_ROUTING_MODE defaults.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.eval import evaluate_exact_tool_routing as exact_eval

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LABELS = (
    ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "microtooling_exact_labels.manual_curated.v2.labels.jsonl"
)
DEFAULT_RUNS_DIR = (
    ROOT / "benchmarks" / "tool_routing_validation" / "family_card_ab" / "runs"
)
MODES = ("legacy", "cards")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
    return rows


@contextmanager
def _tool_search_mode(mode: str) -> Iterator[None]:
    original = {
        "BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE": os.environ.get(
            "BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE"
        ),
        "BR_TOOL_FAMILY_ROUTING_MODE": os.environ.get("BR_TOOL_FAMILY_ROUTING_MODE"),
    }
    try:
        if mode == "cards":
            os.environ["BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE"] = "cards"
            os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] = "cards"
        else:
            os.environ["BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE"] = "legacy"
            os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] = "legacy"
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run_tool_search(query: str, *, limit: int, exposed_only: bool) -> dict[str, Any]:
    from brain_researcher.services.mcp import server as srv

    return srv.tool_search(
        query=query,
        limit=limit,
        exposed_only=exposed_only,
        include_workflows=True,
        include_total=True,
    )


def _tool_ids(payload: dict[str, Any]) -> list[str]:
    tools = payload.get("tools") if isinstance(payload, dict) else []
    out: list[str] = []
    for item in tools or []:
        if not isinstance(item, dict):
            continue
        tool_id = str(
            item.get("name") or item.get("id") or item.get("canonical_tool_id") or ""
        ).strip()
        if tool_id:
            out.append(tool_id)
    return out


def collect_predictions(
    *,
    labels_jsonl: Path,
    limit: int,
    exposed_only: bool,
    max_tasks: int | None,
) -> list[dict[str, Any]]:
    labels = _load_jsonl(labels_jsonl)
    if max_tasks is not None:
        labels = labels[: max(0, max_tasks)]

    predictions: list[dict[str, Any]] = []
    for label in labels:
        task_id = str(label.get("task_id") or "").strip()
        query = str(label.get("query") or "").strip()
        if not task_id or not query:
            continue
        for mode in MODES:
            started = time.perf_counter()
            with _tool_search_mode(mode):
                payload = _run_tool_search(
                    query,
                    limit=limit,
                    exposed_only=exposed_only,
                )
            latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
            predictions.append(
                {
                    "task_id": task_id,
                    "mode": mode,
                    "query": query,
                    "top_tool_ids": _tool_ids(payload),
                    "total_matches": (
                        payload.get("total_matches")
                        if isinstance(payload, dict)
                        else None
                    ),
                    "ok": bool(isinstance(payload, dict) and payload.get("ok")),
                    "latency_ms": latency_ms,
                }
            )
    return predictions


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _compare_rows(
    legacy_rows: Sequence[dict[str, Any]],
    cards_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_legacy = {str(row.get("task_id")): row for row in legacy_rows}
    by_cards = {str(row.get("task_id")): row for row in cards_rows}
    rows: list[dict[str, Any]] = []
    for task_id in sorted(set(by_legacy) & set(by_cards)):
        legacy = by_legacy[task_id]
        cards = by_cards[task_id]
        legacy_hit = bool(legacy.get("tool_recall_at_1"))
        cards_hit = bool(cards.get("tool_recall_at_1"))
        if legacy_hit == cards_hit:
            continue
        rows.append(
            {
                "task_id": task_id,
                "delta": "cards_gain" if cards_hit else "cards_regression",
                "legacy_top": (legacy.get("predicted_tool_ids") or [""])[0],
                "cards_top": (cards.get("predicted_tool_ids") or [""])[0],
                "expected_tool_ids": legacy.get("expected_tool_ids") or [],
                "acceptable_tool_ids": legacy.get("acceptable_tool_ids") or [],
            }
        )
    return rows


def _summary_delta(
    legacy_summary: dict[str, Any],
    cards_summary: dict[str, Any],
) -> dict[str, Any]:
    keys = [
        "tool_recall_at_1",
        "tool_recall_at_3",
        "tool_recall_at_5",
        "family_recall_at_1",
        "family_recall_at_3",
        "family_recall_at_5",
        "wrong_tool_top1_rate",
        "latency_mean_ms",
    ]
    out: dict[str, Any] = {}
    for key in keys:
        legacy = legacy_summary.get(key)
        cards = cards_summary.get(key)
        if isinstance(legacy, int | float) and isinstance(cards, int | float):
            out[f"{key}_delta_cards_minus_legacy"] = cards - legacy
    return out


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# Family-Card Tool Search A/B",
        "",
        "Default runtime mode is unchanged. This report compares legacy and cards mode.",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(summary, indent=2, sort_keys=True),
        "```",
        "",
        "## Top-1 Deltas",
        "",
        "| Task | Delta | Legacy Top | Cards Top | Expected | Acceptable |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["top1_deltas"][:50]:
        lines.append(
            "| {task_id} | {delta} | {legacy_top} | {cards_top} | {expected} | {acceptable} |".format(
                task_id=row["task_id"],
                delta=row["delta"],
                legacy_top=row["legacy_top"],
                cards_top=row["cards_top"],
                expected=", ".join(row["expected_tool_ids"]),
                acceptable=", ".join(row["acceptable_tool_ids"]),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_ab(
    *,
    labels_jsonl: Path,
    output_dir: Path,
    limit: int,
    exposed_only: bool,
    max_tasks: int | None,
    k_values: Sequence[int],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    eval_labels_jsonl = labels_jsonl
    if max_tasks is not None:
        limited_labels = _load_jsonl(labels_jsonl)[: max(0, max_tasks)]
        eval_labels_jsonl = output_dir / "labels.evaluated.jsonl"
        _write_jsonl(eval_labels_jsonl, limited_labels)

    predictions = collect_predictions(
        labels_jsonl=eval_labels_jsonl,
        limit=limit,
        exposed_only=exposed_only,
        max_tasks=None,
    )
    predictions_path = output_dir / "predictions.json"
    predictions_path.write_text(json.dumps(predictions, indent=2), encoding="utf-8")

    legacy_eval = exact_eval.evaluate(
        labels_jsonl=eval_labels_jsonl,
        predictions_json=predictions_path,
        mode="legacy",
        k_values=k_values,
    )
    cards_eval = exact_eval.evaluate(
        labels_jsonl=eval_labels_jsonl,
        predictions_json=predictions_path,
        mode="cards",
        k_values=k_values,
    )
    top1_deltas = _compare_rows(legacy_eval["rows"], cards_eval["rows"])
    payload = {
        "summary": {
            "labels_jsonl": str(eval_labels_jsonl),
            "source_labels_jsonl": str(labels_jsonl),
            "output_dir": str(output_dir),
            "limit": limit,
            "exposed_only": exposed_only,
            "max_tasks": max_tasks,
            "legacy": legacy_eval["summary"],
            "cards": cards_eval["summary"],
            "delta": _summary_delta(legacy_eval["summary"], cards_eval["summary"]),
            "top1_delta_count": len(top1_deltas),
        },
        "top1_deltas": top1_deltas,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_jsonl(output_dir / "legacy_rows.jsonl", legacy_eval["rows"])
    _write_jsonl(output_dir / "cards_rows.jsonl", cards_eval["rows"])
    _write_jsonl(output_dir / "top1_deltas.jsonl", top1_deltas)
    _write_markdown(output_dir / "report.md", payload)
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-jsonl", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-tasks", type=int, default=None)
    parser.add_argument(
        "--exposed-only", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--k",
        dest="k_values",
        action="append",
        type=int,
        default=[],
        help="Recall cutoff. Can be repeated; defaults to 1,3,5.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or DEFAULT_RUNS_DIR / stamp
    payload = run_ab(
        labels_jsonl=args.labels_jsonl,
        output_dir=output_dir,
        limit=args.limit,
        exposed_only=args.exposed_only,
        max_tasks=args.max_tasks,
        k_values=args.k_values or [1, 3, 5],
    )
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
