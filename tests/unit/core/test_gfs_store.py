from __future__ import annotations

import types as pytypes

import pytest

from brain_researcher.core.literature import gfs_store


def test_resolve_stores_from_override_single(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BR_FILE_SEARCH_STORE_NAMES", raising=False)
    assert gfs_store._resolve_stores("storeA") == ["storeA"]


def test_resolve_stores_from_override_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BR_FILE_SEARCH_STORE_NAMES", raising=False)
    assert gfs_store._resolve_stores("storeA, storeB,,storeC") == [
        "storeA",
        "storeB",
        "storeC",
    ]


def test_resolve_stores_from_env_multi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BR_FILE_SEARCH_STORE_NAMES", "s1,s2 , s3")
    monkeypatch.delenv("FILE_SEARCH_STORE", raising=False)
    monkeypatch.delenv("BR_FILE_SEARCH_STORE", raising=False)
    assert gfs_store._resolve_stores() == ["s1", "s2", "s3"]


def test_resolve_stores_from_env_single(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BR_FILE_SEARCH_STORE_NAMES", raising=False)
    monkeypatch.setenv("FILE_SEARCH_STORE", "single-store")
    assert gfs_store._resolve_stores() == ["single-store"]


def test_resolve_stores_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BR_FILE_SEARCH_STORE_NAMES", raising=False)
    monkeypatch.delenv("FILE_SEARCH_STORE", raising=False)
    monkeypatch.delenv("BR_FILE_SEARCH_STORE", raising=False)
    monkeypatch.delenv("BR_GOOGLE_FILE_SEARCH_STORE", raising=False)
    monkeypatch.delenv("GOOGLE_FILE_SEARCH_STORE", raising=False)
    assert gfs_store._resolve_stores() == [
        "fileSearchStores/brain-researcher-codebase-5i70bkfmcumj"
    ]


def test_route_gfs_stores_prefers_papers_for_publication_queries() -> None:
    stores = [
        "fileSearchStores/brain-researcher-codebase-abc",
        "fileSearchStores/papers-fmri-oa-xyz",
    ]
    ordered = gfs_store.route_gfs_stores(
        "find full text guideline citations for fmriprep",
        stores=stores,
    )
    assert ordered == [
        "fileSearchStores/papers-fmri-oa-xyz",
        "fileSearchStores/brain-researcher-codebase-abc",
    ]


def test_should_trigger_auto_gfs_skips_exact_lookup_without_weak_signal() -> None:
    decision = gfs_store.should_trigger_auto_gfs(
        "task:stroop",
        store_override="fileSearchStores/papers-fmri-oa-xyz",
    )
    assert decision.should_trigger is False
    assert decision.reason == "exact_lookup_skip"


def test_should_trigger_auto_gfs_uses_weak_evidence_budget() -> None:
    decision = gfs_store.should_trigger_auto_gfs(
        "recommend default fmriprep confounds",
        result_count=1,
        top_score=0.2,
        store_override="fileSearchStores/papers-fmri-oa-xyz,fileSearchStores/brain-researcher-codebase-abc",
    )
    assert decision.should_trigger is True
    assert decision.call_budget == 2
    assert decision.reason == "intent_papers"


def test_search_gfs_auto_falls_back_to_second_store_when_first_is_weak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def _fake_search_gfs(query, *, top_k=5, store=None, model=None, api_key=None):
        calls.append(store or "")
        if store == "fileSearchStores/brain-researcher-codebase-abc":
            return {
                "status": "ok",
                "query": query,
                "store": store,
                "model": model or "gemini-3-flash-preview",
                "summary": "weak",
                "hits": [],
            }
        return {
            "status": "ok",
            "query": query,
            "store": store,
            "model": model or "gemini-3-flash-preview",
            "summary": "strong",
            "hits": [
                {
                    "doc_id": "doc-1",
                    "title": "API reference",
                    "snippet": "Implementation details for the tool registry.",
                    "text": "Implementation details for the tool registry.",
                    "score": 0.9,
                }
            ],
        }

    monkeypatch.setattr(gfs_store, "search_gfs", _fake_search_gfs)
    result = gfs_store.search_gfs_auto(
        "show me the api schema for tool registry",
        top_k=3,
        store="fileSearchStores/papers-fmri-oa-xyz,fileSearchStores/brain-researcher-codebase-abc",
        weak_evidence=True,
        max_calls=2,
    )

    assert result["status"] == "ok"
    assert result["call_count"] == 2
    assert result["stores_hit"] == [
        "fileSearchStores/brain-researcher-codebase-abc",
        "fileSearchStores/papers-fmri-oa-xyz",
    ]
    assert calls == [
        "fileSearchStores/brain-researcher-codebase-abc",
        "fileSearchStores/papers-fmri-oa-xyz",
    ]
    assert result["hits"][0]["doc_id"] == "doc-1"


def test_normalize_gfs_hit_prefers_embedded_paper_title_over_bundle_name() -> None:
    text = """
===DOC_START===
doc_type: paper
pmcid: 5489207
pmid: 27888059
doi: 10.1016/j.neuroimage.2016.11.052
title: Towards a consensus regarding global signal regression for resting state functional connectivity MRI
journal: Neuroimage
year: 2017
===TEXT===
Abstract text here.
"""
    hit = gfs_store._normalize_gfs_hit(
        raw_title="m4_pubget_papers_bundle_00031.txt",
        text=text,
        score=0.8,
        doc_id="fileSearchStores/papers/files/m4_pubget_papers_bundle_00031.txt",
    )

    assert (
        hit["title"]
        == "Towards a consensus regarding global signal regression for resting state functional connectivity MRI"
    )
    assert hit["pmcid"] == "PMC5489207"
    assert hit["pmid"] == "27888059"
    assert hit["doi"] == "10.1016/j.neuroimage.2016.11.052"


def test_normalize_gfs_hit_uses_excerpt_fallback_when_title_is_missing() -> None:
    hit = gfs_store._normalize_gfs_hit(
        raw_title="m4_pubget_papers_bundle_00088.txt",
        text=(
            "Despite these drawbacks, discerning whether GSR is a beneficial or "
            "detrimental step in the preprocessing of real data remains difficult. "
            "Several studies reached conflicting conclusions."
        ),
        score=0.4,
    )

    assert hit["title"] is not None
    assert hit["title"].startswith("Paper excerpt: ")
    assert "bundle" not in hit["title"].lower()
    assert hit["pmcid"] is None
    assert hit["pmid"] is None
    assert hit["doi"] is None


def test_search_gfs_auto_dedupes_by_doi_and_hides_bundle_titles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_search_gfs(query, *, top_k=5, store=None, model=None, api_key=None):
        del query, top_k, model, api_key
        if store == "fileSearchStores/papers-a":
            return {
                "status": "ok",
                "query": "q",
                "store": store,
                "model": "gemini-3-flash-preview",
                "summary": "papers-a",
                "hits": [
                    {
                    "doc_id": "fileSearchStores/papers-a/files/m4_pubget_papers_bundle_00031.txt",
                    "title": "m4_pubget_papers_bundle_00031.txt",
                    "doi": "10.1016/j.neuroimage.2016.11.052",
                    "snippet": "bundle hit",
                    "text": "bundle hit",
                    "score": 0.1,
                }
            ],
        }
        return {
            "status": "ok",
            "query": "q",
            "store": store,
            "model": "gemini-3-flash-preview",
            "summary": "papers-b",
            "hits": [
                {
                    "doc_id": "fileSearchStores/papers-b/files/doc-2",
                    "title": "Towards a consensus regarding global signal regression for resting state functional connectivity MRI",
                    "doi": "10.1016/j.neuroimage.2016.11.052",
                    "pmcid": "PMC5489207",
                    "pmid": "27888059",
                    "snippet": "clean hit",
                    "text": "clean hit",
                    "score": 0.6,
                }
            ],
        }

    monkeypatch.setattr(gfs_store, "search_gfs", _fake_search_gfs)
    result = gfs_store.search_gfs_auto(
        "find papers on global signal regression",
        top_k=5,
        store="fileSearchStores/papers-a,fileSearchStores/papers-b",
        weak_evidence=True,
        max_calls=2,
    )

    assert result["status"] == "ok"
    assert result["n_docs_hit"] == 1
    assert result["call_count"] == 2
    hit = result["hits"][0]
    assert (
        hit["title"]
        == "Towards a consensus regarding global signal regression for resting state functional connectivity MRI"
    )
    assert hit["doi"] == "10.1016/j.neuroimage.2016.11.052"
    assert hit["pmcid"] == "PMC5489207"
    assert hit["pmid"] == "27888059"
    assert "bundle" not in (hit.get("title") or "").lower()


def test_merge_hits_prefers_real_title_over_higher_score_bundle_title() -> None:
    merged = gfs_store._merge_hits(
        {
            "doc_id": "fileSearchStores/papers-a/files/m4_pubget_papers_bundle_00031.txt",
            "title": "m4_pubget_papers_bundle_00031.txt",
            "doi": "10.1016/j.neuroimage.2016.11.052",
            "snippet": "bundle hit",
            "text": "bundle hit",
            "score": 0.95,
        },
        {
            "doc_id": "fileSearchStores/papers-b/files/doc-2",
            "title": "Towards a consensus regarding global signal regression for resting state functional connectivity MRI",
            "doi": "10.1016/j.neuroimage.2016.11.052",
            "pmcid": "PMC5489207",
            "pmid": "27888059",
            "snippet": "clean hit",
            "text": "clean hit",
            "score": 0.6,
        },
    )

    assert (
        merged["title"]
        == "Towards a consensus regarding global signal regression for resting state functional connectivity MRI"
    )
    assert merged["score"] == 0.95
    assert merged["pmcid"] == "PMC5489207"
    assert merged["pmid"] == "27888059"


def test_finalize_hits_propagates_bundle_metadata_to_titleless_chunk() -> None:
    hits = [
        gfs_store._normalize_gfs_hit(
            raw_title="m4_pubget_papers_bundle_00031.txt",
            text="""
===DOC_START===
doc_type: paper
pmcid: 5489207
pmid: 27888059
doi: 10.1016/j.neuroimage.2016.11.052
title: Towards a consensus regarding global signal regression for resting state functional connectivity MRI
===TEXT===
Abstract text here.
""",
            score=0.7,
        ),
        gfs_store._normalize_gfs_hit(
            raw_title="m4_pubget_papers_bundle_00031.txt",
            text=(
                "gave opposite recommendations as to whether GSR should be used "
                "in the processing of resting state functional connectivity data."
            ),
            score=0.6,
        ),
    ]

    finalized = gfs_store._finalize_hits(hits, top_k=5)

    assert len(finalized) == 1
    hit = finalized[0]
    assert (
        hit["title"]
        == "Towards a consensus regarding global signal regression for resting state functional connectivity MRI"
    )
    assert hit["doi"] == "10.1016/j.neuroimage.2016.11.052"
    assert hit["pmcid"] == "PMC5489207"
    assert hit["pmid"] == "27888059"


def test_search_gfs_anchors_bundle_file_title_when_context_has_no_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = "fileSearchStores/papers-fmri-oa-test"

    def _fake_load_google_genai():
        fake_genai = pytypes.SimpleNamespace(
            Client=lambda api_key: pytypes.SimpleNamespace(models=object())
        )
        fake_types = pytypes.SimpleNamespace(
            Tool=lambda **kwargs: kwargs,
            FileSearch=lambda **kwargs: kwargs,
            GenerateContentConfig=lambda **kwargs: kwargs,
        )
        return fake_genai, fake_types

    def _fake_run_generate_content(client, *, model, query, config, timeout_ms=None):
        del client, model, query, config, timeout_ms
        ctx = pytypes.SimpleNamespace(
            document_name=None,
            uri=None,
            id=None,
            name=None,
            path=None,
            file_search_store=store,
            title="m4_pubget_papers_bundle_00044.txt",
            text=(
                "Feature selection inside the cross-validation loop avoids "
                "overoptimistic neuroimaging classification estimates."
            ),
        )
        chunk = pytypes.SimpleNamespace(retrieved_context=ctx, relevance_score=None)
        gm = pytypes.SimpleNamespace(grounding_chunks=[chunk])
        cand = pytypes.SimpleNamespace(grounding_metadata=gm)
        return pytypes.SimpleNamespace(text="summary", candidates=[cand])

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gfs_store, "_load_google_genai", _fake_load_google_genai)
    monkeypatch.setattr(
        gfs_store,
        "_run_gfs_generate_content",
        _fake_run_generate_content,
    )

    result = gfs_store.search_gfs("nested cross-validation", store=store, top_k=3)

    assert result["status"] == "ok"
    assert result["hits"][0]["doc_id"] == (
        f"{store}/files/m4_pubget_papers_bundle_00044.txt"
    )
    assert result["anchors"][0]["anchor_id"] == (
        f"doc:{store}/files/m4_pubget_papers_bundle_00044.txt"
    )
    assert result["anchors"][0]["anchor_type"] == "retrieved_document"


def test_search_gfs_limits_store_fanout_and_reports_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def _fake_load_google_genai():
        fake_genai = pytypes.SimpleNamespace(
            Client=lambda api_key: pytypes.SimpleNamespace(models=object())
        )
        fake_types = pytypes.SimpleNamespace(
            Tool=lambda **kwargs: kwargs,
            FileSearch=lambda **kwargs: kwargs,
            GenerateContentConfig=lambda **kwargs: kwargs,
        )
        return fake_genai, fake_types

    def _fake_run_generate_content(client, *, model, query, config, timeout_ms=None):
        del client, model, query, timeout_ms
        tool = config["tools"][0]
        store_name = tool["file_search"]["file_search_store_names"][0]
        calls.append(store_name)
        ctx = pytypes.SimpleNamespace(
            text="Grounded text",
            title=f"Paper from {store_name}",
            uri=f"doc:{store_name}",
        )
        chunk = pytypes.SimpleNamespace(retrieved_context=ctx, relevance_score=0.82)
        gm = pytypes.SimpleNamespace(grounding_chunks=[chunk])
        cand = pytypes.SimpleNamespace(grounding_metadata=gm)
        return pytypes.SimpleNamespace(text=f"summary:{store_name}", candidates=[cand])

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gfs_store, "_load_google_genai", _fake_load_google_genai)
    monkeypatch.setattr(
        gfs_store,
        "_run_gfs_generate_content",
        _fake_run_generate_content,
    )

    result = gfs_store.search_gfs(
        "find papers on image decoding",
        store="fileSearchStores/papers-a,fileSearchStores/papers-b",
        max_stores=1,
        timeout_ms=50,
    )

    assert result["status"] == "ok"
    assert result["stores_attempted"] == ["fileSearchStores/papers-a"]
    assert result["stores_hit"] == ["fileSearchStores/papers-a"]
    assert result["call_count"] == 1
    assert result["n_docs_hit"] == 1
    assert result["raw_hit_count"] == 1
    assert result["store_errors"] == []
    assert calls == ["fileSearchStores/papers-a"]


