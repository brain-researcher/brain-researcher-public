"""Tests for tool selection and scoring system."""

import pytest
from dataclasses import dataclass
from typing import List, Optional
from types import SimpleNamespace
from unittest.mock import Mock, patch

from brain_researcher.services.agent.planner.selection import (
    SelectionCandidate,
    select_tools,
    explain_selection,
    _score_intent_match,
    _score_description_relevance,
    _score_metadata,
    _score_resource_fit,  # PR-3
    load_scoring_weights,
    clear_scoring_weights_cache,
    apply_constraints,
)
from brain_researcher.services.agent.planner.preflight import (
    PreflightReport,
    PreflightCheck,
    PreflightStatus,
)

# Import shared test helpers
from .helpers import (
    MockContainer,
    MockPython,
    MockMetadata,
    MockResources,
    MockToolCapability,
)


class TestSelectionCandidate:
    """Test SelectionCandidate dataclass and scoring."""

    def test_candidate_creation(self):
        """Test creating a SelectionCandidate."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="A test tool",
            capabilities=("test_op",),
            runtime_kind="python",
        )

        candidate = SelectionCandidate(
            tool=tool,
            scoring_weights=load_scoring_weights(),
            intent_match_score=0.8,
            preflight_passed=True,
            description_score=0.6,
            metadata_score=0.7,
        )

        assert candidate.tool.id == "test.tool"
        assert candidate.intent_match_score == 0.8
        assert candidate.preflight_passed is True
        assert candidate.description_score == 0.6
        assert candidate.metadata_score == 0.7
        # Final score should be calculated automatically
        assert candidate.final_score > 0.0

    def test_custom_scoring_weights_applied(self):
        """Ensure request-scoped weights influence scoring."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="A test tool",
            capabilities=("test_op",),
            runtime_kind="python",
        )
        custom_weights = {
            "intent_match": 0.6,
            "preflight": 0.0,
            "description": 0.0,
            "metadata": 0.0,
            "resource_fit": 0.0,
            "historical_quality": 0.3,
            "latency_pred": 0.1,
        }
        candidate = SelectionCandidate(
            tool=tool,
            intent_match_score=0.5,
            preflight_passed=True,
            description_score=0.0,
            metadata_score=0.0,
            resource_fit_score=0.0,
            historical_quality_score=1.0,
            latency_score=0.0,
            scoring_weights=custom_weights,
        )

        expected = 0.6 * 0.5 + 0.3 * 1.0
        assert abs(candidate.final_score - expected) < 1e-6

    def test_final_score_calculation(self):
        """Test that final score is weighted correctly."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
        )

        # PR-3: 5-factor weights: intent=0.35, preflight=0.25, description=0.20, metadata=0.10, resource_fit=0.10
        # All scores at 1.0 should give final score of 1.0
        weights = load_scoring_weights()
        candidate = SelectionCandidate(
            tool=tool,
            intent_match_score=1.0,
            preflight_passed=True,  # = 1.0
            description_score=1.0,
            metadata_score=1.0,
            resource_fit_score=1.0,
            historical_quality_score=1.0,
            latency_score=1.0,
            scoring_weights=weights,
        )

        expected = (
            weights["intent_match"] * 1.0
            + weights["preflight"] * 1.0
            + weights["description"] * 1.0
            + weights["metadata"] * 1.0
            + weights["resource_fit"] * 1.0
            + weights.get("historical_quality", 0.0) * 1.0
            + weights.get("latency_pred", 0.0) * 1.0
        )
        assert abs(candidate.final_score - expected) < 0.01

    def test_final_score_preflight_fail(self):
        """Test that preflight failure reduces score significantly."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
        )

        # Perfect scores but preflight fails
        weights = load_scoring_weights()
        candidate = SelectionCandidate(
            tool=tool,
            intent_match_score=1.0,
            preflight_passed=False,  # = 0.0
            description_score=1.0,
            metadata_score=1.0,
            resource_fit_score=1.0,
            historical_quality_score=1.0,
            latency_score=1.0,
            scoring_weights=weights,
        )

        expected = (
            weights["intent_match"] * 1.0
            + weights["preflight"] * 0.0
            + weights["description"] * 1.0
            + weights["metadata"] * 1.0
            + weights["resource_fit"] * 1.0
            + weights.get("historical_quality", 0.0) * 1.0
            + weights.get("latency_pred", 0.0) * 1.0
        )
        assert abs(candidate.final_score - expected) < 0.01

    def test_final_score_clamped(self):
        """Test that final score is clamped to [0, 1]."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
        )

        # All zeros
        candidate = SelectionCandidate(
            tool=tool,
            scoring_weights=load_scoring_weights(),
            intent_match_score=0.0,
            preflight_passed=False,
            description_score=0.0,
            metadata_score=0.0,
            resource_fit_score=0.0,
            historical_quality_score=0.0,
            latency_score=0.0,
        )
        assert candidate.final_score == 0.0


def test_select_tools_masks_disallowed_candidates_before_scoring(monkeypatch):
    from brain_researcher.services.agent.planner import selection as sel

    allowed = MockToolCapability(
        id="allowed.tool",
        name="Allowed Tool",
        description="Allowed",
        capabilities=("skull_strip",),
        runtime_kind="python",
    )
    disallowed = MockToolCapability(
        id="blocked.tool",
        name="Blocked Tool",
        description="Blocked",
        capabilities=("skull_strip",),
        runtime_kind="python",
    )

    monkeypatch.setattr(sel, "match_intents", lambda query, modality=None: ["skull_strip"])
    monkeypatch.setattr(sel, "search_by_capability", lambda capability, include_local_first=False: [allowed, disallowed])
    monkeypatch.setattr(sel, "search_by_modality", lambda modality, include_local_first=False: [allowed, disallowed])
    monkeypatch.setattr(sel, "search_by_intent", lambda intent_id, include_local_first=False: [allowed, disallowed])
    monkeypatch.setattr(
        sel,
        "load_hierarchical_config",
        lambda modality=None, operator=None, environment=None: {
            "policy": {"constraints": {}, "scoring": {"weights": load_scoring_weights()}}
        },
    )
    monkeypatch.setattr(
        sel,
        "preflight_batch",
        lambda tools: {
            tool.id: PreflightReport(tool_id=tool.id, passed=True, checks={})
            for tool in tools
        },
    )

    candidates = select_tools(
        query="skull strip",
        modality="smri",
        allowed_tool_ids={"allowed.tool"},
        include_local_first=True,
    )

    assert [cand.tool.id for cand in candidates] == ["allowed.tool"]


class TestIntentMatchScoring:
    """Test intent match scoring logic."""

    def test_exact_match_high_score(self):
        """Test that exact capability match gets high score."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("skull_strip",),
            runtime_kind="python",
        )

        score = _score_intent_match(
            tool,
            matched_operators=["skull_strip", "other_op"],
            operator_weights={"skull_strip": 1.0, "other_op": 0.9},
        )

        # Exact match at rank 0 should give full weight
        assert score >= 0.9  # Should be close to 1.0

    def test_exact_match_not_only_first_capability(self):
        """Match should consider all tool capabilities, not only the first tag."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("other_tag", "skull_strip"),
            runtime_kind="python",
        )

        score = _score_intent_match(
            tool,
            matched_operators=["skull_strip"],
            operator_weights={"skull_strip": 1.0},
        )

        assert score >= 0.9

    def test_partial_match_lower_score(self):
        """Test that partial match gets lower score."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("skull_strip_fast",),
            runtime_kind="python",
        )

        score = _score_intent_match(
            tool,
            matched_operators=["skull_strip"],
            operator_weights={"skull_strip": 1.0},
        )

        # Partial match should give some score but less than exact
        assert 0.3 <= score < 1.0

    def test_no_match_zero_score(self):
        """Test that no match gives zero score."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("unrelated_op",),
            runtime_kind="python",
        )

        score = _score_intent_match(
            tool,
            matched_operators=["skull_strip"],
            operator_weights={"skull_strip": 1.0},
        )

        assert score == 0.0

    def test_rank_weight_decreases(self):
        """Test that lower-ranked matches get lower scores."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("target_op",),
            runtime_kind="python",
        )

        # Match at rank 0
        score_rank0 = _score_intent_match(
            tool,
            matched_operators=["target_op", "other1", "other2"],
            operator_weights={"target_op": 1.0},
        )

        # Match at rank 2
        score_rank2 = _score_intent_match(
            tool,
            matched_operators=["other1", "other2", "target_op"],
            operator_weights={"target_op": 1.0},
        )

        assert score_rank0 > score_rank2

    def test_empty_operators_zero_score(self):
        """Test that empty operator list gives zero score."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("skull_strip",),
            runtime_kind="python",
        )

        score = _score_intent_match(tool, matched_operators=[], operator_weights={})
        assert score == 0.0


class TestDescriptionRelevance:
    """Test description relevance scoring."""

    def test_keyword_match_high_score(self):
        """Test that keyword matches increase score."""
        tool = MockToolCapability(
            id="test.tool",
            name="Brain Extraction",
            description="Tool for skull stripping and brain extraction from MRI images",
            capabilities=("skull_strip",),
            runtime_kind="python",
        )

        score = _score_description_relevance(tool, "skull strip brain extraction")
        assert score > 0.5  # Should match multiple keywords

    def test_no_match_low_score(self):
        """Test that no keyword matches give low score."""
        tool = MockToolCapability(
            id="test.tool",
            name="Registration Tool",
            description="Aligns images using affine transformations",
            capabilities=("register",),
            runtime_kind="python",
        )

        score = _score_description_relevance(tool, "skull strip brain extraction")
        assert score < 0.5  # Should have few/no matches

    def test_short_query_neutral_score(self):
        """Test that very short queries get neutral score."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test",
            description="Test tool",
            capabilities=("test",),
            runtime_kind="python",
        )

        score = _score_description_relevance(tool, "abc")
        assert score == 0.5  # Neutral for short query

    def test_case_insensitive(self):
        """Test that matching is case insensitive."""
        tool = MockToolCapability(
            id="test.tool",
            name="Brain Extraction",
            description="SKULL STRIPPING tool",
            capabilities=("skull_strip",),
            runtime_kind="python",
        )

        score1 = _score_description_relevance(tool, "skull stripping")
        score2 = _score_description_relevance(tool, "SKULL STRIPPING")
        assert score1 == score2


