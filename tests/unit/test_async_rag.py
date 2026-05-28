import asyncio
import os
import sys
import time

import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

from brain_researcher.core.analysis.rag_retrieval import (
    RAGKnowledgeSystem,
    close_shared_session,
    get_shared_session,
    query_pubmed_async,
)


@pytest.mark.asyncio
async def test_shared_session_reuse():
    """Test that the shared session is reused across calls."""
    s1 = await get_shared_session()
    s2 = await get_shared_session()
    assert s1 is s2
    await close_shared_session()


@pytest.mark.asyncio
async def test_hybrid_concurrency(mocker):
    """Test that hybrid retrieval runs PubMed and spatial queries concurrently."""
    rag = RAGKnowledgeSystem()

    async def fake_pubmed(*args, **kwargs):
        await asyncio.sleep(0.1)
        return [{"id": "1", "title": "T", "abstract": "A", "source": "pubmed"}]

    def fake_spatial(*args, **kwargs):
        time.sleep(0.1)
        return [
            {
                "id": "s1",
                "title": "S",
                "abstract": "A",
                "source": "nimare_dataset (neurosynth_v7)",
                "coordinates": [0, 0, 0],
                "distance_to_query": 1,
                "study_id": "s1",
                "score": 1.0,
            }
        ]

    mocker.patch(
        "brain_researcher.core.analysis.rag_retrieval.query_pubmed_async",
        side_effect=fake_pubmed,
    )
    mocker.patch.object(rag, "retrieve_spatial", side_effect=fake_spatial)

    start = time.perf_counter()
    res = await rag.retrieve_hybrid_async("q", [0, 0, 0], top_k=2)
    duration = time.perf_counter() - start
    await close_shared_session()

    # Should run concurrently, so total time should be ~0.1s not ~0.2s
    assert duration < 0.18
    assert len(res) == 2


@pytest.mark.asyncio
async def test_incremental_update(mocker, tmp_path):
    """Test that incremental update uses the 'since' parameter."""
    rag = RAGKnowledgeSystem(db_path=str(tmp_path))
    # Set last run date
    (tmp_path / "pubmed_last_run.txt").write_text("2020/01/01")

    captured = {}

    async def fake_pubmed(*args, **kwargs):
        captured["since"] = kwargs.get("since")
        return [{"id": "1", "title": "Test", "abstract": "Test", "source": "pubmed"}]

    mocker.patch(
        "brain_researcher.core.analysis.rag_retrieval.query_pubmed_async",
        side_effect=fake_pubmed,
    )
    # Use force_refresh to bypass cache
    await rag.retrieve_semantic_async("test", top_k=1, force_refresh=True)
    await close_shared_session()

    assert captured["since"] == "2020/01/01"
    new_val = (tmp_path / "pubmed_last_run.txt").read_text().strip()
    assert new_val != "2020/01/01"  # Should have been updated to current date


@pytest.mark.asyncio
async def test_query_pubmed_async_basic(mocker):
    """Test basic async PubMed query functionality."""

    # Create a proper async context manager mock for session.get
    class AsyncContextManagerMock:
        def __init__(self, response):
            self.response = response

        async def __aenter__(self):
            return self.response

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    # Mock the search response
    search_response = mocker.MagicMock()
    search_response.json = mocker.AsyncMock(
        return_value={"esearchresult": {"idlist": ["123", "456"]}}
    )

    # Mock the fetch response with valid XML
    fetch_response = mocker.MagicMock()
    fetch_response.text = mocker.AsyncMock(
        return_value="""
        <PubMedArticleSet>
            <PubmedArticle>
                <MedlineCitation>
                    <PMID>123</PMID>
                    <Article>
                        <ArticleTitle>Test Article 1</ArticleTitle>
                        <Abstract>
                            <AbstractText>Test abstract 1</AbstractText>
                        </Abstract>
                    </Article>
                </MedlineCitation>
            </PubmedArticle>
            <PubmedArticle>
                <MedlineCitation>
                    <PMID>456</PMID>
                    <Article>
                        <ArticleTitle>Test Article 2</ArticleTitle>
                        <Abstract>
                            <AbstractText>Test abstract 2</AbstractText>
                        </Abstract>
                    </Article>
                </MedlineCitation>
            </PubmedArticle>
        </PubMedArticleSet>
    """
    )

    # Configure session mock with proper async context manager
    def get_side_effect(url, **kwargs):
        if "esearch" in url:
            return AsyncContextManagerMock(search_response)
        else:
            return AsyncContextManagerMock(fetch_response)

    mock_session = mocker.MagicMock()
    mock_session.get = mocker.MagicMock(side_effect=get_side_effect)

    results = await query_pubmed_async(
        "test query", max_results=2, session=mock_session
    )

    assert len(results) == 2
    assert results[0]["id"] == "123"
    assert results[0]["title"] == "Test Article 1"
    assert results[1]["id"] == "456"
    assert results[1]["title"] == "Test Article 2"


@pytest.mark.asyncio
async def test_retrieve_semantic_async_with_cache(mocker, tmp_path):
    """Test async semantic retrieval with caching."""
    rag = RAGKnowledgeSystem(db_path=str(tmp_path))

    call_count = 0

    async def counting_pubmed(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return [
            {"id": "1", "title": "Test", "abstract": "Abstract", "source": "pubmed"}
        ]

    mocker.patch(
        "brain_researcher.core.analysis.rag_retrieval.query_pubmed_async",
        side_effect=counting_pubmed,
    )

    # Clear any existing cache
    rag.invalidate_cache("pubmed_async")

    # First call should query PubMed
    res1 = await rag.retrieve_semantic_async("test", top_k=1)
    assert call_count == 1

    # Second call should use cache
    res2 = await rag.retrieve_semantic_async("test", top_k=1)
    assert call_count == 1  # Should not have called again

    # Force refresh should query again
    res3 = await rag.retrieve_semantic_async("test", top_k=1, force_refresh=True)
    assert call_count == 2

    await close_shared_session()


@pytest.mark.asyncio
async def test_incremental_pubmed_update(mocker, tmp_path):
    """Test incremental PubMed update functionality."""
    rag = RAGKnowledgeSystem(db_path=str(tmp_path))

    # Mock responses
    async def fake_pubmed(*args, **kwargs):
        return [
            {
                "id": "new1",
                "title": "New Paper 1",
                "abstract": "New abstract 1",
                "source": "pubmed",
            },
            {
                "id": "new2",
                "title": "New Paper 2",
                "abstract": "New abstract 2",
                "source": "pubmed",
            },
        ]

    # Mock index_data to capture calls
    indexed_data = []

    def fake_index(source, data):
        indexed_data.extend(data)

    mocker.patch(
        "brain_researcher.core.analysis.rag_retrieval.query_pubmed_async",
        side_effect=fake_pubmed,
    )
    mocker.patch.object(rag, "index_data", side_effect=fake_index)

    # Run incremental update
    new_records = await rag.incremental_pubmed_update("neuroscience", max_results=10)

    assert len(new_records) == 2
    assert len(indexed_data) == 2
    assert indexed_data[0]["id"] == "new1"

    # Check that last run date was updated
    last_run = rag._read_last_pubmed_run()
    assert last_run is not None

    await close_shared_session()
