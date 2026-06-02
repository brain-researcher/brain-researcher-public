#!/usr/bin/env python3
"""Materialize biological-motion TRIBE stimuli from walkerdata.mat."""
# ruff: noqa: I001

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
for path in (SRC_ROOT, REPO_ROOT):
    rendered = str(path)
    if rendered not in sys.path:
        sys.path.insert(0, rendered)

from brain_researcher.services.tools.tribe_biological_motion_materializer import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
