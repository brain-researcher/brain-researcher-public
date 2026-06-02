#!/usr/bin/env python3
"""
Update timestamps and selected internal version strings in docs and tests.

Scope (safe):
- Replace ISO-style dates starting with 2024- to 2025- in docs/ and tests/ only.
- Replace JSON-like year fields: "year": 2025 -> 2025 in docs/ and tests/.
- Normalize internal model/version examples in docs:
  - BrainGPT-7B-v0.<n> -> BrainGPT-7B-v0.0
  - loader_version "v0.x[.y]" -> "v0.0"

Excluded:
- Binaries, data/, external/, node_modules/, .next/, .git/
- Pinned third-party versions (e.g., GitHub Actions, npm packages) by excluding .github/ and web_ui node_modules/.next explicitly

Run: python scripts/maintenance/update_years_and_versions.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    "external",
    "data",
    "__pycache__",
    "apps/web-ui/.next",
    "apps/web-ui/node_modules",
    ".github",
}

TARGET_DIRS = [
    ROOT / "docs",
    ROOT / "tests",
    ROOT / "backup",
    ROOT / "infrastructure",
    ROOT / "scripts",
]


def should_skip(path: Path) -> bool:
    if not path.is_file():
        return True
    rel = path.relative_to(ROOT)
    # Skip excluded dirs
    for part in rel.parts:
        if part in EXCLUDE_DIRS:
            return True
    # Skip obvious binary types
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".zip", ".gz", ".tar", ".tgz", ".bz2", ".xz", ".pkl", ".npy", ".db"}:
        return True
    return False


REPLACERS = [
    # ISO-like dates beginning with 2024-
    (re.compile(r"(?<!\d)2024-(\d{2}-\d{2}([Tt].*?)?)"), r"2025-\1"),
    # JSON year fields
    (re.compile(r"(\"year\"\s*:\s*)2024\b"), r"\g<1>2025"),
    # Internal model names BrainGPT-7B-v0.x -> v0.0
    (re.compile(r"(BrainGPT-7B-v0\.)\d+"), r"\g<1>0"),
    # loader_version "v0.x[.y]" -> v0.0
    (re.compile(r"(loader_version\"\s*:\s*\")v0\.[0-9]+(?:\.[0-9]+)?(\")"), r"\1v0.0\2"),
]


def process_file(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False

    original = text
    for pattern, repl in REPLACERS:
        text = pattern.sub(repl, text)

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> int:
    changed = 0
    scanned = 0
    for base in TARGET_DIRS:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if should_skip(path):
                continue
            scanned += 1
            if process_file(path):
                changed += 1
    print(f"Scanned: {scanned} files; Modified: {changed} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
