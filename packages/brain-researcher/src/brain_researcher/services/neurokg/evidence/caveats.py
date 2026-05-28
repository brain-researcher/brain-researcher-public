"""NeuroMethods caveats loader + matcher."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from brain_researcher.config.paths import get_data_root

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_cached_caveats: Optional[List[Dict[str, Any]]] = None


def _default_path() -> Path:
    override = os.environ.get("NEUROKG_CAVEATS_PATH")
    if override:
        return Path(override)
    return get_data_root() / "neuro_methods_kb.yaml"


def load_caveats(path: Optional[Path] = None, force: bool = False) -> List[Dict[str, Any]]:
    global _cached_caveats
    if _cached_caveats is not None and not force:
        return _cached_caveats

    path = path or _default_path()
    if not path.exists():
        _cached_caveats = []
        return []

    try:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except Exception:
        _cached_caveats = []
        return []

    if not isinstance(payload, list):
        payload = []
    _cached_caveats = payload
    return payload


def match_caveats(
    *,
    query: str,
    node_type: Optional[str],
    node_label: Optional[str],
    max_items: int = 5,
) -> List[Dict[str, Any]]:
    caveats = load_caveats()
    if not caveats:
        return []

    q = (query or "").lower()
    node_type = (node_type or "").strip()
    node_label = (node_label or "").strip()
    matched: Dict[str, Dict[str, Any]] = {}

    for caveat in caveats:
        triggers = caveat.get("triggers", {}) or {}
        keywords = triggers.get("query_keywords") or []
        labels = triggers.get("node_labels") or []

        keyword_hit = any(str(k).lower() in q for k in keywords if k)
        label_hit = node_type in labels or node_label in labels

        if keyword_hit or label_hit:
            cid = caveat.get("id") or caveat.get("title")
            if not cid:
                continue
            matched[cid] = {
                "id": caveat.get("id"),
                "title": caveat.get("title"),
                "severity": caveat.get("severity", "low"),
                "needs_citation": bool(caveat.get("needs_citation", False)),
                "citations": caveat.get("citations") or [],
                "actionable_fix": caveat.get("actionable_fix"),
            }

    ordered = sorted(
        matched.values(),
        key=lambda c: _SEVERITY_ORDER.get(str(c.get("severity", "low")).lower(), 3),
    )
    return ordered[:max_items]


__all__ = ["load_caveats", "match_caveats"]
