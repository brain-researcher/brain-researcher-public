import json
from datetime import datetime

from brain_researcher.services.br_kg.ml.structural_quality_benchmark import (
    StructuralQualityBenchmarkConfig,
)
from brain_researcher.services.br_kg.ml.structural_quality_runner import (
    StructuralQualitySliceExportConfig,
    build_benchmark_graph_slice,
    export_fixed_graph_slice,
    get_structural_quality_profile,
    run_structural_quality_benchmark_from_graph_slice,
)


class _FakeNode:
    def __init__(self, element_id, labels, properties):
        self.element_id = element_id
        self.labels = set(labels)
        self._properties = dict(properties)

    def __iter__(self):
        return iter(self._properties.items())


class _FakeDB:
    def __init__(self, records_by_query):
        self.records_by_query = records_by_query

    def _run(self, cypher, params=None):
        for needle, rows in self.records_by_query.items():
            if needle in cypher:
                return list(rows)
        return []


def _toy_export_slice():
    return {
        "metadata": {"slice_kind": "toy"},
        "nodes": [
            {
                "id": "t1",
                "element_id": "n1",
                "labels": ["Task"],
                "properties": {
                    "id": "t1",
                    "name": "working memory task",
                    "updated_at": datetime(2026, 1, 1, 0, 0, 0),
                },
            },
            {
                "id": "t2",
                "element_id": "n2",
                "labels": ["Task"],
                "properties": {"id": "t2", "name": "response inhibition task"},
            },
            {
                "id": "t3",
                "element_id": "n3",
                "labels": ["Task"],
                "properties": {"id": "t3", "name": "episodic retrieval task"},
            },
            {
                "id": "t4",
                "element_id": "n4",
                "labels": ["Task"],
                "properties": {"id": "t4", "name": "visual recognition task"},
            },
            {
                "id": "c1",
                "element_id": "n5",
                "labels": ["Concept"],
                "properties": {"id": "c1", "name": "working memory"},
            },
            {
                "id": "c2",
                "element_id": "n6",
                "labels": ["Concept"],
                "properties": {"id": "c2", "name": "response inhibition"},
            },
            {
                "id": "c3",
                "element_id": "n7",
                "labels": ["Concept"],
                "properties": {"id": "c3", "name": "episodic retrieval"},
            },
            {
                "id": "c4",
                "element_id": "n8",
                "labels": ["Concept"],
                "properties": {"id": "c4", "name": "visual recognition"},
            },
        ],
        "edges": [
            {"source": "t1", "target": "c1", "edge_type": "MEASURES"},
            {"source": "t2", "target": "c2", "edge_type": "MEASURES"},
            {"source": "t3", "target": "c3", "edge_type": "MEASURES"},
            {"source": "t4", "target": "c4", "edge_type": "MEASURES"},
        ],
    }


def test_build_benchmark_graph_slice_adds_text_and_features():
    graph_slice = build_benchmark_graph_slice(
        _toy_export_slice(),
        feature_dim=16,
        feature_source="hashed",
    )

    assert graph_slice["metadata"]["feature_mode"] == "hashed_text_v1_dim_16"
    assert graph_slice["metadata"]["feature_source_requested"] == "hashed"
    assert graph_slice["nodes"][0]["node_type"] == "Task"
    assert len(graph_slice["nodes"][0]["features"]) == 16
    assert "working memory task" in graph_slice["nodes"][0]["text"]


def test_build_benchmark_graph_slice_prefers_neo4j_text_v1_features():
    graph_slice = _toy_export_slice()
    graph_slice["nodes"][0]["properties"]["embedding_text_v1"] = [0.1, 0.2, 0.3]
    graph_slice["nodes"][1]["properties"]["embedding_text_v1"] = [0.0, 1.0, 0.0]
    graph_slice["nodes"][2]["properties"]["embedding_text_v1"] = [1.0, 0.0, 0.0]
    graph_slice["nodes"][3]["properties"]["embedding_text_v1"] = [0.0, 0.0, 1.0]
    graph_slice["nodes"][4]["properties"]["embedding_text_v1"] = [0.5, 0.5, 0.5]
    graph_slice["nodes"][5]["properties"]["embedding_text_v1"] = [0.4, 0.4, 0.4]
    graph_slice["nodes"][6]["properties"]["embedding_text_v1"] = [0.3, 0.3, 0.3]
    graph_slice["nodes"][7]["properties"]["embedding_text_v1"] = [0.2, 0.2, 0.2]

    built = build_benchmark_graph_slice(
        graph_slice,
        feature_dim=16,
        feature_source="neo4j_text_v1",
    )

    assert built["metadata"]["feature_mode"] == "neo4j_text_v1_dim_3"
    assert built["metadata"]["feature_stats"]["neo4j_text_v1_nodes"] == 8
    assert built["nodes"][0]["features"] == [0.1, 0.2, 0.3]


