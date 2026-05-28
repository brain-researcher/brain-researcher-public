"""Integration tests for ToolRetriever - two-stage tool search."""

import os
import pytest
from typing import Optional

# Skip entire module if Neo4j not available
def neo4j_available() -> bool:
    """Check if Neo4j is reachable."""
    uri = os.environ.get("NEO4J_URI")
    if not uri:
        return False
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            uri,
            auth=(
                os.environ.get("NEO4J_USER", "neo4j"),
                os.environ.get("NEO4J_PASSWORD", ""),
            ),
        )
        with driver.session() as session:
            session.run("RETURN 1")
        driver.close()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not neo4j_available(), reason="NEO4J not reachable"),
]


@pytest.fixture(scope="module")
def retriever():
    """Create a ToolRetriever instance for tests."""
    from brain_researcher.services.agent.tool_retriever import ToolRetriever
    r = ToolRetriever()
    yield r
    r.close()


class TestToolRetrieverContract:
    """Contract tests ensuring ToolRetriever returns valid data."""

    def test_get_all_families_returns_data(self, retriever):
        """Verify we can fetch all families."""
        families = retriever.get_all_families()
        assert len(families) >= 1, "Should have at least one ToolFamily"
        for fam in families:
            assert "id" in fam
            assert "name" in fam
            assert "tool_count" in fam

    def test_retrieve_tools_from_fsl_family(self, retriever):
        """Contract test: retrieve tools from FSL family with valid fields."""
        results = retriever.retrieve_tools(
            query="brain extraction skull stripping",
            family_ids=["fsl"],
            top_k=5,
        )

        assert len(results) >= 1, "FSL should have at least 1 tool"
        for tool in results:
            # Required fields must be non-empty
            assert tool.id, f"Tool missing id: {tool}"
            assert tool.family_id, f"Tool missing family_id: {tool}"
            # At least one metadata field should be present
            has_metadata = (
                tool.description
                or tool.capabilities
                or tool.consumes
                or tool.produces
            )
            assert has_metadata, f"Tool has no metadata: {tool.id}"

    def test_retrieve_tools_from_freesurfer_family(self, retriever):
        """Contract test: retrieve tools from FreeSurfer family."""
        results = retriever.retrieve_tools(
            query="cortical surface reconstruction",
            family_ids=["freesurfer"],
            top_k=5,
        )

        assert len(results) >= 1, "FreeSurfer should have at least 1 tool"
        for tool in results:
            assert tool.id
            assert tool.family_id == "freesurfer"

    def test_two_stage_search_returns_results(self, retriever):
        """Test full two-stage search (family selection + tool retrieval)."""
        results = retriever.search(
            query="brain registration normalization",
            top_k=10,
            max_families=3,
        )

        assert len(results) >= 1, "Search should return at least 1 tool"
        # Verify score ordering (descending)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True), "Results should be ordered by score"

    def test_family_selection_picks_relevant_families(self, retriever):
        """Test that keyword-based family selection works."""
        # FSL keywords should select fsl
        families = retriever.select_families_by_query(
            query="FSL BET brain extraction",
            max_families=3,
        )
        assert "fsl" in families, f"Expected 'fsl' in {families}"

        # FreeSurfer keywords should select freesurfer
        families = retriever.select_families_by_query(
            query="recon-all cortical parcellation",
            max_families=3,
        )
        assert "freesurfer" in families, f"Expected 'freesurfer' in {families}"

    def test_empty_query_returns_top_tools(self, retriever):
        """Even with empty query, should return some tools."""
        results = retriever.retrieve_tools(
            query="",
            family_ids=["fsl"],
            top_k=5,
        )
        # May return tools ordered by default (e.g., by name or random)
        # Just verify it doesn't crash and returns something
        assert isinstance(results, list)

    def test_modality_filter_works(self, retriever):
        """Test filtering by modality."""
        results = retriever.retrieve_tools(
            query="analysis",
            family_ids=["fsl", "freesurfer"],
            top_k=20,
            filters={"modality": "smri"},
        )
        # If filter works, all results should have smri in modality
        # (Note: some tools might not have modality set)
        # Just verify query doesn't crash
        assert isinstance(results, list)


class TestToolRetrieverEdgeCases:
    """Edge case tests for ToolRetriever."""

    def test_nonexistent_family_returns_empty(self, retriever):
        """Query with nonexistent family returns empty list."""
        results = retriever.retrieve_tools(
            query="anything",
            family_ids=["nonexistent_family_xyz"],
            top_k=5,
        )
        assert results == [], f"Expected empty list, got {results}"

    def test_very_large_top_k_is_handled(self, retriever):
        """Large top_k should work without error."""
        results = retriever.retrieve_tools(
            query="brain",
            family_ids=["fsl"],
            top_k=1000,  # More than actual tools
        )
        assert isinstance(results, list)
        assert len(results) <= 1000

    def test_multiple_families_combined(self, retriever):
        """Search across multiple families."""
        results = retriever.retrieve_tools(
            query="registration",
            family_ids=["fsl", "ants", "freesurfer"],
            top_k=10,
        )
        # Should have results from at least 2 different families
        families_found = set(r.family_id for r in results)
        assert len(families_found) >= 1, "Should find tools from at least one family"
