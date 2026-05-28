import json
from pathlib import Path

import pandas as pd

from brain_researcher.services.tools.executor import execute_tool
from brain_researcher.services.tools.behavior_tools import (
    BehaviorExportBIDSEventsTool,
    BehaviorGeneratePsyflowTaskTool,
    BehaviorIngestPsyflowRunTool,
    BehaviorIngestTAPSTool,
    BehaviorQCScanTool,
    BehaviorResolveTaskSpecTool,
    BehaviorValidateTaskSpecTool,
)


def test_ingest_qc_export_roundtrip(tmp_path: Path):
    data_path = tmp_path / "data.csv"
    rows = [
        {
            "onset": 0.0,
            "duration": 1.5,
            "trial_type": "go",
            "response_time": 0.35,
            "response": "space",
            "correct": True,
        },
        {
            "onset": 2.0,
            "duration": 1.5,
            "trial_type": "go",
            "response_time": 0.05,  # outlier low RT
            "response": "space",
            "correct": True,
        },
        {
            "onset": 4.0,
            "duration": 1.5,
            "trial_type": "nogo",
            "response_time": None,
            "response": "",
            "correct": False,
        },
    ]
    pd.DataFrame(rows).to_csv(data_path, index=False)

    ingest = BehaviorIngestTAPSTool()
    ingest_result = ingest._run(task_dir=str(tmp_path))
    assert ingest_result.status == "success"
    trials = ingest_result.data["trials"]
    assert len(trials) == 3

    qc = BehaviorQCScanTool()
    qc_result = qc._run(trials=trials, policy_path="configs/behavior_outlier_policy.yaml")
    assert qc_result.status == "success"
    qc_trials = qc_result.data["trials"]
    report = qc_result.data["qc_report"]
    assert report["excluded_trials"] == 2  # one low RT + one no response
    assert any(t["is_excluded"] for t in qc_trials)

    export = BehaviorExportBIDSEventsTool()
    out_path = tmp_path / "events.tsv"
    export_result = export._run(trials=qc_trials, output_path=str(out_path), drop_excluded=True)
    assert export_result.status == "success"
    assert Path(export_result.data["events_path"]).exists()
    events = Path(export_result.data["events_path"]).read_text().strip().splitlines()
    # header + one kept row expected
    assert len(events) == 2

    # Ensure TSV columns are present
    header_cols = events[0].split("\t")
    assert {"onset", "duration", "trial_type"}.issubset(set(header_cols))


def test_ingest_handles_psychopy_variants(tmp_path: Path):
    variant1 = Path("tests/fixtures/behavior/psychopy_variant1.csv")
    variant2 = Path("tests/fixtures/behavior/psychopy_variant2.csv")

    # Variant 1: key_resp columns
    ingest = BehaviorIngestTAPSTool()
    res1 = ingest._run(task_dir=str(variant1.parent), data_file=str(variant1))
    assert res1.status == "success"
    trials1 = res1.data["trials"]
    assert len(trials1) == 3
    # RT mapping from key_resp.rt
    assert trials1[0]["rt_sec"] == 0.42
    assert trials1[2]["rt_sec"] == 0.08
    assert trials1[0]["response"] == "space"

    # Variant 2: response_time_ms / condition / sub
    res2 = ingest._run(task_dir=str(variant2.parent), data_file=str(variant2))
    assert res2.status == "success"
    trials2 = res2.data["trials"]
    assert len(trials2) == 3
    assert trials2[0]["rt_sec"] == 0.35
    assert trials2[1]["rt_sec"] == 0.12
    assert trials2[0]["subject_id"] == "S02"

    # Export with sidecar + hash
    qc = BehaviorQCScanTool()
    qc_res = qc._run(trials=trials2, policy_path="configs/behavior_outlier_policy.yaml")
    export = BehaviorExportBIDSEventsTool()
    out_path = tmp_path / "sub-01_task-test_events.tsv"
    tmpl_path = tmp_path / "sidecar_template.yaml"
    tmpl_path.write_text(
        "Columns:\n  parametric: {Description: 'Custom modulator'}\nExtraMeta: demo\n",
        encoding="utf-8",
    )
    out_res = export._run(
        trials=qc_res.data["trials"],
        output_path=str(out_path),
        policy_id=qc_res.data["policy_id"],
        sidecar_template_path=str(tmpl_path),
    )
    assert out_res.status == "success"
    assert out_res.data["events_sidecar"] is not None
    assert out_res.data["events_sha256"] is not None
    # Ensure template merged
    sidecar = Path(out_res.data["events_sidecar"]).read_text(encoding="utf-8")
    assert "parametric" in sidecar
    assert "ExtraMeta" in sidecar


