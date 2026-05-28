from brain_researcher.services.orchestrator.models import (
    PipelineExecutionRequest,
    RunRequest,
)


def test_run_request_accepts_catalog_dataset_id() -> None:
    request = RunRequest(
        prompt="Run rest connectome workflow",
        dataset_id="ds:openneuro:ds000114",
    )

    assert request.dataset_id == "ds:openneuro:ds000114"


def test_pipeline_execution_request_accepts_catalog_dataset_id() -> None:
    request = PipelineExecutionRequest(
        dataset_id="ds:openneuro:ds000114",
        nodes=[
            {
                "id": "node_1",
                "type": "tool",
                "label": "Run workflow",
                "tool": "workflow_rest_connectome_e2e",
            }
        ],
    )

    assert request.dataset_id == "ds:openneuro:ds000114"
