"""Real-data smoke test for ASL perfusion workflow.

This test is skipped unless an ASL file is explicitly provided via env var.

Marked as `realdata` so it is skipped by default in CI.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


@pytest.mark.realdata
def test_workflow_asl_perfusion_smoke(tmp_path: Path):
    asl_bids_root = os.environ.get("BR_ASL_BIDS_ROOT")
    if not asl_bids_root:
        pytest.skip(
            "Set BR_ASL_BIDS_ROOT to a BIDS dataset containing ASL data to run this test"
        )

    bids_root = Path(asl_bids_root)
    if not bids_root.exists():
        pytest.skip(f"ASL BIDS root not found: {bids_root}")

    out_dir = tmp_path / "asl"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_asl_perfusion",
        {
            "bids_dir": str(bids_root),
            "participant_label": ["01"],
            "container_type": "wrapper",
            "container_image": "",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs", {})
    aslprep_dir = out_dir / "aslprep"
    has_dir_artifacts = aslprep_dir.exists() and any(aslprep_dir.rglob("*"))

    def _iter_output_paths(payload: dict[str, Any]) -> list[Path]:
        resolved: list[Path] = []
        for value in payload.values():
            if isinstance(value, str):
                resolved.append(Path(value))
            elif isinstance(value, dict):
                resolved.extend(_iter_output_paths(value))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        resolved.append(Path(item))
        return resolved

    output_paths = _iter_output_paths(outputs if isinstance(outputs, dict) else {})
    has_reported_artifacts = any(p.exists() for p in output_paths)
    has_command_preview = (
        bool(
            outputs.get("command")
            or outputs.get("command_host")
            or outputs.get("command_container")
        )
        if isinstance(outputs, dict)
        else False
    )

    assert has_dir_artifacts or has_reported_artifacts or has_command_preview, outputs