# ---------------------------------------------------------------------------
# Psyflow task-generation tools (behavior-task v1)
# ---------------------------------------------------------------------------


def test_resolve_task_spec_tool_nback():
    tool = BehaviorResolveTaskSpecTool()
    res = tool._run(paradigm="n_back")
    assert res.status == "success"
    assert res.data["spec"]["task_program"]["canonical_task_id"] == "n_back"
    assert res.data["spec"]["task_program"]["engine"] == "psyflow"
    assert len(res.data["spec_digest"]) == 64


def test_resolve_task_spec_tool_unknown():
    tool = BehaviorResolveTaskSpecTool()
    res = tool._run(paradigm="not_a_paradigm")
    assert res.status == "error"


def test_validate_task_spec_tool_valid():
    rtool = BehaviorResolveTaskSpecTool()
    spec = rtool._run(paradigm="flanker").data["spec"]
    vtool = BehaviorValidateTaskSpecTool()
    res = vtool._run(spec=spec)
    assert res.status == "success"
    assert res.data["valid"] is True
    assert len(res.data["spec_digest"]) == 64


def test_validate_task_spec_tool_invalid():
    vtool = BehaviorValidateTaskSpecTool()
    res = vtool._run(spec={"task_program": {}})
    assert res.status == "success"
    assert res.data["valid"] is False
    assert res.data["errors"]


def test_generate_psyflow_task_tool_approval_gate(tmp_path: Path):
    rtool = BehaviorResolveTaskSpecTool()
    rres = rtool._run(paradigm="n_back")
    spec = rres.data["spec"]
    digest = rres.data["spec_digest"]
    gtool = BehaviorGeneratePsyflowTaskTool()

    # digest mismatch -> reject
    res_bad = gtool._run(
        spec=spec,
        out_dir=str(tmp_path / "a"),
        review={"spec_digest": "b" * 64, "approved": True},
    )
    assert res_bad.status == "error"

    # approved + matching digest -> success
    res_ok = gtool._run(
        spec=spec,
        out_dir=str(tmp_path / "b"),
        review={"spec_digest": digest, "approved": True, "reviewer": "alice"},
    )
    assert res_ok.status == "success"
    bundle = res_ok.data["bundle"]
    planned = Path(bundle["planned_dir"])
    assert planned.exists()
    assert (planned / "config" / "config.yaml").exists()


def test_behavior_generate_psyflow_task_accepts_executor_dirs(tmp_path: Path):
    rtool = BehaviorResolveTaskSpecTool()
    rres = rtool._run(paradigm="n_back")
    spec = rres.data["spec"]
    digest = rres.data["spec_digest"]

    result = execute_tool(
        "behavior.generate_psyflow_task",
        {
            "spec": spec,
            "out_dir": str(tmp_path / "bundle"),
            "review": {"spec_digest": digest, "approved": True, "reviewer": "alice"},
        },
        work_dir=str(tmp_path / "work"),
        output_dir=str(tmp_path / "artifacts"),
    )

    assert result.status == "success"
    bundle = result.data["bundle"]
    assert Path(bundle["planned_dir"]).exists()


def test_behavior_paradigm_planner_accepts_executor_dirs(tmp_path: Path):
    result = execute_tool(
        "behavior.paradigm_planner",
        {"query": "2-back letter task, 6 min, TR=2s, 4 dummy scans"},
        work_dir=str(tmp_path / "work"),
        output_dir=str(tmp_path / "artifacts"),
    )

    assert result.status == "success"
    assert result.data["resolution"] == "matched"
    assert result.data["paradigm"] == "n_back"
    assert result.data["scanner_profile"]["n_volumes"] == 184


def test_ingest_psyflow_run_tool_rejects_outside_run(tmp_path: Path):
    rtool = BehaviorResolveTaskSpecTool()
    rres = rtool._run(paradigm="n_back")
    spec = rres.data["spec"]
    digest = rres.data["spec_digest"]
    gtool = BehaviorGeneratePsyflowTaskTool()
    gres = gtool._run(
        spec=spec,
        out_dir=str(tmp_path),
        review={"spec_digest": digest, "approved": True},
    )
    assert gres.status == "success"
    bundle = gres.data["bundle"]

    itool = BehaviorIngestPsyflowRunTool()
    # planned dir is NOT under <out>/run/ -> must error
    res = itool._run(
        bundle=bundle,
        run_data_dir=bundle["planned_dir"],
        out_dir=str(tmp_path),
    )
    assert res.status == "error"
    assert "planned vs run split" in (res.error or "")
