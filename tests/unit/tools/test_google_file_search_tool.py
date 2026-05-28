from __future__ import annotations

from typing import Any

from brain_researcher.core.literature import gfs_store
from brain_researcher.services.tools.google_file_search_tool import GoogleFileSearchTool


def test_query_returns_structured_reference_anchors(monkeypatch):
    def fake_search_gfs(
        query: str,
        *,
        store: str,
        top_k: int,
    ) -> dict[str, Any]:
        assert query == "cross-validation leakage neuroimaging"
        assert store == "fileSearchStores/papers"
        assert top_k == 3
        return {
            "status": "ok",
            "query": query,
            "store": store,
            "stores_attempted": [store],
            "stores_hit": [store],
            "model": "gemini-3-flash-preview",
            "summary": "Feature selection must be nested inside cross-validation.",
            "hits": [
                {
                    "title": "Model selection and feature selection in neuroimaging",
                    "doi": "10.1016/j.neuroimage.2008.09.050",
                    "pmid": "18977811",
                    "pmcid": None,
                    "doc_id": "fileSearchStores/papers/files/doc-1",
                    "snippet": (
                        "Selection outside the cross-validation loop causes bias."
                    ),
                    "score": 0.91,
                },
                {
                    "title": "Document-only hit",
                    "doi": None,
                    "pmid": None,
                    "pmcid": None,
                    "doc_id": "fileSearchStores/papers/files/doc-2",
                    "snippet": (
                        "A document without citation metadata remains traceable."
                    ),
                    "score": 0.72,
                },
            ],
            "raw_hit_count": 2,
            "n_docs_hit": 2,
            "call_count": 1,
            "latency_ms": 12.3,
            "store_errors": [],
        }

    monkeypatch.setattr(gfs_store, "search_gfs", fake_search_gfs)

    result = GoogleFileSearchTool().run(
        operation="query",
        store_name="papers",
        query="cross-validation leakage neuroimaging",
        top_k=3,
    )

    assert result["status"] == "success"
    data = result["data"]
    assert data["store_name"] == "fileSearchStores/papers"
    assert (
        data["results"]
        == "Feature selection must be nested inside cross-validation."
    )
    assert len(data["hits"]) == 2
    assert [anchor["anchor_id"] for anchor in data["anchors"]] == [
        "doc:fileSearchStores/papers/files/doc-1",
        "doi:10.1016/j.neuroimage.2008.09.050",
        "pmid:18977811",
        "doc:fileSearchStores/papers/files/doc-2",
    ]
    assert data["anchors"][0]["anchor_type"] == "retrieved_document"
    assert data["references"] == [
        {
            "reference_type": "doi",
            "reference": "doi:10.1016/j.neuroimage.2008.09.050",
            "title": "Model selection and feature selection in neuroimaging",
            "snippet": "Selection outside the cross-validation loop causes bias.",
            "score": 0.91,
            "doc_id": "fileSearchStores/papers/files/doc-1",
        },
        {
            "reference_type": "document",
            "reference": "doc:fileSearchStores/papers/files/doc-2",
            "title": "Document-only hit",
            "snippet": "A document without citation metadata remains traceable.",
            "score": 0.72,
            "doc_id": "fileSearchStores/papers/files/doc-2",
        },
    ]
    assert data["grounding"]["reference_count"] == 2
    assert data["grounding"]["anchor_count"] == 4
    assert "copying an anchor_id" in data["grounding"]["anchor_policy"]
    assert data["grounding"]["stores_hit"] == ["fileSearchStores/papers"]


def test_query_surfaces_structured_search_errors(monkeypatch):
    def fake_search_gfs(query: str, *, store: str, top_k: int) -> dict[str, Any]:
        del query, store, top_k
        return {
            "status": "unconfigured",
            "reason": "No FILE_SEARCH_STORE configured",
        }

    monkeypatch.setattr(gfs_store, "search_gfs", fake_search_gfs)

    result = GoogleFileSearchTool().run(
        operation="query",
        store_name="papers",
        query="cross-validation leakage neuroimaging",
    )

    assert result["status"] == "error"
    assert result["error"] == "No FILE_SEARCH_STORE configured"
    assert result["data"]["status"] == "unconfigured"
