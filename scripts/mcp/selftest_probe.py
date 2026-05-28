#!/usr/bin/env python3
"""Lightweight probes used by MCP system_self_test.

This script is intentionally tiny and JSON-only so MCP can verify execution
paths without pulling heavy scientific dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def _probe_script() -> dict:
    return {
        "ok": True,
        "probe": "script",
        "python_executable": sys.executable,
        "cwd": str(Path.cwd()),
    }


def _probe_container() -> dict:
    cvmfs_path = Path(
        os.getenv(
            "BR_NEURODESK_CVMFS_CONTAINERS",
            "/cvmfs/neurodesk.ardc.edu.au/containers",
        )
    )
    runtime_binary = shutil.which("apptainer") or shutil.which("singularity")
    cvmfs_exists = cvmfs_path.exists()
    cvmfs_readable = os.access(cvmfs_path, os.R_OK) if cvmfs_exists else False
    ok = bool(runtime_binary) and cvmfs_exists and cvmfs_readable
    return {
        "ok": ok,
        "probe": "container",
        "runtime_binary": runtime_binary,
        "cvmfs_path": str(cvmfs_path),
        "cvmfs_exists": cvmfs_exists,
        "cvmfs_readable": cvmfs_readable,
        "error": None
        if ok
        else "container_runtime_or_cvmfs_unavailable",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", choices={"script", "container"}, required=True)
    args = parser.parse_args()

    if args.probe == "script":
        payload = _probe_script()
    else:
        payload = _probe_container()

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
