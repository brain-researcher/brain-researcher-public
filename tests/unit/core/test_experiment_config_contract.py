from __future__ import annotations

from brain_researcher.core.contracts import ExperimentConfigV1


def test_experiment_config_contract_parses_r5_shape():
    payload = {
        "schema_version": "experiment-config-v1",
        "experiment_id": "r5_test",
        "comparison_type": "integrated_vs_isolated",
        "seeds": {"global_seed": 42},
        "runs": [
            {
                "run_key": "integrated",
                "mode": "integrated",
                "dataset_id": "ds:openneuro:ds000001",
                "workflow_id": "workflow_preprocessing_qc",
                "parameters": {"kg_hints": True},
            },
            {
                "run_key": "isolated",
                "mode": "isolated",
                "dataset_id": "ds:openneuro:ds000001",
                "workflow_id": "workflow_preprocessing_qc",
                "parameters": {"kg_hints": False},
            },
        ],
    }
    cfg = ExperimentConfigV1.model_validate(payload)
    assert cfg.experiment_id == "r5_test"
    assert len(cfg.runs) == 2
    assert cfg.runs[0].run_key == "integrated"
    assert cfg.runs[1].parameters["kg_hints"] is False

