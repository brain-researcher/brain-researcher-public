from brain_researcher.services.neurokg.query_service import KGNodeSummary
from brain_researcher.services.neurokg.search.orchestrator import SearchOrchestrator


def _node(kg_id: str, label: str, score: float, aliases: list[str]) -> KGNodeSummary:
    return KGNodeSummary(
        kg_id=kg_id,
        label=label,
        node_type="Task",
        score=score,
        properties={"aliases": aliases, "label": label},
    )


def test_search_orchestrator_v2_penalizes_conflict_and_uncertainty(monkeypatch):
    node_alpha = _node("task:alpha", "Alpha", 2.0, ["alpha method"])
    node_beta = _node("task:beta", "Beta", 1.8, ["beta method"])

    monkeypatch.setattr(
        "brain_researcher.services.neurokg.search.orchestrator.query_service.search_nodes",
        lambda *args, **kwargs: [node_alpha, node_beta],
    )

    orchestrator = SearchOrchestrator(alpha=0.8, evidence_limit=3)

    support_hits = [
        {
            "title": "A",
            "text": "alpha method is recommended default",
            "snippet": "alpha method is recommended default",
            "score": 0.92,
        },
        {
            "title": "B",
            "text": "beta method is recommended",
            "snippet": "beta method is recommended",
            "score": 0.88,
        },
    ]
    mixed_hits = [
        {
            "title": "A1",
            "text": "alpha method is recommended default",
            "snippet": "alpha method is recommended default",
            "score": 0.92,
        },
        {
            "title": "A2",
            "text": "alpha method is deprecated do not use",
            "snippet": "alpha method is deprecated do not use",
            "score": 0.91,
        },
        {
            "title": "A3",
            "text": "alpha method may be inconclusive",
            "snippet": "alpha method may be inconclusive",
            "score": 0.90,
        },
        {
            "title": "B",
            "text": "beta method is recommended",
            "snippet": "beta method is recommended",
            "score": 0.88,
        },
    ]

    monkeypatch.setattr(
        "brain_researcher.services.neurokg.search.orchestrator.search_gfs_auto",
        lambda *args, **kwargs: {
            "status": "ok",
            "hits": support_hits,
            "store": "dummy",
            "model": "dummy-model",
        },
    )
    support_results, _ = orchestrator.search(
        "method recommendation",
        include_score_breakdown=True,
        confidence_scoring_version="v2",
    )
    support_by_id = {item.node_id: item for item in support_results}

    monkeypatch.setattr(
        "brain_researcher.services.neurokg.search.orchestrator.search_gfs_auto",
        lambda *args, **kwargs: {
            "status": "ok",
            "hits": mixed_hits,
            "store": "dummy",
            "model": "dummy-model",
        },
    )
    mixed_results, _ = orchestrator.search(
        "method recommendation",
        include_score_breakdown=True,
        confidence_scoring_version="v2",
    )
    mixed_by_id = {item.node_id: item for item in mixed_results}

    assert mixed_by_id["task:alpha"].score < support_by_id["task:alpha"].score
    breakdown = mixed_by_id["task:alpha"].score_breakdown or {}
    assert breakdown.get("scoring_version") == "v2"
    assert breakdown.get("contradiction_density", 0.0) > 0.0
    assert breakdown.get("uncertainty_density", 0.0) > 0.0
    assert breakdown.get("confidence_multiplier", 1.0) <= 0.2
    support_breakdown = support_by_id["task:alpha"].score_breakdown or {}
    assert support_breakdown.get("confidence_multiplier", 0.0) >= 0.5


def test_search_orchestrator_v2_ranks_uncertain_only_below_clean_support(monkeypatch):
    node_alpha = _node("task:alpha", "Alpha", 2.0, ["alpha method"])
    node_gamma = _node("task:gamma", "Gamma", 1.95, ["gamma method"])

    monkeypatch.setattr(
        "brain_researcher.services.neurokg.search.orchestrator.query_service.search_nodes",
        lambda *args, **kwargs: [node_alpha, node_gamma],
    )
    monkeypatch.setattr(
        "brain_researcher.services.neurokg.search.orchestrator.search_gfs_auto",
        lambda *args, **kwargs: {
            "status": "ok",
            "hits": [
                {
                    "title": "Alpha positive",
                    "text": "alpha method is recommended default",
                    "snippet": "alpha method is recommended default",
                    "score": 0.95,
                },
                {
                    "title": "Alpha positive 2",
                    "text": "alpha method is recommended",
                    "snippet": "alpha method is recommended",
                    "score": 0.93,
                },
                {
                    "title": "Gamma uncertain",
                    "text": "gamma method may be inconclusive",
                    "snippet": "gamma method may be inconclusive",
                    "score": 0.94,
                },
                {
                    "title": "Gamma uncertain 2",
                    "text": "gamma method might be uncertain",
                    "snippet": "gamma method might be uncertain",
                    "score": 0.92,
                },
            ],
            "store": "dummy",
            "model": "dummy-model",
        },
    )

    orchestrator = SearchOrchestrator(alpha=0.8, evidence_limit=2)
    results, _ = orchestrator.search(
        "method recommendation",
        include_score_breakdown=True,
        confidence_scoring_version="v2",
    )
    by_id = {item.node_id: item for item in results}
    assert by_id["task:alpha"].score > by_id["task:gamma"].score
    gamma_breakdown = by_id["task:gamma"].score_breakdown or {}
    assert gamma_breakdown.get("uncertainty_density", 0.0) > 0.0
    assert gamma_breakdown.get("confidence_multiplier", 1.0) <= 0.2


def test_search_orchestrator_supports_v1_fallback(monkeypatch):
    node_alpha = _node("task:alpha", "Alpha", 2.0, ["alpha method"])
    monkeypatch.setattr(
        "brain_researcher.services.neurokg.search.orchestrator.query_service.search_nodes",
        lambda *args, **kwargs: [node_alpha],
    )
    monkeypatch.setattr(
        "brain_researcher.services.neurokg.search.orchestrator.search_gfs_auto",
        lambda *args, **kwargs: {
            "status": "ok",
            "hits": [
                {
                    "title": "A",
                    "text": "alpha method is recommended",
                    "snippet": "alpha method is recommended",
                    "score": 0.9,
                }
            ],
            "store": "dummy",
            "model": "dummy-model",
        },
    )

    orchestrator = SearchOrchestrator(alpha=0.8, evidence_limit=2)
    results, meta = orchestrator.search(
        "alpha method",
        include_score_breakdown=True,
        confidence_scoring_version="v1",
    )
    assert meta["confidence_scoring_version"] == "v1"
    breakdown = results[0].score_breakdown or {}
    assert breakdown.get("scoring_version") == "v1"
    assert breakdown.get("confidence_multiplier") == 1.0
    assert "contradiction_density" not in breakdown
