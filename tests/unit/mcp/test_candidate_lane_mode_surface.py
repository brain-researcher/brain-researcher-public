from __future__ import annotations


def test_kg_verify_hypothesis_forwards_candidate_lane_mode(monkeypatch):
    from brain_researcher.services.br_kg import query_service as query_service
    from brain_researcher.services.mcp import server as srv

    captured: dict[str, object] = {}

    def fake_verify_hypothesis(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "hypothesis": kwargs["hypothesis"],
            "verdict": "insufficient_evidence",
            "confidence": 0.41,
            "summary": {"n_supporting": 0, "n_conflicting": 0, "n_neutral": 1},
            "supporting_evidence": [],
            "conflicting_evidence": [],
            "neutral_evidence": [{"evidence_id": "n1", "score": 0.4}],
            "warnings": [],
            "provenance": [],
        }

    monkeypatch.setattr(query_service, "verify_hypothesis", fake_verify_hypothesis)

    resp = srv.kg_verify_hypothesis(
        hypothesis="DLPFC is involved in n-back",
        entity_hints=["DLPFC", "n-back"],
        strictness="high_recall",
        candidate_lane_mode="strict",
        rerank_candidate_cap=37,
        hypothesis_budget_seconds=12.5,
        include_subgraph=True,
        include_path_details=False,
    )

    assert resp["ok"] is True
    assert captured["kwargs"]["candidate_lane_mode"] == "strict"
    assert captured["kwargs"]["rerank_candidate_cap"] == 37
    assert captured["kwargs"]["hypothesis_budget_seconds"] == 12.5
    assert captured["kwargs"]["include_subgraph"] is True
    assert captured["kwargs"]["include_path_details"] is False


