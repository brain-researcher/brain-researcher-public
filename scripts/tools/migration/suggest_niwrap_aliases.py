"""Suggest NiWrap aliases for existing curated tools.

Usage:
    python tools/migration/suggest_niwrap_aliases.py

Outputs TSV with columns: curated, suggested_alias, status
- status exact: package + basename match a NiWrap alias exactly
- status close: package matches, basename appears as substring in alias
- status missing: no match found

This is informational only; it does not modify code.
"""
from __future__ import annotations

import pathlib
import re
from typing import List, Tuple

from brain_researcher.services.tools.niwrap.catalog import get_niwrap_tools

# Packages we care about for NiWrap migration
PACKAGES = ["fsl", "afni", "ants"]


def load_aliases(package: str) -> List[str]:
    tools = get_niwrap_tools(packages=[package], use_cache=False, test_mode=False)
    aliases = []
    for t in tools:
        alias = t.get("metadata", {}).get("alias")
        if alias:
            aliases.append(alias)
    return aliases


def curated_tools(package: str) -> List[str]:
    root = pathlib.Path("src/brain_researcher/services/tools")
    pattern = re.compile(rf"^{package}_|^{package}\b|{package}")
    names: List[str] = []
    for path in root.glob(f"{package}_*.py"):
        names.append(path.stem)
    for path in root.glob(f"*{package}*.py"):
        if pattern.search(path.stem) and path.stem not in names:
            names.append(path.stem)
    return sorted(names)


def suggest(package: str) -> List[Tuple[str, str, str]]:
    aliases = load_aliases(package)
    results: List[Tuple[str, str, str]] = []
    for name in curated_tools(package):
        base = name
        if base.endswith("_tool"):
            base = base[:-5]
        base = base.replace(f"{package}_", "")

        exact = [a for a in aliases if a == f"{package}.{base}.run"]
        if exact:
            results.append((name, exact[0], "exact"))
            continue
        close = [a for a in aliases if base.lower() in a.lower()]
        if close:
            results.append((name, close[0], "close"))
        else:
            results.append((name, "", "missing"))
    return results


def main():
    print("curated\tsuggested_alias\tstatus")
    for pkg in PACKAGES:
        for row in suggest(pkg):
            print("\t".join(row))


if __name__ == "__main__":
    main()
