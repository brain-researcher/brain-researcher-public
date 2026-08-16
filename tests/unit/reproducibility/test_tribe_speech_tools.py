"""Golden checks for the public TRIBE speech--tools derived-data replay."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "reproducibility" / "tribe_speech_tools"


def test_tribe_speech_tools_replay_validates_values_and_writes_figure(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [sys.executable, str(PACK / "verify.py"), "--output-dir", str(tmp_path)],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "15-pair open screen" in result.stdout
    assert "11/12 target geometry" in result.stdout
    assert "primary endpoint=not_supported" in result.stdout
    assert "trajectory=inconclusive_or_conflicting" in result.stdout
    for extension in ("pdf", "png", "svg"):
        output = tmp_path / f"figure6_tribe_speech_tools.{extension}"
        assert output.exists()
        assert output.stat().st_size > 0

    summary = json.loads(
        (PACK / "source" / "new_collection_summary.json").read_text(encoding="utf-8")
    )
    assert summary == {
        "aggregate_delta_s": -0.19802239326408583,
        "joint_target_collection_count": 3,
        "collection_count": 4,
        "raw_permutation_p_value": 0.13212,
        "holm_adjusted_p_value": 0.39635999999999993,
        "inference_kind": "balanced_label_permutation",
        "inference_status": "frozen_permutation_complete",
        "primary_endpoint_status": "not_supported",
        "trajectory_outcome": "inconclusive_or_conflicting",
    }


def test_tribe_speech_tools_public_pack_has_no_private_location_or_execution_identifier() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in PACK.rglob("*")
        if path.is_file() and path.suffix in {".csv", ".json", ".md", ".py"}
    )

    for forbidden in ("/data/brain_researcher", "default:user", "brar_", "owners/"):
        assert forbidden not in text
