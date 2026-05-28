"""Psych-101 workflow catalog checks."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from brain_researcher.services.mcp.server import _workflow_search_rows
from brain_researcher.services.tools.catalog_loader import load_orchestration_workflows


def _load_workflow(repo_root: Path, workflow_id: str) -> dict:
    catalog_path = repo_root / "configs" / "workflows" / "workflow_catalog.yaml"
    data = yaml.safe_load(catalog_path.read_text()) or {}
    workflows = data.get("workflows") or []
    for wf in workflows:
        if isinstance(wf, dict) and wf.get("id") == workflow_id:
            return wf
    raise AssertionError(f"{workflow_id} missing from catalog")


@pytest.mark.parametrize(
    "workflow_id",
    [
        "workflow_psych101_ingest_eval",
        "workflow_psych101_hf_snapshot",
        "workflow_psych101_benchmark_import",
        "workflow_psych101_centaur_task_payloads",
        "workflow_psych101_centaur_behavior_embeddings",
        "workflow_behavior_to_fmri_retrieval",
    ],
)
def test_psych101_workflow_is_discoverable_via_orchestration_search(workflow_id: str):
    assert workflow_id in load_orchestration_workflows()

    rows = _workflow_search_rows()
    row_ids = {str(row.get("id") or "") for row in rows}
    assert workflow_id in row_ids


def test_psych101_workflow_has_minimal_two_step_contract():
    repo_root = Path(__file__).resolve().parents[3]
    wf = _load_workflow(repo_root, "workflow_psych101_ingest_eval")

    assert wf.get("stage") == "reporting"
    assert wf.get("supported_recipe_targets") == ["python"]
    assert wf.get("primary_target") == "python"
    assert wf.get("execution_story_kind") == "composite_workflow"

    params = wf.get("params") or {}
    schema = params.get("schema") or {}
    assert schema.get("required") == ["psych101_tsv", "output_dir"]

    props = schema.get("properties") or {}
    assert "psych101_tsv" in props
    assert "output_dir" in props
    assert "output_stem" in props
    assert "dataset_id" in props
    assert "source_name" in props
    assert "heldout_ratio" in props

    defaults = params.get("defaults") or {}
    assert defaults.get("output_stem") == "psych101_eval_manifest"
    assert defaults.get("dataset_id") == "psych101"
    assert defaults.get("source_name") == "Psych-101"
    assert defaults.get("heldout_ratio") == 0.1

    runtime = wf.get("runtime") or {}
    steps = runtime.get("steps") or []
    assert [step.get("tool") for step in steps] == [
        "psych101_ingest",
        "psych101_prepare_eval_manifest",
    ]

    manifest_step = steps[1]
    manifest_params = manifest_step.get("params") or {}
    assert (
        manifest_params.get("qc_table")
        == "${steps.ingest.data.outputs.qc_table}"
    )


def test_psych101_hf_snapshot_workflow_has_official_dataset_contract():
    repo_root = Path(__file__).resolve().parents[3]
    wf = _load_workflow(repo_root, "workflow_psych101_hf_snapshot")

    assert wf.get("stage") == "dataset"
    assert wf.get("supported_recipe_targets") == ["python"]

    params = wf.get("params") or {}
    schema = params.get("schema") or {}
    assert schema.get("required") == ["output_dir"]

    props = schema.get("properties") or {}
    assert "repo_id" in props
    assert "dataset_id" in props
    assert "sample_text" in props
    assert "write_to_neo4j" in props
    assert "neo4j_database" in props

    defaults = params.get("defaults") or {}
    assert defaults.get("repo_id") == "marcelbinz/Psych-101"
    assert defaults.get("dataset_id") == "psych101"
    assert defaults.get("source_name") == "Psych-101"
    assert defaults.get("sample_text") is True
    assert defaults.get("write_to_neo4j") is True

    runtime = wf.get("runtime") or {}
    steps = runtime.get("steps") or []
    assert [step.get("tool") for step in steps] == ["psych101_fetch_hf_snapshot"]
    snapshot_params = (steps[0].get("params") or {})
    assert snapshot_params.get("sample_text") == "${inputs.sample_text:-true}"


def test_psych101_benchmark_import_workflow_has_manifest_bridge_contract():
    repo_root = Path(__file__).resolve().parents[3]
    wf = _load_workflow(repo_root, "workflow_psych101_benchmark_import")

    assert wf.get("stage") == "reporting"
    assert wf.get("supported_recipe_targets") == ["python"]

    params = wf.get("params") or {}
    schema = params.get("schema") or {}
    assert schema.get("required") == ["eval_manifest_json", "output_dir"]

    props = schema.get("properties") or {}
    assert "dataset_id" in props
    assert "version" in props
    assert "benchmark_db_path" in props
    assert "overwrite_governance" in props

    defaults = params.get("defaults") or {}
    assert defaults.get("output_stem") == "psych101_benchmark_import"
    assert defaults.get("version") == "1.0"
    assert defaults.get("overwrite_governance") is False

    runtime = wf.get("runtime") or {}
    steps = runtime.get("steps") or []
    assert [step.get("tool") for step in steps] == ["psych101_import_eval_manifest"]


def test_psych101_centaur_task_payloads_workflow_has_non_gpu_feature_pack_contract():
    repo_root = Path(__file__).resolve().parents[3]
    wf = _load_workflow(repo_root, "workflow_psych101_centaur_task_payloads")

    assert wf.get("stage") == "dataset"
    assert wf.get("supported_recipe_targets") == ["python"]

    params = wf.get("params") or {}
    schema = params.get("schema") or {}
    assert schema.get("required") == ["output_dir"]

    props = schema.get("properties") or {}
    assert "repo_id" in props
    assert "dataset_id" in props
    assert "write_to_neo4j" in props
    assert "include_unmapped" in props
    assert "include_experiments" in props
    assert "recommended_model" in props

    defaults = params.get("defaults") or {}
    assert defaults.get("write_to_neo4j") is False
    assert defaults.get("include_unmapped") is True
    assert defaults.get("include_experiments") is True
    assert defaults.get("recommended_model") == "minitaur"

    runtime = wf.get("runtime") or {}
    steps = runtime.get("steps") or []
    assert [step.get("tool") for step in steps] == [
        "psych101_fetch_hf_snapshot",
        "centaur_prepare_task_payloads",
    ]
    payload_params = (steps[1].get("params") or {})
    assert (
        payload_params.get("graph_plan_json")
        == "${steps.snapshot.data.outputs.graph_plan}"
    )


def test_psych101_centaur_behavior_embeddings_workflow_has_offline_runner_contract():
    repo_root = Path(__file__).resolve().parents[3]
    wf = _load_workflow(repo_root, "workflow_psych101_centaur_behavior_embeddings")

    assert wf.get("stage") == "dataset"
    assert wf.get("supported_recipe_targets") == ["python"]

    params = wf.get("params") or {}
    schema = params.get("schema") or {}
    assert schema.get("required") == ["output_dir", "model_name_or_path"]

    props = schema.get("properties") or {}
    assert "embedding_backend" in props
    assert "pooling" in props
    assert "write_embeddings_to_neo4j" in props
    assert "write_experiment_embeddings" in props
    assert "embedding_property" in props

    defaults = params.get("defaults") or {}
    assert defaults.get("embedding_backend") == "hf_hidden_state"
    assert defaults.get("write_embeddings_to_neo4j") is True
    assert defaults.get("embedding_property") == "embedding_centaur_behavior_v1"

    runtime = wf.get("runtime") or {}
    steps = runtime.get("steps") or []
    assert [step.get("tool") for step in steps] == [
        "psych101_fetch_hf_snapshot",
        "centaur_prepare_task_payloads",
        "centaur_offline_behavior_embeddings",
    ]
    embedding_params = (steps[2].get("params") or {})
    assert (
        embedding_params.get("task_prompts_jsonl")
        == "${steps.prepare_payloads.data.outputs.task_prompts}"
    )


def test_behavior_to_fmri_retrieval_workflow_has_single_step_export_contract():
    repo_root = Path(__file__).resolve().parents[3]
    wf = _load_workflow(repo_root, "workflow_behavior_to_fmri_retrieval")

    assert wf.get("stage") == "reporting"
    assert wf.get("supported_recipe_targets") == ["python"]
    assert wf.get("primary_target") == "python"

    params = wf.get("params") or {}
    schema = params.get("schema") or {}
    assert schema.get("required") == ["output_dir"]

    props = schema.get("properties") or {}
    assert "seed_id" in props
    assert "name" in props
    assert "limit" in props
    assert "max_behavior_neighbors" in props

    defaults = params.get("defaults") or {}
    assert defaults.get("output_stem") == "behavior_to_fmri_retrieval"
    assert defaults.get("seed_id") == "psych101:task:go-no-go"
    assert defaults.get("limit") == 12

    runtime = wf.get("runtime") or {}
    steps = runtime.get("steps") or []
    assert [step.get("tool") for step in steps] == ["behavior_to_fmri_retrieval_export"]
    retrieve_params = (steps[0].get("params") or {})
    assert (
        retrieve_params.get("output_file")
        == "${inputs.output_dir}/${inputs.output_stem:-behavior_to_fmri_retrieval}.json"
    )


def test_psych101_runbook_exists_and_documents_the_two_step_flow():
    repo_root = Path(__file__).resolve().parents[3]
    runbook = repo_root / "docs" / "runbooks" / "workflow_psych101_ingest_eval.md"
    text = runbook.read_text(encoding="utf-8")

    assert "workflow_psych101_ingest_eval" in text
    assert "psych101_ingest" in text
    assert "psych101_prepare_eval_manifest" in text
    assert "psych101_trials.csv" in text
    assert "psych101_eval_manifest.json" in text


def test_psych101_hf_snapshot_runbook_exists():
    repo_root = Path(__file__).resolve().parents[3]
    runbook = repo_root / "docs" / "runbooks" / "workflow_psych101_hf_snapshot.md"
    text = runbook.read_text(encoding="utf-8")

    assert "workflow_psych101_hf_snapshot" in text
    assert "psych101_fetch_hf_snapshot" in text
    assert "psych101_hf_metadata.json" in text
    assert "psych101_hf_metadata_graph_plan.json" in text
    assert "psych101_hf_metadata_neo4j_ingest.json" in text


def test_psych101_benchmark_import_runbook_exists():
    repo_root = Path(__file__).resolve().parents[3]
    runbook = repo_root / "docs" / "runbooks" / "workflow_psych101_benchmark_import.md"
    text = runbook.read_text(encoding="utf-8")

    assert "workflow_psych101_benchmark_import" in text
    assert "psych101_import_eval_manifest" in text
    assert "psych101_benchmark_import.json" in text


def test_psych101_centaur_task_payloads_runbook_exists():
    repo_root = Path(__file__).resolve().parents[3]
    runbook = repo_root / "docs" / "runbooks" / "workflow_psych101_centaur_task_payloads.md"
    text = runbook.read_text(encoding="utf-8")

    assert "workflow_psych101_centaur_task_payloads" in text
    assert "psych101_fetch_hf_snapshot" in text
    assert "centaur_prepare_task_payloads" in text
    assert "psych101_centaur_task_payloads.json" in text
    assert "psych101_centaur_task_prompts.jsonl" in text


def test_psych101_centaur_behavior_embeddings_runbook_exists():
    repo_root = Path(__file__).resolve().parents[3]
    runbook = (
        repo_root
        / "docs"
        / "runbooks"
        / "workflow_psych101_centaur_behavior_embeddings.md"
    )
    text = runbook.read_text(encoding="utf-8")

    assert "workflow_psych101_centaur_behavior_embeddings" in text
    assert "centaur_offline_behavior_embeddings" in text
    assert "embedding_centaur_behavior_v1" in text


def test_behavior_to_fmri_retrieval_runbook_exists():
    repo_root = Path(__file__).resolve().parents[3]
    runbook = repo_root / "docs" / "runbooks" / "workflow_behavior_to_fmri_retrieval.md"
    text = runbook.read_text(encoding="utf-8")

    assert "workflow_behavior_to_fmri_retrieval" in text
    assert "behavior_to_fmri_retrieval_export" in text
    assert "behavior_to_fmri_retrieval.json" in text
    assert "family-aware" in text or "family aware" in text
