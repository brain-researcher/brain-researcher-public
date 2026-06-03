from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.br_kg.etl.loaders.psych101_hf_loader import (
    Psych101DatasetMetadata,
    Psych101ExperimentSummary,
    Psych101ParquetFile,
    Psych101SplitInfo,
)
from brain_researcher.services.br_kg.graph.fake_graph_database import FakeGraphDB
from brain_researcher.services.tools.grandmaster.runtime_functions import (
    behavior_to_fmri_retrieval_export,
    centaur_offline_behavior_embeddings,
    centaur_prepare_task_payloads,
    psych101_fetch_hf_snapshot,
    psych101_import_eval_manifest,
    psych101_ingest,
    psych101_prepare_eval_manifest,
)


def _write_trial_tsv(path: Path) -> Path:
    path.write_text(
        (
            "experiment_id\ttask_name\tparticipant_id\ttrial_index\tchoice\trt_sec\tcorrect\tsex\tsite\tethnicity_group\tsample_weight\n"
            "exp-001\ttwo-step task\tsub-01\t0\tleft\t0.42\t1\tF\tsite_a\tgroup_a\t1.5\n"
            "exp-001\ttwo-step task\tsub-01\t1\tright\t0.58\t0\tF\tsite_a\tgroup_a\t1.5\n"
            "exp-001\ttwo-step task\tsub-02\t0\tleft\t0.39\t1\tM\tsite_b\tgroup_b\t0.5\n"
            "exp-002\tbandit task\tsub-03\t0\tarm_a\t0.61\t1\tF\tsite_a\tgroup_a\t1.0\n"
        ),
        encoding="utf-8",
    )
    return path


def test_psych101_ingest_writes_trials_and_graph_plan(tmp_path: Path) -> None:
    source = _write_trial_tsv(tmp_path / "psych101.tsv")
    out = tmp_path / "psych101_trials.csv"

    result = psych101_ingest(str(source), output_file=str(out))

    assert result.status == "success", result.error
    outputs = (result.data or {}).get("outputs") or {}
    assert Path(outputs["qc_table"]).exists()
    assert Path(outputs["graph_plan"]).exists()

    summary = (result.data or {}).get("summary") or {}
    assert summary["n_rows"] == 4
    assert summary["n_experiments"] == 2
    assert summary["n_participants"] == 3

    graph_plan = json.loads(Path(outputs["graph_plan"]).read_text(encoding="utf-8"))
    assert graph_plan["dataset"]["dataset_id"] == "psych101"
    assert len(graph_plan["experiments"]) == 2


