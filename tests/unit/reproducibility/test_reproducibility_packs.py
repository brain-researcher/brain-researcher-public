"""Regression guard for the public clone-and-verify contract."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
REPRO_ROOT = REPO_ROOT / "reproducibility"
PACKS = sorted(path for path in (REPRO_ROOT / "packs").iterdir() if path.is_dir())


def test_reproducibility_packs_exist() -> None:
    assert PACKS, "no reproducibility packs are shipped"
    assert (REPRO_ROOT / "verify.py").is_file()


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda path: path.name)
def test_reproducibility_pack_self_verifies(pack_dir: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(REPRO_ROOT / "verify.py"), str(pack_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert proc.returncode == 0, (
        f"{pack_dir.name} failed verification (exit {proc.returncode})\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    report = json.loads(proc.stdout)
    assert report["reproduced"] is True
    assert report["n_mismatched"] == 0
    assert report["n_missing"] == 0
    assert report["n_matched"] > 0


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda path: path.name)
def test_manifest_covers_every_tracked_pack_file(pack_dir: Path) -> None:
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest["artifacts"]
    assert manifest["artifact_count"] == len(entries)

    pack_rel = pack_dir.relative_to(REPO_ROOT)
    tracked_output = subprocess.check_output(
        ["git", "ls-files", "--", str(pack_rel)],
        cwd=REPO_ROOT,
        text=True,
    )
    tracked = {
        Path(line).relative_to(pack_rel).as_posix()
        for line in tracked_output.splitlines()
        if line
    }
    tracked -= {".gitignore", "manifest.json"}

    listed = {entry["path"] for entry in entries if not entry.get("schema_only")}
    assert listed == tracked, (
        f"manifest coverage drift for {pack_dir.name}: "
        f"unlisted={sorted(tracked - listed)}, stale={sorted(listed - tracked)}"
    )
