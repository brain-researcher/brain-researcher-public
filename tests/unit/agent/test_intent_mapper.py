"""
Unit tests for intent_mapper (planner with preflight integration).

Tests cover:
- Tool selection with passing preflight
- Tool selection with failing preflight
- Fallback to best scoring tool when all fail
- Proper tracing and provenance
"""

import pytest
from unittest.mock import patch, MagicMock

from brain_researcher.services.agent.planner.intent_mapper import (
    choose_tool,
    CandidateResult,
    PlanResult,
)
from brain_researcher.services.agent.tool_index import ToolEntry, ToolIndex
from brain_researcher.services.agent.preflight import PreflightReport, PreflightItem


@pytest.fixture
def sample_tools():
    """Create sample tool entries."""
    return [
        ToolEntry(
            id="fsl.bet",
            name="bet",
            description="Brain extraction tool",
            tags=["skull-strip"],
            image="/cvmfs/fsl/bet.simg",
        ),
        ToolEntry(
            id="afni.3dSkullStrip",
            name="3dSkullStrip",
            description="AFNI skull stripping",
            tags=["skull-strip"],
            image="/cvmfs/afni/3dSkullStrip.simg",
        ),
    ]


@pytest.fixture
def mock_tool_index(sample_tools):
    """Mock the get_tool_index function."""
    with patch("brain_researcher.services.agent.planner.intent_mapper.get_tool_index") as mock:
        index = ToolIndex(sample_tools)
        mock.return_value = index
        yield mock


@pytest.fixture
def mock_niwrap_containers():
    """Mock the load_niwrap_containers function."""
    with patch("brain_researcher.services.agent.planner.intent_mapper.load_niwrap_containers") as mock:
        mock.return_value = {
            "bet": {"image": "/cvmfs/fsl/bet.simg"},
            "3dSkullStrip": {"image": "/cvmfs/afni/3dSkullStrip.simg"},
        }
        yield mock


def test_choose_tool_with_passing_preflight(mock_tool_index, mock_niwrap_containers):
    """Test that choose_tool selects first tool with passing preflight."""

    # Mock preflight to pass for BET
    with patch("brain_researcher.services.agent.planner.intent_mapper.run_preflight") as mock_preflight:
        mock_preflight.return_value = PreflightReport(
            blockers=[],
            warnings=[],
        )

        result = choose_tool("skull strip")

        # Should return a result
        assert isinstance(result, PlanResult)
        assert result.intent == "skull strip"
        assert len(result.candidates) > 0

        # Chosen tool should be the first one with passing preflight
        assert result.chosen is not None
        assert result.chosen.preflight_ok is True
        assert result.chosen.tool_id in ["fsl.bet", "afni.3dSkullStrip"]


def test_choose_tool_with_failing_preflight(mock_tool_index, mock_niwrap_containers):
    """Test that choose_tool tries next tool when preflight fails."""

    def preflight_side_effect(tool_name, params, image_path):
        # Fail for BET, pass for 3dSkullStrip
        if "bet" in tool_name.lower() or (image_path and "bet" in image_path.lower()):
            return PreflightReport(
                blockers=[
                    PreflightItem(
                        check="disk_space",
                        ok=False,
                        details={"reason": "Not enough disk space"},
                    )
                ],
                warnings=[],
            )
        else:
            return PreflightReport(
                blockers=[],
                warnings=[],
            )

    with patch("brain_researcher.services.agent.planner.intent_mapper.run_preflight") as mock_preflight:
        mock_preflight.side_effect = preflight_side_effect

        result = choose_tool("skull strip")

        # Should select the tool that passed preflight (3dSkullStrip)
        assert result.chosen is not None
        assert result.chosen.preflight_ok is True
        # The chosen tool should not be BET (which failed)
        assert "bet" not in result.chosen.tool_id.lower()


def test_choose_tool_all_fail_preflight(mock_tool_index, mock_niwrap_containers):
    """Test fallback when all tools fail preflight."""

    with patch("brain_researcher.services.agent.planner.intent_mapper.run_preflight") as mock_preflight:
        # All preflights fail
        mock_preflight.return_value = PreflightReport(
            blockers=[
                PreflightItem(
                    check="disk_space",
                    ok=False,
                    details={"reason": "Not enough disk space"},
                )
            ],
            warnings=[],
        )

        result = choose_tool("skull strip")

        # Should still choose the best scoring tool
        assert result.chosen is not None
        assert result.chosen.preflight_ok is False
        assert "Preflight failed" in result.chosen.reason or "blockers" in result.chosen.reason