def test_psych101_prepare_eval_manifest_emits_task_specs(tmp_path: Path) -> None:
    source = _write_trial_tsv(tmp_path / "psych101.tsv")
    ingest_out = tmp_path / "psych101_trials.csv"
    ingest_result = psych101_ingest(str(source), output_file=str(ingest_out))
    qc_table = (ingest_result.data or {}).get("outputs", {}).get("qc_table")
    assert qc_table

    manifest_path = tmp_path / "psych101_eval_manifest.json"
    result = psych101_prepare_eval_manifest(qc_table, output_file=str(manifest_path))

    assert result.status == "success", result.error
    outputs = (result.data or {}).get("outputs") or {}
    assert Path(outputs["eval_manifest"]).exists()

    payload = json.loads(Path(outputs["eval_manifest"]).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "psych101-eval-manifest-v1"
    assert payload["n_experiments"] == 2
    assert payload["n_participants"] == 3
    assert len(payload["benchmark_tasks"]) == 2
    assert payload["benchmark_tasks"][0]["schema_version"] == "task-spec-v1"


def test_psych101_prepare_eval_manifest_emits_fairness_audit_metadata(tmp_path: Path) -> None:
    source = _write_trial_tsv(tmp_path / "psych101.tsv")
    ingest_out = tmp_path / "psych101_trials.csv"
    ingest_result = psych101_ingest(str(source), output_file=str(ingest_out))
    qc_table = (ingest_result.data or {}).get("outputs", {}).get("qc_table")
    assert qc_table

    manifest_path = tmp_path / "psych101_eval_manifest.json"
    result = psych101_prepare_eval_manifest(
        qc_table,
        output_file=str(manifest_path),
        dataset_id="psych101-demo",
        audit_group_keys=["sex", "site", "ethnicity_group", "missing_col"],
        target_population="adult human participants",
        sampling_frame="psych101 synthetic export",
        inclusion_criteria="non-empty participant_id",
        exclusion_criteria="none",
        sample_weight_column="sample_weight",
        min_group_count=2,
    )

    assert result.status == "success", result.error
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    fairness_audit = payload["fairness_audit"]
    assert fairness_audit["schema_version"] == "br-fairness-audit-v1"
    assert fairness_audit["target_population"] == "adult human participants"
    assert fairness_audit["sampling_frame"] == "psych101 synthetic export"
    assert fairness_audit["group_audit"]["resolved_group_keys"] == [
        "sex",
        "site",
        "ethnicity_group",
    ]
    assert fairness_audit["group_audit"]["missing_group_keys"] == ["missing_col"]
    assert fairness_audit["group_audit"]["group_counts"]["site"]["participant_counts"] == {
        "site_a": 2,
        "site_b": 1,
    }
    assert fairness_audit["group_audit"]["group_counts"]["site"]["underpowered_groups"] == {
        "site_b": 1,
    }
    assert fairness_audit["sample_weight_summary"]["status"] == "resolved"
    assert fairness_audit["sample_weight_summary"]["mean"] == 1.125

    task_metadata = payload["benchmark_tasks"][0]["metadata"]
    assert task_metadata["fairness_audit"]["group_audit"]["resolved_group_keys"] == [
        "sex",
        "site",
        "ethnicity_group",
    ]
    assert task_metadata["fairness_audit"]["sample_weight_summary"]["status"] == "resolved"


def test_psych101_import_eval_manifest_registers_tasks(tmp_path: Path) -> None:
    source = _write_trial_tsv(tmp_path / "psych101.tsv")
    ingest_out = tmp_path / "psych101_trials.csv"
    ingest_result = psych101_ingest(str(source), output_file=str(ingest_out))
    qc_table = (ingest_result.data or {}).get("outputs", {}).get("qc_table")
    assert qc_table

    manifest_path = tmp_path / "psych101_eval_manifest.json"
    manifest_result = psych101_prepare_eval_manifest(
        qc_table,
        output_file=str(manifest_path),
        dataset_id="psych101-demo",
    )
    eval_manifest = (manifest_result.data or {}).get("outputs", {}).get("eval_manifest")
    assert eval_manifest

    db_path = tmp_path / "benchmarks.sqlite"
    summary_path = tmp_path / "psych101_benchmark_import.json"
    result = psych101_import_eval_manifest(
        eval_manifest,
        output_file=str(summary_path),
        benchmark_db_path=str(db_path),
    )

    assert result.status == "success", result.error
    outputs = (result.data or {}).get("outputs") or {}
    assert Path(outputs["benchmark_import_summary"]).exists()
    assert Path(outputs["benchmark_db"]).exists()

    payload = json.loads(Path(outputs["benchmark_import_summary"]).read_text(encoding="utf-8"))
    assert payload["dataset_id"] == "psych101-demo"
    assert payload["n_loaded_tasks"] == 2
    assert payload["import_summary"]["added"] == 2

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT task_id FROM benchmark_tasks WHERE dataset_id = ? ORDER BY task_id",
            ("psych101-demo",),
        ).fetchall()
        assert [row[0] for row in rows] == [
            "psych101-demo:exp-001",
            "psych101-demo:exp-002",
        ]
        task_spec_row = conn.execute(
            "SELECT task_spec_json FROM benchmark_tasks WHERE dataset_id = ? AND task_id = ?",
            ("psych101-demo", "psych101-demo:exp-001"),
        ).fetchone()
        assert task_spec_row is not None
        task_spec = json.loads(task_spec_row[0])
        assert task_spec["metadata"]["fairness_audit"]["group_audit"][
            "requested_group_keys"
        ] == []
    finally:
        conn.close()


