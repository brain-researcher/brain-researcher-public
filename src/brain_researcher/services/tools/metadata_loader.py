"""Load catalog metadata and inject into tool instances."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import yaml

from brain_researcher.config.paths import get_config_root
from brain_researcher.services.tools.metadata_schema import normalize_tags

CATALOG = get_config_root() / "tools_catalog_merged.json"
CATALOG_OVERRIDES = get_config_root() / "tools_catalog_overrides.yaml"
_catalog_cache: Dict[str, dict] | None = None


def _load_catalog_meta() -> Dict[str, dict]:
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache

    merged: Dict[str, dict] = {}
    if CATALOG.exists():
        obj = json.loads(CATALOG.read_text())
        tools = obj.get("tools", obj if isinstance(obj, list) else [])
        merged.update(
            {
                t.get("name") or t.get("id"): t
                for t in tools
                if isinstance(t, dict) and (t.get("name") or t.get("id"))
            }
        )

    if CATALOG_OVERRIDES.exists():
        try:
            overrides_obj = yaml.safe_load(CATALOG_OVERRIDES.read_text()) or {}
            tools = overrides_obj.get(
                "tools",
                overrides_obj if isinstance(overrides_obj, list) else [],
            )
            if isinstance(tools, list):
                merged.update(
                    {
                        t.get("name") or t.get("id"): t
                        for t in tools
                        if isinstance(t, dict) and (t.get("name") or t.get("id"))
                    }
                )
        except Exception:
            pass

    _catalog_cache = merged
    return _catalog_cache


def inject_metadata(tool) -> None:
    """Attach catalog metadata to a tool instance if present."""
    catalog = _load_catalog_meta()
    name = getattr(tool, "get_tool_name", lambda: None)()
    if not name:
        return
    meta = catalog.get(name)
    if not meta:
        return

    tags = normalize_tags(
        {
            "domain": meta.get("domain"),
            "function": meta.get("function"),
            "runtime_kind": meta.get("runtime_kind"),
            "risk": meta.get("risk"),
            "tags": meta.get("tags") or [],
        }
    )
    meta = dict(meta)
    meta["tags"] = tags
    try:
        tool.metadata = meta
    except Exception:
        pass