class TestMetadataScoring:
    """Test metadata quality scoring."""

    def test_python_higher_than_container(self):
        """Test that Python tools get higher metadata score."""
        python_tool = MockToolCapability(
            id="python.tool",
            name="Python Tool",
            description="A Python-based tool for analysis",
            capabilities=("analyze",),
            runtime_kind="python",
        )

        container_tool = MockToolCapability(
            id="container.tool",
            name="Container Tool",
            description="A containerized tool for analysis",
            capabilities=("analyze",),
            runtime_kind="container",
        )

        python_score = _score_metadata(python_tool)
        container_score = _score_metadata(container_tool)

        assert python_score > container_score

    def test_description_adds_score(self):
        """Test that having description increases score."""
        with_desc = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="This is a detailed description of the tool that exceeds twenty characters",
            capabilities=("test",),
            runtime_kind="python",
        )

        without_desc = MockToolCapability(
            id="test.tool2",
            name="Test Tool 2",
            description="Short",  # Too short
            capabilities=("test",),
            runtime_kind="python",
        )

        score_with = _score_metadata(with_desc)
        score_without = _score_metadata(without_desc)

        assert score_with > score_without

    def test_documentation_adds_score(self):
        """Test that having documentation increases score."""
        with_docs = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
            documentation="https://docs.example.com/tool",
        )

        without_docs = MockToolCapability(
            id="test.tool2",
            name="Test Tool 2",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
            documentation=None,
        )

        score_with = _score_metadata(with_docs)
        score_without = _score_metadata(without_docs)

        assert score_with > score_without


