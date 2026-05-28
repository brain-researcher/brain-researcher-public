"""Tests for pipeline-first heuristic in PlanningEngine.

These tests verify that:
1. _should_use_pipeline correctly identifies multi-step imaging queries
2. _build_steps_from_pipeline correctly converts pipeline definitions to WorkflowSteps
3. The planner uses pipeline templates when available
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from typing import Dict, List, Any

from brain_researcher.services.agent.planning import PlanningEngine, WorkflowStep, QueryIntent


def make_intent(domain: str, primary_intent: str = "analyze", entities: dict = None) -> QueryIntent:
    """Helper to create QueryIntent with required fields."""
    return QueryIntent(
        primary_intent=primary_intent,
        domain=domain,
        entities=entities or {},
    )


class TestShouldUsePipeline:
    """Test the _should_use_pipeline heuristic."""

    @pytest.fixture
    def engine(self):
        """Create a PlanningEngine with mocked LLM."""
        mock_llm = MagicMock()
        return PlanningEngine(llm=mock_llm)

    @pytest.mark.parametrize("query,expected", [
        # Should trigger pipeline search
        ("preprocess my T1 scan to MNI space", True),
        ("run the preprocessing pipeline", True),
        ("skull strip and register to MNI", True),
        ("do ICA denoising on fMRI", True),
        ("run tractography on diffusion data", True),
        ("normalize brain to template", True),
        ("linear and non-linear registration", True),
        ("run GLM analysis on my fMRI", True),

        # Should NOT trigger pipeline search
        ("what is the motor cortex?", False),
        ("search for papers about memory", False),
        ("find datasets with working memory tasks", False),
        ("visualize this brain map", False),
    ])
    def test_keyword_detection(self, engine, query, expected):
        """Test that keywords correctly trigger pipeline search."""
        intent = make_intent(
            domain="imaging" if expected else "knowledge_graph",
            primary_intent="analyze",
        )
        result = engine._should_use_pipeline(intent, query)
        assert result == expected, f"Query: '{query}' should return {expected}"

    @pytest.mark.parametrize("domain,expected", [
        ("fmri", True),
        ("smri", True),
        ("dmri", True),
        ("imaging", True),
        ("preprocessing", True),
        ("neuroimaging", True),
        ("knowledge_graph", False),
        ("literature", False),
        ("datasets", False),
    ])
    def test_domain_detection(self, engine, domain, expected):
        """Test that domain correctly triggers pipeline search."""
        intent = make_intent(domain=domain, primary_intent="analyze")
        # Use a neutral query that won't trigger keywords
        result = engine._should_use_pipeline(intent, "analyze this data")
        assert result == expected, f"Domain '{domain}' should return {expected}"


class TestBuildStepsFromPipeline:
    """Test the _build_steps_from_pipeline method."""

    @pytest.fixture
    def engine(self):
        """Create a PlanningEngine with mocked LLM."""
        mock_llm = MagicMock()
        return PlanningEngine(llm=mock_llm)

    def test_simple_pipeline(self, engine):
        """Test converting a simple 2-step pipeline."""
        pipeline = {
            "id": "t1_preproc",
            "name": "T1 Preprocessing",
            "description": "Preprocess T1 to MNI",
            "steps": ["fsl.bet", "fsl.fnirt"],
        }

        steps = engine._build_steps_from_pipeline(pipeline)

        assert len(steps) == 2
        assert steps[0].tool_name == "fsl.bet"
        assert steps[1].tool_name == "fsl.fnirt"
        assert steps[0].dependencies == []
        assert steps[1].dependencies == ["step_1"]

    def test_single_step_pipeline(self, engine):
        """Test converting a single-step pipeline."""
        pipeline = {
            "id": "fmri_first_level",
            "name": "fMRI First-Level",
            "description": "First-level GLM",
            "steps": ["fsl.feat"],
        }

        steps = engine._build_steps_from_pipeline(pipeline)

        assert len(steps) == 1
        assert steps[0].tool_name == "fsl.feat"
        assert steps[0].dependencies == []

    def test_empty_pipeline(self, engine):
        """Test handling empty pipeline."""
        pipeline = {
            "id": "empty",
            "name": "Empty",
            "description": "No steps",
            "steps": [],
        }

        steps = engine._build_steps_from_pipeline(pipeline)
        assert len(steps) == 0

    def test_step_ids_sequential(self, engine):
        """Test that step IDs are sequential."""
        pipeline = {
            "id": "multi_step",
            "name": "Multi Step",
            "description": "Three steps",
            "steps": ["tool_a", "tool_b", "tool_c"],
        }

        steps = engine._build_steps_from_pipeline(pipeline)

        assert steps[0].step_id == "step_1"
        assert steps[1].step_id == "step_2"
        assert steps[2].step_id == "step_3"


class TestPipelineFirstIntegration:
    """Integration tests for the pipeline-first flow."""

    @pytest.fixture
    def engine(self):
        """Create a PlanningEngine with mocked LLM."""
        mock_llm = MagicMock()
        return PlanningEngine(llm=mock_llm)

    @pytest.mark.asyncio
    async def test_pipeline_hit_skips_llm(self, engine):
        """Test that when pipeline is found, LLM is not called."""
        mock_pipeline = {
            "id": "t1_preproc",
            "name": "T1 Preprocessing",
            "description": "Standard T1 preprocessing",
            "steps": ["fsl.bet", "fsl.fnirt"],
        }

        with patch("brain_researcher.services.agent.planning.search_pipelines") as mock_search:
            mock_search.return_value = [mock_pipeline]

            intent = make_intent(
                domain="smri",
                primary_intent="preprocess",
                entities={"modalities": ["smri"]},
            )

            steps = await engine._generate_steps(
                query="preprocess T1 to MNI",
                intent=intent,
                context=None,
            )

            # Should have 2 steps from pipeline
            assert len(steps) == 2
            assert steps[0].tool_name == "fsl.bet"
            assert steps[1].tool_name == "fsl.fnirt"

            # search_pipelines should have been called
            mock_search.assert_called_once()
            assert mock_search.call_args.kwargs == {
                "task": "preprocess T1 to MNI",
                "modalities": ["smri"],
                "limit": 1,
            }

    @pytest.mark.asyncio
    async def test_pipeline_miss_falls_back_to_llm(self, engine):
        """Test that when no pipeline found, LLM is called."""
        with patch("brain_researcher.services.agent.planning.search_pipelines") as mock_search:
            mock_search.return_value = []  # No pipeline found

            # Mock LLM response
            mock_response = MagicMock()
            mock_response.content = '[]'
            engine._run_prompt = AsyncMock(return_value=mock_response)

            intent = make_intent(
                domain="smri",
                primary_intent="preprocess",
            )

            await engine._generate_steps(
                query="preprocess T1 to MNI",
                intent=intent,
                context=None,
            )

            # LLM should have been called since no pipeline was found
            engine._run_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_error_falls_back_to_llm(self, engine):
        """Test that when pipeline search fails, LLM is called."""
        with patch("brain_researcher.services.agent.planning.search_pipelines") as mock_search:
            mock_search.side_effect = Exception("Neo4j connection failed")

            # Mock LLM response
            mock_response = MagicMock()
            mock_response.content = '[]'
            engine._run_prompt = AsyncMock(return_value=mock_response)

            intent = make_intent(
                domain="smri",
                primary_intent="preprocess",
            )

            # Should not raise, should fall back to LLM
            await engine._generate_steps(
                query="preprocess T1 to MNI",
                intent=intent,
                context=None,
            )

            # LLM should have been called as fallback
            engine._run_prompt.assert_called_once()


# =============================================================================
# Run quick verification
# =============================================================================

if __name__ == "__main__":
    import sys

    print("Running pipeline-first heuristic tests...")
    print("-" * 50)

    # Test _should_use_pipeline
    from brain_researcher.services.agent.planning import PlanningEngine, QueryIntent

    mock_llm = MagicMock()
    engine = PlanningEngine(llm=mock_llm)

    def make_intent_main(domain: str, primary_intent: str = "analyze") -> QueryIntent:
        return QueryIntent(primary_intent=primary_intent, domain=domain, entities={})

    test_cases = [
        ("preprocess T1 to MNI space", "imaging", True),
        ("skull strip and register", "smri", True),
        ("run ICA denoising", "fmri", True),
        ("search knowledge graph", "knowledge_graph", False),
        ("find papers about memory", "literature", False),
    ]

    all_passed = True
    for query, domain, expected in test_cases:
        intent = make_intent_main(domain=domain, primary_intent="analyze")
        result = engine._should_use_pipeline(intent, query)
        status = "PASS" if result == expected else "FAIL"
        if result != expected:
            all_passed = False
        print(f"  [{status}] '{query[:30]}...' (domain={domain}) -> {result}")

    print("-" * 50)
    print(f"Result: {'All tests passed!' if all_passed else 'Some tests failed!'}")
    sys.exit(0 if all_passed else 1)
