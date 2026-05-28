from brain_researcher.services.orchestrator.plan_adapter import plan_to_workflow


def test_plan_adapter_builds_dependencies():
    plan_payload = {
        "plan_id": "plan-123",
        "version": 1,
        "dag": {
            "steps": [
                {
                    "id": "001-fetch",
                    "tool": "fetch_atlas",
                    "produces": {"atlas": "atlas_artifact"},
                },
                {
                    "id": "002-process",
                    "tool": "process",
                    "consumes": {"atlas": "atlas_artifact"},
                },
            ],
            "artifacts": [],
        },
        "context": {"pipeline": "connectivity"},
    }

    workflow = plan_to_workflow(plan_payload)

    assert workflow.workflow_id == "plan-123"
    assert len(workflow.steps) == 2
    assert workflow.steps[1].depends_on == ["001-fetch"]
    assert workflow.metadata["handoff"]["plan_id"] == "plan-123"
    assert workflow.metadata["handoff"]["pipeline"] == "connectivity"
    assert "context" not in workflow.metadata
    assert "snapshot" not in workflow.metadata
    assert workflow.metadata["execution"]["run_mode_hint"] == "confirm_before_execute"


def test_plan_adapter_generates_ids_when_missing():
    plan_payload = {
        "plan_id": "plan-456",
        "dag": {
            "steps": [
                {
                    # missing id
                    "tool": "first",
                    "produces": {"out": "artifact"},
                },
                {
                    "tool": "second",
                    "consumes": {"input": "artifact"},
                },
            ],
            "artifacts": [],
        },
    }

    workflow = plan_to_workflow(plan_payload)
    generated_ids = [step.step_id for step in workflow.steps]

    assert generated_ids[0].startswith("001-")
    assert generated_ids[1].startswith("002-")
    assert workflow.steps[1].depends_on == [generated_ids[0]]
    assert workflow.metadata["handoff"]["chosen_tool"] == "first"
    assert workflow.metadata["execution"]["approval_level"] == "confirm"


def test_plan_adapter_threads_compact_handoff_metadata():
    plan_payload = {
        "plan_id": "plan-789",
        "version": 3,
        "dag": {
            "steps": [{"id": "001-connectivity", "tool": "connectivity.run"}],
            "artifacts": [],
        },
        "context": {
            "pipeline": "connectivity",
            "inputs": {"dataset_ref": "ds000114", "atlas": "aal"},
        },
        "chosen_tool": "connectivity.run",
        "warnings": ["planner warning"],
        "constraints": {"warnings": ["constraint warning"]},
        "resolvable": True,
        "mask_reasons": [{"code": "soft-warning"}],
        "run_summary": {"plan_conf": 0.92, "notes": ["ready for execution"]},
    }

    workflow = plan_to_workflow(plan_payload)

    assert workflow.metadata["handoff"] == {
        "plan_id": "plan-789",
        "version": 3,
        "pipeline": "connectivity",
        "workflow_id": "plan-789",
        "chosen_tool": "connectivity.run",
        "dataset_ref": "ds000114",
        "inputs": {"dataset_ref": "ds000114", "atlas": "aal"},
        "warnings": ["planner warning", "constraint warning"],
        "validation_summary": {
            "warning_count": 2,
            "resolvable": True,
            "mask_reason_count": 1,
            "plan_conf": 0.92,
            "notes": ["ready for execution"],
        },
        "approval_level": "confirm",
        "allowed_tools": ["connectivity.run"],
        "run_mode_hint": "confirm_before_execute",
    }
    assert workflow.metadata["execution"] == {
        "chosen_tool": "connectivity.run",
        "approval_level": "confirm",
        "allowed_tools": ["connectivity.run"],
        "run_mode_hint": "confirm_before_execute",
    }
