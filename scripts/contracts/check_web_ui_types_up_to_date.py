#!/usr/bin/env python3
"""CI helper: fail if generated web UI contract types are stale."""

from __future__ import annotations

from generate_web_ui_types import main

if __name__ == "__main__":
    raise SystemExit(main(["--check"]))

