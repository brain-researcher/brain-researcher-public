"""Integrity checks for the public reviewer-artifact archive."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ARCHIVE_REL = Path(
    "docs/reviewer_artifacts/brainresearcher_supplement_archive_20260705"
)
ARCHIVE_DIR = REPO_ROOT / ARCHIVE_REL


def test_reviewer_archive_manifest_matches_tracked_files() -> None:
    manifest = json.loads((ARCHIVE_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    entries = manifest["files"]

    assert manifest["file_count"] == len(entries)

    tracked_output = subprocess.check_output(
        ["git", "ls-files", "--", str(ARCHIVE_REL)],
        cwd=REPO_ROOT,
        text=True,
    )
    tracked = {
        Path(line).relative_to(ARCHIVE_REL).as_posix()
        for line in tracked_output.splitlines()
        if line
    }
    tracked.remove("MANIFEST.json")

    listed = {entry["path"] for entry in entries}
    assert listed == tracked, (
        f"reviewer archive manifest coverage drift: "
        f"unlisted={sorted(tracked - listed)}, stale={sorted(listed - tracked)}"
    )

    for entry in entries:
        path = ARCHIVE_DIR / entry["path"]
        payload = path.read_bytes()
        assert len(payload) == entry["size_bytes"], entry["path"]
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"], entry["path"]
