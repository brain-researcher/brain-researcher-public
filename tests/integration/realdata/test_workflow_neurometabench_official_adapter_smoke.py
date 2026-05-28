"""Smoke test for the official NeurometaBench adapter workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_researcher.services.tools.runner import execute_tool


@pytest.mark.realdata
@pytest.mark.timeout(180)
def test_workflow_neurometabench_official_adapter_smoke(tmp_path: Path):
    out_dir = tmp_path / "neurometabench_adapter"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = execute_tool(
        "workflow_neurometabench_official_adapter",
        {
            "meta_pmid": "31872334",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error
    assert isinstance(res.data, dict)
    assert "steps" in res.data

    case_adapter = out_dir / "case_adapter.json"
    results_json = out_dir / "results.json"
    assert case_adapter.exists() and case_adapter.stat().st_size > 0
    assert results_json.exists() and results_json.stat().st_size > 0

    adapter_payload = json.loads(case_adapter.read_text(encoding="utf-8"))
    assert adapter_payload["official_route"] == "nimads_brainmap"

    results_payload = json.loads(results_json.read_text(encoding="utf-8"))
    assert results_payload["official_route"] == "nimads_brainmap"
    assert results_payload["screening_skipped"] is True