def test_choose_tool_no_image_configured(mock_tool_index):
    """Test handling when container image is not configured."""

    # Mock empty niwrap containers
    with patch("brain_researcher.services.agent.planner.intent_mapper.load_niwrap_containers") as mock:
        mock.return_value = {}

        result = choose_tool("skull strip")

        # Should return candidates but mark them as failed
        assert len(result.candidates) > 0
        for candidate in result.candidates:
            assert candidate.preflight_ok is False
            assert "Container image not configured" in candidate.reason


def test_choose_tool_with_constraints(mock_tool_index, mock_niwrap_containers):
    """Test that constraints are passed to preflight."""

    constraints = {"input_file": "/data/brain.nii.gz"}

    with patch("brain_researcher.services.agent.planner.intent_mapper.run_preflight") as mock_preflight:
        mock_preflight.return_value = PreflightReport(
            blockers=[],
            warnings=[],
        )

        result = choose_tool("skull strip", constraints=constraints)

        # Verify preflight was called with constraints
        assert mock_preflight.called
        call_args = mock_preflight.call_args
        assert call_args[1]["params"] == constraints

        # Result should include constraints
        assert result.constraints == constraints


def test_choose_tool_trace_includes_all_candidates(mock_tool_index, mock_niwrap_containers):
    """Test that trace includes all evaluated candidates."""

    with patch("brain_researcher.services.agent.planner.intent_mapper.run_preflight") as mock_preflight:
        mock_preflight.return_value = PreflightReport(
            blockers=[],
            warnings=[],
        )

        result = choose_tool("skull strip", k=5)

        # Trace should include multiple candidates
        assert len(result.candidates) >= 2

        # Each candidate should have required fields
        for candidate in result.candidates:
            assert candidate.tool_id
            assert candidate.tool_name
            assert candidate.score >= 0
            assert candidate.reason


def test_choose_tool_preflight_report_stored(mock_tool_index, mock_niwrap_containers):
    """Test that preflight reports are stored in candidates."""

    with patch("brain_researcher.services.agent.planner.intent_mapper.run_preflight") as mock_preflight:
        preflight_report = PreflightReport(
            blockers=[],
            warnings=[
                PreflightItem(
                    check="cvmfs_mount",
                    ok=False,
                    details={"message": "CVMFS not detected"},
                )
            ],
            disk_free_gb=50.0,
        )
        mock_preflight.return_value = preflight_report

        result = choose_tool("skull strip")

        # Chosen candidate should include preflight report
        assert result.chosen is not None
        assert result.chosen.preflight_report is not None
        assert "disk_free_gb" in result.chosen.preflight_report


def test_choose_tool_no_results(mock_tool_index, mock_niwrap_containers):
    """Test handling when search returns no results."""

    # Mock empty search results
    with patch.object(ToolIndex, "search") as mock_search:
        mock_search.return_value = []

        result = choose_tool("quantum computing")

        # Should return empty candidates
        assert len(result.candidates) == 0
        assert result.chosen is None


def test_choose_tool_preflight_exception_handling(mock_tool_index, mock_niwrap_containers):
    """Test that preflight exceptions are handled gracefully."""

    with patch("brain_researcher.services.agent.planner.intent_mapper.run_preflight") as mock_preflight:
        # Preflight raises exception
        mock_preflight.side_effect = Exception("Preflight crashed")

        result = choose_tool("skull strip")

        # Should still return candidates marked as failed
        assert len(result.candidates) > 0
        for candidate in result.candidates:
            assert candidate.preflight_ok is False
            assert "error" in candidate.reason.lower() or "crashed" in candidate.reason.lower()


def test_candidate_result_model():
    """Test CandidateResult model validation."""
    candidate = CandidateResult(
        tool_id="fsl.bet",
        tool_name="bet",
        score=0.85,
        image="/cvmfs/fsl/bet.simg",
        preflight_ok=True,
        reason="All checks passed",
    )

    assert candidate.tool_id == "fsl.bet"
    assert candidate.score == 0.85
    assert candidate.preflight_ok is True

    # Should be JSON serializable
    json_data = candidate.model_dump()
    assert json_data["tool_id"] == "fsl.bet"