def test_search_gfs_reports_store_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_load_google_genai():
        fake_genai = pytypes.SimpleNamespace(
            Client=lambda api_key: pytypes.SimpleNamespace(models=object())
        )
        fake_types = pytypes.SimpleNamespace(
            Tool=lambda **kwargs: kwargs,
            FileSearch=lambda **kwargs: kwargs,
            GenerateContentConfig=lambda **kwargs: kwargs,
        )
        return fake_genai, fake_types

    def _fake_run_generate_content(client, *, model, query, config, timeout_ms=None):
        del client, model, query, config, timeout_ms
        raise TimeoutError("file_search timed out after 5ms")

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gfs_store, "_load_google_genai", _fake_load_google_genai)
    monkeypatch.setattr(
        gfs_store,
        "_run_gfs_generate_content",
        _fake_run_generate_content,
    )

    result = gfs_store.search_gfs(
        "find papers on image decoding",
        store="fileSearchStores/papers-a",
        timeout_ms=5,
    )

    assert result["status"] == "error"
    assert result["call_count"] == 1
    assert result["stores_attempted"] == ["fileSearchStores/papers-a"]
    assert result["stores_hit"] == []
    assert result["n_docs_hit"] == 0
    assert result["store_errors"] == [
        {
            "store": "fileSearchStores/papers-a",
            "error": "file_search timed out after 5ms",
        }
    ]