def test_export_fixed_graph_slice_uses_fixed_relation_queries():
    t1 = _FakeNode("n1", ["Task"], {"id": "t1", "name": "working memory task"})
    c1 = _FakeNode("n2", ["Concept"], {"id": "c1", "name": "working memory"})
    t2 = _FakeNode("n3", ["Task"], {"id": "t2", "name": "memory span task"})
    fake_db = _FakeDB(
        {
            "MATCH (a)-[r:`MEASURES`]->(b)": [
                {"a": t1, "b": c1, "rel_props": {"source": "test"}},
                {"a": t1, "b": t2, "rel_props": {"source": "should_be_filtered"}},
            ]
        }
    )

    exported = export_fixed_graph_slice(
        config=StructuralQualitySliceExportConfig(
            edge_types=["MEASURES"], limit_per_edge_type=10, include_closure=False
        ),
        db=fake_db,
    )

    assert exported["metadata"]["edge_types"] == ["MEASURES"]
    assert exported["metadata"]["relation_signatures"]["MEASURES"] == {
        "source_types": ["Task"],
        "target_types": ["Concept"],
    }
    assert exported["metadata"]["edge_count"] == 1
    assert exported["edges"][0]["edge_type"] == "MEASURES"
    assert exported["edges"][0]["relation_signature"] == {
        "source_types": ["Task"],
        "target_types": ["Concept"],
    }
    assert {node["id"] for node in exported["nodes"]} == {"c1", "t1"}


def test_export_fixed_graph_slice_applies_profile_filters_and_balanced_sampling():
    family_a = _FakeNode("fa", ["TaskFamily"], {"id": "tf_a", "name": "Family A"})
    family_b = _FakeNode("fb", ["TaskFamily"], {"id": "tf_b", "name": "Family B"})
    uncategorized = _FakeNode(
        "fu",
        ["TaskFamily"],
        {"id": "tf_uncategorized", "name": "Uncategorized"},
    )
    t1 = _FakeNode("n1", ["Task"], {"id": "t1", "name": "task 1", "source": "neurostore"})
    t2 = _FakeNode("n2", ["Task"], {"id": "t2", "name": "task 2", "source": "neurostore"})
    t3 = _FakeNode("n3", ["Task"], {"id": "t3", "name": "task 3", "source": "neurostore"})
    t4 = _FakeNode("n4", ["Task"], {"id": "t4", "name": "task 4", "source": "neurostore"})
    t5 = _FakeNode("n5", ["Task"], {"id": "t5", "name": "task 5", "source": "neurostore"})
    fake_db = _FakeDB(
        {
            "MATCH (a)-[r:`BELONGS_TO_FAMILY`]->(b)": [
                {
                    "a": t1,
                    "b": family_a,
                    "rel_props": {"source": "task_family_matcher_backfill", "match_method": "exact_alias"},
                },
                {
                    "a": t2,
                    "b": family_a,
                    "rel_props": {
                        "source": "task_family_matcher_backfill",
                        "match_method": "aggressive_fuzzy_guarded",
                    },
                },
                {
                    "a": t3,
                    "b": family_a,
                    "rel_props": {
                        "source": "task_family_matcher_backfill",
                        "match_method": "forced_best_candidate",
                    },
                },
                {
                    "a": t4,
                    "b": family_b,
                    "rel_props": {"source": "task_family_matcher_backfill", "match_method": "exact_alias"},
                },
                {
                    "a": t5,
                    "b": uncategorized,
                    "rel_props": {"source": "task_family_matcher_backfill", "match_method": "exact_alias"},
                },
            ]
        }
    )

    exported = export_fixed_graph_slice(
        config=StructuralQualitySliceExportConfig(
            edge_types=["BELONGS_TO_FAMILY"],
            limit_per_edge_type=2,
            include_closure=False,
            profile_name="task_structure_neurostore_strict",
        ),
        db=fake_db,
    )

    assert exported["metadata"]["profile_name"] == "task_structure_neurostore_strict"
    assert exported["metadata"]["edge_count"] == 2
    assert {edge["target"] for edge in exported["edges"]} == {"tf_a", "tf_b"}
    assert all(edge["target"] != "tf_uncategorized" for edge in exported["edges"])
    assert all(edge["properties"]["match_method"] != "forced_best_candidate" for edge in exported["edges"])


def test_get_structural_quality_profile_returns_expected_defaults():
    profile = get_structural_quality_profile("claim_spine_main")
    assert profile["edge_types"] == ["REPORTS_CLAIM", "SUPPORTS"]
    assert profile["feature_source"] == "encoder_text_v1"


def test_runner_writes_graph_slice_and_benchmark_artifacts(tmp_path):
    config = StructuralQualityBenchmarkConfig(
        train_ratio=0.5,
        val_ratio=0.0,
        test_ratio=0.5,
        negatives_per_positive=1,
        hard_negative_ratio=0.0,
        include_node2vec_probe=False,
        include_graphsage_probe=False,
        key_edge_types=["MEASURES"],
        min_positive_edges_per_type=3,
        random_seed=7,
    )

    result = run_structural_quality_benchmark_from_graph_slice(
        _toy_export_slice(),
        output_dir=str(tmp_path),
        benchmark_config=config,
        feature_dim=16,
        feature_source="hashed",
    )

    assert result["benchmark_result"]["graph_diagnostic_report"]["primary_probe_model"] == "text_cosine"
    assert {
        path.name for path in tmp_path.iterdir()
    } == {
        "benchmark_manifest.json",
        "fairness_audit_report.json",
        "graph_diagnostic_report.json",
        "graph_slice.json",
        "probe_model_comparison.json",
        "split_manifest.json",
    }

    graph_slice = json.loads((tmp_path / "graph_slice.json").read_text(encoding="utf-8"))
    fairness = json.loads((tmp_path / "fairness_audit_report.json").read_text(encoding="utf-8"))
    assert graph_slice["metadata"]["feature_mode"] == "hashed_text_v1_dim_16"
    assert graph_slice["edges"][0]["relation_signature"] is None
    assert fairness["status"] == "not_requested"