class TestSelectToolsIntegration:
    """Test integrated tool selection."""

    @patch("brain_researcher.services.agent.planner.selection.match_intents")
    @patch("brain_researcher.services.agent.planner.selection.search_by_capability")
    @patch("brain_researcher.services.agent.planner.selection.preflight_batch")
    def test_select_tools_basic_flow(self, mock_preflight, mock_search, mock_intents):
        """Test basic tool selection flow."""
        # Mock intent matching
        mock_intents.return_value = ["skull_strip"]

        # Mock catalog search
        tool = MockToolCapability(
            id="fsl.bet.run",
            name="BET",
            description="Brain Extraction Tool for skull stripping",
            capabilities=("skull_strip",),
            runtime_kind="container",
        )
        mock_search.return_value = [tool]

        # Mock preflight
        report = PreflightReport(
            tool_id="fsl.bet.run",
            passed=True,
            checks={
                "container_image": PreflightCheck("container_image", True, "OK"),
                "python_import": PreflightCheck("python_import", True, "not-required"),
            },
        )
        mock_preflight.return_value = {"fsl.bet.run": report}

        # Run selection
        candidates = select_tools("skull strip the brain")

        assert len(candidates) > 0
        assert candidates[0].tool.id == "fsl.bet.run"
        assert candidates[0].preflight_passed is True
        assert candidates[0].final_score > 0.0

    @patch("brain_researcher.services.agent.planner.selection.match_intents")
    def test_select_tools_no_intent_match(self, mock_intents):
        """Test that no intent matches returns empty list."""
        mock_intents.return_value = []

        candidates = select_tools("random nonsense text xyz123")
        assert candidates == []

    @patch("brain_researcher.services.agent.planner.selection.match_intents")
    @patch("brain_researcher.services.agent.planner.selection.search_by_capability")
    def test_select_tools_no_catalog_match(self, mock_search, mock_intents):
        """Test that no catalog matches returns empty list."""
        mock_intents.return_value = ["nonexistent_op"]
        mock_search.return_value = []

        candidates = select_tools("some query")
        assert candidates == []

    @patch("brain_researcher.services.agent.planner.selection.match_intents")
    @patch("brain_researcher.services.agent.planner.selection.search_by_capability")
    @patch("brain_researcher.services.agent.planner.selection.preflight_batch")
    def test_select_tools_preflight_filtering(
        self, mock_preflight, mock_search, mock_intents
    ):
        """Test that failed preflight checks are filtered out."""
        mock_intents.return_value = ["test_op"]

        # Create two tools
        tool1 = MockToolCapability(
            id="tool1",
            name="Tool 1",
            description="First tool",
            capabilities=("test_op",),
            runtime_kind="python",
        )
        tool2 = MockToolCapability(
            id="tool2",
            name="Tool 2",
            description="Second tool",
            capabilities=("test_op",),
            runtime_kind="python",
        )
        mock_search.return_value = [tool1, tool2]

        # Mock preflight: tool1 passes, tool2 fails
        mock_preflight.return_value = {
            "tool1": PreflightReport(tool_id="tool1", passed=True),
            "tool2": PreflightReport(tool_id="tool2", passed=False),
        }

        # Run with preflight filtering
        candidates = select_tools("test query", require_preflight_pass=True)

        assert len(candidates) == 1
        assert candidates[0].tool.id == "tool1"

    @patch("brain_researcher.services.agent.planner.selection.match_intents")
    @patch("brain_researcher.services.agent.planner.selection.search_by_capability")
    @patch("brain_researcher.services.agent.planner.selection.preflight_batch")
    def test_select_tools_max_results(self, mock_preflight, mock_search, mock_intents, monkeypatch):
        """Test that max_results limits output."""
        # Phase 1.4: Set strategy to diverse_topk to allow multiple results
        monkeypatch.setenv("BR_PLANNER_STRATEGY", "diverse_topk")

        mock_intents.return_value = ["test_op"]

        # Create 5 tools
        tools = [
            MockToolCapability(
                id=f"tool{i}",
                name=f"Tool {i}",
                description=f"Tool number {i}",
                capabilities=("test_op",),
                runtime_kind="python",
            )
            for i in range(5)
        ]
        mock_search.return_value = tools

        # Mock all pass preflight
        reports = {
            f"tool{i}": PreflightReport(tool_id=f"tool{i}", passed=True)
            for i in range(5)
        }
        mock_preflight.return_value = reports

        # Request max 3 results (diverse_topk default is k=3)
        candidates = select_tools("test query", max_results=3)

        assert len(candidates) == 3

    @patch("brain_researcher.services.agent.planner.selection.match_intents")
    @patch("brain_researcher.services.agent.planner.selection.search_by_capability")
    @patch("brain_researcher.services.agent.planner.selection.search_by_modality")
    @patch("brain_researcher.services.agent.planner.selection.preflight_batch")
    def test_select_tools_modality_filtering(
        self, mock_preflight, mock_search_mod, mock_search_cap, mock_intents
    ):
        """Test that modality filtering works."""
        mock_intents.return_value = ["test_op"]

        tool = MockToolCapability(
            id="fmri.tool",
            name="fMRI Tool",
            description="fMRI analysis tool",
            capabilities=("test_op",),
            runtime_kind="python",
        )

        mock_search_cap.return_value = [tool]
        mock_search_mod.return_value = [tool]

        mock_preflight.return_value = {
            "fmri.tool": PreflightReport(tool_id="fmri.tool", passed=True)
        }

        candidates = select_tools("test query", modality="fmri")

        # Should get results filtered by modality
        assert len(candidates) > 0


