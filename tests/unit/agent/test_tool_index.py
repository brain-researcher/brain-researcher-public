"""
Unit tests for ToolIndex (TF-IDF based tool search).

Tests cover:
- Index building with tool entries
- Basic search functionality
- Synonym expansion
- Ranking determinism
- Edge cases (empty queries, no results)
"""

import pytest
from brain_researcher.services.agent.tool_index import ToolEntry, ToolIndex


@pytest.fixture
def sample_tools():
    """Create sample tool entries for testing."""
    return [
        ToolEntry(
            id="fsl.bet",
            name="bet",
            description="Brain extraction tool for removing skull from brain images",
            tags=["skull-strip", "preprocessing", "brain-extraction"],
            image="/cvmfs/fsl/bet.simg",
            aliases=["brain_extraction", "skull_strip"],
            category="preprocessing",
        ),
        ToolEntry(
            id="afni.3dSkullStrip",
            name="3dSkullStrip",
            description="AFNI tool for skull stripping",
            tags=["skull-strip", "preprocessing"],
            image="/cvmfs/afni/3dSkullStrip.simg",
            aliases=["skull_stripping"],
            category="preprocessing",
        ),
        ToolEntry(
            id="fsl.feat",
            name="feat",
            description="FMRI Expert Analysis Tool for GLM analysis",
            tags=["glm", "analysis", "statistics"],
            image="/cvmfs/fsl/feat.simg",
            aliases=["first_level", "glm_analysis"],
            category="analysis",
        ),
        ToolEntry(
            id="ants.registration",
            name="antsRegistration",
            description="Advanced normalization tools for image registration",
            tags=["registration", "normalization"],
            image="/cvmfs/ants/ants.simg",
            aliases=["normalize", "align"],
            category="registration",
        ),
    ]


@pytest.fixture
def synonyms():
    """Sample synonyms for testing."""
    return {
        "skull strip": ["brain extraction", "BET", "remove skull"],
        "brain extraction": ["skull strip", "BET"],
        "glm": ["general linear model", "statistical analysis"],
    }


def test_tool_index_build(sample_tools):
    """Test that index builds successfully."""
    index = ToolIndex(sample_tools)

    assert index.entries == sample_tools
    assert index.corpus is not None
    assert index.matrix is not None
    assert len(index.corpus) == len(sample_tools)


def test_search_skull_strip(sample_tools, synonyms):
    """Test that 'skull strip' returns BET and 3dSkullStrip."""
    index = ToolIndex(sample_tools, synonyms)
    results = index.search("skull strip", k=5)

    # Should return at least 2 results
    assert len(results) >= 2

    # Top results should be BET and 3dSkullStrip
    tool_ids = [entry.id for entry, score in results[:2]]
    assert "fsl.bet" in tool_ids
    assert "afni.3dSkullStrip" in tool_ids

    # All scores should be positive
    for entry, score in results:
        assert score > 0


def test_search_with_synonym_boost(sample_tools, synonyms):
    """Test that synonyms improve ranking."""
    index = ToolIndex(sample_tools, synonyms)

    # Search for "brain extraction" which is a synonym of "skull strip"
    results = index.search("brain extraction", k=5)

    # Should return BET as top result
    assert len(results) > 0
    top_tool = results[0][0]
    assert top_tool.id == "fsl.bet"


def test_search_glm(sample_tools, synonyms):
    """Test GLM search returns FEAT."""
    index = ToolIndex(sample_tools, synonyms)
    results = index.search("GLM analysis", k=5)

    assert len(results) > 0
    top_tool = results[0][0]
    assert top_tool.id == "fsl.feat"


def test_search_registration(sample_tools):
    """Test registration search."""
    index = ToolIndex(sample_tools)
    results = index.search("image registration", k=5)

    assert len(results) > 0
    top_tool = results[0][0]
    assert top_tool.id == "ants.registration"


