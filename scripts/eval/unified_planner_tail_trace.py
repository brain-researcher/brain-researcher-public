#!/usr/bin/env python3
"""Trace UnifiedPlanner tail routing on curated tool labels.

This is an instrumentation harness. It runs labels through
``UnifiedPlanner.plan`` and records planner-tail routing signals:

* whether the catalog ``select_tools`` call produced base candidates
* whether KG families were selected
* whether the KG-only fallback branch was used
* final ``chosen_tool_id``
* selected-tool modality mismatch
* planner constraints/diagnostics that expose KG and modality-gate behavior

It does not execute selected tools and does not modify production planner code.
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import brain_researcher.services.agent.planner.unified_planner as planner_module  # noqa: E402
from brain_researcher.services.agent.planner.catalog_loader import (  # noqa: E402
    get_capability_index,
    get_tool_by_id,
)
from brain_researcher.services.agent.planner.unified_planner import (  # noqa: E402
    UnifiedPlanner,
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
        "brain volume",
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


@dataclass
class SelectToolsTrace:
    called: bool = False
    candidate_count: int = 0
    available_candidate_count: int = 0
    top_tool_ids: list[str] = field(default_factory=list)
    max_results: int | None = None
    require_preflight_pass: bool | None = None
    include_local_first: bool | None = None
    allowed_tool_count: int | None = None
    error: str | None = None


@dataclass
class RetrieverTrace:
    family_calls: int = 0
    retrieve_calls: int = 0
    kg_families: list[str] = field(default_factory=list)
    raw_kg_tool_ids: list[str] = field(default_factory=list)
    retrieve_filters: list[dict[str, Any] | None] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class NullEvidenceReader:
    """Avoid default Neo4j evidence reads in an eval harness."""

    def read_stats(self, **_: Any) -> dict[str, Any]:
        return {}


class TracingToolRetriever:
    """Wrap ToolRetriever calls without changing UnifiedPlanner."""

    def __init__(self, inner: Any, *, disable_gfs: bool = False) -> None:
        self.inner = inner
        self.disable_gfs = disable_gfs
        self.trace = RetrieverTrace()

    def reset(self) -> None:
        self.trace = RetrieverTrace()

    def select_families_by_query(
        self, query: str, llm: Any = None, max_families: int = 3
    ) -> list[str]:
        self.trace.family_calls += 1
        try:
            families = self.inner.select_families_by_query(
                query, llm=llm, max_families=max_families
            )
        except Exception as exc:
            self.trace.errors.append(f"select_families_by_query:{type(exc).__name__}")
            raise
        if not families:
            self.trace.kg_families = []
            return []
        self.trace.kg_families = [str(family) for family in families if family]
        return self.trace.kg_families

    def retrieve_tools(
        self,
        query: str,
        family_ids: list[str] | None = None,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[Any]:
        self.trace.retrieve_calls += 1
        effective_filters = dict(filters or {})
        if self.disable_gfs:
            effective_filters["disable_gfs"] = True
        filters_arg = effective_filters or None
        self.trace.retrieve_filters.append(filters_arg)
        try:
            matches = self.inner.retrieve_tools(
                query=query,
                family_ids=family_ids,
                top_k=top_k,
                filters=filters_arg,
            )
        except TypeError:
            matches = self.inner.retrieve_tools(
                query=query,
                family_ids=family_ids,
                top_k=top_k,
            )
        except Exception as exc:
            self.trace.errors.append(f"retrieve_tools:{type(exc).__name__}")
            raise
        out = list(matches or [])
        self.trace.raw_kg_tool_ids = [
            str(getattr(match, "id", "") or "").strip()
            for match in out
            if str(getattr(match, "id", "") or "").strip()
        ]
        return out

    def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if callable(close):
            close()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


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


def _planner_modality_arg(requested_modalities: Sequence[str]) -> str | None:
    return requested_modalities[0] if len(requested_modalities) == 1 else None


def _expected_labels(row: Mapping[str, Any]) -> dict[str, list[str]]:
    exact = row.get("exact_labels")
    if not isinstance(exact, Mapping):
        return {
            "expected_tool_ids": [],
            "acceptable_tool_ids": [],
            "expected_family_ids": [],
        }
    return {
        "expected_tool_ids": _as_list(exact.get("expected_tool_ids")),
        "acceptable_tool_ids": _as_list(exact.get("acceptable_tool_ids")),
        "expected_family_ids": _as_list(exact.get("expected_family_ids")),
    }


def _load_tool_modalities() -> dict[str, list[str]]:
    index = get_capability_index(include_local_first=True)
    return {
        str(tool_id): _normalize_modalities(
            getattr(tool, "modality", None) or getattr(tool, "modalities", None)
        )
        for tool_id, tool in index.by_id.items()
    }


def _tool_modalities(
    tool_id: str | None, tool_modalities: Mapping[str, Sequence[str]]
) -> list[str]:
    if not tool_id:
        return []
    if tool_id in tool_modalities:
        return list(tool_modalities.get(tool_id) or [])
    tool = get_tool_by_id(tool_id)
    if tool is None:
        return []
    return _normalize_modalities(
        getattr(tool, "modality", None) or getattr(tool, "modalities", None)
    )


def _selected_modality_mismatch(
    chosen_tool_id: str | None,
    requested_modalities: Sequence[str],
    tool_modalities: Mapping[str, Sequence[str]],
) -> tuple[bool, list[str]]:
    modalities = _tool_modalities(chosen_tool_id, tool_modalities)
    requested = set(requested_modalities)
    mismatch = bool(
        chosen_tool_id
        and requested
        and modalities
        and not requested.intersection(modalities)
    )
    return mismatch, modalities


def _candidate_tool_ids(candidates: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        str(row.get("tool_id") or "").strip()
        for row in candidates
        if str(row.get("tool_id") or "").strip()
    ]


def _candidate_source_counts(candidates: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in candidates:
        source = str(row.get("source") or "catalog")
        counts[source] = counts.get(source, 0) + 1
    return counts


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


@contextmanager
def _trace_select_tools(
    trace: SelectToolsTrace,
    *,
    select_tools_func: Callable[..., Sequence[Any]] | None = None,
) -> Iterator[None]:
    original = planner_module.select_tools
    delegate = select_tools_func or original

    def wrapper(*args: Any, **kwargs: Any) -> list[Any]:
        trace.called = True
        trace.max_results = kwargs.get("max_results")
        trace.require_preflight_pass = kwargs.get("require_preflight_pass")
        trace.include_local_first = kwargs.get("include_local_first")
        allowed = kwargs.get("allowed_tool_ids")
        trace.allowed_tool_count = len(allowed) if allowed is not None else None
        try:
            candidates = list(delegate(*args, **kwargs) or [])
        except Exception as exc:
            trace.error = type(exc).__name__
            raise
        trace.candidate_count = len(candidates)
        trace.available_candidate_count = sum(
            1 for cand in candidates if bool(getattr(cand, "available", True))
        )
        trace.top_tool_ids = [
            str(getattr(getattr(cand, "tool", None), "id", "") or "").strip()
            for cand in candidates[:10]
            if str(getattr(getattr(cand, "tool", None), "id", "") or "").strip()
        ]
        return candidates

    planner_module.select_tools = wrapper
    try:
        yield
    finally:
        planner_module.select_tools = original


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


def _result_row(
    *,
    label: Mapping[str, Any],
    mode: str,
    select_trace: SelectToolsTrace,
    retriever_trace: RetrieverTrace,
    result: Any,
    requested_modalities: Sequence[str],
    requested_source: str,
    modality_arg: str | None,
    latency_ms: float,
    tool_modalities: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    candidates = list(getattr(result, "candidates", None) or [])
    chosen_tool_id = getattr(result, "chosen_tool_id", None)
    chosen_tool_id = str(chosen_tool_id) if chosen_tool_id else None
    selected_mismatch, selected_modalities = _selected_modality_mismatch(
        chosen_tool_id, requested_modalities, tool_modalities
    )
    kg_only_fallback_used = bool(
        select_trace.called
        and select_trace.candidate_count == 0
        and retriever_trace.retrieve_calls > 0
    )
    row = {
        "task_id": str(label.get("task_id") or "").strip(),
        "mode": mode,
        "query": str(label.get("query") or "").strip(),
        "requested_modalities": list(requested_modalities),
        "requested_modalities_source": requested_source,
        "planner_modality_arg": modality_arg,
        **_expected_labels(label),
        "base_select_tools_called": select_trace.called,
        "base_candidate_count": select_trace.candidate_count,
        "base_available_candidate_count": select_trace.available_candidate_count,
        "base_select_tools_produced_candidates": select_trace.candidate_count > 0,
        "base_top_tool_ids": select_trace.top_tool_ids,
        "kg_family_call_count": retriever_trace.family_calls,
        "kg_retrieve_call_count": retriever_trace.retrieve_calls,
        "kg_families": list(
            getattr(result, "kg_families", None) or retriever_trace.kg_families
        ),
        "kg_families_selected": bool(
            getattr(result, "kg_families", None) or retriever_trace.kg_families
        ),
        "kg_raw_tool_ids": retriever_trace.raw_kg_tool_ids,
        "kg_retrieve_filters": retriever_trace.retrieve_filters,
        "kg_only_fallback_used": kg_only_fallback_used,
        "chosen_tool_id": chosen_tool_id,
        "candidate_tool_ids": _candidate_tool_ids(candidates),
        "candidate_count": len(candidates),
        "candidate_source_counts": _candidate_source_counts(candidates),
        "selected_modalities": selected_modalities,
        "selected_modality_mismatch": selected_mismatch,
        "confidence_score": getattr(result, "confidence_score", None),
        "task_family": getattr(result, "task_family", None),
        "intent": list(getattr(result, "intent", None) or []),
        "predicted_capabilities": list(
            getattr(result, "predicted_capabilities", None) or []
        ),
        "predicted_intents": list(getattr(result, "predicted_intents", None) or []),
        "constraints_applied": list(getattr(result, "constraints_applied", None) or []),
        "routing_diagnostics": getattr(result, "routing_diagnostics", None) or {},
        "select_tools_trace": {
            "max_results": select_trace.max_results,
            "require_preflight_pass": select_trace.require_preflight_pass,
            "include_local_first": select_trace.include_local_first,
            "allowed_tool_count": select_trace.allowed_tool_count,
            "error": select_trace.error,
        },
        "retriever_errors": retriever_trace.errors,
        "latency_ms": round(latency_ms, 3),
    }
    return row


def _error_row(
    *,
    label: Mapping[str, Any],
    mode: str,
    select_trace: SelectToolsTrace,
    retriever_trace: RetrieverTrace,
    requested_modalities: Sequence[str],
    requested_source: str,
    modality_arg: str | None,
    exc: Exception,
    latency_ms: float,
) -> dict[str, Any]:
    return {
        "task_id": str(label.get("task_id") or "").strip(),
        "mode": mode,
        "query": str(label.get("query") or "").strip(),
        "requested_modalities": list(requested_modalities),
        "requested_modalities_source": requested_source,
        "planner_modality_arg": modality_arg,
        **_expected_labels(label),
        "error": type(exc).__name__,
        "error_message": str(exc),
        "base_select_tools_called": select_trace.called,
        "base_candidate_count": select_trace.candidate_count,
        "base_select_tools_produced_candidates": select_trace.candidate_count > 0,
        "base_top_tool_ids": select_trace.top_tool_ids,
        "kg_family_call_count": retriever_trace.family_calls,
        "kg_retrieve_call_count": retriever_trace.retrieve_calls,
        "kg_families": retriever_trace.kg_families,
        "kg_families_selected": bool(retriever_trace.kg_families),
        "kg_raw_tool_ids": retriever_trace.raw_kg_tool_ids,
        "kg_only_fallback_used": bool(
            select_trace.called
            and select_trace.candidate_count == 0
            and retriever_trace.retrieve_calls > 0
        ),
        "chosen_tool_id": None,
        "selected_modality_mismatch": False,
        "constraints_applied": [],
        "routing_diagnostics": {},
        "retriever_errors": retriever_trace.errors,
        "latency_ms": round(latency_ms, 3),
    }


def _mode_predictions(
    *,
    mode: str,
    labels: Sequence[Mapping[str, Any]],
    max_candidates: int,
    max_families: int,
    retriever_top_k: int,
    disable_gfs: bool,
    retriever_factory: Callable[[], Any],
    tool_modalities: Mapping[str, Sequence[str]],
    select_tools_func: Callable[..., Sequence[Any]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with _family_routing_mode(mode):
        retriever = TracingToolRetriever(retriever_factory(), disable_gfs=disable_gfs)
        planner = UnifiedPlanner(
            tool_retriever=retriever,
            evidence_reader=NullEvidenceReader(),
        )
        try:
            for label in labels:
                task_id = str(label.get("task_id") or "").strip()
                query = str(label.get("query") or "").strip()
                if not task_id or not query:
                    continue
                retriever.reset()
                select_trace = SelectToolsTrace()
                requested, requested_source = _requested_modalities(label)
                modality_arg = _planner_modality_arg(requested)
                started = time.perf_counter()
                try:
                    with _trace_select_tools(
                        select_trace, select_tools_func=select_tools_func
                    ):
                        result = planner.plan(
                            query=query,
                            modality=modality_arg,
                            max_candidates=max_candidates,
                            retriever_max_families=max_families,
                            retriever_top_k=retriever_top_k,
                        )
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    rows.append(
                        _result_row(
                            label=label,
                            mode=mode,
                            select_trace=select_trace,
                            retriever_trace=retriever.trace,
                            result=result,
                            requested_modalities=requested,
                            requested_source=requested_source,
                            modality_arg=modality_arg,
                            latency_ms=latency_ms,
                            tool_modalities=tool_modalities,
                        )
                    )
                except Exception as exc:
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    rows.append(
                        _error_row(
                            label=label,
                            mode=mode,
                            select_trace=select_trace,
                            retriever_trace=retriever.trace,
                            requested_modalities=requested,
                            requested_source=requested_source,
                            modality_arg=modality_arg,
                            exc=exc,
                            latency_ms=latency_ms,
                        )
                    )
        finally:
            retriever.close()
    return rows


def collect_predictions(
    *,
    labels_jsonl: Path,
    max_tasks: int | None,
    mode: str,
    max_candidates: int,
    max_families: int,
    retriever_top_k: int,
    disable_gfs: bool = False,
    retriever_factory: Callable[[], Any] | None = None,
    tool_modalities: Mapping[str, Sequence[str]] | None = None,
    select_tools_func: Callable[..., Sequence[Any]] | None = None,
) -> list[dict[str, Any]]:
    labels = _load_jsonl(labels_jsonl)
    if max_tasks is not None:
        labels = labels[: max(0, max_tasks)]
    modes = list(MODES) if mode == "both" else [mode]
    retriever_factory = retriever_factory or _make_tool_retriever
    tool_modalities = (
        tool_modalities if tool_modalities is not None else _load_tool_modalities()
    )

    rows: list[dict[str, Any]] = []
    for current_mode in modes:
        rows.extend(
            _mode_predictions(
                mode=current_mode,
                labels=labels,
                max_candidates=max_candidates,
                max_families=max_families,
                retriever_top_k=retriever_top_k,
                disable_gfs=disable_gfs,
                retriever_factory=retriever_factory,
                tool_modalities=tool_modalities,
                select_tools_func=select_tools_func,
            )
        )
    return rows


def _mode_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "task_count": len(rows),
        "error_count": sum(1 for row in rows if row.get("error")),
        "base_candidate_case_count": sum(
            1 for row in rows if row.get("base_select_tools_produced_candidates")
        ),
        "kg_family_case_count": sum(
            1 for row in rows if row.get("kg_families_selected")
        ),
        "kg_retrieve_case_count": sum(
            1 for row in rows if int(row.get("kg_retrieve_call_count") or 0) > 0
        ),
        "kg_only_fallback_case_count": sum(
            1 for row in rows if row.get("kg_only_fallback_used")
        ),
        "chosen_tool_count": sum(1 for row in rows if row.get("chosen_tool_id")),
        "selected_modality_mismatch_count": sum(
            1 for row in rows if row.get("selected_modality_mismatch")
        ),
        "candidate_total": sum(int(row.get("candidate_count") or 0) for row in rows),
        "base_candidate_total": sum(
            int(row.get("base_candidate_count") or 0) for row in rows
        ),
    }


def _summary(
    *,
    rows: Sequence[Mapping[str, Any]],
    labels_jsonl: Path,
    output_dir: Path,
    max_tasks: int | None,
    mode: str,
    max_candidates: int,
    max_families: int,
    retriever_top_k: int,
    disable_gfs: bool,
) -> dict[str, Any]:
    by_mode = {
        current_mode: [row for row in rows if row.get("mode") == current_mode]
        for current_mode in MODES
        if mode == "both" or current_mode == mode
    }
    return {
        "scope": (
            "unified_planner_plan_path_tail_trace: calls UnifiedPlanner.plan with "
            "instrumented select_tools and ToolRetriever; does not execute tools"
        ),
        "labels_jsonl": str(labels_jsonl),
        "output_dir": str(output_dir),
        "max_tasks": max_tasks,
        "mode": mode,
        "max_candidates": max_candidates,
        "max_families": max_families,
        "retriever_top_k": retriever_top_k,
        "disable_gfs": disable_gfs,
        "task_mode_rows": len(rows),
        "modes": {
            current_mode: _mode_summary(mode_rows)
            for current_mode, mode_rows in by_mode.items()
        },
        "overall": _mode_summary(rows),
    }


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# UnifiedPlanner Tail Trace",
        "",
        "This report runs labels through `UnifiedPlanner.plan` with instrumentation.",
        "It traces planner routing only; selected tools are not executed.",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(summary, indent=2, sort_keys=True),
        "```",
        "",
        "## KG-Only Fallback Cases",
        "",
        "| Task | Mode | Chosen Tool | KG Families | Modality Mismatch |",
        "| --- | --- | --- | --- | --- |",
    ]
    fallback_rows = [
        row for row in payload["predictions"] if row.get("kg_only_fallback_used")
    ]
    for row in fallback_rows[:50]:
        lines.append(
            "| {task_id} | {mode} | {chosen} | {families} | {mismatch} |".format(
                task_id=row.get("task_id") or "",
                mode=row.get("mode") or "",
                chosen=row.get("chosen_tool_id") or "",
                families=", ".join(row.get("kg_families") or []),
                mismatch=row.get("selected_modality_mismatch"),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_tail_trace(
    *,
    labels_jsonl: Path,
    output_dir: Path,
    max_tasks: int | None,
    mode: str = "both",
    max_candidates: int = 10,
    max_families: int = 3,
    retriever_top_k: int = 20,
    disable_gfs: bool = False,
    retriever_factory: Callable[[], Any] | None = None,
    tool_modalities: Mapping[str, Sequence[str]] | None = None,
    select_tools_func: Callable[..., Sequence[Any]] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = collect_predictions(
        labels_jsonl=labels_jsonl,
        max_tasks=max_tasks,
        mode=mode,
        max_candidates=max_candidates,
        max_families=max_families,
        retriever_top_k=retriever_top_k,
        disable_gfs=disable_gfs,
        retriever_factory=retriever_factory,
        tool_modalities=tool_modalities,
        select_tools_func=select_tools_func,
    )
    payload = {
        "summary": _summary(
            rows=rows,
            labels_jsonl=labels_jsonl,
            output_dir=output_dir,
            max_tasks=max_tasks,
            mode=mode,
            max_candidates=max_candidates,
            max_families=max_families,
            retriever_top_k=retriever_top_k,
            disable_gfs=disable_gfs,
        ),
        "predictions": rows,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(payload["summary"], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_jsonl(output_dir / "predictions.jsonl", rows)
    _write_markdown(output_dir / "report.md", payload)
    return payload


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip("'\"")
        os.environ[key] = value


def _load_runtime_env() -> None:
    _load_env_file(ROOT / ".env")
    _load_env_file(ROOT / ".env.local")


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(os.environ.get("TMPDIR", "/tmp")) / "br_unified_planner_tail" / stamp


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-jsonl", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--max-tasks", type=int, default=None)
    parser.add_argument("--mode", choices=("legacy", "cards", "both"), default="both")
    parser.add_argument("--max-candidates", type=int, default=10)
    parser.add_argument("--max-families", type=int, default=3)
    parser.add_argument("--retriever-top-k", type=int, default=20)
    parser.add_argument(
        "--disable-gfs",
        action="store_true",
        help="Pass filters={disable_gfs: true} through the retriever wrapper.",
    )
    parser.add_argument(
        "--load-env",
        action="store_true",
        help="Load repo .env/.env.local at runtime without printing values.",
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
    if args.load_env:
        _load_runtime_env()
    output_dir = args.output_dir or _default_output_dir()

    def factory() -> Any:
        return _make_tool_retriever(
            neo4j_uri=args.neo4j_uri,
            neo4j_user=args.neo4j_user,
            neo4j_password=args.neo4j_password,
            enable_semantic=False if args.disable_semantic else None,
        )

    payload = run_tail_trace(
        labels_jsonl=args.labels_jsonl,
        output_dir=output_dir,
        max_tasks=args.max_tasks,
        mode=args.mode,
        max_candidates=args.max_candidates,
        max_families=args.max_families,
        retriever_top_k=args.retriever_top_k,
        disable_gfs=args.disable_gfs,
        retriever_factory=factory,
    )
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