class TestExplainSelection:
    """Test selection explanation generation."""

    def test_explain_selection_format(self):
        """Test that explanation has expected format."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="A test tool",
            capabilities=("test",),
            runtime_kind="python",
        )

        candidate = SelectionCandidate(
            tool=tool,
            scoring_weights=load_scoring_weights(),
            intent_match_score=0.8,
            preflight_passed=True,
            preflight_detail={"check1": "passed", "check2": "not-required"},
            description_score=0.6,
            metadata_score=0.7,
        )

        # PR-3: Non-verbose mode doesn't include preflight details
        explanation = explain_selection(candidate, verbose=False)

        # Check key components are present
        assert "test.tool" in explanation
        assert "Test Tool" in explanation
        assert "Final Score:" in explanation
        assert "Intent Match:" in explanation
        assert "Preflight: PASSED" in explanation
        assert "Explanation:" in explanation  # PR-3 adds narrative explanation

        # PR-3: Use verbose mode to see preflight details
        verbose_explanation = explain_selection(candidate, verbose=True)
        assert "check1" in verbose_explanation
        assert "check2" in verbose_explanation

    def test_explain_selection_preflight_failed(self):
        """Test explanation for failed preflight."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
        )

        candidate = SelectionCandidate(
            tool=tool,
            scoring_weights=load_scoring_weights(),
            intent_match_score=0.8,
            preflight_passed=False,
            preflight_detail={"python_import": "import failed: No module named 'foo'"},
            description_score=0.6,
            metadata_score=0.7,
        )

        # PR-3: Verbose mode needed to see preflight details
        explanation = explain_selection(candidate, verbose=True)

        assert "Preflight: FAILED" in explanation
        assert "import failed" in explanation