def test_plan_result_model():
    """Test PlanResult model validation."""
    candidate = CandidateResult(
        tool_id="fsl.bet",
        tool_name="bet",
        score=0.85,
        preflight_ok=True,
        reason="All checks passed",
    )

    plan = PlanResult(
        intent="skull strip",
        candidates=[candidate],
        chosen=candidate,
        plan_id="test-plan-123",
        constraints={"input": "/data/brain.nii.gz"},
    )

    assert plan.intent == "skull strip"
    assert len(plan.candidates) == 1
    assert plan.chosen == candidate
    assert plan.plan_id == "test-plan-123"

    # Should be JSON serializable
    json_data = plan.model_dump()
    assert json_data["intent"] == "skull strip"
    assert json_data["plan_id"] == "test-plan-123"


# ===== Comprehensive Tests for _resolve_image_path() =====


from brain_researcher.services.agent.planner.intent_mapper import _resolve_image_path


def test_resolve_image_path_exact_match():
    """Test exact tool_name match in container info."""
    with patch("brain_researcher.services.agent.planner.intent_mapper.load_niwrap_containers") as mock:
        mock.return_value = {
            "bet": {"image": "/cvmfs/fsl/bet.simg"},
            "3dSkullStrip": {"image": "/cvmfs/afni/3dSkullStrip.simg"},
        }

        result = _resolve_image_path("fsl.bet", "bet")
        assert result == "/cvmfs/fsl/bet.simg"


def test_resolve_image_path_category_prefix_stripping():
    """Test that category prefix is stripped for matching."""
    with patch("brain_researcher.services.agent.planner.intent_mapper.load_niwrap_containers") as mock:
        mock.return_value = {
            "bet": {"image": "/cvmfs/fsl/bet.simg"},
        }

        # Tool ID has category prefix, should still match
        result = _resolve_image_path("skull-strip.bet", "bet")
        assert result == "/cvmfs/fsl/bet.simg"


def test_resolve_image_path_tool_family_matching():
    """Test tool family matching for versioned tools."""
    with patch("brain_researcher.services.agent.planner.intent_mapper.load_niwrap_containers") as mock:
        mock.return_value = {
            "fsl": {"image": "/cvmfs/fsl/fsl.simg"},
        }

        # Query for versioned tool, should match family
        result = _resolve_image_path("fsl.bet.v2.1", "fsl.bet.v2.1")
        assert result == "/cvmfs/fsl/fsl.simg"


def test_resolve_image_path_not_found():
    """Test that None is returned when no match is found."""
    with patch("brain_researcher.services.agent.planner.intent_mapper.load_niwrap_containers") as mock:
        mock.return_value = {
            "bet": {"image": "/cvmfs/fsl/bet.simg"},
        }

        result = _resolve_image_path("unknown.tool", "unknown")
        assert result is None


def test_resolve_image_path_non_dict_container_info():
    """Test handling of container_info as string instead of dict."""
    with patch("brain_researcher.services.agent.planner.intent_mapper.load_niwrap_containers") as mock:
        mock.return_value = {
            "bet": "/cvmfs/fsl/bet.simg",  # String instead of dict
        }

        result = _resolve_image_path("fsl.bet", "bet")
        # Function should handle non-dict gracefully (returns None)
        assert result is None


def test_resolve_image_path_empty_image_field():
    """Test handling of dict with empty or missing image field."""
    with patch("brain_researcher.services.agent.planner.intent_mapper.load_niwrap_containers") as mock:
        mock.return_value = {
            "bet": {"image": ""},
            "3dSkullStrip": {"other_field": "value"},  # No image field
        }

        result1 = _resolve_image_path("fsl.bet", "bet")
        assert result1 is None or result1 == ""

        result2 = _resolve_image_path("afni.3dSkullStrip", "3dSkullStrip")
        assert result2 is None


def test_resolve_image_path_dots_in_toolname():
    """Test handling of tools with multiple dots in name."""
    with patch("brain_researcher.services.agent.planner.intent_mapper.load_niwrap_containers") as mock:
        mock.return_value = {
            "fsl": {"image": "/cvmfs/fsl/fsl.simg"},
            "bet": {"image": "/cvmfs/fsl/bet.simg"},
        }

        result = _resolve_image_path("fsl.bet.v2", "fsl.bet.v2")
        # Should match "fsl" or "bet" via family matching
        assert result in ["/cvmfs/fsl/fsl.simg", "/cvmfs/fsl/bet.simg"]


def test_resolve_image_path_multiple_strategies():
    """Test that all matching strategies are tried in sequence."""
    with patch("brain_researcher.services.agent.planner.intent_mapper.load_niwrap_containers") as mock:
        mock.return_value = {
            "bet": {"image": "/cvmfs/fsl/bet.simg"},
        }

        # Should try exact match first, then category stripping, then family matching
        result = _resolve_image_path("skull-strip.bet", "bet")
        assert result == "/cvmfs/fsl/bet.simg"


