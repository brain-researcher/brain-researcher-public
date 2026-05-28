"""Synthetic smoke test for workflow_psych101_centaur_task_payloads."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_researcher.services.mcp import server as mcp_server
from brain_researcher.services.neurokg.etl.loaders.psych101_hf_loader import (
    Psych101DatasetMetadata,
    Psych101ExperimentSummary,
    Psych101ParquetFile,
    Psych101SplitInfo,
)
from brain_researcher.services.tools.runner import execute_tool


def _workflow_present() -> bool:
    resp = mcp_server.workflow_search("psych101", limit=50)
    if not resp.get("ok"):
        return False
    return any(
        str(row.get("id") or "") == "workflow_psych101_centaur_task_payloads"
        for row in (resp.get("workflows") or [])
    )


@pytest.mark.timeout(120)
def test_workflow_psych101_centaur_task_payloads_smoke(tmp_path: Path, monkeypatch):
    if not _workflow_present():
        pytest.skip("workflow_psych101_centaur_task_payloads is not registered yet")

    metadata = Psych101DatasetMetadata(
        dataset_id="marcelbinz/Psych-101",
        title="Psych-101",
        license="apache-2.0",
        tags=("psychology",),
        splits=(Psych101SplitInfo(split="train", num_rows=5),),
        parquet_files=(
            Psych101ParquetFile(
                split="train",
                url="https://example.org/0000.parquet",
                filename="0000.parquet",
                num_rows=5,
            ),
        ),
        source_url="https://huggingface.co/datasets/marcelbinz/Psych-101",
        card_url="https://huggingface.co/datasets/marcelbinz/Psych-101",
    )
    experiments = [
        Psych101ExperimentSummary(
            experiment="peterson2021using/exp1.csv",
            row_count=3,
            participant_count=3,
        ),
        Psych101ExperimentSummary(
            experiment="hebart2023things/exp1.csv",
            row_count=2,
            participant_count=2,
        ),
    ]

    monkeypatch.setattr(
        "brain_researcher.services.neurokg.etl.loaders.psych101_hf_loader.fetch_psych101_dataset_metadata",
        lambda dataset_id="marcelbinz/Psych-101", **_: metadata,
    )
    monkeypatch.setattr(
        "brain_researcher.services.neurokg.etl.loaders.psych101_hf_loader.summarize_psych101_from_metadata",
        lambda metadata, **_: experiments,
    )

    out_dir = tmp_path / "psych101_centaur_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_psych101_centaur_task_payloads",
        {
            "output_dir": str(out_dir),
            "dataset_id": "psych101-demo",
            "write_to_neo4j": False,
            "recommended_model": "minitaur",
        },
    )

    assert res.status == "success", res.error
    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_psych101_centaur_task_payloads"

    payload_path = out_dir / "psych101_centaur_task_payloads.json"
    task_prompts_path = out_dir / "psych101_centaur_task_prompts.jsonl"
    experiment_prompts_path = out_dir / "psych101_centaur_experiment_prompts.jsonl"
    assert payload_path.exists()
    assert task_prompts_path.exists()
    assert experiment_prompts_path.exists()

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "centaur-task-payloads-v1"
    assert payload["recommended_model"] == "minitaur"
    assert payload["summary"]["n_task_payloads"] >= 1
    assert payload["summary"]["n_experiment_payloads"] == 2
