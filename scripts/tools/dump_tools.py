"""Dump the tool universe (registry + catalog) for classification.

Outputs TSV: id, source, runtime_kind, module
Sources:
  - registry: discovered runtime tools (module/runtime_kind filled)
  - catalog: tools from configs/catalog/capabilities.yaml
  - family_ops: leaf ids referenced in tool_families.yaml
  - chat_whitelist: ids in chat_tools.yaml

Usage:
  python scripts/tools/dump_tools.py > tool_universe.tsv

Env:
  TOOL_DUMP_LIGHT=true  # use light_mode and disable integrations
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from brain_researcher.services.tools.tool_registry import ToolRegistry


def main() -> int:
    light = os.environ.get("TOOL_DUMP_LIGHT", "false").lower() == "true"
    root = Path(__file__).resolve().parents[2]

    # Registry tools
    reg = ToolRegistry(
        auto_discover=True,
        use_capabilities=True,
        enable_integrations=not light,
        light_mode=light,
    )
    registry_rows = []
    for t in reg.get_all_tools():
        registry_rows.append(
            (
                t_id(t),
                "registry",
                getattr(t, "runtime_kind", "python"),
                t.__class__.__module__,
            )
        )

    # Catalog tools
    catalog_rows = []
    cap_dir = root / "configs" / "catalog"
    for cap_path in cap_dir.glob("capabilities*.yaml"):
        cap_data = yaml.safe_load(cap_path.read_text()) or {}
        for entry in cap_data.get("tools", []):
            if isinstance(entry, dict) and entry.get("id"):
                catalog_rows.append((entry["id"], "catalog", entry.get("runtime_kind", "catalog"), cap_path.name))

    # Family ops
    fam_rows = []
    fam_path = root / "configs" / "catalog" / "tool_families.yaml"
    if fam_path.exists():
        fam_data = yaml.safe_load(fam_path.read_text()) or {}
        for fam in fam_data.get("families", []):
            fam_id = fam.get("id")
            ops = (fam.get("ops") or {}).items()
            for op_name, leaf in ops:
                fam_rows.append((leaf, "family_ops", fam_id or "family", fam_path.name))

    # Chat whitelist
    chat_rows = []
    chat_path = root / "configs" / "catalog" / "chat_tools.yaml"
    if chat_path.exists():
        chat_data = yaml.safe_load(chat_path.read_text()) or {}
        for tid in chat_data.get("chat_tools", []):
            chat_rows.append((tid, "chat_whitelist", "chat", chat_path.name))

    # Merge
    rows = {}
    for rid, source, rk, mod in registry_rows + catalog_rows + fam_rows + chat_rows:
        if rid in rows:
            rows[rid]["sources"].add(source)
        else:
            rows[rid] = {"runtime_kind": rk, "module": mod, "sources": {source}}

    print("id\tsources\truntime_kind\tmodule")
    for rid in sorted(rows):
        entry = rows[rid]
        src_str = ",".join(sorted(entry["sources"]))
        print(f"{rid}\t{src_str}\t{entry['runtime_kind']}\t{entry['module']}")
    return 0


def t_id(tool) -> str:
    return getattr(tool, "id", None) or getattr(tool, "name", None) or getattr(tool, "tool_name", None) or getattr(tool, "get_tool_name", lambda: None)() or getattr(tool, "get_tool_name", lambda: "")() or tool.__class__.__name__


if __name__ == "__main__":
    raise SystemExit(main())