def test_psych101_fetch_hf_snapshot_writes_graph_ready_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class StubNeo4jDB:
        def __init__(self) -> None:
            self.closed = False
            self.nodes: list[tuple[list[str], dict[str, object], str | None]] = []
            self.relationships: list[tuple[str, str, str, dict[str, object]]] = []

        def create_node(self, labels, properties=None, node_id=None, auto_commit=True):
            del auto_commit
            label_list = [labels] if isinstance(labels, str) else list(labels)
            self.nodes.append((label_list, dict(properties or {}), node_id))
            return node_id or f"node-{len(self.nodes)}"

        def create_relationship(
            self,
            start_node,
            end_node,
            rel_type,
            properties=None,
            auto_commit=True,
        ):
            del auto_commit
            self.relationships.append(
                (start_node, end_node, rel_type, dict(properties or {}))
            )
            return True

        def close(self) -> None:
            self.closed = True

    metadata = Psych101DatasetMetadata(
        dataset_id="marcelbinz/Psych-101",
        title="Psych-101",
        license="apache-2.0",
        tags=("psychology", "benchmark"),
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
        "brain_researcher.services.br_kg.etl.loaders.psych101_hf_loader."
        "psych101_hf_snapshot_to_graph_inputs",
        lambda repo_id="marcelbinz/Psych-101", **_: {
            "metadata": metadata,
            "dataset_metadata": {
                "dataset_id": "psych101-demo",
                "title": "Psych-101",
                "source": repo_id,
                "description": f"Psych-101 Hugging Face snapshot for {repo_id}",
                "url": metadata.card_url,
                "license": metadata.license,
                "n_experiments": len(experiments),
                "n_participants": 5,
                "n_trials": 5,
                "tags": list(metadata.tags),
            },
            "experiment_summaries": experiments,
            "experiment_rows": [
                {
                    "experiment_id": "peterson2021using/exp1.csv",
                    "experiment_name": "exp1",
                    "experiment_path": "peterson2021using/2-back/exp1.csv",
                    "n_participants": 3,
                    "n_trials": 3,
                },
                {
                    "experiment_id": "hebart2023things/exp1.csv",
                    "experiment_name": "exp1",
                    "experiment_path": "hebart2023things/bandit-choice/exp1.csv",
                    "n_participants": 2,
                    "n_trials": 2,
                },
            ],
        },
    )
    stub_db = StubNeo4jDB()
    monkeypatch.setattr(
        "brain_researcher.services.br_kg.graph.neo4j_utils.require_neo4j_db",
        lambda **_: stub_db,
    )

    out = tmp_path / "psych101_hf_metadata.json"
    result = psych101_fetch_hf_snapshot(
        output_file=str(out),
        dataset_id="psych101-demo",
    )

    assert result.status == "success", result.error
    outputs = (result.data or {}).get("outputs") or {}
    assert Path(outputs["dataset_metadata"]).exists()
    assert Path(outputs["experiment_summary"]).exists()
    assert Path(outputs["graph_plan"]).exists()
    assert Path(outputs["neo4j_ingest_summary"]).exists()

    metadata_payload = json.loads(Path(outputs["dataset_metadata"]).read_text(encoding="utf-8"))
    assert metadata_payload["repo_id"] == "marcelbinz/Psych-101"
    assert metadata_payload["graph_dataset_metadata"]["n_participants"] == 5
    assert metadata_payload["neo4j_ingest"]["status"] == "success"

    graph_payload = json.loads(Path(outputs["graph_plan"]).read_text(encoding="utf-8"))
    assert graph_payload["dataset"]["dataset_id"] == "psych101-demo"
    assert len(graph_payload["experiments"]) == 2
    assert stub_db.closed is True


