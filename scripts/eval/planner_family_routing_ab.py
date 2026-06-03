#!/usr/bin/env python3
"""A/B evaluate planner KG-fallback family-card routing.

This is an instrumentation harness only. It measures the cards-sensitive
unified-planner tail proxy:

    ToolRetriever.select_families_by_query(query)
    -> ToolRetriever.retrieve_tools(query, family_ids=..., filters=None)

It does not instantiate UnifiedPlanner, does not route through
implementation_router, and does not change production defaults. It does mirror
the current UnifiedPlanner KG-only fallback's post-retrieval modality gate so
the reported selected_tool_id is the post-gate planner candidate, while
raw_top_tool_ids preserves the unfiltered retriever output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from brain_researcher.services.agent.planner.catalog_loader import (  # noqa: E402
    get_capability_index,
)
from brain_researcher.services.shared.planner.models import (  # noqa: E402
    normalize_modality,
)

DEFAULT_LABELS = (
    ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "microtooling_exact_labels.manual_curated.v2.labels.jsonl"
)
MODES = ("legacy", "cards")

_MODALITY_HINTS: dict[str, tuple[str, ...]] = {
    "fmri": (
        "fmri",
        "f-mri",
        "bold",
        "resting-state",
        "resting state",
        "functional mri",
        "functional connectivity",
    ),
    "smri": (
        "smri",
        "structural mri",
        "t1w",
        "t1-weighted",
        "t1 weighted",
        "cortical thickness",
        "freesurfer",
        "morphometry",
    ),
    "dmri": ("dmri", "dwi", "diffusion", "dti", "tractography"),
    "eeg": ("eeg",),
    "meg": ("meg",),
    "pet": ("pet",),
    "behavior": ("behavior", "behaviour", "questionnaire", "cognitive score"),
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        raw = value
    else:
        raw = re.split(r"[,;]", str(value))
    return [str(item).strip() for item in raw if str(item).strip()]


def _normalize_modalities(value: Any) -> list[str]:
    out: list[str] = []
    for item in _as_list(value):
        try:
            normalized = normalize_modality(item)
        except Exception:
            normalized = str(item).strip().lower()
        if normalized and normalized not in out:
            out.append(normalized)
    return out


def _requested_modalities(row: Mapping[str, Any]) -> tuple[list[str], str]:
    requested: list[str] = []
    for key in (
        "modality",
        "modalities",
        "requested_modality",
        "requested_modalities",
    ):
        requested.extend(_normalize_modalities(row.get(key)))

    exact = row.get("exact_labels")
    if isinstance(exact, Mapping):
        requested.extend(
            _normalize_modalities(
                exact.get("modality")
                or exact.get("modalities")
                or exact.get("requested_modality")
                or exact.get("requested_modalities")
            )
        )
    if requested:
        return sorted(set(requested)), "label"

    query = str(row.get("query") or "").lower()
    inferred = [
        modality
        for modality, hints in _MODALITY_HINTS.items()
        if any(hint in query for hint in hints)
    ]
    return sorted(set(inferred)), "query_hint" if inferred else "none"


@contextmanager
def _family_routing_mode(mode: str) -> Iterator[None]:
    original = os.environ.get("BR_TOOL_FAMILY_ROUTING_MODE")
    try:
        os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] = mode
        yield
    finally:
        if original is None:
            os.environ.pop("BR_TOOL_FAMILY_ROUTING_MODE", None)
        else:
            os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] = original


def _make_tool_retriever(
    *,
    neo4j_uri: str | None = None,
    neo4j_user: str | None = None,
    neo4j_password: str | None = None,
    enable_semantic: bool | None = None,
) -> Any:
    from brain_researcher.services.agent.tool_retriever import ToolRetriever

    return ToolRetriever(
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
        enable_semantic=enable_semantic,
    )


def _load_tool_modalities() -> dict[str, list[str]]:
    index = get_capability_index(include_local_first=True)
    return {
        str(tool_id): _normalize_modalities(getattr(tool, "modality", None))
        for tool_id, tool in index.by_id.items()
    }


def _tool_id(match: Any) -> str:
    return str(getattr(match, "id", "") or "").strip()


def _tool_score(match: Any) -> float | None:
    try:
        return float(getattr(match, "score", None))
    except (TypeError, ValueError):
        return None


def _modality_summary(
    tool_ids: Sequence[str],
    requested_modalities: Sequence[str],
    tool_modalities: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    requested = set(requested_modalities)
    tools: list[dict[str, Any]] = []
    empty_count = 0
    mismatch_count = 0
    for tool_id in tool_ids:
        modalities = list(tool_modalities.get(tool_id, []) or [])
        empty = not modalities
        mismatch = bool(requested and modalities and not (requested & set(modalities)))
        empty_count += int(empty)
        mismatch_count += int(mismatch)
        tools.append(
            {
                "tool_id": tool_id,
                "modalities": modalities,
                "empty_modality": empty,
                "modality_mismatch": mismatch,
            }
        )
    selected = tools[0] if tools else None
    return {
        "tools": tools,
        "candidate_empty_modality_count": empty_count,
        "candidate_modality_mismatch_count": mismatch_count,
        "selected_empty_modality": bool(selected and selected["empty_modality"]),
        "selected_modality_mismatch": bool(selected and selected["modality_mismatch"]),
        "selected_modalities": (selected or {}).get("modalities") or [],
    }


def _apply_planner_modality_gate(
    tool_ids: Sequence[str],
    requested_modalities: Sequence[str],
    tool_modalities: Mapping[str, Sequence[str]],
) -> tuple[list[str], list[str]]:
    """Mirror UnifiedPlanner KG fallback modality semantics.

    Empty tool modality is treated as match-all. Explicit disjoint modality is
    rejected after retrieval, not filtered in Cypher.
    """
    requested = set(requested_modalities)
    if not requested:
        return list(tool_ids), []

    kept: list[str] = []
    rejected: list[str] = []
    for tool_id in tool_ids:
        modalities = set(tool_modalities.get(tool_id, []) or [])
        if modalities and not (requested & modalities):
            rejected.append(tool_id)
        else:
            kept.append(tool_id)
    return kept, rejected


def _collect_mode_predictions(
    *,
    mode: str,
    labels: Sequence[Mapping[str, Any]],
    max_families: int,
    top_k: int,
    disable_gfs: bool,
    retriever_factory: Callable[[], Any],
    tool_modalities: Mapping[str, Sequence[str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with _family_routing_mode(mode):
        retriever = retriever_factory()
        try:
            for label in labels:
                task_id = str(label.get("task_id") or "").strip()
                query = str(label.get("query") or "").strip()
                if not task_id or not query:
                    continue

                requested, requested_source = _requested_modalities(label)
                started = time.perf_counter()
                kg_families = list(
                    retriever.select_families_by_query(
                        query,
                        llm=None,
                        max_families=max_families,
                    )
                    or []
                )
                matches: list[Any] = []
                if kg_families:
                    # Match unified_planner.py's cards-sensitive call shape. Keep
                    # filters=None so empty-modality behavior is measured, not hidden.
                    matches = list(
                        retriever.retrieve_tools(
                            query=query,
                            family_ids=kg_families,
                            top_k=top_k,
                            filters={"disable_gfs": True} if disable_gfs else None,
                        )
                        or []
                    )
                latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
                raw_tool_ids = [_tool_id(match) for match in matches if _tool_id(match)]
                tool_ids, rejected_for_modality = _apply_planner_modality_gate(
                    raw_tool_ids,
                    requested,
                    tool_modalities,
                )
                raw_modality = _modality_summary(
                    raw_tool_ids,
                    requested,
                    tool_modalities,
                )
                post_gate_modality = _modality_summary(
                    tool_ids,
                    requested,
                    tool_modalities,
                )
                rows.append(
                    {
                        "task_id": task_id,
                        "mode": mode,
                        "query": query,
                        "requested_modalities": requested,
                        "requested_modalities_source": requested_source,
                        "kg_families": kg_families,
                        "has_kg_families": bool(kg_families),
                        "would_reach_kg_fallback_proxy": bool(kg_families),
                        "raw_top_tool_ids": raw_tool_ids,
                        "top_tool_ids": tool_ids,
                        "top_tool_scores": [
                            _tool_score(match) for match in matches if _tool_id(match)
                        ],
                        "raw_selected_tool_id": (
                            raw_tool_ids[0] if raw_tool_ids else None
                        ),
                        "selected_tool_id": tool_ids[0] if tool_ids else None,
                        "raw_candidate_count": len(raw_tool_ids),
                        "candidate_count": len(tool_ids),
                        "modality_rejected_tool_ids": rejected_for_modality,
                        "modality_rejected_count": len(rejected_for_modality),
                        "latency_ms": latency_ms,
                        "raw_modality": raw_modality,
                        "raw_candidate_empty_modality_count": raw_modality[
                            "candidate_empty_modality_count"
                        ],
                        "raw_candidate_modality_mismatch_count": raw_modality[
                            "candidate_modality_mismatch_count"
                        ],
                        "raw_selected_empty_modality": raw_modality[
                            "selected_empty_modality"
                        ],
                        "raw_selected_modality_mismatch": raw_modality[
                            "selected_modality_mismatch"
                        ],
                        **post_gate_modality,
                    }
                )
        finally:
            close = getattr(retriever, "close", None)
            if callable(close):
                close()
    return rows


def collect_predictions(
    *,
    labels_jsonl: Path,
    max_tasks: int | None,
    max_families: int,
    top_k: int,
    disable_gfs: bool = False,
    retriever_factory: Callable[[], Any] | None = None,
    tool_modalities: Mapping[str, Sequence[str]] | None = None,
) -> list[dict[str, Any]]:
    labels = _load_jsonl(labels_jsonl)
    if max_tasks is not None:
        labels = labels[: max(0, max_tasks)]
    retriever_factory = retriever_factory or _make_tool_retriever
    tool_modalities = (
        tool_modalities if tool_modalities is not None else _load_tool_modalities()
    )

    rows: list[dict[str, Any]] = []
    for mode in MODES:
        rows.extend(
            _collect_mode_predictions(
                mode=mode,
                labels=labels,
                max_families=max_families,
                top_k=top_k,
                disable_gfs=disable_gfs,
                retriever_factory=retriever_factory,
                tool_modalities=tool_modalities,
            )
        )
    return rows


def _mode_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    selected_rows = [row for row in rows if row.get("selected_tool_id")]
    return {
        "task_count": len(rows),
        "has_kg_families_count": sum(1 for row in rows if row.get("has_kg_families")),
        "would_reach_kg_fallback_proxy_count": sum(
            1 for row in rows if row.get("would_reach_kg_fallback_proxy")
        ),
        "selected_tool_count": len(selected_rows),
        "raw_top_candidate_total": sum(
            int(row.get("raw_candidate_count") or 0) for row in rows
        ),
        "top_candidate_total": sum(
            int(row.get("candidate_count") or 0) for row in rows
        ),
        "modality_rejected_total": sum(
            int(row.get("modality_rejected_count") or 0) for row in rows
        ),
        "modality_rejected_case_count": sum(
            1 for row in rows if int(row.get("modality_rejected_count") or 0) > 0
        ),
        "raw_candidate_empty_modality_total": sum(
            int(row.get("raw_candidate_empty_modality_count") or 0) for row in rows
        ),
        "raw_candidate_empty_modality_case_count": sum(
            1
            for row in rows
            if int(row.get("raw_candidate_empty_modality_count") or 0) > 0
        ),
        "raw_selected_empty_modality_count": sum(
            1 for row in rows if row.get("raw_selected_empty_modality")
        ),
        "raw_candidate_modality_mismatch_total": sum(
            int(row.get("raw_candidate_modality_mismatch_count") or 0) for row in rows
        ),
        "raw_candidate_modality_mismatch_case_count": sum(
            1
            for row in rows
            if int(row.get("raw_candidate_modality_mismatch_count") or 0) > 0
        ),
        "raw_selected_modality_mismatch_count": sum(
            1 for row in rows if row.get("raw_selected_modality_mismatch")
        ),
        "candidate_empty_modality_total": sum(
            int(row.get("candidate_empty_modality_count") or 0) for row in rows
        ),
        "candidate_empty_modality_case_count": sum(
            1 for row in rows if int(row.get("candidate_empty_modality_count") or 0) > 0
        ),
        "selected_empty_modality_count": sum(
            1 for row in selected_rows if row.get("selected_empty_modality")
        ),
        "candidate_modality_mismatch_total": sum(
            int(row.get("candidate_modality_mismatch_count") or 0) for row in rows
        ),
        "candidate_modality_mismatch_case_count": sum(
            1
            for row in rows
            if int(row.get("candidate_modality_mismatch_count") or 0) > 0
        ),
        "selected_modality_mismatch_count": sum(
            1 for row in selected_rows if row.get("selected_modality_mismatch")
        ),
    }


def compare_modes(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_task_mode = {
        (str(row.get("task_id")), str(row.get("mode"))): row for row in rows
    }
    diffs: list[dict[str, Any]] = []
    for task_id in sorted({task_id for task_id, _mode in by_task_mode}):
        legacy = by_task_mode.get((task_id, "legacy"))
        cards = by_task_mode.get((task_id, "cards"))
        if legacy is None or cards is None:
            continue
        legacy_top = list(legacy.get("top_tool_ids") or [])
        cards_top = list(cards.get("top_tool_ids") or [])
        family_diff = list(legacy.get("kg_families") or []) != list(
            cards.get("kg_families") or []
        )
        top_ids_diff = legacy_top != cards_top
        selected_diff = legacy.get("selected_tool_id") != cards.get("selected_tool_id")
        if not (family_diff or top_ids_diff or selected_diff):
            continue
        diffs.append(
            {
                "task_id": task_id,
                "query": legacy.get("query") or cards.get("query"),
                "family_diff": family_diff,
                "top_tool_ids_diff": top_ids_diff,
                "selected_tool_diff": selected_diff,
                "legacy_kg_families": legacy.get("kg_families") or [],
                "cards_kg_families": cards.get("kg_families") or [],
                "legacy_selected_tool_id": legacy.get("selected_tool_id"),
                "cards_selected_tool_id": cards.get("selected_tool_id"),
                "legacy_raw_selected_tool_id": legacy.get("raw_selected_tool_id"),
                "cards_raw_selected_tool_id": cards.get("raw_selected_tool_id"),
                "legacy_modality_rejected_tool_ids": legacy.get(
                    "modality_rejected_tool_ids"
                )
                or [],
                "cards_modality_rejected_tool_ids": cards.get(
                    "modality_rejected_tool_ids"
                )
                or [],
                "legacy_top_tool_ids": legacy_top,
                "cards_top_tool_ids": cards_top,
                "legacy_selected_modality_mismatch": bool(
                    legacy.get("selected_modality_mismatch")
                ),
                "cards_selected_modality_mismatch": bool(
                    cards.get("selected_modality_mismatch")
                ),
                "legacy_selected_empty_modality": bool(
                    legacy.get("selected_empty_modality")
                ),
                "cards_selected_empty_modality": bool(
                    cards.get("selected_empty_modality")
                ),
            }
        )
    return diffs


def _summary(
    rows: Sequence[Mapping[str, Any]], diffs: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    by_mode = {mode: [row for row in rows if row.get("mode") == mode] for mode in MODES}
    by_task: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_task.setdefault(str(row.get("task_id")), []).append(row)
    return {
        "scope": (
            "planner_kg_fallback_proxy_only: select_families_by_query plus "
            "retrieve_tools with family_ids, then UnifiedPlanner-style "
            "post-retrieval modality gate"
        ),
        "modes": {
            mode: _mode_summary(mode_rows) for mode, mode_rows in by_mode.items()
        },
        "comparison": {
            "comparable_task_count": sum(
                1
                for task_rows in by_task.values()
                if {row.get("mode") for row in task_rows} == set(MODES)
            ),
            "any_mode_has_kg_families_count": sum(
                1
                for task_rows in by_task.values()
                if any(row.get("has_kg_families") for row in task_rows)
            ),
            "both_modes_have_kg_families_count": sum(
                1
                for task_rows in by_task.values()
                if all(row.get("has_kg_families") for row in task_rows)
            ),
            "any_mode_reaches_proxy_count": sum(
                1
                for task_rows in by_task.values()
                if any(row.get("would_reach_kg_fallback_proxy") for row in task_rows)
            ),
            "both_modes_reach_proxy_count": sum(
                1
                for task_rows in by_task.values()
                if all(row.get("would_reach_kg_fallback_proxy") for row in task_rows)
            ),
            "diff_count": len(diffs),
            "family_diff_count": sum(1 for row in diffs if row.get("family_diff")),
            "top_tool_ids_diff_count": sum(
                1 for row in diffs if row.get("top_tool_ids_diff")
            ),
            "selected_tool_diff_count": sum(
                1 for row in diffs if row.get("selected_tool_diff")
            ),
        },
    }


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# Planner Family Routing A/B",
        "",
        "This report measures the unified planner KG-fallback proxy only.",
        "It mirrors the post-retrieval modality gate but does not instantiate "
        "UnifiedPlanner or change production defaults.",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(summary, indent=2, sort_keys=True),
        "```",
        "",
        "## Top Tool Diffs",
        "",
        (
            "| Task | Family Diff | Selected Diff | Legacy Selected | Cards Selected "
            "| Legacy Mismatch | Cards Mismatch |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in list(payload["top_tool_diffs"])[:50]:
        lines.append(
            "| {task_id} | {family_diff} | {selected_diff} | {legacy} | {cards} | "
            "{legacy_mismatch} | {cards_mismatch} |".format(
                task_id=row["task_id"],
                family_diff=row["family_diff"],
                selected_diff=row["selected_tool_diff"],
                legacy=row.get("legacy_selected_tool_id") or "",
                cards=row.get("cards_selected_tool_id") or "",
                legacy_mismatch=row["legacy_selected_modality_mismatch"],
                cards_mismatch=row["cards_selected_modality_mismatch"],
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_ab(
    *,
    labels_jsonl: Path,
    output_dir: Path,
    max_tasks: int | None,
    max_families: int,
    top_k: int,
    disable_gfs: bool = False,
    retriever_factory: Callable[[], Any] | None = None,
    tool_modalities: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    evaluated_labels_jsonl = labels_jsonl
    if max_tasks is not None:
        limited = _load_jsonl(labels_jsonl)[: max(0, max_tasks)]
        evaluated_labels_jsonl = output_dir / "labels.evaluated.jsonl"
        _write_jsonl(evaluated_labels_jsonl, limited)

    rows = collect_predictions(
        labels_jsonl=evaluated_labels_jsonl,
        max_tasks=None,
        max_families=max_families,
        top_k=top_k,
        disable_gfs=disable_gfs,
        retriever_factory=retriever_factory,
        tool_modalities=tool_modalities,
    )
    diffs = compare_modes(rows)
    payload = {
        "summary": {
            "labels_jsonl": str(evaluated_labels_jsonl),
            "source_labels_jsonl": str(labels_jsonl),
            "output_dir": str(output_dir),
            "max_tasks": max_tasks,
            "max_families": max_families,
            "top_k": top_k,
            "disable_gfs": disable_gfs,
            **_summary(rows, diffs),
        },
        "predictions": rows,
        "top_tool_diffs": diffs,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(payload["summary"], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_jsonl(output_dir / "predictions.jsonl", rows)
    _write_jsonl(output_dir / "top_tool_diffs.jsonl", diffs)
    _write_markdown(output_dir / "report.md", payload)
    return payload


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        Path(os.environ.get("TMPDIR", "/tmp")) / "br_planner_family_routing_ab" / stamp
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-jsonl", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--max-tasks", type=int, default=None)
    parser.add_argument("--max-families", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--disable-gfs",
        action="store_true",
        help=(
            "Pass filters={disable_gfs: true} to ToolRetriever.retrieve_tools. "
            "Use this to isolate family routing from file-search permission/latency noise."
        ),
    )
    parser.add_argument("--neo4j-uri", type=str, default=None)
    parser.add_argument("--neo4j-user", type=str, default=None)
    parser.add_argument("--neo4j-password", type=str, default=None)
    parser.add_argument(
        "--disable-semantic",
        action="store_true",
        help="Pass enable_semantic=False to ToolRetriever for local debugging.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    output_dir = args.output_dir or _default_output_dir()

    def factory() -> Any:
        return _make_tool_retriever(
            neo4j_uri=args.neo4j_uri,
            neo4j_user=args.neo4j_user,
            neo4j_password=args.neo4j_password,
            enable_semantic=False if args.disable_semantic else None,
        )

    payload = run_ab(
        labels_jsonl=args.labels_jsonl,
        output_dir=output_dir,
        max_tasks=args.max_tasks,
        max_families=args.max_families,
        top_k=args.top_k,
        disable_gfs=args.disable_gfs,
        retriever_factory=factory,
    )
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
