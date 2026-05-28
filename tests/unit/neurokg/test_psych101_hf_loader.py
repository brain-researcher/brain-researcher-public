from __future__ import annotations

import httpx
import pandas as pd

import brain_researcher.services.neurokg.etl.loaders.psych101_hf_loader as psych101_hf_loader
from brain_researcher.services.neurokg.etl.loaders.psych101_hf_loader import (
    DEFAULT_DATASET_ID,
    Psych101DatasetMetadata,
    Psych101ExperimentSummary,
    Psych101ParquetFile,
    Psych101SplitInfo,
    aggregate_psych101_experiments,
    fetch_psych101_dataset_metadata,
    ingest_psych101_hf_snapshot,
    psych101_hf_snapshot_to_graph_inputs,
    summarize_psych101_from_metadata,
)


def _mock_transport(response_map: dict[str, dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.url.scheme}://{request.url.host}{request.url.path}"
        if key not in response_map:
            raise AssertionError(f"Unexpected request: {request.method} {request.url}")
        payload = response_map[key]
        return httpx.Response(200, json=payload, request=request)

    return httpx.MockTransport(handler)


def test_fetch_psych101_dataset_metadata_reads_hf_and_datasets_server() -> None:
    dataset_url = f"https://huggingface.co/api/datasets/{DEFAULT_DATASET_ID}"
    splits_url = "https://datasets-server.huggingface.co/splits"
    parquet_url = "https://datasets-server.huggingface.co/parquet"

    transport = _mock_transport(
        {
            dataset_url: {
                "id": DEFAULT_DATASET_ID,
                "title": "Psych-101",
                "license": "apache-2.0",
                "tags": ["psychology", "benchmark"],
                "cardData": {
                    "pretty_name": "Psych-101",
                    "license": "apache-2.0",
                    "tags": ["decision-making", "memory"],
                },
            },
            splits_url: {
                "splits": [
                    {"split": "train", "num_examples": 120},
                    {"split": "test", "num_rows": 20},
                ]
            },
            parquet_url: {
                "parquet_files": [
                    {
                        "split": "train",
                        "filename": "train-00000-of-00001.parquet",
                        "url": "https://huggingface.co/datasets/marcelbinz/Psych-101/resolve/main/train-00000-of-00001.parquet",
                        "num_rows": 120,
                    },
                    {
                        "split": "test",
                        "filename": "test-00000-of-00001.parquet",
                        "url": "https://huggingface.co/datasets/marcelbinz/Psych-101/resolve/main/test-00000-of-00001.parquet",
                        "num_rows": 20,
                    },
                ]
            },
        }
    )

    with httpx.Client(transport=transport, timeout=10.0) as client:
        metadata = fetch_psych101_dataset_metadata(client=client)

    assert metadata.dataset_id == DEFAULT_DATASET_ID
    assert metadata.title == "Psych-101"
    assert metadata.license == "apache-2.0"
    assert metadata.tags == ("psychology", "benchmark", "decision-making", "memory")
    assert [(split.split, split.num_rows) for split in metadata.splits] == [
        ("train", 120),
        ("test", 20),
    ]
    assert [file.url for file in metadata.parquet_files] == [
        "https://huggingface.co/datasets/marcelbinz/Psych-101/resolve/main/train-00000-of-00001.parquet",
        "https://huggingface.co/datasets/marcelbinz/Psych-101/resolve/main/test-00000-of-00001.parquet",
    ]


def test_fetch_psych101_dataset_metadata_falls_back_to_siblings() -> None:
    dataset_url = f"https://huggingface.co/api/datasets/{DEFAULT_DATASET_ID}"
    splits_url = "https://datasets-server.huggingface.co/splits"
    parquet_url = "https://datasets-server.huggingface.co/parquet"

    transport = _mock_transport(
        {
            dataset_url: {
                "id": DEFAULT_DATASET_ID,
                "title": "Psych-101",
                "siblings": [
                    {"rfilename": "train-00000-of-00001.parquet"},
                    {"rfilename": "not-parquet.txt"},
                ],
            },
            splits_url: {"splits": []},
            parquet_url: {"parquet_files": []},
        }
    )

    with httpx.Client(transport=transport, timeout=10.0) as client:
        metadata = fetch_psych101_dataset_metadata(client=client)

    assert len(metadata.parquet_files) == 1
    assert metadata.parquet_files[0].filename == "train-00000-of-00001.parquet"
    assert metadata.parquet_files[0].split is None
    assert metadata.parquet_files[0].url.endswith(
        "/datasets/marcelbinz/Psych-101/resolve/main/train-00000-of-00001.parquet"
    )


def test_aggregate_psych101_experiments_reads_only_requested_columns() -> None:
    sources = ["file-a.parquet", "file-b.parquet"]
    frames = {
        "file-a.parquet": pd.DataFrame(
            {
                "experiment": ["exp-a", "exp-a", "exp-b"],
                "participant": ["p1", "p2", "p1"],
                "text": ["first", None, "beta"],
                "unused": [1, 2, 3],
            }
        ),
        "file-b.parquet": pd.DataFrame(
            {
                "experiment": ["exp-a", "exp-c"],
                "participant": ["p3", "p4"],
                "text": ["second", "gamma"],
                "unused": [4, 5],
            }
        ),
    }
    seen_calls: list[tuple[str, tuple[str, ...] | None]] = []

    def fake_read_parquet(source: str, *, columns: list[str] | None = None):
        seen_calls.append((source, tuple(columns) if columns is not None else None))
        frame = frames[source]
        if columns is None:
            return frame
        return frame.loc[:, columns]

    summaries = aggregate_psych101_experiments(
        sources,
        read_parquet=fake_read_parquet,
        sample_text_column="text",
    )

    assert seen_calls == [
        ("file-a.parquet", ("experiment", "participant", "text")),
        ("file-b.parquet", ("experiment", "participant", "text")),
    ]
    assert [summary.experiment for summary in summaries] == ["exp-a", "exp-b", "exp-c"]
    exp_a = next(summary for summary in summaries if summary.experiment == "exp-a")
    assert exp_a.row_count == 3
    assert exp_a.participant_count == 3
    assert exp_a.sample_text == "first"
    assert exp_a.source_files == ("file-a.parquet", "file-b.parquet")


def test_aggregate_psych101_experiments_emits_cohort_metadata() -> None:
    frames = {
        "file-a.parquet": pd.DataFrame(
            {
                "experiment": ["exp-a", "exp-a", "exp-b"],
                "participant": ["p1", "p2", "p3"],
                "site": ["site_a", "site_b", "site_a"],
                "sex": ["F", "M", "F"],
                "sample_weight": [1.5, 0.5, 1.0],
            }
        )
    }

    summaries = aggregate_psych101_experiments(
        ["file-a.parquet"],
        read_parquet=lambda source, **_: frames[str(source)],
        audit_group_columns=["site", "sex"],
        sample_weight_column="sample_weight",
        min_group_count=2,
    )

    exp_a = next(summary for summary in summaries if summary.experiment == "exp-a")
    assert exp_a.group_audit["resolved_group_keys"] == ["site", "sex"]
    assert exp_a.group_audit["group_counts"]["site"]["participant_counts"] == {
        "site_a": 1,
        "site_b": 1,
    }
    assert exp_a.group_audit["group_counts"]["site"]["underpowered_groups"] == {
        "site_a": 1,
        "site_b": 1,
    }
    assert exp_a.sample_weight_summary["status"] == "resolved"
    assert exp_a.sample_weight_summary["mean"] == 1.0


def test_summarize_psych101_from_metadata_reuses_parquet_urls() -> None:
    assert summarize_psych101_from_metadata(
        Psych101DatasetMetadata(dataset_id=DEFAULT_DATASET_ID)
    ) == []


def test_psych101_hf_snapshot_to_graph_inputs_preserves_experiment_paths(
    monkeypatch,
) -> None:
    metadata = Psych101DatasetMetadata(
        dataset_id=DEFAULT_DATASET_ID,
        title="Psych-101",
        license="apache-2.0",
        tags=("psychology",),
        splits=(Psych101SplitInfo(split="train", num_rows=2),),
        parquet_files=(
            Psych101ParquetFile(
                split="train",
                url="https://example.org/train.parquet",
                filename="train.parquet",
                num_rows=2,
            ),
        ),
        source_url="https://huggingface.co/datasets/marcelbinz/Psych-101",
        card_url="https://huggingface.co/datasets/marcelbinz/Psych-101",
    )
    summaries = [
        Psych101ExperimentSummary(
            experiment="peterson2021using/2-back/exp1.csv",
            row_count=2,
            participant_count=2,
            sample_text="working memory",
        )
    ]
    monkeypatch.setattr(
        psych101_hf_loader,
        "fetch_psych101_dataset_metadata",
        lambda repo_id=DEFAULT_DATASET_ID, **_: metadata,
    )
    monkeypatch.setattr(
        psych101_hf_loader,
        "summarize_psych101_from_metadata",
        lambda resolved_metadata, **_: summaries,
    )

    snapshot = psych101_hf_snapshot_to_graph_inputs(
        dataset_id="psych101-demo",
        sample_text_column="text",
    )
    row = snapshot["experiment_rows"][0]

    assert snapshot["dataset_metadata"]["dataset_id"] == "psych101-demo"
    assert snapshot["dataset_metadata"]["n_participants"] == 2
    assert row["experiment_id"] == "peterson2021using/2-back/exp1.csv"
    assert row["experiment_name"] == "exp1"
    assert row["experiment_path"] == "peterson2021using/2-back/exp1.csv"
    assert row["description"] == "working memory"
    assert row["n_trials"] == 2


def test_psych101_hf_snapshot_to_graph_inputs_preserves_cohort_metadata(monkeypatch) -> None:
    metadata = Psych101DatasetMetadata(
        dataset_id=DEFAULT_DATASET_ID,
        parquet_files=(Psych101ParquetFile(split="train", url="https://example.org/train.parquet"),),
    )
    summaries = [
        Psych101ExperimentSummary(
            experiment="exp-a",
            row_count=2,
            participant_count=2,
            group_audit={
                "requested_group_keys": ["site"],
                "resolved_group_keys": ["site"],
                "missing_group_keys": [],
                "group_counts": {
                    "site": {
                        "participant_counts": {"site_a": 2},
                        "row_counts": {"site_a": 2},
                        "missing_rows": 0,
                        "missing_participants": 0,
                        "underpowered_groups": {},
                    }
                },
            },
        )
    ]
    monkeypatch.setattr(
        psych101_hf_loader,
        "fetch_psych101_dataset_metadata",
        lambda repo_id=DEFAULT_DATASET_ID, **_: metadata,
    )
    monkeypatch.setattr(
        psych101_hf_loader,
        "summarize_psych101_from_metadata",
        lambda resolved_metadata, **_: summaries,
    )

    snapshot = psych101_hf_snapshot_to_graph_inputs(
        audit_group_columns=["site"],
        sample_weight_column="sample_weight",
    )

    assert snapshot["dataset_metadata"]["audit_group_keys"] == ["site"]
    assert snapshot["dataset_metadata"]["cohort_metadata"]["schema_version"] == "br-cohort-metadata-v1"
    assert snapshot["experiment_rows"][0]["cohort_metadata"]["group_audit"]["group_counts"]["site"][
        "participant_counts"
    ] == {"site_a": 2}


class StubNeo4jDB:
    def __init__(self) -> None:
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


def test_ingest_psych101_hf_snapshot_writes_direct_graph_records() -> None:
    dataset_url = f"https://huggingface.co/api/datasets/{DEFAULT_DATASET_ID}"
    splits_url = "https://datasets-server.huggingface.co/splits"
    parquet_url = "https://datasets-server.huggingface.co/parquet"

    transport = _mock_transport(
        {
            dataset_url: {
                "id": DEFAULT_DATASET_ID,
                "title": "Psych-101",
                "license": "apache-2.0",
                "tags": ["psychology", "benchmark"],
                "cardData": {
                    "pretty_name": "Psych-101",
                    "license": "apache-2.0",
                    "tags": ["decision-making"],
                },
            },
            splits_url: {
                "splits": [
                    {"split": "train", "num_examples": 2},
                    {"split": "test", "num_examples": 1},
                ]
            },
            parquet_url: {
                "parquet_files": [
                    {
                        "split": "train",
                        "filename": "train-00000-of-00001.parquet",
                        "url": "https://huggingface.co/datasets/marcelbinz/Psych-101/resolve/main/train-00000-of-00001.parquet",
                    },
                    {
                        "split": "test",
                        "filename": "test-00000-of-00001.parquet",
                        "url": "https://huggingface.co/datasets/marcelbinz/Psych-101/resolve/main/test-00000-of-00001.parquet",
                    },
                ]
            },
        }
    )

    parquet_frames = {
        "https://huggingface.co/datasets/marcelbinz/Psych-101/resolve/main/train-00000-of-00001.parquet": pd.DataFrame(
            {
                "experiment": ["train.bandit", "train.bandit"],
                "participant": ["p1", "p2"],
                "text": ["reward learning", "reward learning"],
            }
        ),
        "https://huggingface.co/datasets/marcelbinz/Psych-101/resolve/main/test-00000-of-00001.parquet": pd.DataFrame(
            {
                "experiment": ["test.memory"],
                "participant": ["p3"],
                "text": ["working memory"],
            }
        ),
    }
    read_calls: list[tuple[str, tuple[str, ...] | None]] = []

    def fake_read_parquet(source: str, *, columns: list[str] | None = None):
        read_calls.append((source, tuple(columns) if columns is not None else None))
        frame = parquet_frames[source]
        return frame.loc[:, columns] if columns is not None else frame

    db = StubNeo4jDB()

    with httpx.Client(transport=transport, timeout=10.0) as client:
        result = ingest_psych101_hf_snapshot(
            db,
            client=client,
            read_parquet=fake_read_parquet,
            sample_text_column="text",
        )

    assert read_calls == [
        (
            "https://huggingface.co/datasets/marcelbinz/Psych-101/resolve/main/train-00000-of-00001.parquet",
            ("experiment", "participant", "text"),
        ),
        (
            "https://huggingface.co/datasets/marcelbinz/Psych-101/resolve/main/test-00000-of-00001.parquet",
            ("experiment", "participant", "text"),
        ),
    ]
    assert result["dataset_metadata"]["dataset_id"] == "psych101"
    assert [row["experiment_id"] for row in result["experiment_rows"]] == [
        "test.memory",
        "train.bandit",
    ]
    assert result["ingest_result"]["stats"]["dataset_nodes"] == 1
    assert result["ingest_result"]["stats"]["experiment_nodes"] == 2
    assert result["ingest_result"]["stats"]["relationships"] >= 3
    assert any(labels == ["Dataset", "Psych101Dataset"] for labels, _, _ in db.nodes)
    assert any(labels == ["Experiment", "Psych101Experiment"] for labels, _, _ in db.nodes)
    assert any(rel_type == "HAS_EXPERIMENT" for _, _, rel_type, _ in db.relationships)
