"""Public newcomer fixture checks for the TRIBE v2 evaluator."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "scripts" / "demos" / "run_tribe_speech_tools_public_fixture.py"


def test_public_fixture_runs_evaluate_then_verify(tmp_path: Path) -> None:
    output_dir = tmp_path / "tribe-public-fixture"
    completed = subprocess.run(
        [sys.executable, str(FIXTURE), "--output-dir", str(output_dir)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    report = json.loads(completed.stdout)

    assert report["fixture"] == "tribe_speech_tools_public_v2"
    assert report["execution_kind"] == "synthetic_fixture"
    assert report["scientific_evidence"] == "synthetic_fixture_only"
    assert report["matrix_file_count"] == 12
    assert report["evaluate"]["execution_kind"] == "synthetic_fixture"
    assert report["verify"]["status"] == "verified"

    evaluation = json.loads(
        (output_dir / "artifacts" / "evaluation.json").read_text(encoding="utf-8")
    )
    assert evaluation["scientific_evidence"] == "synthetic_fixture_only"
    assert evaluation["evaluation"]["evaluation_status"] == "valid"
    assert len(list((output_dir / "inputs").glob("*.npy"))) == 12


def test_public_fixture_refuses_a_nonempty_output_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "nonempty"
    output_dir.mkdir()
    (output_dir / "existing.txt").write_text("keep\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(FIXTURE), "--output-dir", str(output_dir)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "output directory must be empty" in completed.stderr
    assert (output_dir / "existing.txt").read_text(encoding="utf-8") == "keep\n"