# ===== Additional Edge Cases for choose_tool() =====


def test_choose_tool_k_equals_zero(mock_tool_index, mock_niwrap_containers):
    """Test that k=0 returns empty candidates."""
    result = choose_tool("skull strip", k=0)

    assert len(result.candidates) == 0
    assert result.chosen is None


@pytest.mark.parametrize("k_value", [1, 5, 100])
def test_choose_tool_k_variations(mock_tool_index, mock_niwrap_containers, k_value):
    """Test different k values."""
    with patch("brain_researcher.services.agent.planner.intent_mapper.run_preflight") as mock_preflight:
        mock_preflight.return_value = PreflightReport(blockers=[], warnings=[])

        result = choose_tool("skull strip", k=k_value)

        # Should not return more candidates than available tools
        assert len(result.candidates) <= k_value
        assert len(result.candidates) <= 2  # We only have 2 sample tools


def test_choose_tool_empty_constraints_handling(mock_tool_index, mock_niwrap_containers):
    """Test that empty constraints dict and None are handled equivalently."""
    with patch("brain_researcher.services.agent.planner.intent_mapper.run_preflight") as mock_preflight:
        mock_preflight.return_value = PreflightReport(blockers=[], warnings=[])

        result1 = choose_tool("skull strip", constraints=None)
        result2 = choose_tool("skull strip", constraints={})

        # Both should succeed
        assert result1.chosen is not None
        assert result2.chosen is not None


def test_choose_tool_duplicate_scores():
    """Test handling when multiple tools have identical scores."""
    # Create a ToolIndex with tools that will match the search term
    tools = [
        ToolEntry(id="tool1", name="tool1", description="Test tool 1 for testing", tags=["test"]),
        ToolEntry(id="tool2", name="tool2", description="Test tool 2 for testing", tags=["test"]),
    ]

    with patch("brain_researcher.services.agent.planner.intent_mapper.get_tool_index") as mock_index:
        index = ToolIndex(tools)
        mock_index.return_value = index

        with patch("brain_researcher.services.agent.planner.intent_mapper.load_niwrap_containers") as mock_containers:
            mock_containers.return_value = {
                "tool1": {"image": "/cvmfs/tool1.simg"},
                "tool2": {"image": "/cvmfs/tool2.simg"},
            }

            with patch("brain_researcher.services.agent.planner.intent_mapper.run_preflight") as mock_preflight:
                mock_preflight.return_value = PreflightReport(blockers=[], warnings=[])

                result = choose_tool("test tool", k=2)

                # Should have at least one candidate
                assert len(result.candidates) >= 1
                # Should choose one of them
                assert result.chosen is not None


def test_choose_tool_preflight_with_warnings_but_passing(mock_tool_index, mock_niwrap_containers):
    """Test that tool with warnings but no blockers is still chosen."""
    with patch("brain_researcher.services.agent.planner.intent_mapper.run_preflight") as mock_preflight:
        mock_preflight.return_value = PreflightReport(
            blockers=[],
            warnings=[
                PreflightItem(
                    check="cvmfs_mount",
                    ok=False,
                    details={"message": "CVMFS not detected, using fallback"},
                )
            ],
        )

        result = choose_tool("skull strip")

        # Should still be marked as passing (warnings don't block)
        assert result.chosen is not None
        assert result.chosen.preflight_ok is True
        assert result.chosen.preflight_report is not None


def test_choose_tool_single_candidate(mock_tool_index, mock_niwrap_containers):
    """Test behavior with k=1 to get only single candidate."""
    with patch("brain_researcher.services.agent.planner.intent_mapper.run_preflight") as mock_preflight:
        mock_preflight.return_value = PreflightReport(blockers=[], warnings=[])

        result = choose_tool("skull strip", k=1)

        # Should return exactly 1 candidate
        assert len(result.candidates) == 1
        assert result.chosen is not None


