#!/usr/bin/env python3
"""CI helper: fail if generated contract schemas are stale."""

from __future__ import annotations

from generate_schemas import main

if __name__ == "__main__":
    raise SystemExit(main(["--check"]))