def test_verify_hypothesis_alias_forwards_candidate_lane_mode(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    captured: dict[str, object] = {}

    def fake_kg_verify_hypothesis(**kwargs):
        captured["kwargs"] = kwargs
        return {"ok": True, "result": {"verdict": "insufficient_evidence"}}

    monkeypatch.setattr(srv, "kg_verify_hypothesis", fake_kg_verify_hypothesis)

    resp = srv.verify_hypothesis_with_kg(
        hypothesis="DLPFC is involved in n-back",
        entity_hints=["DLPFC", "n-back"],
        strictness="high_recall",
        candidate_lane_mode="broad",
        rerank_candidate_cap=42,
        hypothesis_budget_seconds=9.5,
    )

    assert resp["ok"] is True
    assert captured["kwargs"]["candidate_lane_mode"] == "broad"
    assert captured["kwargs"]["rerank_candidate_cap"] == 42
    assert captured["kwargs"]["hypothesis_budget_seconds"] == 9.5


def test_kg_sample_and_verify_hypotheses_forwards_candidate_lane_mode(monkeypatch):
    from brain_researcher.services.br_kg import query_service as query_service
    from brain_researcher.services.mcp import server as srv

    captured: dict[str, object] = {}

    def fake_sample_and_verify_hypotheses(
        seed_kg_ids,
        *,
        query=None,
        relation_types=None,
        sample_limit=5,
        verify_top_k=None,
        taste=None,
        strictness="high_recall",
        allowed_node_types=None,
        max_evidence=60,
        max_paths=60,
        min_evidence_score=None,
        include_subgraph=False,
        include_path_details=False,
        confidence_scoring_version="v2",
        candidate_lane_mode="broad",
        use_external_literature=False,
        external_literature_top_k=5,
        external_literature_recency_days=365,
        external_literature_exclude_domains=None,
        db=None,
    ):
        del db
        captured["kwargs"] = {
            "seed_kg_ids": list(seed_kg_ids),
            "query": query,
            "relation_types": relation_types,
            "sample_limit": sample_limit,
            "verify_top_k": verify_top_k,
            "taste": taste,
            "strictness": strictness,
            "allowed_node_types": allowed_node_types,
            "max_evidence": max_evidence,
            "max_paths": max_paths,
            "min_evidence_score": min_evidence_score,
            "include_subgraph": include_subgraph,
            "include_path_details": include_path_details,
            "confidence_scoring_version": confidence_scoring_version,
            "candidate_lane_mode": candidate_lane_mode,
            "use_external_literature": use_external_literature,
            "external_literature_top_k": external_literature_top_k,
            "external_literature_recency_days": external_literature_recency_days,
            "external_literature_exclude_domains": external_literature_exclude_domains,
        }
        return {
            "sampled_hypotheses": [{"rank": 1, "statement": "H1"}],
            "tested_hypotheses": [],
            "summary": {"n_tested": 0},
        }

    monkeypatch.setattr(
        query_service,
        "sample_and_verify_hypotheses",
        fake_sample_and_verify_hypotheses,
        raising=False,
    )

    resp = srv.kg_sample_and_verify_hypotheses(
        seed_kg_ids=["node:seed"],
        n_samples=3,
        verify_top_k=2,
        max_hops=3,
        strategy="evidence_first",
        strictness="conservative",
        candidate_lane_mode="strict",
        allowed_node_types=["Task", "Concept"],
        include_subgraph=True,
    )

    assert resp["ok"] is True
    assert captured["kwargs"]["candidate_lane_mode"] == "strict"
    assert captured["kwargs"]["sample_limit"] == 3
    assert captured["kwargs"]["taste"] == {"mode": "evidence_first"}


def test_kg_verify_sampled_hypotheses_forwards_candidate_lane_mode(monkeypatch):
    from brain_researcher.services.br_kg import query_service as query_service
    from brain_researcher.services.mcp import server as srv

    captured: dict[str, object] = {}

    def fake_verify_sampled_hypotheses(
        sampled_hypotheses,
        *,
        query=None,
        seed_kg_ids=None,
        verify_top_k=None,
        strictness="high_recall",
        allowed_node_types=None,
        max_evidence=60,
        max_paths=60,
        min_evidence_score=None,
        include_subgraph=False,
        include_path_details=False,
        confidence_scoring_version="v2",
        candidate_lane_mode="broad",
        use_external_literature=False,
        external_literature_top_k=5,
        external_literature_recency_days=365,
        external_literature_exclude_domains=None,
        db=None,
    ):
        del db
        captured["kwargs"] = {
            "sampled_hypotheses": sampled_hypotheses,
            "query": query,
            "seed_kg_ids": seed_kg_ids,
            "verify_top_k": verify_top_k,
            "strictness": strictness,
            "allowed_node_types": allowed_node_types,
            "max_evidence": max_evidence,
            "max_paths": max_paths,
            "min_evidence_score": min_evidence_score,
            "include_subgraph": include_subgraph,
            "include_path_details": include_path_details,
            "confidence_scoring_version": confidence_scoring_version,
            "candidate_lane_mode": candidate_lane_mode,
            "use_external_literature": use_external_literature,
            "external_literature_top_k": external_literature_top_k,
            "external_literature_recency_days": external_literature_recency_days,
            "external_literature_exclude_domains": external_literature_exclude_domains,
        }
        return {
            "tested_hypotheses": [{"rank": 1, "statement": "H1"}],
            "summary": {"n_tested": 1},
        }

    monkeypatch.setattr(
        query_service,
        "verify_sampled_hypotheses",
        fake_verify_sampled_hypotheses,
        raising=False,
    )

    resp = srv.kg_verify_sampled_hypotheses(
        sampled_hypotheses=[{"rank": 1, "statement": "H1"}],
        seed_kg_ids=["node:seed"],
        verify_top_k=1,
        strictness="conservative",
        candidate_lane_mode="strict",
        allowed_node_types=["Task"],
        include_subgraph=True,
    )

    assert resp["ok"] is True
    assert captured["kwargs"]["candidate_lane_mode"] == "strict"
    assert captured["kwargs"]["verify_top_k"] == 1