def test_choose_tool_mixed_failures(mock_tool_index):
    """Test mix of image missing and preflight failures."""
    # Mock partial container info (only one tool has image)
    with patch("brain_researcher.services.agent.planner.intent_mapper.load_niwrap_containers") as mock_containers:
        mock_containers.return_value = {
            "bet": {"image": "/cvmfs/fsl/bet.simg"},
            # 3dSkullStrip missing
        }

        with patch("brain_researcher.services.agent.planner.intent_mapper.run_preflight") as mock_preflight:
            # BET preflight fails
            mock_preflight.return_value = PreflightReport(
                blockers=[
                    PreflightItem(check="disk_space", ok=False, details={"reason": "No space"})
                ],
                warnings=[],
            )

            result = choose_tool("skull strip", k=5)

            # Should have candidates with different failure reasons
            assert len(result.candidates) >= 2
            reasons = [c.reason for c in result.candidates]
            # One should mention image, one should mention preflight
            assert any("image" in r.lower() or "container" in r.lower() for r in reasons)
            assert any("preflight" in r.lower() or "blocker" in r.lower() for r in reasons)


def test_choose_tool_logging_output(mock_tool_index, mock_niwrap_containers, caplog):
    """Test that appropriate log messages are generated."""
    import logging

    caplog.set_level(logging.INFO)

    with patch("brain_researcher.services.agent.planner.intent_mapper.run_preflight") as mock_preflight:
        mock_preflight.return_value = PreflightReport(blockers=[], warnings=[])

        result = choose_tool("skull strip", k=2)

        # Should have logged search and preflight activities
        assert any("intent=" in record.message or "skull strip" in record.message for record in caplog.records)


# ===== Model Serialization Tests =====


def test_candidate_result_full_serialization():
    """Test CandidateResult with all fields populated."""
    candidate = CandidateResult(
        tool_id="fsl.bet",
        tool_name="bet",
        score=0.92,
        image="/cvmfs/fsl/bet.simg",
        preflight_ok=True,
        reason="All checks passed successfully",
        preflight_report={"disk_free_gb": 100.5, "blockers": [], "warnings": []},
    )

    # JSON round-trip
    json_data = candidate.model_dump()
    restored = CandidateResult(**json_data)

    assert restored.tool_id == candidate.tool_id
    assert restored.score == candidate.score
    assert restored.preflight_ok == candidate.preflight_ok
    assert restored.preflight_report == candidate.preflight_report


def test_candidate_result_with_nested_preflight():
    """Test CandidateResult with complex PreflightReport."""
    complex_report = {
        "blockers": [
            {"check": "disk_space", "ok": False, "details": {"free_gb": 1.5, "required_gb": 10.0}}
        ],
        "warnings": [
            {"check": "cvmfs_mount", "ok": False, "details": {"message": "CVMFS unavailable"}}
        ],
        "disk_free_gb": 1.5,
        "memory_free_gb": 8.0,
    }

    candidate = CandidateResult(
        tool_id="test.tool",
        tool_name="test",
        score=0.5,
        preflight_ok=False,
        reason="Disk space insufficient",
        preflight_report=complex_report,
    )

    # Should serialize nested structures
    json_data = candidate.model_dump()
    assert "blockers" in json_data["preflight_report"]
    assert len(json_data["preflight_report"]["blockers"]) == 1


def test_plan_result_json_roundtrip():
    """Test PlanResult JSON serialization and deserialization."""
    candidates = [
        CandidateResult(
            tool_id=f"tool_{i}",
            tool_name=f"Tool {i}",
            score=0.9 - i * 0.1,
            preflight_ok=i == 0,
            reason=f"Reason {i}",
        )
        for i in range(3)
    ]

    plan = PlanResult(
        intent="test intent",
        candidates=candidates,
        chosen=candidates[0],
        plan_id="plan-xyz",
        constraints={"input": "/data/test.nii.gz", "threshold": 0.5},
    )

    # Serialize and deserialize
    json_data = plan.model_dump()
    restored = PlanResult(**json_data)

    assert restored.intent == plan.intent
    assert len(restored.candidates) == len(plan.candidates)
    assert restored.chosen.tool_id == plan.chosen.tool_id
    assert restored.constraints == plan.constraints


def test_plan_result_validation_invalid_data():
    """Test that PlanResult raises ValidationError for invalid data."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        # Missing required field 'intent'
        PlanResult(candidates=[], chosen=None)


def test_candidate_result_score_bounds():
    """Test that scores are properly validated."""
    # Valid score
    candidate = CandidateResult(
        tool_id="test",
        tool_name="test",
        score=0.75,
        preflight_ok=True,
        reason="OK",
    )
    assert 0.0 <= candidate.score <= 1.0

    # Score can be > 1.0 for some scoring methods
    candidate2 = CandidateResult(
        tool_id="test",
        tool_name="test",
        score=1.5,
        preflight_ok=True,
        reason="OK",
    )
    assert candidate2.score == 1.5