class TestScoringEnhancements:
    """Test PR-3 scoring enhancements: resource fit, configurable weights, explanations."""

    def test_resource_fit_score_added_to_candidate(self):
        """Test that SelectionCandidate includes resource_fit_score."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
        )

        candidate = SelectionCandidate(
            tool=tool,
            scoring_weights=load_scoring_weights(),
            intent_match_score=0.8,
            preflight_passed=True,
            description_score=0.6,
            metadata_score=0.7,
            resource_fit_score=0.9,  # PR-3
        )

        assert hasattr(candidate, "resource_fit_score")
        assert candidate.resource_fit_score == 0.9

    def test_resource_fit_scoring_cvmfs_container(self):
        """Test resource fit scoring for CVMFS container tools."""
        from brain_researcher.services.agent.planner.selection import _score_resource_fit

        tool = MockToolCapability(
            id="fsl.bet.run",
            name="BET",
            description="Brain Extraction",
            capabilities=("skull_strip",),
            runtime_kind="container",
            container=MockContainer(image="/cvmfs/neurodesk.ardc.edu.au/fsl.sif"),
        )

        # Mock preflight report - CVMFS accessible
        from brain_researcher.services.agent.planner.preflight import PreflightStatus
        preflight = PreflightReport(
            tool_id="fsl.bet.run",
            passed=True,
            checks={
                "container_image": PreflightCheck(
                    "container_image", True, "CVMFS accessible", PreflightStatus.CVMFS_AVAILABLE
                ),
                "python_import": PreflightCheck(
                    "python_import", True, "not-required", PreflightStatus.NOT_REQUIRED
                ),
            },
        )

        score = _score_resource_fit(tool, preflight)

        # CVMFS container with good preflight should score high
        assert score >= 0.8

    def test_resource_fit_scoring_python_tool(self):
        """Test resource fit scoring for Python tools."""
        from brain_researcher.services.agent.planner.selection import _score_resource_fit

        tool = MockToolCapability(
            id="python.numpy.test",
            name="NumPy Test",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
            python=MockPython(module="numpy"),
        )

        # Mock preflight report - import successful
        from brain_researcher.services.agent.planner.preflight import PreflightStatus
        preflight = PreflightReport(
            tool_id="python.numpy.test",
            passed=True,
            checks={
                "container_image": PreflightCheck(
                    "container_image", True, "not-required", PreflightStatus.NOT_REQUIRED
                ),
                "python_import": PreflightCheck(
                    "python_import", True, "module imported successfully", PreflightStatus.IMPORT_SUCCESS
                ),
            },
        )

        score = _score_resource_fit(tool, preflight)

        # Python tool with successful import should score reasonably
        assert score > 0.3

    def test_resource_fit_scoring_unavailable(self):
        """Test resource fit scoring when resources unavailable."""
        from brain_researcher.services.agent.planner.selection import _score_resource_fit

        tool = MockToolCapability(
            id="missing.tool",
            name="Missing Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="container",
            container=MockContainer(image="/cvmfs/missing.sif"),
        )

        # Mock preflight report - CVMFS not mounted
        from brain_researcher.services.agent.planner.preflight import PreflightStatus
        preflight = PreflightReport(
            tool_id="missing.tool",
            passed=False,
            checks={
                "container_image": PreflightCheck(
                    "container_image", False, "CVMFS not mounted", PreflightStatus.NOT_AVAILABLE
                ),
                "python_import": PreflightCheck(
                    "python_import", True, "not-required", PreflightStatus.NOT_REQUIRED
                ),
            },
        )

        score = _score_resource_fit(tool, preflight)

        # Unavailable resources should give low score
        assert score < 0.5

    def test_configurable_weights_from_env(self):
        """Test that scoring weights can be overridden via environment."""
        import os

        # Set environment variable
        os.environ["BR_SCORE_WEIGHT_INTENT_MATCH"] = "0.50"
        os.environ["BR_SCORE_WEIGHT_PREFLIGHT"] = "0.20"

        try:
            clear_scoring_weights_cache()
            weights = load_scoring_weights()

            # Env vars should override defaults
            assert weights["intent_match"] == 0.50
            assert weights["preflight"] == 0.20

        finally:
            # Cleanup
            del os.environ["BR_SCORE_WEIGHT_INTENT_MATCH"]
            del os.environ["BR_SCORE_WEIGHT_PREFLIGHT"]
            clear_scoring_weights_cache()

    def test_five_factor_scoring(self):
        """Test that final score uses all 5 factors."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
        )

        weights = load_scoring_weights()
        candidate = SelectionCandidate(
            tool=tool,
            intent_match_score=1.0,
            preflight_passed=True,
            description_score=1.0,
            metadata_score=1.0,
            resource_fit_score=1.0,
            historical_quality_score=1.0,
            latency_score=1.0,
            scoring_weights=weights,
        )

        # All factors at 1.0 should sum to total weight
        expected = (
            weights["intent_match"]
            + weights["preflight"]
            + weights["description"]
            + weights["metadata"]
            + weights["resource_fit"]
            + weights.get("historical_quality", 0.0)
            + weights.get("latency_pred", 0.0)
        )
        assert abs(candidate.final_score - expected) < 0.01

    def test_explanation_generation(self):
        """Test that candidates generate narrative explanations."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
        )

        candidate = SelectionCandidate(
            tool=tool,
            scoring_weights=load_scoring_weights(),
            intent_match_score=0.9,  # High
            preflight_passed=True,
            description_score=0.7,
            metadata_score=0.6,
            resource_fit_score=0.85,  # High
        )

        # Should have generated explanation
        assert candidate.explanation != ""
        assert "match" in candidate.explanation.lower()
        assert "ready" in candidate.explanation.lower()

    def test_explanation_quality_levels(self):
        """Test that explanations reflect different quality levels."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
        )

        # High quality candidate
        high_candidate = SelectionCandidate(
            tool=tool,
            scoring_weights=load_scoring_weights(),
            intent_match_score=0.95,
            preflight_passed=True,
            resource_fit_score=0.90,
            description_score=0.8,
            metadata_score=0.7,
        )

        # Low quality candidate
        low_candidate = SelectionCandidate(
            tool=tool,
            scoring_weights=load_scoring_weights(),
            intent_match_score=0.3,
            preflight_passed=False,
            resource_fit_score=0.2,
            description_score=0.4,
            metadata_score=0.5,
        )

        # High quality should mention "excellent" or "good"
        assert "excellent" in high_candidate.explanation.lower() or "good" in high_candidate.explanation.lower()

        # Low quality should mention "partial" or "setup"
        assert "partial" in low_candidate.explanation.lower() or "setup" in low_candidate.explanation.lower()

    def test_explain_selection_includes_resource_fit(self):
        """Test that explain_selection output includes resource fit score."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
        )

        candidate = SelectionCandidate(
            tool=tool,
            scoring_weights=load_scoring_weights(),
            intent_match_score=0.8,
            preflight_passed=True,
            preflight_detail={"check1": "passed"},
            description_score=0.6,
            metadata_score=0.7,
            resource_fit_score=0.85,  # PR-3
        )

        explanation = explain_selection(candidate, verbose=False)

        # Should include resource fit in component scores
        assert "Resource Fit" in explanation
        assert "0.85" in explanation

        # Should include narrative explanation
        assert "Explanation:" in explanation

    def test_explain_selection_verbose_mode(self):
        """Test that verbose mode includes preflight details."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
        )

        candidate = SelectionCandidate(
            tool=tool,
            scoring_weights=load_scoring_weights(),
            intent_match_score=0.8,
            preflight_passed=True,
            preflight_detail={"python_import": "passed", "container_image": "not-required"},
            description_score=0.6,
            metadata_score=0.7,
            resource_fit_score=0.9,
        )

        # Non-verbose should not include preflight details
        brief = explain_selection(candidate, verbose=False)
        assert "python_import" not in brief

        # Verbose should include preflight details
        verbose = explain_selection(candidate, verbose=True)
        assert "Preflight Checks:" in verbose
        assert "python_import" in verbose