def test_search_empty_query(sample_tools):
    """Test that empty query returns no results."""
    index = ToolIndex(sample_tools)

    assert index.search("") == []
    assert index.search("   ") == []
    assert index.search(None) == []


def test_search_no_matches(sample_tools):
    """Test query with no matches."""
    index = ToolIndex(sample_tools)
    results = index.search("quantum computing", k=5)

    # Should return empty or very low scores
    if results:
        # If there are results, scores should be very low
        for entry, score in results:
            assert score < 0.1


def test_search_deterministic(sample_tools, synonyms):
    """Test that search results are deterministic."""
    index = ToolIndex(sample_tools, synonyms)

    results1 = index.search("skull strip", k=5)
    results2 = index.search("skull strip", k=5)

    # Results should be identical
    assert len(results1) == len(results2)
    for (entry1, score1), (entry2, score2) in zip(results1, results2):
        assert entry1.id == entry2.id
        assert abs(score1 - score2) < 1e-6


def test_search_k_parameter(sample_tools):
    """Test that k parameter limits results."""
    index = ToolIndex(sample_tools)

    results_k2 = index.search("preprocessing", k=2)
    results_k10 = index.search("preprocessing", k=10)

    # k=2 should return at most 2 results
    assert len(results_k2) <= 2

    # k=10 should return more results (up to available)
    assert len(results_k10) >= len(results_k2)


def test_get_tool_by_id(sample_tools):
    """Test retrieval by tool ID."""
    index = ToolIndex(sample_tools)

    tool = index.get_tool_by_id("fsl.bet")
    assert tool is not None
    assert tool.id == "fsl.bet"
    assert tool.name == "bet"

    # Non-existent tool
    assert index.get_tool_by_id("nonexistent") is None


def test_get_tools_by_category(sample_tools):
    """Test retrieval by category."""
    index = ToolIndex(sample_tools)

    preprocessing = index.get_tools_by_category("preprocessing")
    assert len(preprocessing) == 2  # BET and 3dSkullStrip

    analysis = index.get_tools_by_category("analysis")
    assert len(analysis) == 1  # FEAT

    # Non-existent category
    empty = index.get_tools_by_category("nonexistent")
    assert len(empty) == 0


def test_synonym_expansion_in_corpus(sample_tools, synonyms):
    """Test that synonyms are expanded in the corpus during indexing."""
    index = ToolIndex(sample_tools, synonyms)

    # The corpus for BET should include expanded synonyms
    bet_entry = [e for e in sample_tools if e.id == "fsl.bet"][0]
    bet_idx = sample_tools.index(bet_entry)
    bet_corpus = index.corpus[bet_idx]

    # Should contain original tags and their synonyms
    assert "skull-strip" in bet_corpus.lower() or "skull strip" in bet_corpus.lower()


def test_alias_matching(sample_tools):
    """Test that aliases improve search results."""
    index = ToolIndex(sample_tools)

    # Search for an alias
    results = index.search("first level analysis", k=5)

    # Should return FEAT (which has "first_level" alias)
    assert len(results) > 0
    tool_ids = [entry.id for entry, score in results]
    assert "fsl.feat" in tool_ids


def test_tag_matching(sample_tools):
    """Test that tags contribute to search."""
    index = ToolIndex(sample_tools)

    # Search for a tag
    results = index.search("normalization", k=5)

    # Should return ANTs
    assert len(results) > 0
    top_tool = results[0][0]
    assert top_tool.id == "ants.registration"


def test_case_insensitive_search(sample_tools):
    """Test that search is case-insensitive."""
    index = ToolIndex(sample_tools)

    results_lower = index.search("skull strip", k=5)
    results_upper = index.search("SKULL STRIP", k=5)
    results_mixed = index.search("Skull Strip", k=5)

    # All should return similar results
    assert len(results_lower) == len(results_upper) == len(results_mixed)

    for (e1, s1), (e2, s2), (e3, s3) in zip(results_lower, results_upper, results_mixed):
        assert e1.id == e2.id == e3.id
