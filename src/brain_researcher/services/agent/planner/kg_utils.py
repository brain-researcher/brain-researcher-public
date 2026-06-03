"""
Lightweight helpers for canonicalizing KG identifiers used by planner/writeback.

Goals:
- Avoid OR scans in Cypher by emitting deterministic keys.
- Normalize common dataset/tool id shapes before Neo4j lookups.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

_OPENNEURO_PREFIX = "ds:openneuro:"
_OPENNEURO_RE = re.compile(r"^ds:?0*\d+$", re.IGNORECASE)  # e.g., ds000001 or DS000123


def normalize_tool_id(tool_id: Optional[str]) -> Optional[str]:
    """Best-effort tool key normalization."""
    if not tool_id:
        return None
    return str(tool_id).strip()


def normalize_dataset_id(dataset_id: Optional[str]) -> Optional[str]:
    """
    Normalize dataset ids to the canonical KG form.

    Heuristics:
    - If already starts with ds:openneuro:, keep as-is.
    - If looks like ds000001 / DS000001 -> prefix with ds:openneuro:
    - Otherwise, return stripped original.
    """
    if not dataset_id:
        return None
    ds = str(dataset_id).strip()
    if ds.startswith(_OPENNEURO_PREFIX):
        return ds
    if _OPENNEURO_RE.match(ds):
        lower = ds.lower()
        canon = lower if lower.startswith("ds") else f"ds{lower}"
        return _OPENNEURO_PREFIX + canon
    return ds


def extract_dataset_from_context(context: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Pull a dataset id from plan/query context if available.

    Expected places:
    - context["query_understanding"]["resolved_datasets"][0]["dataset_id" or "id"]
    - context["query_understanding"]["candidate_datasets"][...]
    - context["dataset_id"]
    """
    if not isinstance(context, dict):
        return None

    def _pick(ds_obj: Dict[str, Any]) -> Optional[str]:
        for key in ("dataset_id", "id", "openneuro_id"):
            val = ds_obj.get(key)
            if isinstance(val, str) and val.strip():
                return val
        aliases = ds_obj.get("aliases")
        if isinstance(aliases, list):
            for val in aliases:
                if isinstance(val, str) and val.strip():
                    return val
        return None

    qur = context.get("query_understanding")
    if isinstance(qur, dict):
        resolved = qur.get("resolved_datasets")
        if isinstance(resolved, list) and resolved:
            val = _pick(resolved[0]) if isinstance(resolved[0], dict) else None
            if val:
                return val
        cand = qur.get("candidate_datasets")
        if isinstance(cand, list) and cand:
            val = _pick(cand[0]) if isinstance(cand[0], dict) else None
            if val:
                return val

    direct = context.get("dataset_id")
    if isinstance(direct, str) and direct.strip():
        return direct
    return None


def extract_task_family(context: Optional[Dict[str, Any]], pipeline: Optional[str]) -> Optional[str]:
    """
    Derive task_family for failure/evidence records.
    Preference: query_understanding.intent[0] -> pipeline -> None
    """
    if isinstance(context, dict):
        qur = context.get("query_understanding")
        if isinstance(qur, dict):
            intent = qur.get("intent") or qur.get("intents")
            if isinstance(intent, list) and intent and isinstance(intent[0], str):
                return intent[0]
    if pipeline and pipeline.strip():
        return pipeline.strip()
    return None


__all__ = [
    "normalize_tool_id",
    "normalize_dataset_id",
    "extract_dataset_from_context",
    "extract_task_family",
]
