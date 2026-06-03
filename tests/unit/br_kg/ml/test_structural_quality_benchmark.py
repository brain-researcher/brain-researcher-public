import json

from brain_researcher.services.br_kg.ml.structural_quality_benchmark import (
    StructuralQualityBenchmark,
    StructuralQualityBenchmarkConfig,
    run_structural_quality_benchmark,
)


def _make_graph_data():
    nodes = [
        {"id": "t1", "node_type": "Task", "features": [1.0, 0.0, 0.0], "properties": {"site_or_cohort": "site_a"}},
        {"id": "t2", "node_type": "Task", "features": [0.9, 0.1, 0.0], "properties": {"site_or_cohort": "site_a"}},
        {"id": "t3", "node_type": "Task", "features": [0.0, 1.0, 0.0], "properties": {"site_or_cohort": "site_b"}},
        {"id": "t4", "node_type": "Task", "features": [0.0, 0.9, 0.1], "properties": {"site_or_cohort": "site_b"}},
        {"id": "c1", "node_type": "Concept", "features": [1.0, 0.0, 0.0], "properties": {}},
        {"id": "c2", "node_type": "Concept", "features": [0.9, 0.1, 0.0], "properties": {}},
        {"id": "c3", "node_type": "Concept", "features": [0.0, 1.0, 0.0], "properties": {}},
        {"id": "c4", "node_type": "Concept", "features": [0.0, 0.9, 0.1], "properties": {}},
        {"id": "tool1", "node_type": "Tool", "features": [1.0, 0.0, 0.0], "properties": {}},
        {"id": "tool2", "node_type": "Tool", "features": [0.0, 1.0, 0.0], "properties": {}},
        {"id": "fam1", "node_type": "ToolFamily", "features": [1.0, 0.0, 0.0], "properties": {}},
        {"id": "fam2", "node_type": "ToolFamily", "features": [0.0, 1.0, 0.0], "properties": {}},
    ]

    edges = [
        {"source": "t1", "target": "c1", "edge_type": "MEASURES"},
        {"source": "t2", "target": "c2", "edge_type": "MEASURES"},
        {"source": "t3", "target": "c3", "edge_type": "MEASURES"},
        {"source": "t4", "target": "c4", "edge_type": "MEASURES"},
        {"source": "t1", "target": "tool1", "edge_type": "USES_TOOL"},
        {"source": "t2", "target": "tool1", "edge_type": "USES_TOOL"},
        {"source": "t3", "target": "tool2", "edge_type": "USES_TOOL"},
        {"source": "t4", "target": "tool2", "edge_type": "USES_TOOL"},
        {"source": "tool1", "target": "fam1", "edge_type": "BELONGS_TO_FAMILY"},
        {"source": "tool2", "target": "fam2", "edge_type": "BELONGS_TO_FAMILY"},
    ]
    return {"nodes": nodes, "edges": edges}


def _make_config():
    return StructuralQualityBenchmarkConfig(
        train_ratio=0.5,
        val_ratio=0.0,
        test_ratio=0.5,
        negatives_per_positive=1,
        hard_negative_ratio=0.0,
        include_node2vec_probe=False,
        include_graphsage_probe=False,
        key_edge_types=["MEASURES", "USES_TOOL"],
        min_positive_edges_per_type=3,
        random_seed=7,
    )


def test_structural_quality_benchmark_emits_graph_diagnostics():
    result = run_structural_quality_benchmark(_make_graph_data(), config=_make_config())

    report = result["graph_diagnostic_report"]
    comparison = result["probe_model_comparison"]

    assert report["total_nodes"] == 12
    assert report["total_edges"] == 10
    assert report["primary_probe_model"] == "text_cosine"
    assert 0.0 <= report["structure_consistency_score"] <= 1.0

    assert report["per_edge_type_diagnostics"]["MEASURES"]["diagnostic_bucket"] in {
        "strong",
        "marginal",
    }
    assert (
        report["per_edge_type_diagnostics"]["BELONGS_TO_FAMILY"]["diagnostic_bucket"]
        == "underpowered"
    )

    assert comparison["models"]["type_prior"]["status"] == "completed"
    assert comparison["models"]["degree_only"]["status"] == "completed"
    assert comparison["models"]["text_cosine"]["status"] == "completed"
    assert comparison["models"]["text_cosine"]["overall"]["auroc"] is not None


def test_structural_quality_benchmark_writes_expected_artifacts(tmp_path):
    benchmark = StructuralQualityBenchmark(config=_make_config())
    result = benchmark.run(
        _make_graph_data(),
        output_dir=str(tmp_path),
        graph_metadata={"snapshot_id": "toy_v1", "generated_at": "2026-03-23T00:00:00Z"},
    )

    assert result["graph_metadata"]["snapshot_id"] == "toy_v1"

    expected_files = {
        "benchmark_manifest.json",
        "fairness_audit_report.json",
        "split_manifest.json",
        "graph_diagnostic_report.json",
        "probe_model_comparison.json",
    }
    assert expected_files == {path.name for path in tmp_path.iterdir()}

    manifest = json.loads((tmp_path / "benchmark_manifest.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((tmp_path / "graph_diagnostic_report.json").read_text(encoding="utf-8"))
    fairness = json.loads((tmp_path / "fairness_audit_report.json").read_text(encoding="utf-8"))
    probes = json.loads((tmp_path / "probe_model_comparison.json").read_text(encoding="utf-8"))

    assert manifest["benchmark_id"] == "br_kg_structural_quality_v1"
    assert diagnostics["primary_probe_model"] == "text_cosine"
    assert fairness["status"] == "not_requested"
    assert probes["models"]["text_cosine"]["status"] == "completed"


def test_structural_quality_benchmark_emits_fairness_audit_report():
    config = _make_config()
    config.audit_group_keys = ["site_or_cohort"]
    config.min_group_samples = 2

    result = run_structural_quality_benchmark(_make_graph_data(), config=config)
    fairness = result["fairness_audit_report"]

    assert fairness["status"] == "completed"
    assert fairness["resolved_group_keys"] == ["site_or_cohort"]
    site_report = fairness["per_group_key"]["site_or_cohort"]
    assert site_report["node_coverage"]["resolved_source_nodes"] == 2
    assert "site_a" in site_report["per_group_value"]
    assert "site_b" in site_report["per_group_value"]