class TestConstraintFiltering:
    """Tests for apply_constraints helper."""

    def test_gpu_requirement_filters_cpu_tools(self):
        """gpu_required_if should drop tools without GPU resources."""
        class Resources:
            def __init__(self, gpu: bool):
                self.gpu = gpu

        gpu_tool = MockToolCapability(
            id="gpu.tool",
            name="GPU Tool",
            description="gpu",
            capabilities=("deep_denoise",),
            runtime_kind="python",
            resources=Resources(gpu=True),
        )
        cpu_tool = MockToolCapability(
            id="cpu.tool",
            name="CPU Tool",
            description="cpu",
            capabilities=("deep_denoise",),
            runtime_kind="python",
            resources=Resources(gpu=False),
        )
        weights = load_scoring_weights()
        candidates = [
            SelectionCandidate(
                tool=gpu_tool,
                intent_match_score=1.0,
                preflight_passed=True,
                description_score=0.5,
                metadata_score=0.5,
                resource_fit_score=0.5,
                scoring_weights=weights,
            ),
            SelectionCandidate(
                tool=cpu_tool,
                intent_match_score=1.0,
                preflight_passed=True,
                description_score=0.5,
                metadata_score=0.5,
                resource_fit_score=0.5,
                scoring_weights=weights,
            ),
        ]

        config = {
            "policy": {
                "constraints": {
                    "require_preflight": True,
                    "require_capability_match": "relaxed",
                    "require_container_availability": False,
                    "gpu_required_if": ["deep_denoise"],
                }
            }
        }

        filtered = apply_constraints(candidates, config, matched_operators=["deep_denoise"])
        assert len(filtered) == 1
        assert filtered[0].tool.id == "gpu.tool"

    def test_kg_constraints_filter_candidates(self):
        """KG-backed constraints should filter to KG-matching tool ids."""
        tool_keep = MockToolCapability(
            id="tool.keep",
            name="Keep Tool",
            description="keep",
            capabilities=("test",),
            runtime_kind="python",
        )
        tool_drop = MockToolCapability(
            id="tool.drop",
            name="Drop Tool",
            description="drop",
            capabilities=("test",),
            runtime_kind="python",
        )
        weights = load_scoring_weights()
        candidates = [
            SelectionCandidate(
                tool=tool_keep,
                intent_match_score=1.0,
                preflight_passed=True,
                description_score=0.5,
                metadata_score=0.5,
                resource_fit_score=0.5,
                scoring_weights=weights,
            ),
            SelectionCandidate(
                tool=tool_drop,
                intent_match_score=1.0,
                preflight_passed=True,
                description_score=0.5,
                metadata_score=0.5,
                resource_fit_score=0.5,
                scoring_weights=weights,
            ),
        ]

        config = {
            "policy": {
                "constraints": {
                    "require_preflight": True,
                    "require_capability_match": "relaxed",
                    "require_container_availability": False,
                    "use_kg_constraints": True,
                    "kg_modalities": ["fmri"],
                }
            }
        }

        with patch(
            "brain_researcher.services.agent.planner.selection.get_tool_ids_for_constraints"
        ) as mock_kg:
            mock_kg.return_value = {"tool.keep"}
            filtered = apply_constraints(
                candidates, config, matched_operators=["test"], modality="fmri"
            )
            assert len(filtered) == 1
            assert filtered[0].tool.id == "tool.keep"

    def test_weights_sum_validation(self):
        """Test that weight validation warns if sum != 1.0."""
        import os
        from brain_researcher.services.agent.planner.selection import load_scoring_weights
        import logging

        # Set weights that don't sum to 1.0
        os.environ["BR_SCORE_WEIGHT_INTENT_MATCH"] = "0.50"
        os.environ["BR_SCORE_WEIGHT_PREFLIGHT"] = "0.50"
        os.environ["BR_SCORE_WEIGHT_DESCRIPTION"] = "0.50"
        os.environ["BR_SCORE_WEIGHT_METADATA"] = "0.10"
        os.environ["BR_SCORE_WEIGHT_RESOURCE_FIT"] = "0.10"

        try:
            # Should load but log warning (sum = 1.7)
            with patch('brain_researcher.services.agent.planner.selection.logger') as mock_logger:
                clear_scoring_weights_cache()
                load_scoring_weights()
                mock_logger.warning.assert_called()
        finally:
            # Cleanup
            for key in ["BR_SCORE_WEIGHT_INTENT_MATCH", "BR_SCORE_WEIGHT_PREFLIGHT",
                        "BR_SCORE_WEIGHT_DESCRIPTION", "BR_SCORE_WEIGHT_METADATA",
                        "BR_SCORE_WEIGHT_RESOURCE_FIT"]:
                os.environ.pop(key, None)
            clear_scoring_weights_cache()


