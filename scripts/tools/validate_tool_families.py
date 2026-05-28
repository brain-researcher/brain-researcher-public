#!/usr/bin/env python
"""Validate that chat-whitelisted families/leaves resolve against tools_catalog_merged.json.

Usage: python scripts/tools/validate_tool_families.py
Exits non-zero if missing leaves are found.
"""
import json
import os
import sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
MERGED = ROOT / "configs" / "tools_catalog_merged.json"
OVERRIDES = ROOT / "configs" / "tools_catalog_overrides.yaml"
CHAT = ROOT / "configs" / "catalog" / "chat_tools.yaml"
FAMS = ROOT / "configs" / "catalog" / "tool_families.yaml"

ids = set()
if MERGED.exists():
    data = json.loads(MERGED.read_text())
    tools = data["tools"] if isinstance(data, dict) and "tools" in data else data
    for t in tools:
        for key in ("name", "id", "tool_id", "tool_name"):
            if key in t and t[key]:
                ids.add(t[key])

if OVERRIDES.exists():
    overrides = yaml.safe_load(OVERRIDES.read_text()) or {}
    tools = overrides.get("tools", overrides if isinstance(overrides, list) else [])
    for t in tools or []:
        for key in ("name", "id", "tool_id", "tool_name"):
            if isinstance(t, dict) and key in t and t[key]:
                ids.add(t[key])

chat = yaml.safe_load(CHAT.read_text()).get("chat_tools", [])
fam_data = {f["id"]: f for f in yaml.safe_load(FAMS.read_text()).get("families", [])}
missing = {}
for cid in chat:
    if cid in fam_data:
        for op, leaf in (fam_data[cid].get("ops") or {}).items():
            if leaf not in ids:
                missing.setdefault(cid, []).append(leaf)
    else:
        if cid not in ids:
            missing.setdefault(cid, []).append("(not in catalog)")

strict = "--strict" in sys.argv or os.getenv("BR_TOOL_FAMILY_STRICT") == "1"
if missing:
    print("Missing leaves for chat tools:")
    for fam, leaves in missing.items():
        print(f"- {fam}: {leaves}")
    if strict:
        sys.exit(1)
    sys.exit(0)
print("OK: all chat tools/families resolve in tools_catalog_merged.json")
