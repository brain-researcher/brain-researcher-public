"""Lightweight smoke test for workflow_psych101_ingest_eval.

This test is intentionally synthetic:
- it only depends on tmp_path
- it generates a tiny Psych-101-like JSONL input on the fly
- it expects the workflow to run in dry-run / non-GPU mode
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_researcher.services.mcp import server as mcp_server
from brain_researcher.services.tools.runner import execute_tool


def _workflow_row() -> dict[str, object] | None:
    resp = mcp_server.workflow_search("psych101", limit=20)
    if not resp.get("ok"):
        return None
    for row in resp.get("workflows") or []:
        if str(row.get("id") or "") == "workflow_psych101_ingest_eval":
            return row
    return None


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _synth_value_for_param(name: str, schema: dict[str, object], tmp_path: Path) -> object:
    lowered = name.lower()
    prop_type = str(schema.get("type") or "").lower()

    if lowered == "dry_run" or prop_type == "boolean":
        return True

    if "output_dir" in lowered or lowered.endswith("_dir"):
        out_dir = tmp_path / name.replace("/", "_")
        out_dir.mkdir(parents=True, exist_ok=True)
        return str(out_dir)

    if "jsonl" in lowered:
        return str(
            _write_jsonl(
                tmp_path / f"{name.replace('/', '_')}.jsonl",
                [
                    {
                        "experiment_id": "psych101-demo-001",
                        "task_name": "two-step task",
                        "participant_id": "sub-01",
                        "trial_index": 0,
                        "choice": "left",
                        "rt_sec": 0.42,
                        "correct": True,
                    },
                    {
                        "experiment_id": "psych101-demo-001",
                        "task_name": "two-step task",
                        "participant_id": "sub-01",
                        "trial_index": 1,
                        "choice": "right",
                        "rt_sec": 0.58,
                        "correct": False,
                    },
                ],
            )
        )

    if "tsv" in lowered or "csv" in lowered:
        tsv_path = tmp_path / f"{name.replace('/', '_')}.tsv"
        tsv_path.write_text(
            (
                "experiment_id\ttask_name\tparticipant_id\ttrial_index\tchoice\trt_sec\tcorrect\n"
                "psych101-demo-001\ttwo-step task\tsub-01\t0\tleft\t0.42\t1\n"
                "psych101-demo-001\ttwo-step task\tsub-01\t1\tright\t0.58\t0\n"
                "psych101-demo-001\ttwo-step task\tsub-02\t0\tleft\t0.39\t1\n"
            ),
            encoding="utf-8",
        )
        return str(tsv_path)

    if "json" in lowered:
        return str(
            _write_json(
                tmp_path / f"{name.replace('/', '_')}.json",
                {
                    "dataset_id": "psych101-demo",
                    "source": "synthetic",
                    "n_experiments": 1,
                    "n_trials": 2,
                },
            )
        )

    if "path" in lowered or "file" in lowered or "input" in lowered:
        file_path = tmp_path / f"{name.replace('/', '_')}.jsonl"
        if "manifest" in lowered:
            file_path = tmp_path / f"{name.replace('/', '_')}.json"
            _write_json(
                file_path,
                {
                    "dataset_id": "psych101-demo",
                    "source": "synthetic",
                    "n_trials": 2,
                },
            )
        else:
            _write_jsonl(
                file_path,
                [
                    {
                        "experiment_id": "psych101-demo-001",
                        "task_name": "two-step task",
                        "participant_id": "sub-01",
                        "trial_index": 0,
                        "choice": "left",
                        "rt_sec": 0.42,
                    }
                ],
            )
        return str(file_path)

    if prop_type == "array":
        items = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        item_type = str(items.get("type") or "").lower()
        return ["psych101-demo"] if item_type == "string" else [1]

    if prop_type in {"integer", "number"}:
        return 1 if prop_type == "integer" else 0.1

    if prop_type == "object":
        return {"dataset_id": "psych101-demo"}

    return "psych101-demo"


def _build_params(row: dict[str, object], tmp_path: Path) -> dict[str, object]:
    params = row.get("params") if isinstance(row.get("params"), dict) else {}
    schema = params.get("schema") if isinstance(params, dict) else {}
    properties = schema.get("properties") if isinstance(schema, dict) else {}
    required = schema.get("required") if isinstance(schema, dict) else []

    values: dict[str, object] = {}
    for name, prop_schema in (properties or {}).items():
        if isinstance(prop_schema, dict):
            values[name] = _synth_value_for_param(name, prop_schema, tmp_path)

    for name in required or []:
        if name not in values:
            prop_schema = properties.get(name) if isinstance(properties, dict) else {}
            values[name] = _synth_value_for_param(
                str(name),
                prop_schema if isinstance(prop_schema, dict) else {},
                tmp_path,
            )

    if "output_dir" not in values:
        fallback_out = tmp_path / "psych101_output"
        fallback_out.mkdir(parents=True, exist_ok=True)
        values["output_dir"] = str(fallback_out)

    if "dry_run" not in values:
        values["dry_run"] = True

    return values


@pytest.mark.timeout(120)
def test_workflow_psych101_ingest_eval_smoke(tmp_path: Path):
    row = _workflow_row()
    if row is None:
        pytest.skip("workflow_psych101_ingest_eval is not registered yet")

    params = _build_params(row, tmp_path)
    res = execute_tool("workflow_psych101_ingest_eval", params)
    assert res.status == "success", res.error

    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_psych101_ingest_eval"

    steps = workflow_data.get("steps") or {}
    step_ids = {str(step_id) for step_id in steps}
    assert step_ids, "workflow should emit at least one step"
    assert any("ingest" in step_id for step_id in step_ids)
    assert any(
        token in " ".join(step_ids).lower()
        for token in ("eval", "report", "manifest")
    )

    outputs = workflow_data.get("outputs") or {}
    if isinstance(outputs, dict):
        for value in outputs.values():
            if isinstance(value, str) and Path(value).exists():
                break
        else:
            out_dir = Path(params["output_dir"])
            assert out_dir.exists()