class TestPhase14HierarchicalOverrides:
    """Phase 1.4 overrides & strategy tests.

    Reference: docs/issues/09_move_planning_into_agent.md (lines 13-52)
    """

    def _setup_preflight(self, mock_preflight, reports):
        """Helper to configure preflight_batch mock with proper side_effect."""
        def _side_effect(tools, *_args, **_kwargs):
            return {tool.id: reports[tool.id] for tool in tools}
        mock_preflight.side_effect = _side_effect

    @patch("brain_researcher.services.agent.planner.selection.match_intents")
    @patch("brain_researcher.services.agent.planner.selection.preflight_batch")
    @patch("brain_researcher.services.agent.planner.selection.search_by_modality")
    @patch("brain_researcher.services.agent.planner.selection.search_by_capability")
    def test_modality_override_changes_ranking(
        self,
        mock_search_capability,
        mock_search_modality,
        mock_preflight,
        mock_match,
    ):
        """Test that modality-specific overrides change tool ranking.

        Task 4.1: Verify that setting modality="fmri" applies fMRI overrides
        from scoring_weights.yaml and changes which tool is selected.
        """
        tool_a = MockToolCapability(
            id="nilearn.glm",
            name="Nilearn GLM",
            description="Fast GLM helper",
            capabilities=("fmri_glm",),
            runtime_kind="python",
            documentation="https://nilearn",
            metadata=MockMetadata(literature=("nilearn",), urls=("https://nilearn",)),
            resources=MockResources(time_min_default=3.0),
            source="catalog",
        )
        tool_b = MockToolCapability(
            id="fsl.feat",
            name="FSL FEAT",
            description="Comprehensive fMRI analysis pipeline with documentation",
            capabilities=("fmri_glm",),
            runtime_kind="container",
            container=MockContainer(image="fsl:6.0.7"),
            documentation="https://fsl",
            metadata=MockMetadata(),
            resources=MockResources(time_min_default=40.0),
        )

        mock_match.return_value = ["fmri_glm"]
        mock_search_capability.return_value = [tool_a, tool_b]
        mock_search_modality.return_value = [tool_a, tool_b]
        reports = {
            "nilearn.glm": PreflightReport(
                "nilearn.glm",
                True,
                {
                    "container_image": PreflightCheck(
                        "container_image", True, status_code=PreflightStatus.NOT_REQUIRED
                    ),
                    "python_import": PreflightCheck(
                        "python_import", True, status_code=PreflightStatus.IMPORT_SUCCESS
                    ),
                },
            ),
            "fsl.feat": PreflightReport(
                "fsl.feat",
                True,
                {
                    "container_image": PreflightCheck(
                        "container_image", False, status_code=PreflightStatus.NOT_AVAILABLE
                    ),
                    "python_import": PreflightCheck(
                        "python_import", False, status_code=PreflightStatus.NOT_REQUIRED
                    ),
                },
            ),
        }
        self._setup_preflight(mock_preflight, reports)

        base = select_tools("run fMRI GLM analysis")
        fmri = select_tools("run fMRI GLM analysis", modality="fmri")

        assert len(base) == 1
        assert len(fmri) == 1
        assert base[0].tool.id == "nilearn.glm"
        assert fmri[0].tool.id == "fsl.feat"

    @patch("brain_researcher.services.agent.planner.selection.match_intents")
    @patch("brain_researcher.services.agent.planner.selection.preflight_batch")
    @patch("brain_researcher.services.agent.planner.selection.search_by_modality")
    @patch("brain_researcher.services.agent.planner.selection.search_by_capability")
    def test_environment_override_changes_ranking(
        self,
        mock_search_capability,
        mock_search_modality,
        mock_preflight,
        mock_match,
    ):
        """Test that environment-specific overrides change tool ranking.

        Task 4.2: Verify that environment="local" vs "cloud" applies different
        weights and changes ranking.
        """
        tool_local = MockToolCapability(
            id="local.fast",
            name="Local Fast Tool",
            description="Optimized for local execution",
            capabilities=("analyze",),
            runtime_kind="python",
            metadata=MockMetadata(),
            resources=MockResources(time_min_default=3.0),
        )
        tool_cloud = MockToolCapability(
            id="cloud.scalable",
            name="Cloud Scalable Tool",
            description="Cloud-optimized with auto-scaling",
            capabilities=("analyze",),
            runtime_kind="container",
            container=MockContainer(image="cloud:latest"),
            documentation="https://cloud",
            metadata=MockMetadata(literature=("cloud",), urls=("https://cloud",)),
            resources=MockResources(time_min_default=40.0),
            source="catalog",
        )

        mock_match.return_value = ["analyze"]
        mock_search_capability.return_value = [tool_local, tool_cloud]
        mock_search_modality.return_value = [tool_local, tool_cloud]
        reports = {
            "local.fast": PreflightReport(
                "local.fast",
                True,
                {
                    "container_image": PreflightCheck(
                        "container_image", True, status_code=PreflightStatus.NOT_REQUIRED
                    ),
                    "python_import": PreflightCheck(
                        "python_import", True, status_code=PreflightStatus.IMPORT_SUCCESS
                    ),
                },
            ),
            "cloud.scalable": PreflightReport(
                "cloud.scalable",
                True,
                {
                    "container_image": PreflightCheck(
                        "container_image", True, status_code=PreflightStatus.LOCAL_AVAILABLE
                    ),
                    "python_import": PreflightCheck(
                        "python_import", True, status_code=PreflightStatus.NOT_REQUIRED
                    ),
                },
            ),
        }
        self._setup_preflight(mock_preflight, reports)

        result_local = select_tools("analyze data", environment="local")
        result_cloud = select_tools("analyze data", environment="cloud")

        assert len(result_local) > 0
        assert len(result_cloud) > 0
        assert result_local[0].tool.id == "local.fast"
        assert result_cloud[0].tool.id == "cloud.scalable"

    @patch("brain_researcher.services.agent.planner.selection.match_intents")
    @patch("brain_researcher.services.agent.planner.selection.preflight_batch")
    @patch("brain_researcher.services.agent.planner.selection.search_by_modality")
    @patch("brain_researcher.services.agent.planner.selection.search_by_capability")
    def test_feature_toggle_env_var_affects_score(
        self,
        mock_search_capability,
        mock_search_modality,
        mock_preflight,
        mock_match,
    ):
        """Test that BR_SCORE_WEIGHT_* env vars override YAML config.

        Task 4.3: Verify that setting BR_SCORE_WEIGHT_LATENCY_PRED changes
        the final score when latency values differ.
        """
        import os

        tool_fast = MockToolCapability(
            id="fast.tool",
            name="Fast Tool",
            description="Quick execution",
            capabilities=("process",),
            runtime_kind="python",
            resources=MockResources(time_min_default=2.0),  # Fast: 2 min
        )
        tool_slow = MockToolCapability(
            id="slow.tool",
            name="Slow Tool",
            description="Thorough processing",
            capabilities=("process",),
            runtime_kind="python",
            resources=MockResources(time_min_default=45.0),  # Slow: 45 min
        )

        mock_match.return_value = ["process"]
        mock_search_capability.return_value = [tool_fast, tool_slow]
        mock_search_modality.return_value = [tool_fast, tool_slow]
        reports = {
            "fast.tool": PreflightReport("fast.tool", True, {}),
            "slow.tool": PreflightReport("slow.tool", True, {}),
        }
        self._setup_preflight(mock_preflight, reports)

        clear_scoring_weights_cache()
        try:
            # Set high latency weight via env var
            os.environ["BR_SCORE_WEIGHT_LATENCY_PRED"] = "0.8"
            os.environ["BR_SCORE_WEIGHT_INTENT_MATCH"] = "0.2"
            os.environ["BR_SCORE_WEIGHT_PREFLIGHT"] = "0.0"
            os.environ["BR_SCORE_WEIGHT_DESCRIPTION"] = "0.0"
            os.environ["BR_SCORE_WEIGHT_METADATA"] = "0.0"
            os.environ["BR_SCORE_WEIGHT_RESOURCE_FIT"] = "0.0"
            os.environ["BR_SCORE_WEIGHT_HISTORICAL_QUALITY"] = "0.0"

            clear_scoring_weights_cache()
            result = select_tools("process data")

            assert len(result) > 0
            # Latency weight is 0.8, fast tool (2 min) should rank higher than slow tool (45 min)
            assert result[0].tool.id == "fast.tool"

        finally:
            # Cleanup
            for key in ["BR_SCORE_WEIGHT_LATENCY_PRED", "BR_SCORE_WEIGHT_INTENT_MATCH",
                        "BR_SCORE_WEIGHT_PREFLIGHT", "BR_SCORE_WEIGHT_DESCRIPTION",
                        "BR_SCORE_WEIGHT_METADATA", "BR_SCORE_WEIGHT_RESOURCE_FIT",
                        "BR_SCORE_WEIGHT_HISTORICAL_QUALITY"]:
                os.environ.pop(key, None)
            clear_scoring_weights_cache()

    @patch("brain_researcher.services.agent.planner.selection.match_intents")
    @patch("brain_researcher.services.agent.planner.selection.preflight_batch")
    @patch("brain_researcher.services.agent.planner.selection.search_by_modality")
    @patch("brain_researcher.services.agent.planner.selection.search_by_capability")
    @patch("brain_researcher.services.agent.planner.selection.load_hierarchical_config")
    def test_gpu_constraint_integration_end_to_end(
        self,
        mock_load_config,
        mock_search_capability,
        mock_search_modality,
        mock_preflight,
        mock_match,
    ):
        """Test GPU constraint filtering through full select_tools() flow.

        Task 4.4: End-to-end test verifying gpu_required_if constraint
        filters to only GPU-capable tools.
        """
        # Create GPU-capable and CPU-only tools with resources
        @dataclass(frozen=True)
        class MockResources:
            gpu: bool = False
            cpu_cores: int = 1

        gpu_tool = MockToolCapability(
            id="gpu.denoise",
            name="GPU Denoiser",
            description="GPU-accelerated denoising",
            capabilities=("deep_denoise",),
            runtime_kind="container",
            container=MockContainer(image="gpu:latest"),
            resources=MockResources(gpu=True, cpu_cores=4),
        )

        cpu_tool = MockToolCapability(
            id="cpu.denoise",
            name="CPU Denoiser",
            description="CPU-based denoising",
            capabilities=("deep_denoise",),
            runtime_kind="python",
            resources=MockResources(gpu=False, cpu_cores=1),
        )

        mock_match.return_value = ["deep_denoise"]
        mock_search_capability.return_value = [gpu_tool, cpu_tool]
        mock_search_modality.return_value = [gpu_tool, cpu_tool]
        reports = {
            "gpu.denoise": PreflightReport("gpu.denoise", True, {}),
            "cpu.denoise": PreflightReport("cpu.denoise", True, {}),
        }
        self._setup_preflight(mock_preflight, reports)

        # Mock config with GPU constraint
        mock_load_config.return_value = {
            "policy": {
                "constraints": {
                    "gpu_required_if": ["deep_denoise"],
                },
                "scoring": {"weights": {}, "features": {}},
                "strategies": {},
            }
        }

        result = select_tools("deep denoise image")

        # Should return only GPU-capable tool
        assert len(result) == 1
        assert result[0].tool.id == "gpu.denoise", \
            "GPU constraint should filter to only GPU-capable tools"
        assert result[0].tool.resources.gpu is True


