"""Tests for paper utility functions."""

import pytest

from brain_researcher.core.analysis.paper_utils import (
    SKLEARN_AVAILABLE,
    _extract_year,
    cluster_papers,
    deduplicate_papers,
    rank_papers_in_cluster,
)


class TestDeduplicatePapers:
    """Test paper deduplication functionality."""

    def test_empty_list(self):
        """Test deduplication with empty list."""
        assert deduplicate_papers([]) == []

    def test_no_duplicates(self):
        """Test deduplication with no duplicates."""
        papers = [
            {"id": "1", "doi": "10.1234/a", "title": "Paper A"},
            {"id": "2", "doi": "10.1234/b", "title": "Paper B"},
            {"id": "3", "doi": "10.1234/c", "title": "Paper C"},
        ]
        result = deduplicate_papers(papers)
        assert len(result) == 3
        assert result == papers

    def test_duplicate_by_doi(self):
        """Test deduplication by DOI."""
        papers = [
            {"id": "1", "doi": "10.1234/a", "title": "Paper A"},
            {"id": "2", "doi": "10.1234/a", "title": "Paper A v2"},  # Same DOI
            {"id": "3", "doi": "10.1234/b", "title": "Paper B"},
        ]
        result = deduplicate_papers(papers)
        assert len(result) == 2
        assert result[0]["id"] == "1"  # Keep first occurrence
        assert result[1]["id"] == "3"

    def test_duplicate_by_id(self):
        """Test deduplication by ID when DOI is missing."""
        papers = [
            {"id": "123", "doi": None, "title": "Paper A"},
            {"id": "123", "doi": None, "title": "Paper A duplicate"},  # Same ID
            {"id": "456", "doi": None, "title": "Paper B"},
        ]
        result = deduplicate_papers(papers)
        assert len(result) == 2
        assert result[0]["title"] == "Paper A"
        assert result[1]["id"] == "456"

    def test_none_values(self):
        """Test handling of None values in DOI and ID."""
        papers = [
            {"id": None, "doi": None, "title": "Paper A"},
            {"id": None, "doi": None, "title": "Paper B"},  # Different paper, both None
            {"id": "123", "doi": None, "title": "Paper C"},
            {"id": "123", "doi": None, "title": "Paper C duplicate"},
        ]
        result = deduplicate_papers(papers)
        assert len(result) == 3  # Two papers with None IDs + one unique

    def test_mixed_duplicates(self):
        """Test complex case with mixed duplicates."""
        papers = [
            {"id": "1", "doi": "10.1234/a", "title": "Paper A"},
            {"id": "2", "doi": "10.1234/b", "title": "Paper B"},
            {"id": "1", "doi": "10.1234/a", "title": "Paper A dup"},  # Duplicate
            {"id": "3", "doi": "10.1234/c", "title": "Paper C"},
            {"id": "2", "doi": "10.1234/b", "title": "Paper B dup"},  # Duplicate
        ]
        result = deduplicate_papers(papers)
        assert len(result) == 3
        titles = [p["title"] for p in result]
        assert "Paper A" in titles
        assert "Paper B" in titles
        assert "Paper C" in titles


class TestExtractYear:
    """Test year extraction functionality."""

    def test_direct_year_field(self):
        """Test extraction from year field."""
        assert _extract_year({"year": 2023}) == 2023
        assert _extract_year({"year": "2022"}) == 2022

    def test_date_field(self):
        """Test extraction from date field."""
        assert _extract_year({"date": "2021-06-15"}) == 2021
        assert _extract_year({"date": "2020-01"}) == 2020
        assert _extract_year({"date": "2019"}) == 2019

    def test_publication_date_field(self):
        """Test extraction from publication_date field."""
        assert _extract_year({"publication_date": "2018-12-01"}) == 2018

    def test_invalid_values(self):
        """Test handling of invalid values."""
        assert _extract_year({"year": "invalid"}) is None
        assert _extract_year({"date": "abc"}) is None
        assert _extract_year({}) is None
        assert _extract_year({"year": None}) is None