def test_centaur_prepare_task_payloads_emits_feature_pack(tmp_path: Path) -> None:
    source = _write_trial_tsv(tmp_path / "psych101.tsv")
    ingest_out = tmp_path / "psych101_trials.csv"
    ingest_result = psych101_ingest(str(source), output_file=str(ingest_out))
    graph_plan = (ingest_result.data or {}).get("outputs", {}).get("graph_plan")
    assert graph_plan

    out = tmp_path / "psych101_centaur_task_payloads.json"
    result = centaur_prepare_task_payloads(
        graph_plan,
        output_file=str(out),
        recommended_model="minitaur",
    )

    assert result.status == "success", result.error
    outputs = (result.data or {}).get("outputs") or {}
    assert Path(outputs["task_payloads"]).exists()
    assert Path(outputs["task_prompts"]).exists()
    assert Path(outputs["experiment_prompts"]).exists()

    payload = json.loads(Path(outputs["task_payloads"]).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "centaur-task-payloads-v1"
    assert payload["integration_mode"] == "feature_provider_non_gpu"
    assert payload["recommended_model"] == "minitaur"
    assert payload["summary"]["n_task_payloads"] >= 2
    assert payload["summary"]["n_experiment_payloads"] == 2
    assert payload["task_payloads"][0]["centaur_prompt_text"]
    assert payload["task_payloads"][0]["task_text_v1"]
    assert any(
        task_payload["mapping_status"] == "unmapped"
        for task_payload in payload["task_payloads"]
    )

    task_prompt_lines = [
        line
        for line in Path(outputs["task_prompts"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    experiment_prompt_lines = [
        line
        for line in Path(outputs["experiment_prompts"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert task_prompt_lines
    assert len(experiment_prompt_lines) == 2


def test_centaur_prepare_task_payloads_can_filter_unmapped_records(tmp_path: Path) -> None:
    graph_plan = {
        "dataset": {"dataset_id": "psych101-demo", "name": "Psych-101"},
        "experiments": [
            {
                "experiment_id": "exp-001",
                "experiment_name": "exp-001",
                "description": "Repeated choices between uncertain options.",
            }
        ],
        "nodes": [
            {
                "node_id": "psych101:task:bandit-task",
                "labels": ["Task"],
                "properties": {
                    "id": "psych101:task:bandit-task",
                    "name": "bandit task",
                    "schema_version": "psych101-task-v1",
                },
            }
        ],
        "relationships": [
            {
                "start_node": "exp-001",
                "end_node": "psych101:task:bandit-task",
                "rel_type": "USES_TASK",
                "properties": {"source": "Psych-101", "confidence": 0.85},
            }
        ],
    }
    graph_path = tmp_path / "graph_plan.json"
    graph_path.write_text(json.dumps(graph_plan, indent=2), encoding="utf-8")

    out = tmp_path / "payloads.json"
    result = centaur_prepare_task_payloads(
        str(graph_path),
        output_file=str(out),
        include_unmapped=False,
    )

    assert result.status == "success", result.error
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["n_task_payloads"] == 0
    assert payload["summary"]["n_experiment_payloads"] == 0


def test_centaur_offline_behavior_embeddings_writes_task_feature_space(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _write_trial_tsv(tmp_path / "psych101.tsv")
    ingest_out = tmp_path / "psych101_trials.csv"
    ingest_result = psych101_ingest(str(source), output_file=str(ingest_out))
    graph_plan = (ingest_result.data or {}).get("outputs", {}).get("graph_plan")
    assert graph_plan

    payload_out = tmp_path / "psych101_centaur_task_payloads.json"
    payload_result = centaur_prepare_task_payloads(
        graph_plan,
        output_file=str(payload_out),
        recommended_model="minitaur",
    )
    payload_outputs = (payload_result.data or {}).get("outputs") or {}
    task_prompts = payload_outputs["task_prompts"]
    experiment_prompts = payload_outputs["experiment_prompts"]

    feature_pack = json.loads(payload_out.read_text(encoding="utf-8"))
    fake_db = FakeGraphDB()
    for task_payload in feature_pack["task_payloads"]:
        fake_db.create_node(
            "Task",
            {
                "id": task_payload["local_task_id"],
                "name": task_payload["local_task_name"],
            },
            node_id=task_payload["local_task_id"],
        )

    monkeypatch.setattr(
        "brain_researcher.services.br_kg.graph.neo4j_utils.require_neo4j_db",
        lambda **_: fake_db,
    )

    out = tmp_path / "psych101_centaur_behavior_embeddings.json"
    result = centaur_offline_behavior_embeddings(
        task_prompts,
        output_file=str(out),
        model_name_or_path="hash-test",
        experiment_prompts_jsonl=experiment_prompts,
        embedding_backend="hash",
        write_to_neo4j=True,
    )

    assert result.status == "success", result.error
    outputs = (result.data or {}).get("outputs") or {}
    assert Path(outputs["behavior_embeddings"]).exists()
    assert Path(outputs["task_embeddings"]).exists()
    assert Path(outputs["experiment_embeddings"]).exists()
    assert Path(outputs["neo4j_ingest_summary"]).exists()

    payload = json.loads(Path(outputs["behavior_embeddings"]).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "centaur-behavior-embeddings-v1"
    assert payload["embedding_property"] == "embedding_centaur_behavior_v1"
    assert payload["backend"] == "hash"
    assert payload["summary"]["n_task_embeddings"] >= 2
    assert payload["summary"]["neo4j_ingest_status"] == "success"

    first_task_id = feature_pack["task_payloads"][0]["local_task_id"]
    stored_node = fake_db.get_node(first_task_id)
    assert stored_node is not None
    assert "embedding_centaur_behavior_v1" in stored_node
    assert stored_node["embedding_centaur_behavior_v1_dim"] == 384


def test_behavior_to_fmri_retrieval_export_writes_json_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class StubNeo4jDB:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "brain_researcher.services.br_kg.graph.neo4j_utils.require_neo4j_db",
        lambda **_: StubNeo4jDB(),
    )
    monkeypatch.setattr(
        "brain_researcher.services.br_kg.query_service.behavior_to_fmri_retrieval",
        lambda **_: {
            "seed": {"id": "psych101:task:go-no-go"},
            "items": [{"item_id": "taskanalysis:ds000009:stopsignal"}],
            "summary": {
                "item_count": 1,
                "behavior_neighbor_count": 1,
                "retrieval_method_counts": {
                    "family_bridge": 1,
                    "behavior_similar_family_bridge": 1,
                },
            },
        },
    )

    out = tmp_path / "behavior_to_fmri_retrieval.json"
    result = behavior_to_fmri_retrieval_export(
        output_file=str(out),
        seed_id="psych101:task:go-no-go",
        limit=1,
    )

    assert result.status == "success", result.error
    outputs = (result.data or {}).get("outputs") or {}
    assert Path(outputs["retrieval_json"]).exists()

    payload = json.loads(Path(outputs["retrieval_json"]).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "behavior-to-fmri-retrieval-v1"
    assert payload["seed_id"] == "psych101:task:go-no-go"
    assert payload["retrieval"]["summary"]["item_count"] == 1
