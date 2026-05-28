import networkx as nx

from brain_researcher.services.neurokg import query_service


def _make_graph_db_stub(graph: nx.MultiDiGraph):
    class _GraphDBStub:
        def __init__(self, graph: nx.MultiDiGraph):
            self.graph = graph

    return _GraphDBStub(graph)


def _build_compatibility_graph(
    rel_type: str,
    *,
    design_id: str = "design:repeated_measures",
    design_name: str = "Repeated measures",
    design_labels: tuple[str, ...] = ("ExperimentalDesign",),
    method_id: str = "method:paired_t_test",
    method_name: str = "Paired t-test",
    method_labels: tuple[str, ...] = ("StatisticalMethod",),
):
    graph = nx.MultiDiGraph()
    graph.add_node(
        design_id,
        id=design_id,
        name=design_name,
        labels=list(design_labels),
        aliases=["within-subject", "repeated measures"],
    )
    graph.add_node(
        method_id,
        id=method_id,
        name=method_name,
        labels=list(method_labels),
        aliases=["dependent t-test", "paired t test"],
    )
    graph.add_edge(design_id, method_id, type=rel_type)
    return graph


def test_get_method_compatibility_flags_repeated_measures_vs_independent_t_test():
    verdict = query_service.get_method_compatibility(
        design="repeated measures",
        method="independent samples t-test",
    )

    assert verdict is not None
    assert verdict["compatible"] is False
    assert verdict["verdict"] == "incompatible"
    assert verdict["severity"] == "error"
    assert verdict["rule_id"] == "repeated_measures_blocks_independent_t_test"
    assert verdict["design"]["canonical"] == "repeated_measures"
    assert verdict["method"]["canonical"] == "independent_t_test"


def test_get_method_compatibility_accepts_within_subject_and_paired_t_test():
    verdict = query_service.get_method_compatibility(
        design="within-subject",
        method="paired t-test",
    )

    assert verdict is not None
    assert verdict["compatible"] is True
    assert verdict["verdict"] == "compatible"
    assert verdict["severity"] == "ok"
    assert verdict["rule_id"] == "repeated_measures_requires_paired_t_test"
    assert verdict["design"]["canonical"] == "repeated_measures"
    assert verdict["method"]["canonical"] == "paired_t_test"


def test_get_method_compatibility_prefers_graph_compatibility_edge():
    graph = _build_compatibility_graph("COMPATIBLE_WITH")
    verdict = query_service.get_method_compatibility(
        design="within-subject",
        method="paired t test",
        db=_make_graph_db_stub(graph),
    )

    assert verdict is not None
    assert verdict["source"] == "graph"
    assert verdict["compatible"] is True
    assert verdict["verdict"] == "compatible"
    assert verdict["severity"] == "ok"
    assert verdict["rule_id"] == "repeated_measures_requires_paired_t_test"
    assert verdict["evidence"]["relationship_type"] == "COMPATIBLE_WITH"


def test_get_method_compatibility_prefers_graph_incompatibility_edge():
    graph = _build_compatibility_graph(
        "INCOMPATIBLE_WITH",
        method_id="method:independent_t_test",
        method_name="Independent samples t-test",
        method_labels=("StatisticalMethod",),
    )
    verdict = query_service.get_method_compatibility(
        design="repeated measures",
        method="independent samples t-test",
        db=_make_graph_db_stub(graph),
    )

    assert verdict is not None
    assert verdict["source"] == "graph"
    assert verdict["compatible"] is False
    assert verdict["verdict"] == "incompatible"
    assert verdict["severity"] == "error"
    assert verdict["rule_id"] == "repeated_measures_blocks_independent_t_test"
    assert verdict["evidence"]["relationship_type"] == "INCOMPATIBLE_WITH"


def test_get_method_compatibility_falls_back_to_seed_when_graph_has_no_match():
    graph = nx.MultiDiGraph()
    graph.add_node(
        "design:mixed_effects",
        id="design:mixed_effects",
        name="Mixed effects",
        labels=["ExperimentalDesign"],
    )
    graph.add_node(
        "method:anova",
        id="method:anova",
        name="ANOVA",
        labels=["StatisticalMethod"],
    )
    graph.add_edge("design:mixed_effects", "method:anova", type="COMPATIBLE_WITH")

    verdict = query_service.get_method_compatibility(
        design="repeated measures",
        method="independent samples t-test",
        db=_make_graph_db_stub(graph),
    )

    assert verdict is not None
    assert verdict["source"] == "seed"
    assert verdict["compatible"] is False
    assert verdict["rule_id"] == "repeated_measures_blocks_independent_t_test"


def test_get_method_compatibility_returns_none_for_unseeded_pair():
    verdict = query_service.get_method_compatibility(
        design="mixed effects",
        method="permutation test",
    )

    assert verdict is None