@pytest.mark.skipif(not SKLEARN_AVAILABLE, reason="scikit-learn not available")
class TestClusterPapers:
    """Test paper clustering functionality."""

    def test_empty_list(self):
        """Test clustering with empty list."""
        assert cluster_papers([]) == []

    def test_no_abstracts(self):
        """Test clustering with papers lacking abstracts."""
        papers = [
            {"id": "1", "title": "Paper A"},
            {"id": "2", "title": "Paper B"},
            {"id": "3", "title": "Paper C"},
        ]
        result = cluster_papers(papers)
        assert len(result) == 1
        assert "No abstracts available" in result[0]["summary"]

    def test_too_few_papers(self):
        """Test clustering with too few papers."""
        papers = [
            {
                "id": "1",
                "title": "Paper A",
                "abstract": "This is about neural networks",
            },
            {"id": "2", "title": "Paper B", "abstract": "This is about brain imaging"},
        ]
        result = cluster_papers(papers)
        assert len(result) == 1
        assert result[0]["size"] == 2
        assert "Small dataset" in result[0]["summary"]

    def test_basic_clustering(self):
        """Test basic clustering functionality."""
        papers = [
            {
                "id": "1",
                "title": "Neural Networks",
                "abstract": "Deep learning neural networks for image recognition using convolutional layers",
            },
            {
                "id": "2",
                "title": "Brain Networks",
                "abstract": "Neural pathways and brain connectivity networks in cognitive processing",
            },
            {
                "id": "3",
                "title": "CNN Architecture",
                "abstract": "Convolutional neural network architectures for deep learning applications",
            },
            {
                "id": "4",
                "title": "fMRI Analysis",
                "abstract": "Brain imaging using functional magnetic resonance imaging techniques",
            },
            {
                "id": "5",
                "title": "Deep Learning",
                "abstract": "Deep neural networks and machine learning for pattern recognition",
            },
        ]
        result = cluster_papers(papers, n_clusters=2)

        assert len(result) == 2
        assert all(c["size"] > 0 for c in result)
        assert sum(c["size"] for c in result) == 5
        assert all("papers" in c for c in result)
        assert all("keywords" in c for c in result)

    def test_auto_cluster_number(self):
        """Test automatic cluster number determination."""
        # Create 10 papers with distinct topics
        papers = []
        for i in range(10):
            topic = [
                "neural networks",
                "brain imaging",
                "genetics",
                "cognition",
                "memory",
            ][i % 5]
            papers.append(
                {
                    "id": str(i),
                    "title": f"Paper {i} about {topic}",
                    "abstract": f"This paper discusses {topic} and related research in neuroscience",
                    "journal": "Nature" if i % 2 == 0 else "Science",
                    "year": 2020 + (i % 3),
                }
            )

        result = cluster_papers(papers)  # Auto-determine clusters

        assert len(result) >= 2  # Should create multiple clusters
        assert len(result) <= 5  # But not too many
        assert all(c["summary"] for c in result)

        # Check that summaries contain meaningful information
        for cluster in result:
            assert "papers" in cluster["summary"]
            assert any(str(y) in cluster["summary"] for y in [2020, 2021, 2022])


class TestRankPapersInCluster:
    """Test paper ranking functionality."""

    def test_empty_list(self):
        """Test ranking with empty list."""
        assert rank_papers_in_cluster([]) == []

    def test_basic_ranking(self):
        """Test basic ranking functionality."""
        papers = [
            {
                "id": "1",
                "title": "Old paper",
                "year": 2010,
                "score": 0.5,
                "source": "pubmed",
                "doi": "10.1234/a",
                "abstract": "Short abstract",
            },
            {
                "id": "2",
                "title": "Recent paper",
                "year": 2023,
                "score": 0.8,
                "source": "pubmed",
                "doi": "10.1234/b",
                "abstract": "This is a much longer abstract with more detailed information about the research methodology and findings",
            },
            {
                "id": "3",
                "title": "No year paper",
                "score": 0.6,
                "source": "arxiv",
                "abstract": "Medium length abstract with some details",
            },
        ]

        result = rank_papers_in_cluster(papers)

        # Check all papers have ranking scores and positions
        assert all("cluster_rank_score" in p for p in result)
        assert all("cluster_rank" in p for p in result)

        # Check ranking order (highest score first)
        assert result[0]["cluster_rank"] == 1
        assert result[1]["cluster_rank"] == 2
        assert result[2]["cluster_rank"] == 3

        # Recent paper with high score and DOI should rank first
        assert result[0]["id"] == "2"

    def test_ranking_factors(self):
        """Test that various factors affect ranking."""
        papers = [
            {
                "id": "1",
                "score": 1.0,  # High retrieval score
                "source": "unknown",
                "year": 2000,
            },
            {
                "id": "2",
                "score": 0.1,
                "source": "pubmed",  # Good source
                "doi": "10.1234/x",  # Has DOI
                "year": 2023,  # Recent
                "abstract": "A" * 600,  # Long abstract
                "citation_count": 50,  # High citations
            },
        ]

        result = rank_papers_in_cluster(papers)

        # Paper 2 should rank higher despite lower retrieval score
        # due to other positive factors
        scores = {p["id"]: p["cluster_rank_score"] for p in result}
        assert scores["2"] > scores["1"]


@pytest.mark.skipif(SKLEARN_AVAILABLE, reason="Test for when sklearn is not available")
class TestClusteringFallback:
    """Test clustering behavior when scikit-learn is not available."""

    def test_fallback_clustering(self):
        """Test that clustering falls back gracefully."""
        papers = [
            {"id": "1", "title": "Paper A", "abstract": "Abstract A"},
            {"id": "2", "title": "Paper B", "abstract": "Abstract B"},
            {"id": "3", "title": "Paper C", "abstract": "Abstract C"},
        ]

        result = cluster_papers(papers)

        assert len(result) == 1
        assert "clustering unavailable" in result[0]["summary"]
        assert result[0]["size"] == 3
        assert len(result[0]["papers"]) == 3
