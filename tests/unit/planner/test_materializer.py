"""Tests for plan materializer (PR-3)."""

import pytest
from dataclasses import dataclass
from typing import Optional
from unittest.mock import Mock

from brain_researcher.services.agent.planner.materializer import (
    materialize_simple_plan,
    materialize_plan_with_alternatives,
    create_plan_preview,
    materialize_multi_step_plan,
    convert_candidate_to_plan,
)
from brain_researcher.services.agent.planner.selection import (
    SelectionCandidate,
    load_scoring_weights,
)

# Import shared test helpers
from .helpers import (
    MockContainer,
    MockPython,
    MockToolCapability,
)


class TestMaterializeSimplePlan:
    """Test single-step plan materialization."""

    def test_simple_plan_creation(self):
        """Test creating a simple single-step plan."""
        tool = MockToolCapability(
            id="fsl.bet.run",
            name="FSL BET",
            description="Brain Extraction Tool",
            capabilities=("skull_strip",),
            runtime_kind="container",
        )

        candidate = SelectionCandidate(
                scoring_weights=load_scoring_weights(),
            tool=tool,
            intent_match_score=0.9,
            preflight_passed=True,
            preflight_detail={"container_image": "CVMFS accessible"},
            description_score=0.8,
            metadata_score=0.7,
            resource_fit_score=0.95,
        )

        plan = materialize_simple_plan(
            candidate,
            query="skull strip T1 image",
            domain="neuroimaging",
        )

        # Check plan structure
        assert plan.plan_id.startswith("plan_")
        assert plan.domain == "neuroimaging"
        assert plan.resolvable is True  # Preflight passed
        assert len(plan.dag.steps) == 1

        # Check step
        step = plan.dag.steps[0]
        assert step.id == "step_001"
        assert step.tool == "fsl_bet"

        # Check estimates
        assert "confidence" in plan.estimates
        assert plan.estimates["confidence"] == candidate.final_score
        assert "resource_fit" in plan.estimates
        assert plan.estimates["resource_fit"] == 0.95

    def test_simple_plan_preflight_failed(self):
        """Test plan creation when preflight fails."""
        tool = MockToolCapability(
            id="missing.tool",
            name="Missing Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="container",
        )

        candidate = SelectionCandidate(
                scoring_weights=load_scoring_weights(),
            tool=tool,
            intent_match_score=0.8,
            preflight_passed=False,  # Failed
            preflight_detail={"container_image": "CVMFS not mounted"},
            description_score=0.7,
            metadata_score=0.6,
            resource_fit_score=0.2,
        )

        plan = materialize_simple_plan(candidate, query="test")

        # Plan should not be resolvable
        assert plan.resolvable is False
        # Should have warnings
        assert len(plan.warnings) > 0

    def test_simple_plan_with_modality(self):
        """Test plan creation with modality specified."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
        )

        candidate = SelectionCandidate(
                scoring_weights=load_scoring_weights(),
            tool=tool,
            intent_match_score=0.9,
            preflight_passed=True,
            description_score=0.8,
            metadata_score=0.7,
            resource_fit_score=0.9,
        )

        plan = materialize_simple_plan(
            candidate,
            query="test query",
            modality=["fmri", "smri"],
        )

        assert "fmri" in plan.modality
        assert "smri" in plan.modality

    def test_materialize_simple_plan_propagates_runtime_kind_python(self):
        """Test that runtime_kind='python' is propagated from tool to StepSpec."""
        tool = MockToolCapability(
            id="python.neuroimaging.fetch_atlas",
            name="Fetch Atlas",
            description="Fetch standard atlas",
            capabilities=("fetch_atlas",),
            runtime_kind="python",  # Python tool
        )

        candidate = SelectionCandidate(
            scoring_weights=load_scoring_weights(),
            tool=tool,
            intent_match_score=0.9,
            preflight_passed=True,
            description_score=0.8,
            metadata_score=0.7,
            resource_fit_score=0.9,
        )

        plan = materialize_simple_plan(
            candidate,
            query="fetch atlas",
            domain="neuroimaging",
        )

        # Verify runtime_kind was propagated to step
        assert len(plan.dag.steps) == 1
        step = plan.dag.steps[0]
        assert step.runtime_kind == "python", \
            f"Expected runtime_kind='python', got '{step.runtime_kind}'"

    def test_materialize_simple_plan_propagates_runtime_kind_container(self):
        """Test that runtime_kind='container' is propagated from tool to StepSpec."""
        tool = MockToolCapability(
            id="fsl.bet.run",
            name="FSL BET",
            description="Brain Extraction Tool",
            capabilities=("skull_strip",),
            runtime_kind="container",  # Container tool
        )

        candidate = SelectionCandidate(
            scoring_weights=load_scoring_weights(),
            tool=tool,
            intent_match_score=0.9,
            preflight_passed=True,
            description_score=0.8,
            metadata_score=0.7,
            resource_fit_score=0.9,
        )

        plan = materialize_simple_plan(
            candidate,
            query="skull strip",
            domain="neuroimaging",
        )

        # Verify runtime_kind was propagated to step
        assert len(plan.dag.steps) == 1
        step = plan.dag.steps[0]
        assert step.runtime_kind == "container", \
            f"Expected runtime_kind='container', got '{step.runtime_kind}'"


class TestMaterializePlanWithAlternatives:
    """Test plan materialization with alternatives."""

    def test_plan_with_alternatives(self):
        """Test creating plan with alternative tools."""
        # Create multiple candidates
        tools = [
            MockToolCapability(
                id=f"tool.{i}",
                name=f"Tool {i}",
                description=f"Test tool {i}",
                capabilities=("test",),
                runtime_kind="python",
            )
            for i in range(4)
        ]

        candidates = [
            SelectionCandidate(
                scoring_weights=load_scoring_weights(),
                tool=tool,
                intent_match_score=1.0 - (i * 0.1),
                preflight_passed=True,
                description_score=0.8,
                metadata_score=0.7,
                resource_fit_score=0.9,
            )
            for i, tool in enumerate(tools)
        ]

        plan = materialize_plan_with_alternatives(
            candidates,
            query="test query",
            include_top_n=3,
        )

        # Best tool should be in plan
        assert plan.dag.steps[0].tool == "tool.0"

        # Alternatives should be in estimates
        assert "alternatives" in plan.estimates
        alternatives = plan.estimates["alternatives"]
        assert len(alternatives) == 2  # Top 3 means best + 2 alternatives

        # Check alternative structure
        alt1 = alternatives[0]
        assert alt1["tool_id"] == "tool.1"
        assert alt1["rank"] == 2
        assert "score" in alt1
        assert "explanation" in alt1

    def test_plan_with_no_alternatives(self):
        """Test plan when only one candidate available."""
        tool = MockToolCapability(
            id="single.tool",
            name="Single Tool",
            description="Only option",
            capabilities=("test",),
            runtime_kind="python",
        )

        candidate = SelectionCandidate(
                scoring_weights=load_scoring_weights(),
            tool=tool,
            intent_match_score=0.9,
            preflight_passed=True,
            description_score=0.8,
            metadata_score=0.7,
            resource_fit_score=0.9,
        )

        plan = materialize_plan_with_alternatives(
            [candidate],
            query="test",
            include_top_n=3,
        )

        # Should not have alternatives
        assert "alternatives" not in plan.estimates or not plan.estimates["alternatives"]
        # Should have explanation
        assert "explanation" in plan.estimates

    def test_plan_with_alternatives_empty_list(self):
        """Test that empty candidate list raises error."""
        with pytest.raises(ValueError, match="empty candidate list"):
            materialize_plan_with_alternatives([], query="test")


class TestCreatePlanPreview:
    """Test plan preview creation."""

    def test_plan_preview_structure(self):
        """Test preview contains all expected fields."""
        tool = MockToolCapability(
            id="fsl.bet.run",
            name="FSL BET",
            description="Brain Extraction Tool",
            capabilities=("skull_strip",),
            runtime_kind="container",
        )

        candidate = SelectionCandidate(
                scoring_weights=load_scoring_weights(),
            tool=tool,
            intent_match_score=0.9,
            preflight_passed=True,
            preflight_detail={"container_image": "CVMFS accessible"},
            description_score=0.8,
            metadata_score=0.7,
            resource_fit_score=0.95,
        )

        preview = create_plan_preview(candidate, query="skull strip")

        # Check all required fields
        assert preview["query"] == "skull strip"
        assert preview["tool_id"] == "fsl_bet"
        assert preview["tool_name"] == "FSL BET"
        assert preview["tool_description"] == "Brain Extraction Tool"
        assert preview["confidence"] == candidate.final_score
        assert preview["explanation"] == candidate.explanation
        assert preview["ready_to_execute"] is True
        assert preview["runtime_kind"] == "container"

        # Check scores dict
        scores = preview["scores"]
        assert scores["intent_match"] == 0.9
        assert scores["preflight"] == 1.0  # Passed
        assert scores["description"] == 0.8
        assert scores["metadata"] == 0.7
        assert scores["resource_fit"] == 0.95

        # Check capabilities list
        assert "skull_strip" in preview["capabilities"]

    def test_plan_preview_preflight_failed(self):
        """Test preview when preflight fails."""
        tool = MockToolCapability(
            id="failing.tool",
            name="Failing Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
        )

        candidate = SelectionCandidate(
                scoring_weights=load_scoring_weights(),
            tool=tool,
            intent_match_score=0.8,
            preflight_passed=False,
            preflight_detail={"python_import": "import failed"},
            description_score=0.7,
            metadata_score=0.6,
            resource_fit_score=0.3,
        )

        preview = create_plan_preview(candidate, query="test")

        assert preview["ready_to_execute"] is False
        assert preview["scores"]["preflight"] == 0.0
        assert "import failed" in preview["preflight_details"]["python_import"]


class TestMaterializeMultiStepPlan:
    """Test multi-step plan materialization."""

    def test_multi_step_plan_creation(self):
        """Test creating multi-step plan from candidates."""
        tools = [
            MockToolCapability(
                id="step1.tool",
                name="Step 1",
                description="First step",
                capabilities=("prep",),
                runtime_kind="python",
            ),
            MockToolCapability(
                id="step2.tool",
                name="Step 2",
                description="Second step",
                capabilities=("process",),
                runtime_kind="container",
            ),
        ]

        candidates = [
            SelectionCandidate(
                scoring_weights=load_scoring_weights(),
                tool=tool,
                intent_match_score=0.9,
                preflight_passed=True,
                description_score=0.8,
                metadata_score=0.7,
                resource_fit_score=0.9,
            )
            for tool in tools
        ]

        plan = materialize_multi_step_plan(
            candidates,
            query="prep and process data",
        )

        # Check multiple steps
        assert len(plan.dag.steps) == 2
        assert plan.dag.steps[0].id == "step_001"
        assert plan.dag.steps[0].tool == "step1.tool"
        assert plan.dag.steps[1].id == "step_002"
        assert plan.dag.steps[1].tool == "step2.tool"

        # Check estimates
        assert "step_count" in plan.estimates
        assert plan.estimates["step_count"] == 2
        assert "avg_intent_match" in plan.estimates
        assert "all_preflight_passed" in plan.estimates
        assert bool(plan.estimates["all_preflight_passed"]) is True

    def test_multi_step_plan_mixed_preflight(self):
        """Test multi-step plan when some preflights fail."""
        tools = [
            MockToolCapability(id=f"tool.{i}", name=f"Tool {i}", description="Test",
                              capabilities=("test",), runtime_kind="python")
            for i in range(2)
        ]

        candidates = [
            SelectionCandidate(
                scoring_weights=load_scoring_weights(),
                tool=tools[0],
                intent_match_score=0.9,
                preflight_passed=True,  # Passes
                description_score=0.8,
                metadata_score=0.7,
                resource_fit_score=0.9,
            ),
            SelectionCandidate(
                scoring_weights=load_scoring_weights(),
                tool=tools[1],
                intent_match_score=0.8,
                preflight_passed=False,  # Fails
                description_score=0.7,
                metadata_score=0.6,
                resource_fit_score=0.4,
            ),
        ]

        plan = materialize_multi_step_plan(candidates, query="test")

        # Plan should not be resolvable if any step fails
        assert plan.resolvable is False
        assert bool(plan.estimates["all_preflight_passed"]) is False
        assert len(plan.warnings) > 0

    def test_multi_step_plan_empty_list(self):
        """Test that empty candidate list raises error."""
        with pytest.raises(ValueError, match="empty candidate list"):
            materialize_multi_step_plan([], query="test")

    def test_materialize_multi_step_plan_mixed_runtime_kinds(self):
        """Test that mixed runtime_kinds (python and container) are propagated correctly."""
        # Create tools with different runtime_kinds
        tools = [
            MockToolCapability(
                id="python.fetch_atlas",
                name="Fetch Atlas",
                description="Fetch atlas (python)",
                capabilities=("fetch_atlas",),
                runtime_kind="python",  # Python tool
            ),
            MockToolCapability(
                id="fsl.bet.run",
                name="FSL BET",
                description="Brain extraction (container)",
                capabilities=("skull_strip",),
                runtime_kind="container",  # Container tool
            ),
            MockToolCapability(
                id="python.extract_ts",
                name="Extract Timeseries",
                description="Extract timeseries (python)",
                capabilities=("timeseries_extraction",),
                runtime_kind="python",  # Python tool
            ),
        ]

        candidates = [
            SelectionCandidate(
                scoring_weights=load_scoring_weights(),
                tool=tool,
                intent_match_score=0.9,
                preflight_passed=True,
                description_score=0.8,
                metadata_score=0.7,
                resource_fit_score=0.9,
            )
            for tool in tools
        ]

        plan = materialize_multi_step_plan(
            candidates,
            query="fetch atlas, skull strip, extract timeseries",
            domain="neuroimaging",
        )

        # Verify all steps have correct runtime_kind
        assert len(plan.dag.steps) == 3

        # Step 1: python
        assert plan.dag.steps[0].tool == "fetch_atlas"
        assert plan.dag.steps[0].runtime_kind == "python", \
            f"Step 1: Expected runtime_kind='python', got '{plan.dag.steps[0].runtime_kind}'"

        # Step 2: container
        assert plan.dag.steps[1].tool == "fsl_bet"
        assert plan.dag.steps[1].runtime_kind == "container", \
            f"Step 2: Expected runtime_kind='container', got '{plan.dag.steps[1].runtime_kind}'"

        # Step 3: python
        assert plan.dag.steps[2].tool == "python.extract_ts"
        assert plan.dag.steps[2].runtime_kind == "python", \
            f"Step 3: Expected runtime_kind='python', got '{plan.dag.steps[2].runtime_kind}'"


class TestBackwardCompatibility:
    """Test backward compatibility aliases."""

    def test_convert_candidate_to_plan_alias(self):
        """Test legacy alias works."""
        tool = MockToolCapability(
            id="test.tool",
            name="Test Tool",
            description="Test",
            capabilities=("test",),
            runtime_kind="python",
        )

        candidate = SelectionCandidate(
                scoring_weights=load_scoring_weights(),
            tool=tool,
            intent_match_score=0.9,
            preflight_passed=True,
            description_score=0.8,
            metadata_score=0.7,
            resource_fit_score=0.9,
        )

        # Should work the same as materialize_simple_plan
        plan = convert_candidate_to_plan(candidate, query="test")

        assert plan.plan_id.startswith("plan_")
        assert plan.dag.steps[0].tool == "test.tool"
