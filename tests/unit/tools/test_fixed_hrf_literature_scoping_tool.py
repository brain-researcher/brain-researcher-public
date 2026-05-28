from __future__ import annotations

from brain_researcher.services.tools.params.fixed_hrf_literature_scoping import (
    FixedHrfLiteratureScopingParameters,
    bucket_fixed_hrf_hit,
    build_fixed_hrf_scoping_query,
    fixed_hrf_literature_scoping_from_payload,
    gather_fixed_hrf_static_refs,
    run_fixed_hrf_literature_scoping,
    summarize_fixed_hrf_hits,
)


def test_build_fixed_hrf_scoping_query_is_explicit_about_scope():
    params = FixedHrfLiteratureScopingParameters(
        query="working memory",
        task="n-back",
    )
    query = build_fixed_hrf_scoping_query(params)
    assert "working memory" in query
    assert "scoping review" in query
    assert "fixed HRF" in query
    assert "canonical HRF" in query
    assert "FIR" in query


def test_bucket_fixed_hrf_hit_prefers_fixed_hrf_terms():
    assert (
        bucket_fixed_hrf_hit(
            {"title": "Canonical HRF versus FIR basis functions in fMRI"}
        )
        == "fir_flobs"
    )
    assert (
        bucket_fixed_hrf_hit(
            {"title": "Temporal derivative basis improves latency fit"}
        )
        == "derivative_basis"
    )
    assert (
        bucket_fixed_hrf_hit({"title": "SPM canonical HRF for event-related fMRI"})
        == "canonical_hrf"
    )


def test_summarize_fixed_hrf_hits_counts_buckets():
    hits = [
        {"title": "Canonical HRF and GLM design"},
        {"title": "FIR and FLOBS in fMRI"},
        {"title": "Temporal derivative basis for HRF"},
        {"title": "Model comparison for hemodynamic response"},
    ]
    summary = summarize_fixed_hrf_hits(hits, top_k=2)
    assert summary["total_hits"] == 4
    assert summary["bucket_counts"]["canonical_hrf"] == 1
    assert summary["bucket_counts"]["fir_flobs"] == 1
    assert summary["bucket_counts"]["derivative_basis"] == 1
    assert summary["bucket_counts"]["model_comparison"] == 1
    assert summary["top_titles"] == [
        "Canonical HRF and GLM design",
        "FIR and FLOBS in fMRI",
    ]


def test_run_fixed_hrf_literature_scoping_uses_search_and_static_refs(monkeypatch):
    seen = {}

    def fake_search(query, **kwargs):
        seen["query"] = query
        seen["kwargs"] = kwargs
        return {
            "status": "ok",
            "query": query,
            "hits": [
                {"title": "Canonical HRF in SPM"},
                {"title": "FIR versus FLOBS basis functions"},
            ],
            "n_docs_hit": 2,
            "call_count": 1,
            "stores_hit": ["papers-store"],
        }

    monkeypatch.setattr(
        "brain_researcher.services.tools.params.fixed_hrf_literature_scoping.search_gfs_auto",
        fake_search,
    )
    params = FixedHrfLiteratureScopingParameters(query="stroke", include_static=True)
    payload = run_fixed_hrf_literature_scoping(params)

    assert seen["query"].startswith("stroke")
    assert seen["kwargs"]["weak_evidence"] is True
    assert payload["review_type"] == "scoping_review"
    assert payload["hit_summary"]["bucket_counts"]["canonical_hrf"] == 1
    assert payload["hit_summary"]["bucket_counts"]["fir_flobs"] == 1
    assert len(payload["static_refs"]) == 3


def test_fixed_hrf_payload_round_trips():
    params = fixed_hrf_literature_scoping_from_payload(
        {"query": "memory", "top_k": 4, "gfs_enabled": False}
    )
    assert params.query == "memory"
    assert params.top_k == 4
    assert params.gfs_enabled is False
    assert len(gather_fixed_hrf_static_refs()) == 3
