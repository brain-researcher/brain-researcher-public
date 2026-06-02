"""KG multi-hop QA tool-call preview helpers.

Pure functions that inspect raw tool_call dicts (as stored on chat reply
messages) and build a structured ``result_preview`` payload for the UI.
No Flask, no I/O, no side-effects — safe to import anywhere.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Low-level name / tool-identity helpers
# ---------------------------------------------------------------------------


def _normalize_tool_name(value: Any) -> str:
    """Normalize tool identifiers for robust matching."""
    if value is None:
        return ""
    return str(value).strip().lower()


def _is_kg_multihop_qa_tool_call(tool_call: dict[str, Any]) -> bool:
    """Return True when a tool_call record represents kg_multihop_qa."""
    names: list[Any] = [
        tool_call.get("name"),
        tool_call.get("tool"),
        tool_call.get("function_name"),
    ]
    plan = tool_call.get("plan")
    if isinstance(plan, dict):
        names.extend([plan.get("tool"), plan.get("leaf_runtime_id"), plan.get("name")])

    for raw_name in names:
        name = _normalize_tool_name(raw_name)
        if not name:
            continue
        if name in {"kg_multihop_qa", "kg_multihop_qa_tool"}:
            return True
        if name.endswith(".kg_multihop_qa") or name.endswith(".kg_multihop_qa_tool"):
            return True
    return False


def _extract_kg_multihop_arguments(tool_call: dict[str, Any]) -> dict[str, Any]:
    """Extract multihop args from known tool_call shapes."""
    candidates: list[Any] = [tool_call.get("arguments"), tool_call.get("args")]
    plan = tool_call.get("plan")
    if isinstance(plan, dict):
        candidates.extend([plan.get("params"), plan.get("arguments")])

    for candidate in candidates:
        if isinstance(candidate, dict):
            return dict(candidate)
    return {}


def _extract_kg_multihop_payload(tool_call: dict[str, Any]) -> dict[str, Any]:
    """Extract the result payload carrying multihop data from nested wrappers."""
    root = tool_call.get("result")
    queue: list[Any] = [root]
    seen: set[int] = set()

    while queue:
        current = queue.pop(0)
        if current is None:
            continue
        current_id = id(current)
        if current_id in seen:
            continue
        seen.add(current_id)

        if isinstance(current, dict):
            if any(
                key in current
                for key in (
                    "outputs",
                    "summary",
                    "paths",
                    "top_paths",
                    "subgraph",
                    "answer",
                    "warnings",
                    "seed_entities",
                )
            ):
                return current
            for key in ("data", "result"):
                nested = current.get(key)
                if isinstance(nested, dict):
                    queue.append(nested)
        elif isinstance(current, list):
            for nested in current:
                if isinstance(nested, dict | list):
                    queue.append(nested)

    return {}


def _multihop_node_label(node: dict[str, Any]) -> str:
    for key in ("label", "name", "id", "concept_id", "task_id", "region_id", "kg_id"):
        value = node.get(key)
        if value:
            return str(value)
    return ""


def _format_multihop_path_preview(path: dict[str, Any]) -> str:
    nodes = path.get("nodes")
    if not isinstance(nodes, list):
        nodes = []
    labels = [_multihop_node_label(node) for node in nodes if isinstance(node, dict)]
    labels = [label for label in labels if label][:5]
    if len(labels) >= 2:
        return " -> ".join(labels)
    if len(labels) == 1:
        return labels[0]

    start = path.get("start_node_id")
    end = path.get("end_node_id")
    if start and end:
        return f"{start} -> {end}"
    return ""


def _build_kg_multihop_result_preview(tool_call: dict[str, Any]) -> dict[str, Any]:
    """Build UI preview for kg_multihop_qa tool calls."""
    from brain_researcher.services.agent.ui_api import (
        KG_MULTIHOP_LEGACY_OUTPUTS_WARNING,  # lazy
    )

    payload = _extract_kg_multihop_payload(tool_call)
    legacy_outputs = (
        payload.get("outputs") if isinstance(payload.get("outputs"), dict) else {}
    )
    legacy_outputs_consumed = False

    def _coalesce(
        keys: tuple[str, ...],
        expected_type: type | tuple[type, ...],
    ) -> Any:
        nonlocal legacy_outputs_consumed
        for key in keys:
            value = payload.get(key)
            if isinstance(value, expected_type):
                return value
        for key in keys:
            value = legacy_outputs.get(key)
            if isinstance(value, expected_type):
                legacy_outputs_consumed = True
                return value
        return None

    summary_obj = _coalesce(("summary",), (dict, str))
    args = _extract_kg_multihop_arguments(tool_call)

    paths = _coalesce(("paths", "top_paths"), list)
    if not isinstance(paths, list):
        paths = []
    warnings = _coalesce(("warnings",), list)
    if not isinstance(warnings, list):
        warnings = []
    warning_messages = [str(w) for w in warnings]

    top_paths: list[str] = []
    for path in paths:
        preview = ""
        if isinstance(path, str):
            preview = path.strip()
        elif isinstance(path, dict):
            preview = _format_multihop_path_preview(path)
        if preview:
            top_paths.append(preview)
        if len(top_paths) >= 3:
            break

    subgraph = _coalesce(("subgraph",), dict)
    if not isinstance(subgraph, dict):
        subgraph = {}
    has_subgraph = bool(subgraph.get("nodes") or subgraph.get("edges"))

    answer_value = payload.get("answer")
    if answer_value is None and "answer" in legacy_outputs:
        legacy_outputs_consumed = True
        answer_value = legacy_outputs.get("answer")

    summary = ""
    if isinstance(answer_value, str) and answer_value.strip():
        summary = answer_value.strip()
    elif isinstance(summary_obj, str) and summary_obj.strip():
        summary = summary_obj.strip()
    elif isinstance(summary_obj, dict):
        n_paths = summary_obj.get("n_paths")
        hops_used = summary_obj.get("hops_used")
        max_hops = summary_obj.get("max_hops")
        if isinstance(n_paths, int | float):
            summary = f"Found {int(n_paths)} path(s)"
            hops = hops_used if isinstance(hops_used, int | float) else max_hops
            if isinstance(hops, int | float):
                summary += f" within {int(hops)} hop(s)"
    if not summary:
        summary = "Multi-hop KG result available."

    summary_dict = summary_obj if isinstance(summary_obj, dict) else {}
    if (
        legacy_outputs_consumed
        and KG_MULTIHOP_LEGACY_OUTPUTS_WARNING not in warning_messages
    ):
        warning_messages.append(KG_MULTIHOP_LEGACY_OUTPUTS_WARNING)

    expand_args = {
        "question": args.get("question") or summary_dict.get("question"),
        "max_hops": args.get("max_hops", summary_dict.get("max_hops")),
        "mode": args.get("mode") or summary_dict.get("mode"),
        "max_results": args.get("max_results"),
        "allowed_edge_types": args.get("allowed_edge_types"),
        "return_subgraph": True,
    }

    return {
        "kind": "kg_multihop_qa",
        "summary": summary,
        "summary_stats": summary_dict,
        "top_paths": top_paths,
        "warnings": warning_messages,
        "has_subgraph": has_subgraph,
        "expand_args": expand_args,
    }


def _attach_kg_multihop_previews(tool_calls: Any) -> None:
    """In-place normalization: attach `result_preview` for kg_multihop_qa calls."""
    if not isinstance(tool_calls, list):
        return

    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        if not _is_kg_multihop_qa_tool_call(tool_call):
            continue
        tool_call["result_preview"] = _build_kg_multihop_result_preview(tool_call)
