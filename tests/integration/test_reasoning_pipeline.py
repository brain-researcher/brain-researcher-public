"""
Integration tests for Chain-of-Thought Reasoning Pipeline (AGENT-011)

Tests cover:
- Planning integration with CoT reasoning
- API endpoint responses
- Error recovery and resilience
- Full pipeline with real LLM integration (mocked)
- Performance under realistic conditions
"""

import json
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from brain_researcher.services.agent.cot_reasoning import (
    ChainOfThoughtReasoner,
    ReasoningType,
    ReasoningTrace,
    get_cot_reasoner
)


class MockLLMClient:
    """Mock LLM client for integration testing."""
    
    def __init__(self):
        self.call_count = 0
        self.responses = []
    
    async def ainvoke(self, inputs):
        """Mock async invoke with realistic responses."""
        self.call_count += 1
        
        # Simulate realistic response times
        await asyncio.sleep(0.1)
        
        prompt = str(inputs)
        mock_response = MagicMock()
        
        # Type detection responses
        if "reasoning type" in prompt.lower() or "analytical" in prompt.lower():
            if "compare" in inputs.get("query", "").lower():
                mock_response.content = "COMPARATIVE"
            elif "correlat" in inputs.get("query", "").lower():
                mock_response.content = "CAUSAL"
            else:
                mock_response.content = "ANALYTICAL"
        
        # Step generation responses
        elif "step-by-step reasoning" in prompt.lower():
            query = inputs.get("query", "")
            if "working memory" in query.lower():
                mock_response.content = json.dumps([
                    {
                        "step_number": 1,
                        "premise": "Query asks about working memory analysis",
                        "inference": "Working memory involves prefrontal and parietal regions",
                        "conclusion": "Need to identify PFC and parietal activation",
                        "confidence": 0.9,
                        "evidence": ["Meta-analyses show consistent PFC activation", "Parietal involvement in attention"],
                        "assumptions": ["Data contains working memory task", "Standard preprocessing applied"]
                    },
                    {
                        "step_number": 2,
                        "premise": "Have identified key brain regions for working memory",
                        "inference": "Statistical analysis needed to quantify activation",
                        "conclusion": "Extract ROI data and compute statistical contrasts",
                        "confidence": 0.85,
                        "evidence": ["GLM is standard approach", "ROI analysis provides interpretable results"],
                        "assumptions": ["Proper GLM specification", "Adequate sample size"]
                    }
                ])
            else:
                mock_response.content = json.dumps([
                    {
                        "step_number": 1,
                        "premise": f"Query asks about: {query}",
                        "inference": "This requires systematic analysis approach",
                        "conclusion": "Will break down the analysis into manageable steps",
                        "confidence": 0.75,
                        "evidence": ["Systematic approaches improve reliability"],
                        "assumptions": ["Query is well-formed"]
                    }
                ])
        
        # Conclusion generation responses
        elif "final conclusion" in prompt.lower():
            mock_response.content = "Based on the reasoning steps, the analysis should proceed with ROI extraction from prefrontal and parietal regions, followed by statistical testing to quantify working memory activation patterns."
        
        # Explanation generation responses
        elif "explain this reasoning" in prompt.lower():
            mock_response.content = "This analytical reasoning process systematically breaks down the working memory analysis task. We first identified the key brain regions known to be involved (prefrontal and parietal cortex), then determined the appropriate statistical methods (GLM and ROI analysis). The high confidence in these steps reflects the strong empirical foundation from neuroimaging literature."
        
        else:
            mock_response.content = "Default response"
        
        return mock_response


@pytest.fixture
async def mock_reasoner():
    """Create a CoT reasoner with mock LLM for testing."""
    mock_llm = MockLLMClient()
    return ChainOfThoughtReasoner(mock_llm)


