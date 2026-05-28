from brain_researcher.services.shared.planner.handoff import (
    HANDOFF_SCHEMA_VERSION,
    build_handoff_from_plan_payload,
    build_handoff_from_recipe_context,
)


def test_build_handoff_from_plan_payload_projects_compact_summary():
    handoff = build_handoff_from_plan_payload(
        {
            "plan_id": "plan-123",
            "version": 2,
            "resolvable": False,
            "warnings": ["planner warning"],
            "constraints": {"warnings": ["planner warning", "constraint warning"]},
            "mask_reasons": [{"code": "tool_unavailable"}],
            "run_summary": {
                "plan_conf": 0.25,
                "notes": ["plan is not resolvable"],
            },
            "context": {
                "pipeline": "glm",
                "inputs": {
                    "dataset_ref": "ds000001",
                    "contrast": "faces>shapes",
                },
                "query_understanding": {
                    "resolved_datasets": [{"dataset_id": "ds999999"}],
                },
            },
        },
        workflow_id="workflow-123",
    )

    assert handoff == {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "plan_id": "plan-123",
        "version": 2,
        "pipeline": "glm",
        "workflow_id": "workflow-123",
        "chosen_tool": None,
        "dataset_ref": "ds000001",
        "inputs": {"dataset_ref": "ds000001", "contrast": "faces>shapes"},
        "warnings": ["planner warning", "constraint warning"],
        "validation_summary": {
            "warning_count": 2,
            "resolvable": False,
            "mask_reason_count": 1,
            "plan_conf": 0.25,
            "notes": ["plan is not resolvable"],
        },
        "approval_level": "none",
        "allowed_tools": [],
        "run_mode_hint": "manual_review",
    }


def test_build_handoff_from_plan_payload_falls_back_to_qur_and_first_step_tool():
    handoff = build_handoff_from_plan_payload(
        {
            "plan_id": "plan-456",
            "dag": {"steps": [{"tool": "resolve_dataset_asset"}]},
            "context": {
                "pipeline": "dataset_browse",
                "query_understanding": {
                    "resolved_datasets": [{"dataset_id": "ds000114"}],
                },
            },
        }
    )

    assert handoff["chosen_tool"] == "resolve_dataset_asset"
    assert handoff["dataset_ref"] == "ds000114"
    assert handoff["workflow_id"] == "plan-456"
    assert handoff["validation_summary"] == {"warning_count": 0}
    assert handoff["approval_level"] in {"none", "confirm"}
    assert handoff["run_mode_hint"] in {
        "confirm_before_execute",
        "direct_execute",
        "manual_review",
    }


def test_build_handoff_from_recipe_context_keeps_runtime_compatibility():
    handoff = build_handoff_from_recipe_context(
        tool_id="clean_confounds",
        params={
            "dataset_ref": "ds000114",
            "img": "/tmp/sub-01_bold.nii.gz",
            "output_file": "/tmp/out.nii.gz",
        },
        metadata={"execution_story_kind": "portable_python_compute"},
        target_runtime="python",
    )

    assert handoff["schema_version"] == HANDOFF_SCHEMA_VERSION
    assert handoff["chosen_tool"] == "clean_confounds"
    assert handoff["workflow_id"] is None
    assert handoff["dataset_ref"] == "ds000114"
    assert handoff["inputs"]["img"] == "/tmp/sub-01_bold.nii.gz"
    assert handoff["approval_level"] == "confirm"
    assert handoff["allowed_tools"] == ["clean_confounds"]
    assert handoff["run_mode_hint"] == "confirm_before_execute"
    assert handoff["execution"] == {
        "target_runtime": "python",
        "execution_story_kind": "portable_python_compute",
    }
