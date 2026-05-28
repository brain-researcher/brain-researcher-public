"""Validate backend tool coverage.

Rules:
- Backend tool IDs are those with prefixes: container., neurodesk., niwrap., mcp.
- A backend tool is OK if either:
    * It is referenced by a canonical tool's backend.provider (or backend.candidates[*].id), or
    * It lives in a family marked internal: true.
- Report backend tools that are neither referenced nor internal.
"""
from __future__ import annotations

import sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
CAP_PATH = ROOT / "configs" / "catalog" / "capabilities.yaml"
FAM_PATH = ROOT / "configs" / "catalog" / "tool_families.yaml"

BACKEND_PREFIXES = ("container.", "neurodesk", "niwrap", "mcp.")


def load_capabilities_backends():
    cap_data = yaml.safe_load(CAP_PATH.read_text()) or {}
    refs = set()
    for tool in cap_data.get("tools", []):
        backend = tool.get("backend")
        if not backend:
            continue
        if isinstance(backend, dict):
            if backend.get("provider"):
                refs.add(str(backend["provider"]))
            candidates = backend.get("candidates") or []
            for c in candidates:
                if c.get("id"):
                    refs.add(str(c["id"]))
    return refs


def load_internal_backends():
    fam_data = yaml.safe_load(FAM_PATH.read_text()) or {}
    internal_ids = set()
    for fam in fam_data.get("families", []):
        if fam.get("internal"):
            internal_ids.update((fam.get("ops") or {}).values())
    return internal_ids


def load_all_ids():
    ids = set()
    cap_data = yaml.safe_load(CAP_PATH.read_text()) or {}
    for tool in cap_data.get("tools", []):
        tid = tool.get("id")
        if tid:
            ids.add(str(tid))
    fam_data = yaml.safe_load(FAM_PATH.read_text()) or {}
    for fam in fam_data.get("families", []):
        ids.update((fam.get("ops") or {}).values())
    return ids


def main() -> int:
    all_ids = load_all_ids()
    backend_ids = {i for i in all_ids if i.startswith(BACKEND_PREFIXES)}
    referenced = load_capabilities_backends()
    internal = load_internal_backends()

    unreferenced = sorted([i for i in backend_ids if i not in referenced and i not in internal])

    print(f"Total backend candidates: {len(backend_ids)}")
    print(f"Referenced by canonical backend: {len(referenced & backend_ids)}")
    print(f"Internal backend tools: {len(internal & backend_ids)}")
    print(f"Unreferenced & not internal: {len(unreferenced)}")

    if unreferenced:
        print("\nUnreferenced backend tools:")
        for i in unreferenced:
            print(f" - {i}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