@pytest.fixture
def sample_queries():
    """Load sample queries from fixtures."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-011" / "sample_queries.json"
    with open(fixture_path, 'r') as f:
        return json.load(f)


class TestCoTReasoningPipeline:
    """Test the complete CoT reasoning pipeline."""
    
    @pytest.mark.asyncio
    async def test_simple_query_full_pipeline(self, mock_reasoner, sample_queries):
        """Test full pipeline with simple query."""
        simple_query = sample_queries["simple_queries"][0]
        query = simple_query["query"]
        
        trace = await mock_reasoner.reason(query)
        
        # Verify trace structure
        assert isinstance(trace, ReasoningTrace)
        assert trace.query == query
        assert len(trace.steps) > 0
        assert trace.final_conclusion
        assert trace.explanation
        assert 0.0 <= trace.overall_confidence <= 1.0
        
        # Verify reasoning type detection worked
        assert "reasoning_type" in trace.metadata
        
        # Verify timing metadata
        assert "generation_time" in trace.metadata
        assert trace.metadata["generation_time"] > 0
    
    @pytest.mark.asyncio
    async def test_complex_query_multi_step_reasoning(self, mock_reasoner, sample_queries):
        """Test complex query with multiple reasoning steps."""
        complex_query = sample_queries["complex_queries"][0]
        query = complex_query["query"]
        
        trace = await mock_reasoner.reason(query, max_steps=5)
        
        # Complex queries should generate detailed reasoning
        assert len(trace.steps) >= 1
        assert trace.overall_confidence > 0
        
        # Should have proper step sequence
        step_numbers = [step.step_number for step in trace.steps]
        assert step_numbers == list(range(1, len(trace.steps) + 1))
        
        # Each step should have required components
        for step in trace.steps:
            assert step.premise
            assert step.inference
            assert step.conclusion
            assert 0.0 <= step.confidence <= 1.0
    
    @pytest.mark.asyncio
    async def test_reasoning_type_detection_accuracy(self, mock_reasoner):
        """Test reasoning type detection for different query types."""
        test_cases = [
            ("analyze working memory activation", ReasoningType.ANALYTICAL),
            ("compare young vs old subjects", ReasoningType.COMPARATIVE),
            ("what causes connectivity differences", ReasoningType.CAUSAL),
        ]
        
        for query, expected_type in test_cases:
            detected_type = await mock_reasoner._detect_reasoning_type(query)
            assert detected_type == expected_type, f"Query: {query}"
    
    @pytest.mark.asyncio
    async def test_context_integration(self, mock_reasoner):
        """Test integration of contextual information."""
        query = "analyze the activation patterns"
        context = {
            "previous_analysis": "working memory task",
            "dataset": "ds000114",
            "preprocessing_done": True
        }
        
        trace = await mock_reasoner.reason(query, context=context)
        
        # Context should be reflected in metadata
        assert trace.metadata["context_used"] == True
        
        # Reasoning should be context-aware (check in explanation)
        explanation_lower = trace.explanation.lower()
        # The explanation should reference the context in some way
        assert len(explanation_lower) > 0
    
    @pytest.mark.asyncio
    async def test_confidence_calculation_accuracy(self, mock_reasoner):
        """Test confidence calculation reflects step confidences."""
        query = "analyze working memory activation in prefrontal cortex"
        
        trace = await mock_reasoner.reason(query)
        
        if len(trace.steps) > 0:
            # Overall confidence should be related to step confidences
            step_confidences = [step.confidence for step in trace.steps]
            avg_confidence = sum(step_confidences) / len(step_confidences)
            
            # Geometric mean should be lower than arithmetic mean (more conservative)
            assert trace.overall_confidence <= avg_confidence
            
            # Should be above minimum threshold for valid reasoning
            assert trace.overall_confidence >= mock_reasoner.min_confidence


class TestPlanningIntegration:
    """Test integration with planning engine."""
    
    @pytest.mark.asyncio
    async def test_planning_integration_mock(self, mock_reasoner):
        """Test CoT integration with planning engine (mocked)."""
        
        # Mock a planning context
        planning_context = {
            "available_tools": ["glm_analysis", "roi_extraction", "visualization"],
            "current_dataset": "working_memory_study",
            "analysis_goal": "identify brain activation patterns"
        }
        
        query = "analyze working memory activation using available tools"
        trace = await mock_reasoner.reason(query, context=planning_context)
        
        # Planning integration should enhance reasoning
        assert len(trace.steps) > 0
        
        # Steps should be tool-aware (check if tools mentioned)
        reasoning_text = " ".join([step.conclusion for step in trace.steps])
        # At least some tool concepts should appear
        has_tool_references = any(tool_concept in reasoning_text.lower() 
                                for tool_concept in ["analysis", "extraction", "statistical"])
        assert has_tool_references
    
    @pytest.mark.asyncio
    async def test_reasoning_confidence_thresholds(self, mock_reasoner):
        """Test reasoning confidence thresholds affect planning."""
        
        # Test with high confidence threshold
        mock_reasoner.confidence_threshold = 0.9
        trace_high = await mock_reasoner.reason("analyze simple activation")
        
        # Test with low confidence threshold
        mock_reasoner.confidence_threshold = 0.3
        trace_low = await mock_reasoner.reason("analyze simple activation")
        
        # Both should succeed but confidence assessment might differ
        assert isinstance(trace_high, ReasoningTrace)
        assert isinstance(trace_low, ReasoningTrace)
        
        # Check that confidence is properly calculated
        assert 0.0 <= trace_high.overall_confidence <= 1.0
        assert 0.0 <= trace_low.overall_confidence <= 1.0


class TestAPIEndpoints:
    """Test API endpoint integration (mocked)."""
    
    def test_reasoning_trace_serialization(self, sample_queries):
        """Test that reasoning traces can be serialized for API responses."""
        # Create a sample trace
        from brain_researcher.services.agent.cot_reasoning import ReasoningStep
        
        steps = [
            ReasoningStep(
                step_id="step_1",
                step_number=1,
                reasoning_type=ReasoningType.ANALYTICAL,
                premise="Test premise",
                inference="Test inference", 
                conclusion="Test conclusion",
                confidence=0.8,
                evidence=["evidence1"],
                assumptions=["assumption1"]
            )
        ]
        
        trace = ReasoningTrace(
            trace_id="test_trace",
            query="test query",
            steps=steps,
            final_conclusion="test conclusion",
            overall_confidence=0.8,
            explanation="test explanation"
        )
        
        # Test serialization to dict (for JSON API responses)
        trace_dict = {
            "trace_id": trace.trace_id,
            "query": trace.query,
            "steps": [
                {
                    "step_id": step.step_id,
                    "step_number": step.step_number,
                    "reasoning_type": step.reasoning_type.value,
                    "premise": step.premise,
                    "inference": step.inference,
                    "conclusion": step.conclusion,
                    "confidence": step.confidence,
                    "confidence_level": step.confidence_level.value,
                    "evidence": step.evidence,
                    "assumptions": step.assumptions
                }
                for step in trace.steps
            ],
            "final_conclusion": trace.final_conclusion,
            "overall_confidence": trace.overall_confidence,
            "explanation": trace.explanation,
            "reasoning_path": trace.reasoning_path,
            "metadata": trace.metadata,
            "created_at": trace.created_at
        }
        
        # Should be JSON serializable
        json_str = json.dumps(trace_dict, default=str)
        assert len(json_str) > 0
        
        # Should be able to parse back
        parsed = json.loads(json_str)
        assert parsed["trace_id"] == "test_trace"
        assert len(parsed["steps"]) == 1
    
    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_reasoner):
        """Test API-level error handling."""
        
        # Test with problematic query that might cause issues
        problematic_queries = [
            "",  # Empty query
            "a" * 10000,  # Very long query
            "query with special chars: @#$%^&*()",  # Special characters
            None  # None query (would cause error before reaching reasoner)
        ]
        
        for query in problematic_queries[:-1]:  # Skip None for now
            try:
                trace = await mock_reasoner.reason(query)
                # Should handle gracefully
                assert isinstance(trace, ReasoningTrace)
                assert trace.query == query
            except Exception as e:
                # If it fails, should be a controlled failure
                assert isinstance(e, (ValueError, TypeError))
    
    def test_reasoning_summary_api_response(self, mock_reasoner):
        """Test reasoning summary for API responses."""
        # Create a sample trace
        from brain_researcher.services.agent.cot_reasoning import ReasoningStep
        
        steps = [
            ReasoningStep("step_1", 1, ReasoningType.ANALYTICAL, "p1", "i1", "c1", 0.9),
            ReasoningStep("step_2", 2, ReasoningType.ANALYTICAL, "p2", "i2", "c2", 0.7),
        ]
        
        trace = ReasoningTrace(
            "test_id", "test query", steps, "conclusion", 0.8, "explanation",
            metadata={"reasoning_type": "analytical", "generation_time": 2.5}
        )
        
        summary = mock_reasoner.get_reasoning_summary(trace)
        
        # Summary should have all expected fields for API
        expected_fields = [
            "trace_id", "query", "reasoning_type", "total_steps",
            "high_confidence_steps", "overall_confidence", "confidence_level",
            "final_conclusion", "generation_time", "validation_issues"
        ]
        
        for field in expected_fields:
            assert field in summary, f"Missing field: {field}"
        
        # Values should be appropriate for API consumption
        assert summary["total_steps"] == 2
        assert summary["high_confidence_steps"] == 1
        assert summary["confidence_level"] in ["Low", "Medium", "High"]


class TestErrorRecovery:
    """Test error recovery and resilience."""
    
    @pytest.mark.asyncio
    async def test_llm_failure_recovery(self, mock_reasoner):
        """Test recovery when LLM calls fail."""
        
        # Mock LLM to raise exception
        mock_reasoner.llm.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
        
        # Should handle gracefully and return a fallback trace
        trace = await mock_reasoner.reason("test query")
        
        # Should still return a valid trace, possibly with fallback reasoning
        assert isinstance(trace, ReasoningTrace)
        assert trace.query == "test query"
        # May have fallback steps or empty steps
        assert isinstance(trace.steps, list)
    
    @pytest.mark.asyncio
    async def test_malformed_llm_response_recovery(self):
        """Test recovery from malformed LLM responses."""
        
        # Create mock LLM that returns malformed JSON
        class MalformedMockLLM:
            async def ainvoke(self, inputs):
                mock_response = MagicMock()
                mock_response.content = "{ invalid json response"
                return mock_response
        
        reasoner = ChainOfThoughtReasoner(MalformedMockLLM())
        trace = await reasoner.reason("test query")
        
        # Should recover with fallback reasoning
        assert isinstance(trace, ReasoningTrace)
        assert len(trace.steps) > 0  # Should have fallback step
        assert trace.steps[0].premise == "Query: test query"
    
    @pytest.mark.asyncio
    async def test_validation_failure_handling(self, mock_reasoner):
        """Test handling of validation failures."""
        
        # Force validation to find issues
        with patch.object(mock_reasoner.validator, 'validate_trace') as mock_validate:
            mock_validate.return_value = ["Validation error 1", "Validation error 2"]
            
            trace = await mock_reasoner.reason("test query")
            
            # Should still complete but with validation warnings
            assert isinstance(trace, ReasoningTrace)
            assert len(trace.metadata.get("validation_issues", [])) == 2
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self, mock_reasoner):
        """Test handling of operation timeouts."""
        
        # Mock slow LLM response
        async def slow_response(inputs):
            await asyncio.sleep(0.5)
            mock_response = MagicMock()
            mock_response.content = "ANALYTICAL"
            return mock_response
        
        mock_reasoner.llm.ainvoke = slow_response
        
        # Should complete within reasonable time
        start_time = time.time()
        trace = await mock_reasoner.reason("test query")
        elapsed = time.time() - start_time
        
        assert isinstance(trace, ReasoningTrace)
        # Should not take too long (allowing for mock delays)
        assert elapsed < 5.0


class TestPerformanceIntegration:
    """Test performance characteristics in integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_concurrent_reasoning_performance(self):
        """Test performance with concurrent reasoning requests."""
        mock_llm = MockLLMClient()
        reasoner = ChainOfThoughtReasoner(mock_llm)
        
        # Create multiple concurrent reasoning tasks
        queries = [
            "analyze working memory activation",
            "compare brain networks",
            "examine connectivity patterns",
            "decode stimulus information",
            "visualize statistical maps"
        ]
        
        start_time = time.time()
        
        # Run concurrently
        tasks = [reasoner.reason(query) for query in queries]
        traces = await asyncio.gather(*tasks)
        
        elapsed = time.time() - start_time
        
        # All should succeed
        assert len(traces) == 5
        assert all(isinstance(trace, ReasoningTrace) for trace in traces)
        
        # Should be reasonably fast (accounting for mock delays)
        assert elapsed < 10.0
        
        # Each trace should be valid
        for trace in traces:
            assert trace.query in queries
            assert trace.overall_confidence >= 0.0
    
    @pytest.mark.asyncio
    async def test_memory_usage_with_large_reasoning_chains(self, mock_reasoner):
        """Test memory usage with large reasoning chains."""
        
        # Test with maximum allowed steps
        trace = await mock_reasoner.reason("complex analysis query", max_steps=mock_reasoner.max_steps)
        
        assert isinstance(trace, ReasoningTrace)
        assert len(trace.steps) <= mock_reasoner.max_steps
        
        # Memory usage should be reasonable (trace should not consume excessive memory)
        # This is a basic check - in a real scenario you'd use memory profiling tools
        assert len(str(trace)) < 1000000  # Less than 1MB when serialized
    
    @pytest.mark.asyncio
    async def test_reasoning_quality_consistency(self):
        """Test that reasoning quality is consistent across multiple runs."""
        mock_llm = MockLLMClient()
        reasoner = ChainOfThoughtReasoner(mock_llm)
        
        query = "analyze working memory activation in prefrontal cortex"
        
        # Run same query multiple times
        traces = []
        for _ in range(3):
            trace = await reasoner.reason(query)
            traces.append(trace)
        
        # Results should be consistent
        assert all(trace.query == query for trace in traces)
        
        # Confidence scores should be similar (within reasonable range)
        confidences = [trace.overall_confidence for trace in traces]
        confidence_range = max(confidences) - min(confidences)
        assert confidence_range < 0.3  # Should not vary too much
        
        # All should have reasonable step counts
        step_counts = [len(trace.steps) for trace in traces]
        assert all(count > 0 for count in step_counts)


class TestFactoryFunction:
    """Test the factory function for creating CoT reasoners."""
    
    def test_get_cot_reasoner_factory(self):
        """Test factory function creates proper reasoner."""
        mock_llm = MagicMock()
        reasoner = get_cot_reasoner(mock_llm)
        
        assert isinstance(reasoner, ChainOfThoughtReasoner)
        assert reasoner.llm == mock_llm
        assert hasattr(reasoner, 'templates')
        assert hasattr(reasoner, 'validator')
    
    def test_factory_with_different_llm_types(self):
        """Test factory works with different LLM client types."""
        
        # Test with different mock types
        llm_types = [
            MagicMock(),
            AsyncMock(),
            MockLLMClient()
        ]
        
        for llm in llm_types:
            reasoner = get_cot_reasoner(llm)
            assert isinstance(reasoner, ChainOfThoughtReasoner)
            assert reasoner.llm == llm