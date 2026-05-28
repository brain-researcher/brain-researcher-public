from brain_researcher.services.neurokg.query_service import KGNodeSummary
from brain_researcher.services.neurokg.search.hybrid_v1 import (
    HybridConfig,
    hybrid_search_v1,
    _HYBRID_CACHE,
)


class _VectorHit:
    def __init__(self, node_id, node_type, score, metadata):
        self.node_id = node_id
        self.node_type = node_type
        self.score = score
        self.metadata = metadata


def _fake_search_nodes(query, node_types=None, limit=20, db=None):
    return [
        KGNodeSummary(
            kg_id="n1",
            label="working memory",
            node_type="Task",
            score=2.0,
            properties={"name": "working memory"},
        )
    ]


def _fake_vector_search(**kwargs):
    return [_VectorHit("n1", "Task", 0.9, {"name": "working memory"})]


def setup_function(_):
    _HYBRID_CACHE.clear()


def test_hybrid_v1_fulltext_only():
    payload = hybrid_search_v1(
        query="working memory task",
        node_types=["Task"],
        filters=None,
        limit=5,
        include_explain=False,
        db=None,
        config=HybridConfig(gfs_enabled=False),
        search_nodes_fn=_fake_search_nodes,
        vector_search_fn=None,
    )

    assert payload["mode"] == "hybrid_v1"
    assert payload["results"]
    item = payload["results"][0]
    assert "explain_min" in item
    assert "RECALL_FULLTEXT_HIT" in item["explain_min"]["reason_codes"]
    assert item["evidence"] == []


def test_hybrid_v1_include_explain():
    payload = hybrid_search_v1(
        query="working memory task",
        node_types=["Task"],
        filters=None,
        limit=5,
        include_explain=True,
        db=None,
        config=HybridConfig(gfs_enabled=False),
        search_nodes_fn=_fake_search_nodes,
        vector_search_fn=_fake_vector_search,
    )

    item = payload["results"][0]
    assert "explain_full" in item
    assert "score_breakdown" in item["explain_full"]
    assert "retrieval_trace_full" in item["explain_full"]


def test_hybrid_v1_cache_hit():
    first = hybrid_search_v1(
        query="working memory task",
        node_types=["Task"],
        filters=None,
        limit=5,
        include_explain=False,
        db=None,
        config=HybridConfig(gfs_enabled=False),
        search_nodes_fn=_fake_search_nodes,
        vector_search_fn=_fake_vector_search,
    )
    assert first["cache"]["hit"] is False

    second = hybrid_search_v1(
        query="working memory task",
        node_types=["Task"],
        filters=None,
        limit=5,
        include_explain=False,
        db=None,
        config=HybridConfig(gfs_enabled=False),
        search_nodes_fn=_fake_search_nodes,
        vector_search_fn=_fake_vector_search,
    )
    assert second["cache"]["hit"] is True


def test_hybrid_v1_gfs_evidence_attached(monkeypatch):
    def _fake_search_gfs_auto(
        query,
        top_k=5,
        store=None,
        model=None,
        gfs_enabled=True,
        include_explain=False,
        result_count=None,
        top_score=None,
        weak_evidence=False,
        max_calls=2,
    ):
        return {
            "status": "ok",
            "query": query,
            "query_used": query,
            "store": "fileSearchStores/test-store",
            "stores_hit": ["fileSearchStores/test-store"],
            "call_count": 1,
            "reason": "intent_papers",
            "model": "gemini-2.5-flash",
            "triggered": True,
            "hits": [
                {
                    "doc_id": "doc1",
                    "title": "Working memory guideline",
                    "snippet": "Working memory tasks are recommended." * 20,
                    "text": "Working memory tasks are recommended." * 20,
                    "score": 0.9,
                }
            ],
        }

    monkeypatch.setattr(
        "brain_researcher.services.neurokg.search.hybrid_v1.search_gfs_auto",
        _fake_search_gfs_auto,
    )

    payload = hybrid_search_v1(
        query="working memory task recommended",
        node_types=["Task"],
        filters=None,
        limit=5,
        include_explain=True,
        db=None,
        config=HybridConfig(gfs_enabled=True, gfs_top_k=5),
        search_nodes_fn=_fake_search_nodes,
        vector_search_fn=_fake_vector_search,
    )

    assert payload["gfs"]["status"] == "ok"
    assert payload["gfs"]["call_count"] == 1
    assert payload["gfs"]["reason"] == "intent_papers"
    item = payload["results"][0]
    assert item["evidence_status"] == "ok"
    assert item["evidence"]
    assert item["evidence"][0]["doc_id"] == "doc1"
    assert len(item["evidence"][0]["snippet"]) <= 303  # truncated with ellipsis
    assert item["evidence"][0]["doc_role"]  # inferred
