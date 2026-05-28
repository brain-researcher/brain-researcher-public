"""
Unit tests for the Planning Engine (AGENT-002).

Tests query parsing, step generation, dependency resolution, and parameter inference.
"""

import json
import pytest
import time
from unittest.mock import Mock, patch, AsyncMock
from typing import List, Dict, Any
from types import SimpleNamespace

from brain_researcher.services.agent.planning import (
    PlanningEngine,
    QueryIntent,
    WorkflowStep,
    ExecutionPlan,
    StepStatus,
    ResourceType,
    get_planning_engine,
)


def _make_planning_engine(llm: Mock | None = None) -> PlanningEngine:
    """Utility to build a PlanningEngine that never touches real LLMs."""

    if llm is None:
        llm = Mock()
    if not hasattr(llm, "ainvoke"):
        llm.ainvoke = AsyncMock()

    return PlanningEngine(
        llm=llm,
        use_cot_reasoning=False,
        use_advanced_parsing=False,
        enable_optimization=False,
    )


def _ai_json(payload: Dict[str, Any] | List[Dict[str, Any]]) -> SimpleNamespace:
    """Build a simple object mimicking an LLM message with JSON content."""

    return SimpleNamespace(content=json.dumps(payload))


class TestQueryParsing:
    """Test query parsing and intent extraction."""
    
    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM for testing."""
        llm = Mock()
        llm.ainvoke = AsyncMock()
        return llm
    
    @pytest.fixture
    def planning_engine(self, mock_llm):
        """Create a planning engine with mock LLM."""
        return _make_planning_engine(mock_llm)
    
    @pytest.mark.asyncio
    async def test_parse_simple_query(self, planning_engine):
        """Test parsing a simple neuroscience query."""
        # Mock LLM response
        planning_engine.llm.ainvoke.return_value = _ai_json({
            "primary_intent": "analyze fMRI data",
            "domain": "fmri",
            "entities": {
                "datasets": ["ds000001"],
                "tasks": ["motor"],
                "brain_regions": []
            },
            "constraints": ["use GLM"],
            "output_format": "nifti"
        })
        
        intent = await planning_engine.parse_query("Analyze motor task fMRI from ds000001 using GLM")
        
        assert intent.primary_intent == "analyze fMRI data"
        assert intent.domain == "fmri"
        assert "ds000001" in intent.entities["datasets"]
        assert "motor" in intent.entities["tasks"]
        assert "use GLM" in intent.constraints
        assert intent.output_format == "nifti"
    
    @pytest.mark.asyncio
    async def test_parse_complex_query(self, planning_engine):
        """Test parsing a complex multi-step query."""
        planning_engine.llm.ainvoke.return_value = _ai_json({
            "primary_intent": "connectivity analysis",
            "domain": "connectivity",
            "entities": {
                "datasets": ["ds000002"],
                "brain_regions": ["motor cortex", "SMA"],
                "tasks": ["rest"]
            },
            "constraints": ["threshold at p<0.05", "use FDR correction"],
            "output_format": "matrix"
        })
        
        intent = await planning_engine.parse_query(
            "Calculate connectivity between motor cortex and SMA in resting state, "
            "threshold at p<0.05 with FDR correction"
        )
        
        assert intent.domain == "connectivity"
        assert "motor cortex" in intent.entities["brain_regions"]
        assert len(intent.constraints) == 2
    
    @pytest.mark.asyncio
    async def test_parse_query_timing(self, planning_engine):
        """Test that query parsing is fast."""
        planning_engine.llm.ainvoke.return_value = _ai_json({"primary_intent": "test", "domain": "test", "entities": {}})
        
        start = time.time()
        await planning_engine.parse_query("Quick test query")
        elapsed = time.time() - start
        
        # Should be fast (accounting for async overhead)
        assert elapsed < 1.0


class TestStepGeneration:
    """Test workflow step generation."""
    
    @pytest.fixture
    def planning_engine(self):
        """Create planning engine with mock LLM."""
        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock()
        return _make_planning_engine(mock_llm)
    
    @pytest.mark.asyncio
    async def test_generate_simple_plan(self, planning_engine):
        """Test generating a simple execution plan."""
        # Mock parse_query
        intent = QueryIntent(
            primary_intent="analyze",
            domain="fmri",
            entities={"datasets": ["ds000001"]}
        )
        
        # Mock step generation
        planning_engine.llm.ainvoke.return_value = _ai_json([
            {
                "step_number": 1,
                "description": "Load dataset",
                "tool_name": "load_dataset",
                "tool_args": {"dataset_id": "ds000001"},
                "dependencies": [],
                "expected_output": "BIDS dataset"
            },
            {
                "step_number": 2,
                "description": "Run GLM",
                "tool_name": "glm_analysis",
                "tool_args": {"model": "standard"},
                "dependencies": [1],
                "expected_output": "Statistical maps"
            }
        ])
        
        with patch.object(planning_engine, 'parse_query', return_value=intent):
            plan = await planning_engine.generate_plan("Analyze ds000001")
        
        assert len(plan.steps) == 2
        assert plan.steps[0].tool_name == "load_dataset"
        assert plan.steps[1].tool_name == "glm_analysis"
        assert "step_1" in plan.steps[1].dependencies

    @pytest.mark.asyncio
    async def test_generate_steps_injects_planning_policies(self, planning_engine):
        """Planner system prompt should include prod-grounded planning policies."""
        intent = QueryIntent(
            primary_intent="explain task",
            domain="fmri",
            entities={},
            constraints=[],
            output_format="text",
        )
        planning_engine.llm.ainvoke.return_value = _ai_json(
            [
                {
                    "step_number": 1,
                    "description": "Ground the task name",
                    "tool_name": "task_to_concept_mapping",
                    "tool_args": {"task_name": "n-back"},
                    "dependencies": [],
                    "expected_output": "Normalized task and concepts",
                }
            ]
        )

        await planning_engine._generate_steps("Explain the n-back task", intent, None)

        messages = planning_engine.llm.ainvoke.await_args.args[0]
        system_message = messages[0]
        assert "Planning policies:" in system_message.content
        assert "first normalize it with a cheap grounding step" in system_message.content
        assert "do not repeat the same call with only minor argument changes" in system_message.content
        assert "preserve those fields explicitly in the plan" in system_message.content
    
    @pytest.mark.asyncio
    async def test_dependency_resolution(self, planning_engine):
        """Test that dependencies are properly resolved."""
        steps = [
            WorkflowStep(
                step_id="step_1",
                step_number=1,
                description="First step",
                tool_name="tool1",
                tool_args={},
                dependencies=[]
            ),
            WorkflowStep(
                step_id="step_2",
                step_number=2,
                description="Second step",
                tool_name="tool2",
                tool_args={},
                dependencies=[1]  # Numeric dependency
            ),
            WorkflowStep(
                step_id="step_3",
                step_number=3,
                description="Third step",
                tool_name="tool3",
                tool_args={},
                dependencies=["step_2"]  # String dependency
            )
        ]
        
        resolved = planning_engine._resolve_dependencies(steps)
        
        assert resolved[1].dependencies == ["step_1"]
        assert resolved[2].dependencies == ["step_2"]
    
    def test_cycle_detection(self, planning_engine):
        """Test detection of circular dependencies."""
        # Create steps with a cycle
        steps = [
            WorkflowStep(
                step_id="step_1",
                step_number=1,
                description="Step 1",
                tool_name="tool1",
                tool_args={},
                dependencies=["step_3"]
            ),
            WorkflowStep(
                step_id="step_2",
                step_number=2,
                description="Step 2",
                tool_name="tool2",
                tool_args={},
                dependencies=["step_1"]
            ),
            WorkflowStep(
                step_id="step_3",
                step_number=3,
                description="Step 3",
                tool_name="tool3",
                tool_args={},
                dependencies=["step_2"]
            )
        ]
        
        has_cycle = planning_engine._has_cycle(steps)
        assert has_cycle is True
        
        # Resolve should remove cycles
        resolved = planning_engine._resolve_dependencies(steps)
        has_cycle_after = planning_engine._has_cycle(resolved)
        assert has_cycle_after is False


class TestParameterInference:
    """Test parameter inference from context."""
    
    @pytest.fixture
    def planning_engine(self):
        """Create planning engine."""
        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock()
        return _make_planning_engine(mock_llm)
    
    @pytest.mark.asyncio
    async def test_infer_dataset_from_intent(self, planning_engine):
        """Test inferring dataset ID from intent."""
        steps = [
            WorkflowStep(
                step_id="step_1",
                step_number=1,
                description="Load data",
                tool_name="load_dataset",
                tool_args={}  # Missing dataset_id
            )
        ]
        
        intent = QueryIntent(
            primary_intent="analyze",
            domain="fmri",
            entities={"datasets": ["ds000001"]}
        )
        
        inferred = await planning_engine._infer_parameters(steps, intent, None)
        
        assert inferred[0].tool_args["dataset_id"] == "ds000001"
    
    @pytest.mark.asyncio
    async def test_infer_from_context(self, planning_engine):
        """Test inferring parameters from context."""
        steps = [
            WorkflowStep(
                step_id="step_1",
                step_number=1,
                description="Analyze",
                tool_name="glm_analysis",
                tool_args={}
            )
        ]
        
        intent = QueryIntent(
            primary_intent="analyze",
            domain="fmri",
            entities={}
        )
        
        context = {
            "dataset_id": "ds000002",
            "task": "motor"
        }
        
        inferred = await planning_engine._infer_parameters(steps, intent, context)
        
        assert inferred[0].tool_args["dataset_id"] == "ds000002"


class TestCostEstimation:
    """Test cost and resource estimation."""
    
    @pytest.fixture
    def planning_engine(self):
        """Create planning engine."""
        return _make_planning_engine()
    
    def test_time_estimation(self, planning_engine):
        """Test execution time estimation."""
        steps = [
            WorkflowStep(
                step_id="step_1",
                step_number=1,
                description="Quick task",
                tool_name="query",
                tool_args={},
                estimated_time_seconds=5.0
            ),
            WorkflowStep(
                step_id="step_2",
                step_number=2,
                description="Slow task",
                tool_name="preprocessing",
                tool_args={},
                estimated_time_seconds=3600.0
            )
        ]
        
        total_time, _ = planning_engine._calculate_costs(steps)
        
        assert total_time == 3605.0
    
    def test_resource_estimation(self, planning_engine):
        """Test resource requirement estimation."""
        steps = [
            WorkflowStep(
                step_id="step_1",
                step_number=1,
                description="CPU task",
                tool_name="analysis",
                tool_args={},
                resource_requirements={
                    ResourceType.CPU: 2.0,
                    ResourceType.MEMORY: 8.0
                }
            ),
            WorkflowStep(
                step_id="step_2",
                step_number=2,
                description="Memory task",
                tool_name="processing",
                tool_args={},
                resource_requirements={
                    ResourceType.CPU: 1.0,
                    ResourceType.MEMORY: 16.0
                }
            )
        ]
        
        _, total_resources = planning_engine._calculate_costs(steps)
        
        # Should take max for parallel execution
        assert total_resources[ResourceType.CPU] == 2.0
        assert total_resources[ResourceType.MEMORY] == 16.0


class TestPlanValidation:
    """Test plan validation and optimization."""
    
    @pytest.fixture
    def planning_engine(self):
        """Create planning engine."""
        return _make_planning_engine()
    
    def test_validate_valid_plan(self, planning_engine):
        """Test validation of a valid plan."""
        plan = ExecutionPlan(
            plan_id="test_plan",
            query="Test query",
            objectives=["Test objective"],
            steps=[
                WorkflowStep(
                    step_id="step_1",
                    step_number=1,
                    description="Valid step",
                    tool_name="task_to_concept_mapping",  # Known tool
                    tool_args={"task": "test"}
                )
            ],
            success_criteria=["Complete test"],
            total_estimated_time=60.0,
            total_resource_requirements={}
        )
        
        issues = planning_engine.validate_plan(plan)
        
        assert len(issues) == 0
    
    def test_validate_invalid_plan(self, planning_engine):
        """Test validation catches issues."""
        plan = ExecutionPlan(
            plan_id="bad_plan",
            query="Test",
            objectives=[],
            steps=[
                WorkflowStep(
                    step_id="step_1",
                    step_number=1,
                    description="Bad step",
                    tool_name="unknown_tool",  # Unknown tool
                    tool_args={},
                    dependencies=["step_99"]  # Invalid dependency
                )
            ],
            success_criteria=[],
            total_estimated_time=10000.0,  # Too long
            total_resource_requirements={}
        )
        
        issues = planning_engine.validate_plan(plan)
        
        assert len(issues) > 0
        assert any("Unknown tool" in issue for issue in issues)
        assert any("invalid dependency" in issue for issue in issues)
        assert any("exceeds time limit" in issue for issue in issues)
    
    def test_plan_optimization(self, planning_engine):
        """Test plan optimization for parallel execution."""
        # Create plan with independent steps
        plan = ExecutionPlan(
            plan_id="test_plan",
            query="Test",
            objectives=["Test"],
            steps=[
                WorkflowStep(
                    step_id="step_1",
                    step_number=1,
                    description="Independent 1",
                    tool_name="tool1",
                    tool_args={},
                    dependencies=[],
                    estimated_time_seconds=100.0
                ),
                WorkflowStep(
                    step_id="step_2",
                    step_number=2,
                    description="Independent 2",
                    tool_name="tool2",
                    tool_args={},
                    dependencies=[],
                    estimated_time_seconds=150.0
                ),
                WorkflowStep(
                    step_id="step_3",
                    step_number=3,
                    description="Dependent",
                    tool_name="tool3",
                    tool_args={},
                    dependencies=["step_1"],
                    estimated_time_seconds=50.0
                )
            ],
            success_criteria=["Done"],
            total_estimated_time=300.0,  # Sequential time
            total_resource_requirements={}
        )
        
        optimized = planning_engine.optimize_plan(plan)
        
        # Steps 1 and 2 can run in parallel, then step 3
        # Time should be max(100, 150) + 50 = 200
        assert optimized.total_estimated_time < 300.0


class TestPlanningPerformance:
    """Test planning engine performance requirements."""
    
    @pytest.mark.asyncio
    async def test_planning_speed_simple_query(self):
        """Test that simple queries plan in <500ms."""
        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock(
            return_value=_ai_json({"primary_intent": "analyze", "domain": "fmri", "entities": {}})
        )
        
        engine = _make_planning_engine(mock_llm)
        
        # Mock fast responses
        with patch.object(engine, '_generate_steps', return_value=[]):
            start = time.time()
            plan = await engine.generate_plan("Simple fMRI analysis")
            elapsed = time.time() - start
            
            # Should meet <500ms requirement for simple queries
            assert elapsed < 0.5 or len(plan.steps) > 3  # Allow longer for complex plans


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
