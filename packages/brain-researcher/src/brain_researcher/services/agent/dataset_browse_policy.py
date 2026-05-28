"""Shared heuristics for browse-before-resolve dataset asset routing."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

DATASET_BROWSE_TOOL_PRIORITY: dict[str, int] = {
    "list_dataset_assets": 0,
    "datasets.list_resources": 1,
    "datasets.describe_resources": 2,
    "datasets.client": 3,
}

DATASET_RESOLVE_TOOL_IDS: frozenset[str] = frozenset(
    {"resolve_dataset_asset", "resolve_bids"}
)

_BROWSE_HINTS: tuple[str, ...] = (
    "available",
    "browse",
    "explore",
    "inspect",
    "inventory",
    "list",
    "show",
    "what",
    "which",
)
_ASSET_HINTS: tuple[str, ...] = (
    "asset",
    "assets",
    "bids",
    "confounds",
    "dataset",
    "datasets",
    "derivative",
    "derivatives",
    "events",
    "file",
    "files",
    "t1w",
    "bold",
)
_RESOLVE_HINTS: tuple[str, ...] = (
    "exact path",
    "locate",
    "materialize",
    "path to",
    "resolve",
    "resolved path",
)
_DATASET_ID_RE = re.compile(r"\bds\d{6}\b", re.IGNORECASE)


def _resolved_datasets(query_understanding: Any) -> list[Any]:
    if query_understanding is None:
        return []
    resolved = getattr(query_understanding, "resolved_datasets", None)
    if resolved is not None:
        return list(resolved)
    if isinstance(query_understanding, Mapping):
        raw = query_understanding.get("resolved_datasets")
        if isinstance(raw, list):
            return raw
    return []


def has_dataset_context(
    query: str,
    *,
    query_understanding: Any = None,
    inputs: Mapping[str, Any] | None = None,
) -> bool:
    text = str(query or "").strip().lower()
    if _resolved_datasets(query_understanding):
        return True
    if inputs:
        if any(
            str(inputs.get(key) or "").strip()
            for key in ("dataset_ref", "dataset_id", "bids_root")
        ):
            return True
    return bool(
        _DATASET_ID_RE.search(text)
        or "openneuro" in text
        or "dandi" in text
        or "dandiset" in text
        or "bids_root" in text
        or "bids root" in text
        or "bids" in text
    )


def is_exploratory_dataset_asset_request(
    query: str,
    *,
    query_understanding: Any = None,
    inputs: Mapping[str, Any] | None = None,
) -> bool:
    text = str(query or "").strip().lower()
    if not has_dataset_context(
        text,
        query_understanding=query_understanding,
        inputs=inputs,
    ):
        return False
    browse_hit = any(hint in text for hint in _BROWSE_HINTS)
    asset_hit = any(hint in text for hint in _ASSET_HINTS)
    resolve_hit = any(hint in text for hint in _RESOLVE_HINTS)
    return browse_hit and asset_hit and not resolve_hit


def dataset_browse_instruction() -> str:
    return (
        "For exploratory dataset asset discovery, prefer list_dataset_assets "
        "before resolve_dataset_asset or resolve_bids. Resolve a specific asset "
        "only after the desired file or derivative has been identified."
    )


def reorder_tool_ids_for_dataset_browse(
    tool_ids: Iterable[str],
) -> list[str]:
    indexed = list(enumerate(tool_ids))
    return [
        tool_id
        for _index, tool_id in sorted(
            indexed,
            key=lambda item: (
                DATASET_BROWSE_TOOL_PRIORITY.get(str(item[1]).strip().lower(), 100),
                item[0],
            ),
        )
    ]


def dataset_browse_score_adjustment(
    tool_id: str,
    *,
    available_tool_ids: Iterable[str],
) -> int:
    normalized = str(tool_id or "").strip().lower()
    available = {
        str(candidate or "").strip().lower()
        for candidate in available_tool_ids
        if str(candidate or "").strip()
    }
    priority = DATASET_BROWSE_TOOL_PRIORITY.get(normalized)
    if priority is not None:
        return max(0, 6 - priority)
    if normalized in DATASET_RESOLVE_TOOL_IDS and any(
        browse_id in available for browse_id in DATASET_BROWSE_TOOL_PRIORITY
    ):
        return -3
    return 0


__all__ = [
    "DATASET_BROWSE_TOOL_PRIORITY",
    "DATASET_RESOLVE_TOOL_IDS",
    "dataset_browse_instruction",
    "dataset_browse_score_adjustment",
    "has_dataset_context",
    "is_exploratory_dataset_asset_request",
    "reorder_tool_ids_for_dataset_browse",
]
