from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("workflow_id", "params", "target_runtime", "runbook", "required_outputs"),
    [
        (
            "workflow_preprocessing_qc",
            {"bids_dir": "/data/bids", "output_dir": "/data/out", "dry_run": True},
            "neurodesk",
            "docs/runbooks/workflow_preprocessing_qc.md",
            ["qc_table.csv", "qc_outliers.csv", "qc_summary.json", "index.html"],
        ),
        (
            "workflow_rest_connectome_e2e",
            {"img": "/data/bold.nii.gz", "output_dir": "/data/out"},
            "python",
            "docs/runbooks/workflow_rest_connectome_e2e.md",
            [
                "timeseries/timeseries.npy",
                "timeseries/timeseries.csv",
                "connectivity_matrix.npy",
                "feature_contract.json",
            ],
        ),
        (
            "workflow_task_glm_group",
            {
                "bids_dir": "/data/bids",
                "fmriprep_dir": "/data/fmriprep",
                "task": "linebisection",
                "output_dir": "/tmp/task_glm_group_out",
            },
            "python",
            "docs/runbooks/workflow_task_glm_group.md",
            [
                "first_level_dirs",
                "selected_zmaps",
                "second_level/group_zmap.nii.gz",
                "second_level/glm_second_level_summary.json",
            ],
        ),
        (
            "workflow_psych101_ingest_eval",
            {
                "psych101_tsv": "/data/psych101.tsv",
                "output_dir": "/tmp/psych101_out",
            },
            "python",
            "docs/runbooks/workflow_psych101_ingest_eval.md",
            [
                "psych101_trials.csv",
                "psych101_eval_manifest.json",
            ],
        ),
        (
            "workflow_psych101_hf_snapshot",
            {
                "output_dir": "/tmp/psych101_hf_out",
            },
            "python",
            "docs/runbooks/workflow_psych101_hf_snapshot.md",
            [
                "psych101_hf_metadata.json",
                "psych101_hf_metadata_experiments.json",
                "psych101_hf_metadata_graph_plan.json",
                "psych101_hf_metadata_neo4j_ingest.json",
            ],
        ),
        (
            "workflow_psych101_benchmark_import",
            {
                "eval_manifest_json": "/data/psych101_eval_manifest.json",
                "output_dir": "/tmp/psych101_benchmark_out",
            },
            "python",
            "docs/runbooks/workflow_psych101_benchmark_import.md",
            [
                "psych101_benchmark_import.json",
            ],
        ),
        (
            "workflow_psych101_centaur_task_payloads",
            {
                "output_dir": "/tmp/psych101_centaur_out",
            },
            "python",
            "docs/runbooks/workflow_psych101_centaur_task_payloads.md",
            [
                "psych101_hf_metadata.json",
                "psych101_hf_metadata_experiments.json",
                "psych101_hf_metadata_graph_plan.json",
                "psych101_hf_metadata_neo4j_ingest.json",
                "psych101_centaur_task_payloads.json",
                "psych101_centaur_task_prompts.jsonl",
                "psych101_centaur_experiment_prompts.jsonl",
            ],
        ),
        (
            "workflow_psych101_centaur_behavior_embeddings",
            {
                "output_dir": "/tmp/psych101_centaur_embed_out",
                "model_name_or_path": "hash-test",
            },
            "python",
            "docs/runbooks/workflow_psych101_centaur_behavior_embeddings.md",
            [
                "psych101_hf_metadata.json",
                "psych101_hf_metadata_experiments.json",
                "psych101_hf_metadata_graph_plan.json",
                "psych101_hf_metadata_neo4j_ingest.json",
                "psych101_centaur_task_payloads.json",
                "psych101_centaur_task_prompts.jsonl",
                "psych101_centaur_experiment_prompts.jsonl",
                "psych101_centaur_behavior_embeddings.json",
                "psych101_centaur_task_embeddings.jsonl",
                "psych101_centaur_experiment_embeddings.jsonl",
                "psych101_centaur_neo4j_ingest.json",
            ],
        ),
        (
            "workflow_behavior_to_fmri_retrieval",
            {
                "output_dir": "/tmp/behavior_to_fmri_out",
                "seed_id": "psych101:task:go-no-go",
            },
            "python",
            "docs/runbooks/workflow_behavior_to_fmri_retrieval.md",
            [
                "behavior_to_fmri_retrieval.json",
            ],
        ),
    ],
)
def test_workflow_search_and_execution_recipe_preserve_runbook_and_artifact_contract(
    workflow_id: str,
    params: dict[str, object],
    target_runtime: str,
    runbook: str,
    required_outputs: list[str],
) -> None:
    from brain_researcher.services.mcp import server as srv

    search_resp = srv.workflow_search(workflow_id, limit=10)
    assert search_resp["ok"] is True
    row = next(
        workflow
        for workflow in search_resp["workflows"]
        if workflow.get("id") == workflow_id
    )

    assert row["runbook"] == runbook
    assert row["artifact_contract"]["required_outputs"] == required_outputs

    recipe_resp = srv.get_execution_recipe(
        workflow_id,
        params=params,
        target_runtime=target_runtime,
    )
    assert recipe_resp["ok"] is True
    assert recipe_resp["runbook"] == runbook
    assert recipe_resp["artifact_contract"] == row["artifact_contract"]
