"""Regression guard for the public clone-and-verify contract."""

from __future__ import annotations

import hashlib
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
VERIFY = runpy.run_path(str(REPRO_ROOT / "verify.py"))
VERIFY_MANIFEST = VERIFY["_verify_manifest"]
VERIFY_PACK = VERIFY["verify_pack"]
VERIFY_MAIN = VERIFY["main"]


def _checksum(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _write_manifest(pack_dir: Path, artifacts: list[dict]) -> None:
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "manifest.json").write_text(
        json.dumps({"artifacts": artifacts}), encoding="utf-8"
    )


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
    assert "constraints-py311.txt" in generator
    assert (CLAIM_TUTORIAL / "constraints-py311.txt").is_file()


@pytest.mark.parametrize(
    "example_dir", [A1_PACK, CLAIM_TUTORIAL], ids=lambda path: path.name
)
def test_agentic_driver_resolves_repository_root(example_dir: Path) -> None:
    driver = runpy.run_path(str(example_dir / "drive_from_language.py"))
    assert driver["REPO_ROOT"] == REPO_ROOT
    assert driver["CALL_TOOL"] == REPO_ROOT / "scripts" / "mcp" / "call_http_tool.py"
    assert driver["CALL_TOOL"].is_file()


@pytest.mark.parametrize(
    ("pack_dir", "expected_exit", "integrity_verified", "n_indeterminate"),
    [
        (A1_PACK, 0, True, 0),
        (REPRO_ROOT / "fitlins_multiverse_yeo17", 2, None, 2),
    ],
    ids=["bounded_autoresearch_a1", "fitlins_multiverse_yeo17"],
)
def test_reproducibility_pack_reports_its_integrity_boundary(
    pack_dir: Path,
    expected_exit: int,
    integrity_verified: bool | None,
    n_indeterminate: int,
) -> None:
    proc = subprocess.run(
        [sys.executable, str(REPRO_ROOT / "verify.py"), str(pack_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert proc.returncode == expected_exit, (
        f"{pack_dir.name} failed verification (exit {proc.returncode})\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    report = json.loads(proc.stdout)
    assert report["integrity_verified"] is integrity_verified
    assert report["executed"] is False
    assert report["scientifically_reproduced"] is False
    assert report["reproduced"] is False
    assert report["n_mismatched"] == 0
    assert report["n_missing"] == 0
    assert report["n_matched"] > 0
    assert report["n_indeterminate"] == n_indeterminate


def test_manifest_match_only_proves_integrity(tmp_path: Path) -> None:
    payload = b"recorded result\n"
    (tmp_path / "result.txt").write_bytes(payload)
    _write_manifest(
        tmp_path, [{"path": "result.txt", "sha256": _checksum(payload)}]
    )

    report = VERIFY_MANIFEST(tmp_path)

    assert report["integrity_verified"] is True
    assert report["executed"] is False
    assert report["scientifically_reproduced"] is False
    assert report["reproduced"] is False
    assert report["artifacts"][0]["status"] == "match"
    assert VERIFY_MAIN([str(tmp_path)]) == 0


def test_manifest_mismatch_fails_integrity(tmp_path: Path) -> None:
    (tmp_path / "result.txt").write_text("changed\n", encoding="utf-8")
    _write_manifest(
        tmp_path,
        [{"path": "result.txt", "sha256": _checksum(b"recorded result\n")}],
    )

    report = VERIFY_MANIFEST(tmp_path)

    assert report["integrity_verified"] is False
    assert report["scientifically_reproduced"] is False
    assert report["artifacts"][0]["status"] == "mismatch"
    assert VERIFY_MAIN([str(tmp_path)]) == 1


def test_manifest_missing_file_fails_integrity(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        [{"path": "missing.txt", "sha256": _checksum(b"recorded result\n")}],
    )

    report = VERIFY_MANIFEST(tmp_path)

    assert report["integrity_verified"] is False
    assert report["scientifically_reproduced"] is False
    assert report["artifacts"][0]["status"] == "missing"
    assert VERIFY_MAIN([str(tmp_path)]) == 1


@pytest.mark.parametrize("hash_state", ["schema_only", "skipped", "error"])
def test_indeterminate_entry_never_claims_complete_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hash_state: str
) -> None:
    entry = {"path": "result.bin", "sha256": _checksum(b"recorded result\n")}
    if hash_state == "schema_only":
        entry = {"path": "result.bin", "schema_only": True}
    else:
        monkeypatch.setitem(
            VERIFY_MANIFEST.__globals__, "_sha256", lambda _path: (None, hash_state)
        )
    _write_manifest(tmp_path, [entry])

    report = VERIFY_MANIFEST(tmp_path)

    assert report["integrity_verified"] is None
    assert report["executed"] is False
    assert report["scientifically_reproduced"] is False
    assert report["reproduced"] is False
    assert report["n_indeterminate"] == 1
    assert report["artifacts"][0]["status"] == "indeterminate"
    assert VERIFY_MAIN([str(tmp_path)]) == 2


def test_execution_pack_can_record_scientific_reproduction(tmp_path: Path) -> None:
    execution_pack = tmp_path / "execution_pack"
    execution_pack.mkdir()
    (execution_pack / "expected_artifacts.json").write_text("{}\n", encoding="utf-8")
    (execution_pack / "run_pack.py").write_text(
        """\
import json
from pathlib import Path

Path("reproduction_report.json").write_text(json.dumps({
    "integrity_verified": True,
    "executed": True,
    "scientifically_reproduced": True,
}))
""",
        encoding="utf-8",
    )

    report = VERIFY_PACK(tmp_path)

    assert report["mode"] == "run_pack"
    assert report["exit_code"] == 0
    assert report["integrity_verified"] is True
    assert report["executed"] is True
    assert report["scientifically_reproduced"] is True
    assert report["reproduced"] is True
    assert VERIFY_MAIN([str(tmp_path)]) == 0


def test_legacy_execution_report_remains_compatible() -> None:
    report = VERIFY["_normalize_execution_report"]({"reproduced": True}, 0)

    assert report["integrity_verified"] is True
    assert report["executed"] is True
    assert report["scientifically_reproduced"] is True
    assert report["reproduced"] is True


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
