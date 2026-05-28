from benchmarks.planner_microtooling.runner import BenchmarkTask, _run_workflow_track
from benchmarks.planner_microtooling.workflow_track import (
    WorkflowRule,
    extract_missing_required_params,
    match_workflow,
)


def test_match_workflow_uses_capability_map_rules():
    rules = [
        WorkflowRule(
            workflow_id="workflow_preprocessing_qc",
            any_capabilities=("fmriprep_tool", "qc_tools"),
            query_keywords=("preprocess", "qc"),
        ),
        WorkflowRule(
            workflow_id="workflow_task_glm_group",
            any_capabilities=("nilearn_glm_tool",),
            query_keywords=("glm",),
        ),
    ]

    match = match_workflow(
        query="Run preprocessing and QC on this resting-state dataset",
        expected_capabilities=("fmriprep_tool", "mriqc_tool"),
        rules=rules,
        allowed_workflows={"workflow_preprocessing_qc", "workflow_task_glm_group"},
    )
    assert match is not None
    assert match.workflow_id == "workflow_preprocessing_qc"
    assert match.reason == "capability_map"
    assert match.score > 0


def test_extract_missing_required_params_from_validate_issue():
    issues = [
        {
            "level": "error",
            "code": "params_missing_required",
            "message": "Missing required params for workflow_preprocessing_qc: ['bids_dir', 'output_dir']",
        }
    ]
    assert extract_missing_required_params(issues) == ["bids_dir", "output_dir"]


def test_run_workflow_track_validate_only_success(monkeypatch):
    class _FakeMCP:
        def workflow_search(self, query: str = "", limit: int = 20, offset: int = 0):
            return {
                "ok": True,
                "workflows": [{"id": "workflow_preprocessing_qc"}],
                "count": 1,
            }

        def pipeline_plan_validate(self, plan):
            params = plan["steps"][0]["params"]
            if "bids_dir" in params:
                return {"ok": True, "issues": []}
            return {
                "ok": False,
                "issues": [
                    {
                        "level": "error",
                        "code": "params_missing_required",
                        "message": "Missing required params for workflow_preprocessing_qc: ['bids_dir']",
                    }
                ],
            }

    monkeypatch.setattr(
        "benchmarks.planner_microtooling.runner.load_workflow_capability_map",
        lambda: [
            WorkflowRule(
                workflow_id="workflow_preprocessing_qc",
                any_capabilities=("fmriprep_tool",),
                query_keywords=("preprocess",),
            )
        ],
    )
    monkeypatch.setattr(
        "benchmarks.planner_microtooling.runner.load_workflow_param_templates",
        lambda: {
            "workflow_preprocessing_qc": {
                "bids_dir": "/tmp/bids",
                "output_dir": "/tmp/out",
                "outlier_metric": "fd_mean",
                "outlier_z": 2.5,
            }
        },
    )

    tasks = [
        BenchmarkTask(
            task_id="PREP-002",
            query="Preprocess ADHD resting-state with QC",
            expected_capabilities=("fmriprep_tool", "qc_tools"),
            category="Preprocessing",
        )
    ]
    rows, summary = _run_workflow_track(tasks, include_context=False, limit=None, mcp_api=_FakeMCP())

    assert len(rows) == 1
    assert rows[0]["matched_workflow_id"] == "workflow_preprocessing_qc"
    assert rows[0]["plan_validate_ok"] is True
    assert summary["workflow_match_rate"] == 1.0
    assert summary["validate_pass_rate"] == 1.0
    assert summary["param_missing_rate"] == 0.0
