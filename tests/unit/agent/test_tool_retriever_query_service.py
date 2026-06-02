from brain_researcher.services.agent.tool_retriever import FileSearchHit, ToolRetriever


def test_tool_retriever_uses_query_service(monkeypatch):
    monkeypatch.setenv("BR_TOOL_RETRIEVER_SOURCE", "br_kg")

    seen_kwargs = {}

    def _fake_search_tools_structured(**kwargs):
        nonlocal seen_kwargs
        seen_kwargs = dict(kwargs)
        return {
            "candidates": [
                {
                    "tool_id": "kg_tool.run",
                    "method": "glm",
                    "software": "fsl",
                    "op_key": "feat",
                    "version": "1.0",
                }
            ]
        }

    monkeypatch.setattr(
        "brain_researcher.services.br_kg.query_service.search_tools_structured",
        _fake_search_tools_structured,
    )

    retriever = ToolRetriever(
        neo4j_uri="bolt://localhost:7687"
    )  # driver won't be used in this path
    results = retriever.retrieve_tools("glm analysis", top_k=3)

    assert results
    first = results[0]
    assert first.id == "kg_tool.run"
    assert first.source == "br_kg"
    assert seen_kwargs.get("exposed_only") is True
    retriever.close()


def test_tool_retriever_allows_explicit_unexposed_tool_reference(monkeypatch):
    monkeypatch.setenv("BR_TOOL_RETRIEVER_SOURCE", "br_kg")

    def _fake_search_tools_structured(**kwargs):
        # Explicit tool reference should bypass exposure gating.
        assert kwargs.get("exposed_only") is False
        return {
            "candidates": [
                {
                    "tool_id": "fsl.6.0.4.film_gls.run",
                    "method": "glm_first_level_fmri",
                    "software": "fsl",
                    "op_key": "filmgls",
                    "version": "6.0.4",
                }
            ]
        }

    monkeypatch.setattr(
        "brain_researcher.services.br_kg.query_service.search_tools_structured",
        _fake_search_tools_structured,
    )

    retriever = ToolRetriever(
        neo4j_uri="bolt://localhost:7687"
    )  # driver won't be used in this path
    results = retriever.retrieve_tools("fsl.6.0.4.film_gls.run", top_k=3)
    assert results and results[0].id == "fsl.6.0.4.film_gls.run"
    retriever.close()


def test_tool_retriever_preflight_gfs_enriches_query_service_path(monkeypatch):
    monkeypatch.setenv("BR_TOOL_RETRIEVER_SOURCE", "br_kg")
    seen_queries = []

    def _fake_search_tools_structured(**kwargs):
        seen_queries.append(kwargs.get("query"))
        return {
            "candidates": [
                {
                    "tool_id": "kg_tool.run",
                    "method": "glm",
                    "software": "fsl",
                    "op_key": "feat",
                    "version": "1.0",
                    "score": 0.8,
                }
            ]
        }

    monkeypatch.setattr(
        "brain_researcher.services.br_kg.query_service.search_tools_structured",
        _fake_search_tools_structured,
    )

    retriever = ToolRetriever(neo4j_uri="bolt://localhost:7687")
    monkeypatch.setattr(
        retriever,
        "_enrich_query_with_file_search",
        lambda query, **kwargs: (
            query + "\n\nCONTEXT (gfs):\npaper snippet",
            {"status": "ok", "triggered": True, "query": query, "query_used": query},
        ),
    )

    results = retriever.retrieve_tools("what publication supports feat design", top_k=3)

    assert results
    assert seen_queries
    assert "CONTEXT (gfs)" in seen_queries[0]
    retriever.close()


def test_tool_retriever_weak_fallback_reruns_query_service_with_gfs(monkeypatch):
    monkeypatch.setenv("BR_TOOL_RETRIEVER_SOURCE", "br_kg")
    seen_queries = []

    def _fake_search_tools_structured(**kwargs):
        seen_queries.append(kwargs.get("query"))
        return {
            "candidates": [
                {
                    "tool_id": "kg_tool.run",
                    "method": "glm",
                    "software": "fsl",
                    "op_key": "feat",
                    "version": "1.0",
                    "score": 0.2,
                }
            ]
        }

    monkeypatch.setattr(
        "brain_researcher.services.br_kg.query_service.search_tools_structured",
        _fake_search_tools_structured,
    )

    retriever = ToolRetriever(neo4j_uri="bolt://localhost:7687")
    calls = {"count": 0}

    def _fake_enrich(query, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return query, {
                "status": "skipped",
                "triggered": False,
                "query": query,
                "query_used": query,
            }
        return query + "\n\nCONTEXT (gfs):\nfull text snippet", {
            "status": "ok",
            "triggered": True,
            "query": query,
            "query_used": query,
        }

    monkeypatch.setattr(retriever, "_enrich_query_with_file_search", _fake_enrich)

    results = retriever.retrieve_tools("which code path implements feat glm", top_k=3)

    assert results
    assert len(seen_queries) == 2
    assert "CONTEXT (gfs)" not in seen_queries[0]
    assert "CONTEXT (gfs)" in seen_queries[1]
    retriever.close()


def test_tool_retriever_returns_file_search_hits_when_semantic_disabled(monkeypatch):
    monkeypatch.setenv("BR_TOOL_RETRIEVER_SOURCE", "vector")

    class _DummyDriver:
        def close(self):
            return None

    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever.GraphDatabase.driver",
        lambda *args, **kwargs: _DummyDriver(),
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever._cached_sentence_transformer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("semantic embedding model should not load")
        ),
    )

    retriever = ToolRetriever(neo4j_uri="bolt://localhost:7687", enable_semantic=False)
    monkeypatch.setattr(
        retriever,
        "_enrich_query_with_file_search",
        lambda query, **kwargs: (
            query,
            {
                "status": "skipped",
                "triggered": False,
                "query": query,
                "query_used": query,
            },
        ),
    )
    monkeypatch.setattr(
        retriever,
        "_file_search_hits",
        lambda *args, **kwargs: [FileSearchHit(tool_id="kg_tool.run", score=0.73)],
    )

    results = retriever.retrieve_tools("glm analysis", top_k=3)

    assert results
    assert results[0].id == "kg_tool.run"
    assert results[0].source == "file_search"
    retriever.close()