def test_budget_constraint_masks_reason():
    """Budget constraint should drop over-budget tools and record structured reason."""
    expensive_tool = SimpleNamespace(
        id="pkg.expensive",
        name="pkg.expensive",
        package="pkg",
        runtime_kind="container",
        capabilities=[],
        resources=SimpleNamespace(gpu=False),
        pricing=SimpleNamespace(estimated_cost_usd=25.0),
    )
    weights = {"intent_match": 1.0, "description": 0.0, "metadata": 0.0, "resource_fit": 0.0}
    cand = SelectionCandidate(
        tool=expensive_tool,
        intent_match_score=1.0,
        preflight_passed=True,
        preflight_detail={},
        description_score=0.5,
        metadata_score=0.5,
        resource_fit_score=0.5,
        scoring_weights=weights,
    )

    config = {"policy": {"constraints": {"max_cost_usd": 10.0}}}
    kept, removed, mask_reasons = apply_constraints(
        [cand], config, matched_operators=[], return_unavailable=True
    )
    assert kept == []
    assert len(removed) == 1
    reason = removed[0].reasons[-1]
    assert reason["code"] == "BUDGET_EXCEEDED"
    assert "cost" in (reason.get("detail") or "")
    assert mask_reasons and mask_reasons[-1].code == "BUDGET_EXCEEDED"


def test_intent_router_emits_mask_reason_when_no_intent(monkeypatch):
    """Intent router should emit a violation when no intent matches."""
    from brain_researcher.services.agent.planner import selection as selection_mod
    from brain_researcher.services.shared.planner.models import PlanRequest

    monkeypatch.setattr(selection_mod, "plan_operations", lambda req: [])

    mask_reasons = []
    req = PlanRequest(pipeline="nonsense pipeline", domain="neuroimaging", modality=["fmri"])
    plan = selection_mod.choose_tool_intent_router(req, mask_reasons_out=mask_reasons)

    assert plan is None
    assert mask_reasons
    assert mask_reasons[0].code == "INTENT_UNMAPPED"
