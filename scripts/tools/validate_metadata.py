#!/usr/bin/env python
"""Validate ToolSpec metadata fields across the catalog.

Checks that every tool has domain/function/runtime_kind/risk/tags and that
values are within allowed vocab defined in metadata_schema.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from brain_researcher.services.tools.metadata_schema import (
    DOMAIN,
    FUNCTION,
    RISK,
    RUNTIME_KIND,
    normalize_tags,
    validate_metadata,
)

CATALOG = Path("configs/tools_catalog_merged.json")


def main() -> int:
    if not CATALOG.exists():
        print(f"Missing catalog file: {CATALOG}")
        return 1

    data = json.loads(CATALOG.read_text())
    tools = data.get("tools", data if isinstance(data, list) else [])

    problems = []
    for t in tools:
        meta = {
            "domain": t.get("domain"),
            "function": t.get("function"),
            "runtime_kind": t.get("runtime_kind"),
            "risk": t.get("risk"),
            "exposure": t.get("exposure"),
            "tags": t.get("tags"),
        }
        errs = validate_metadata(meta)
        if errs:
            problems.append((t.get("name") or t.get("id"), errs))
        else:
            # Optionally normalize tags (dry-run; not writing back)
            norm = normalize_tags(meta)
            # if tags missing domain, we could warn here
            if set(norm) - set(meta.get("tags") or []):
                problems.append((t.get("name") or t.get("id"), ["tags missing core fields; normalize_tags would add them"]))

    if problems:
        print("Metadata validation issues:")
        for name, errs in problems[:200]:
            print(f"- {name}: {errs}")
        print(f"Total tools with issues: {len(problems)} / {len(tools)}")
        return 1

    print(f"OK: metadata present for {len(tools)} tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
