from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_root_level_execution_pack_artifacts_are_not_tracked() -> None:
    result = subprocess.run(
        ["git", "ls-files", "."],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    offenders = [
        relpath
        for relpath in tracked
        if relpath == "execution_pack"
        or relpath.startswith("execution_pack/")
        or relpath.endswith("_execution_pack")
        or "_execution_pack/" in relpath
    ]
    assert not offenders, (
        "Execution-pack artifacts must not be tracked from the repo root: "
        f"{offenders}"
    )
