"""Regression guard for the public clone-and-verify contract."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
REPRO_ROOT = REPO_ROOT / "reproducibility"
PACKS = sorted(
    path
    for path in REPRO_ROOT.iterdir()
    if path.is_dir() and (path / "manifest.json").is_file()
)
A1_PACK = REPRO_ROOT / "bounded_autoresearch_a1"
CLAIM_TUTORIAL = REPRO_ROOT / "auditable_claim_record"


def test_reproducibility_packs_exist() -> None:
    assert {path.name for path in PACKS} == {
        "bounded_autoresearch_a1",
        "fitlins_multiverse_yeo17",
    }
    assert (REPRO_ROOT / "verify.py").is_file()
    assert not (REPRO_ROOT / "packs").exists()
    assert not (REPRO_ROOT / "tutorials").exists()


def test_auditable_claim_tutorial_is_colocated() -> None:
    assert CLAIM_TUTORIAL.is_dir()
    assert not (REPO_ROOT / "examples" / "auditable_claim_record").exists()
    assert not (CLAIM_TUTORIAL / "manifest.json").exists()

    generator = (
        REPO_ROOT / "scripts" / "autoresearch" / "run_auditable_claim_demo.py"
    ).read_text(encoding="utf-8")
    assert '"cd brain-researcher-public"' in generator
    assert '"python -m pip install -e . nimare nilearn"' in generator


@pytest.mark.parametrize(
    "example_dir", [A1_PACK, CLAIM_TUTORIAL], ids=lambda path: path.name
)
def test_agentic_driver_resolves_repository_root(example_dir: Path) -> None:
    driver = runpy.run_path(str(example_dir / "drive_from_language.py"))
    assert driver["REPO_ROOT"] == REPO_ROOT
    assert driver["CALL_TOOL"] == REPO_ROOT / "scripts" / "mcp" / "call_http_tool.py"
    assert driver["CALL_TOOL"].is_file()


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
