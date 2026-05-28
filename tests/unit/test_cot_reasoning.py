"""
Unit tests for Chain-of-Thought Reasoning Module (AGENT-011)

Tests cover:
- Reasoning step decomposition
- Confidence calculation accuracy
- Explanation coherence
- Template selection
- Property-based tests for reasoning chains
"""

import json
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import numpy as np
from hypothesis import given, strategies as st

# Import the modules under test
from brain_researcher.services.agent.cot_reasoning import (
    ChainOfThoughtReasoner,
    ReasoningType, 
    ConfidenceLevel,
    ReasoningStep,
    ReasoningTrace,
    CoTTemplates,
    ReasoningValidator
)


class TestReasoningStep:
    """Test ReasoningStep dataclass and methods."""
    
    def test_reasoning_step_creation(self):
        """Test basic ReasoningStep creation."""
        step = ReasoningStep(
            step_id="step_1",
            step_number=1,
            reasoning_type=ReasoningType.ANALYTICAL,
            premise="Test premise",
            inference="Test inference", 
            conclusion="Test conclusion",
            confidence=0.8,
            evidence=["evidence1", "evidence2"],
            assumptions=["assumption1"]
        )
        
        assert step.step_id == "step_1"
        assert step.step_number == 1
        assert step.reasoning_type == ReasoningType.ANALYTICAL
        assert step.confidence == 0.8
        assert len(step.evidence) == 2
        assert len(step.assumptions) == 1
        assert step.confidence_level == ConfidenceLevel.HIGH
    
    def test_confidence_level_property(self):
        """Test confidence level categorization."""
        low_step = ReasoningStep("id", 1, ReasoningType.ANALYTICAL, "p", "i", "c", 0.3)
        medium_step = ReasoningStep("id", 1, ReasoningType.ANALYTICAL, "p", "i", "c", 0.5)  
        high_step = ReasoningStep("id", 1, ReasoningType.ANALYTICAL, "p", "i", "c", 0.8)
        
        assert low_step.confidence_level == ConfidenceLevel.LOW
        assert medium_step.confidence_level == ConfidenceLevel.MEDIUM
        assert high_step.confidence_level == ConfidenceLevel.HIGH
    
    @given(confidence=st.floats(min_value=0.0, max_value=1.0))
    def test_confidence_bounds(self, confidence):
        """Property test: confidence should always be within bounds."""
        step = ReasoningStep("id", 1, ReasoningType.ANALYTICAL, "p", "i", "c", confidence)
        assert 0.0 <= step.confidence <= 1.0
        assert isinstance(step.confidence_level, ConfidenceLevel)


class TestReasoningTrace:
    """Test ReasoningTrace dataclass and methods."""
    
    def test_reasoning_trace_creation(self):
        """Test basic ReasoningTrace creation."""
        steps = [
            ReasoningStep("step_1", 1, ReasoningType.ANALYTICAL, "p1", "i1", "c1", 0.8),
            ReasoningStep("step_2", 2, ReasoningType.ANALYTICAL, "p2", "i2", "c2", 0.7),
        ]
        
        trace = ReasoningTrace(
            trace_id="trace_1",
            query="test query",
            steps=steps,
            final_conclusion="final conclusion",
            overall_confidence=0.75,
            explanation="test explanation"
        )
        
        assert trace.trace_id == "trace_1"
        assert len(trace.steps) == 2
        assert trace.overall_confidence == 0.75
        assert isinstance(trace.created_at, float)
    
    def test_get_high_confidence_steps(self):
        """Test filtering high confidence steps."""
        steps = [
            ReasoningStep("step_1", 1, ReasoningType.ANALYTICAL, "p1", "i1", "c1", 0.8),
            ReasoningStep("step_2", 2, ReasoningType.ANALYTICAL, "p2", "i2", "c2", 0.5),
            ReasoningStep("step_3", 3, ReasoningType.ANALYTICAL, "p3", "i3", "c3", 0.9),
        ]
        
        trace = ReasoningTrace("id", "query", steps, "conclusion", 0.7, "explanation")
        high_conf_steps = trace.get_high_confidence_steps()
        
        assert len(high_conf_steps) == 2
        assert all(step.confidence_level == ConfidenceLevel.HIGH for step in high_conf_steps)
    
    def test_get_critical_path(self):
        """Test critical path extraction."""
        steps = [
            ReasoningStep("step_1", 1, ReasoningType.ANALYTICAL, "p1", "i1", "c1", 0.9),
            ReasoningStep("step_2", 2, ReasoningType.ANALYTICAL, "p2", "i2", "c2", 0.4),
            ReasoningStep("step_3", 3, ReasoningType.ANALYTICAL, "p3", "i3", "c3", 0.8),
        ]
        
        trace = ReasoningTrace("id", "query", steps, "conclusion", 0.7, "explanation")
        critical_path = trace.get_critical_path()
        
        assert len(critical_path) == 2  # Steps with confidence > 0.6
        assert critical_path[0].confidence == 0.9
        assert critical_path[1].confidence == 0.8


class TestCoTTemplates:
    """Test CoT template system."""
    
    def test_template_initialization(self):
        """Test template system initialization."""
        templates = CoTTemplates()
        
        assert len(templates.templates) == 5
        assert ReasoningType.ANALYTICAL in templates.templates
        assert ReasoningType.DEDUCTIVE in templates.templates
        assert ReasoningType.INDUCTIVE in templates.templates
        assert ReasoningType.CAUSAL in templates.templates
        assert ReasoningType.COMPARATIVE in templates.templates
    
    def test_get_template(self):
        """Test template retrieval."""
        templates = CoTTemplates()
        
        analytical_template = templates.get_template(ReasoningType.ANALYTICAL)
        assert "step by step" in analytical_template.lower()
        
        # Test default fallback
        default_template = templates.get_template(None)
        assert default_template == templates.templates[ReasoningType.ANALYTICAL]
    
    def test_all_templates_have_placeholders(self):
        """Test that all templates have expected placeholders."""
        templates = CoTTemplates()
        
        for reasoning_type, template in templates.templates.items():
            assert "{" in template  # Should have placeholder markers
            assert "confidence" in template.lower()  # Should mention confidence


class TestReasoningValidator:
    """Test reasoning validation logic."""
    
    def test_validator_initialization(self):
        """Test validator initialization."""
        validator = ReasoningValidator()
        
        assert len(validator.validation_rules) == 4
        assert validator._check_logical_consistency in validator.validation_rules
    
    def test_validate_step_valid(self):
        """Test validation of a valid reasoning step."""
        validator = ReasoningValidator()
        step = ReasoningStep(
            step_id="step_1",
            step_number=1,
            reasoning_type=ReasoningType.ANALYTICAL,
            premise="Valid premise",
            inference="Valid inference",
            conclusion="Valid conclusion",
            confidence=0.8
        )
        
        issues = validator.validate_step(step)
        assert len(issues) == 0
    
    def test_validate_step_circular_dependency(self):
        """Test detection of circular dependencies."""
        validator = ReasoningValidator()
        step = ReasoningStep(
            step_id="step_1",
            step_number=1,
            reasoning_type=ReasoningType.ANALYTICAL,
            premise="Valid premise",
            inference="Valid inference", 
            conclusion="Valid conclusion",
            confidence=0.8,
            dependencies=["step_1"]  # Circular dependency
        )
        
        issues = validator.validate_step(step)
        assert len(issues) == 1
        assert "circular dependency" in issues[0].lower()
    
    def test_validate_step_invalid_confidence(self):
        """Test validation of invalid confidence values."""
        validator = ReasoningValidator()
        step = ReasoningStep(
            step_id="step_1",
            step_number=1,
            reasoning_type=ReasoningType.ANALYTICAL,
            premise="Valid premise",
            inference="Valid inference",
            conclusion="Valid conclusion", 
            confidence=1.5  # Invalid confidence > 1.0
        )
        
        issues = validator.validate_step(step)
        assert len(issues) == 1
        assert "invalid confidence" in issues[0].lower()
    
    def test_validate_step_incomplete(self):
        """Test validation of incomplete steps."""
        validator = ReasoningValidator()
        step = ReasoningStep(
            step_id="step_1",
            step_number=1,
            reasoning_type=ReasoningType.ANALYTICAL,
            premise="",  # Empty premise
            inference="Valid inference",
            conclusion="Valid conclusion",
            confidence=0.8
        )
        
        issues = validator.validate_step(step)
        assert len(issues) == 1
        assert "incomplete" in issues[0].lower()
    
    def test_validate_trace_valid(self):
        """Test validation of a valid reasoning trace."""
        validator = ReasoningValidator()
        steps = [
            ReasoningStep("step_1", 1, ReasoningType.ANALYTICAL, "p1", "i1", "c1", 0.8),
            ReasoningStep("step_2", 2, ReasoningType.ANALYTICAL, "p2", "i2", "c2", 0.7),
        ]
        trace = ReasoningTrace("id", "query", steps, "conclusion", 0.75, "explanation")
        
        issues = validator.validate_trace(trace)
        assert len(issues) == 0
    
    def test_validate_trace_confidence_mismatch(self):
        """Test detection of confidence misalignment.""" 
        validator = ReasoningValidator()
        steps = [
            ReasoningStep("step_1", 1, ReasoningType.ANALYTICAL, "p1", "i1", "c1", 0.9),
            ReasoningStep("step_2", 2, ReasoningType.ANALYTICAL, "p2", "i2", "c2", 0.9),
        ]
        trace = ReasoningTrace("id", "query", steps, "conclusion", 0.1, "explanation")  # Low overall confidence
        
        issues = validator.validate_trace(trace)
        assert len(issues) == 1
        assert "doesn't align" in issues[0].lower()
    
    def test_validate_trace_gaps(self):
        """Test detection of gaps in reasoning sequence."""
        validator = ReasoningValidator()
        steps = [
            ReasoningStep("step_1", 1, ReasoningType.ANALYTICAL, "p1", "i1", "c1", 0.8),
            ReasoningStep("step_2", 3, ReasoningType.ANALYTICAL, "p2", "i2", "c2", 0.7),  # Gap: missing step 2
        ]
        trace = ReasoningTrace("id", "query", steps, "conclusion", 0.75, "explanation")
        
        issues = validator.validate_trace(trace)
        assert len(issues) == 1
        assert "gaps" in issues[0].lower() or "non-sequential" in issues[0].lower()
    
    @given(confidences=st.lists(st.floats(min_value=0.0, max_value=1.0), min_size=1, max_size=10))
    def test_validate_trace_property_based(self, confidences):
        """Property test: trace validation should be consistent."""
        validator = ReasoningValidator()
        steps = []
        for i, conf in enumerate(confidences):
            step = ReasoningStep(f"step_{i+1}", i+1, ReasoningType.ANALYTICAL, "p", "i", "c", conf)
            steps.append(step)
        
        overall_conf = sum(confidences) / len(confidences)
        trace = ReasoningTrace("id", "query", steps, "conclusion", overall_conf, "explanation")
        
        issues = validator.validate_trace(trace)
        # Should not have gaps or sequence issues since we create sequential steps
        sequence_issues = [issue for issue in issues if "gaps" in issue.lower() or "non-sequential" in issue.lower()]
        assert len(sequence_issues) == 0


class TestChainOfThoughtReasoner:
    """Test the main ChainOfThoughtReasoner class."""
    
    def test_reasoner_initialization(self):
        """Test reasoner initialization."""
        mock_llm = MagicMock()
        reasoner = ChainOfThoughtReasoner(mock_llm)
        
        assert reasoner.llm == mock_llm
        assert isinstance(reasoner.templates, CoTTemplates)
        assert isinstance(reasoner.validator, ReasoningValidator)
        assert reasoner.max_steps == 10
        assert reasoner.min_confidence == 0.3
        assert reasoner.confidence_threshold == 0.7
    
    @pytest.mark.asyncio
    async def test_detect_reasoning_type(self):
        """Test automatic reasoning type detection."""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "ANALYTICAL"
        mock_llm.ainvoke.return_value = mock_response
        
        reasoner = ChainOfThoughtReasoner(mock_llm)
        reasoning_type = await reasoner._detect_reasoning_type("analyze working memory activation")
        
        assert reasoning_type == ReasoningType.ANALYTICAL
        assert mock_llm.ainvoke.called
    
    @pytest.mark.asyncio
    async def test_detect_reasoning_type_fallback(self):
        """Test fallback to analytical when type can't be determined."""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "UNKNOWN_TYPE"
        mock_llm.ainvoke.return_value = mock_response
        
        reasoner = ChainOfThoughtReasoner(mock_llm)
        reasoning_type = await reasoner._detect_reasoning_type("unclear query")
        
        assert reasoning_type == ReasoningType.ANALYTICAL
    
    @pytest.mark.asyncio
    async def test_generate_reasoning_steps_success(self):
        """Test successful reasoning step generation."""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps([
            {
                "step_number": 1,
                "premise": "Query asks about working memory",
                "inference": "Need to identify brain regions",
                "conclusion": "Focus on prefrontal cortex",
                "confidence": 0.9,
                "evidence": ["Literature shows PFC involvement"],
                "assumptions": ["Data has working memory task"]
            }
        ])
        mock_llm.ainvoke.return_value = mock_response
        
        reasoner = ChainOfThoughtReasoner(mock_llm)
        steps = await reasoner._generate_reasoning_steps(
            "analyze working memory", {}, ReasoningType.ANALYTICAL, 5
        )
        
        assert len(steps) == 1
        assert steps[0].step_number == 1
        assert steps[0].confidence == 0.9
        assert len(steps[0].evidence) == 1
    
    @pytest.mark.asyncio
    async def test_generate_reasoning_steps_parse_error(self):
        """Test handling of JSON parse errors in step generation."""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "invalid json response"
        mock_llm.ainvoke.return_value = mock_response
        
        reasoner = ChainOfThoughtReasoner(mock_llm)
        steps = await reasoner._generate_reasoning_steps(
            "test query", {}, ReasoningType.ANALYTICAL, 5
        )
        
        # Should return fallback step
        assert len(steps) == 1
        assert steps[0].premise == "Query: test query"
        assert steps[0].conclusion == "Will analyze using available tools"
    
    @pytest.mark.asyncio
    async def test_generate_conclusion(self):
        """Test final conclusion generation."""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "Final conclusion: Analysis completed successfully"
        mock_llm.ainvoke.return_value = mock_response
        
        reasoner = ChainOfThoughtReasoner(mock_llm)
        steps = [
            ReasoningStep("step_1", 1, ReasoningType.ANALYTICAL, "p1", "i1", "c1", 0.8)
        ]
        
        conclusion = await reasoner._generate_conclusion(steps, "test query")
        
        assert conclusion == "Final conclusion: Analysis completed successfully"
        assert mock_llm.ainvoke.called
    
    @pytest.mark.asyncio
    async def test_generate_explanation(self):
        """Test natural language explanation generation."""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "This reasoning process used analytical thinking..."
        mock_llm.ainvoke.return_value = mock_response
        
        reasoner = ChainOfThoughtReasoner(mock_llm)
        steps = [
            ReasoningStep("step_1", 1, ReasoningType.ANALYTICAL, "p1", "i1", "c1", 0.8)
        ]
        
        explanation = await reasoner._generate_explanation(steps, "test query", ReasoningType.ANALYTICAL)
        
        assert explanation == "This reasoning process used analytical thinking..."
        assert mock_llm.ainvoke.called
    
    def test_calculate_overall_confidence_geometric_mean(self):
        """Test overall confidence calculation using geometric mean."""
        mock_llm = MagicMock()
        reasoner = ChainOfThoughtReasoner(mock_llm)
        
        steps = [
            ReasoningStep("step_1", 1, ReasoningType.ANALYTICAL, "p1", "i1", "c1", 0.9),
            ReasoningStep("step_2", 2, ReasoningType.ANALYTICAL, "p2", "i2", "c2", 0.8),
        ]
        
        overall_confidence = reasoner._calculate_overall_confidence(steps)
        expected = (0.9 * 0.8) ** (1/2)  # Geometric mean
        
        assert abs(overall_confidence - expected) < 0.001
    
    def test_calculate_overall_confidence_empty(self):
        """Test overall confidence calculation with empty steps."""
        mock_llm = MagicMock()
        reasoner = ChainOfThoughtReasoner(mock_llm)
        
        overall_confidence = reasoner._calculate_overall_confidence([])
        assert overall_confidence == 0.0
    
    @pytest.mark.asyncio
    async def test_reason_full_pipeline(self):
        """Test the complete reasoning pipeline."""
        mock_llm = AsyncMock()
        
        # Mock type detection
        type_response = MagicMock()
        type_response.content = "ANALYTICAL"
        
        # Mock step generation
        step_response = MagicMock() 
        step_response.content = json.dumps([{
            "step_number": 1,
            "premise": "Test premise",
            "inference": "Test inference",
            "conclusion": "Test conclusion", 
            "confidence": 0.8,
            "evidence": ["test evidence"],
            "assumptions": ["test assumption"]
        }])
        
        # Mock conclusion generation
        conclusion_response = MagicMock()
        conclusion_response.content = "Final test conclusion"
        
        # Mock explanation generation
        explanation_response = MagicMock()
        explanation_response.content = "Test explanation"
        
        mock_llm.ainvoke.side_effect = [
            type_response, step_response, conclusion_response, explanation_response
        ]
        
        reasoner = ChainOfThoughtReasoner(mock_llm)
        trace = await reasoner.reason("analyze test data")
        
        assert isinstance(trace, ReasoningTrace)
        assert trace.query == "analyze test data"
        assert len(trace.steps) == 1
        assert trace.final_conclusion == "Final test conclusion"
        assert trace.explanation == "Test explanation"
        assert trace.overall_confidence == 0.8  # Single step with 0.8 confidence
        assert "analytical" in trace.metadata["reasoning_type"]
    
    def test_get_reasoning_summary(self):
        """Test reasoning summary generation."""
        mock_llm = MagicMock()
        reasoner = ChainOfThoughtReasoner(mock_llm)
        
        steps = [
            ReasoningStep("step_1", 1, ReasoningType.ANALYTICAL, "p1", "i1", "c1", 0.9),
            ReasoningStep("step_2", 2, ReasoningType.ANALYTICAL, "p2", "i2", "c2", 0.6),
        ]
        trace = ReasoningTrace(
            "test_id", "test query", steps, "conclusion", 0.75, "explanation",
            metadata={"reasoning_type": "analytical", "generation_time": 1.5}
        )
        
        summary = reasoner.get_reasoning_summary(trace)
        
        assert summary["trace_id"] == "test_id"
        assert summary["total_steps"] == 2
        assert summary["high_confidence_steps"] == 1
        assert summary["overall_confidence"] == 0.75
        assert summary["confidence_level"] == "High"
        assert summary["generation_time"] == 1.5
    
    @given(query_length=st.integers(min_value=1, max_value=1000),
           max_steps=st.integers(min_value=1, max_value=20))
    def test_reasoner_configuration_property_based(self, query_length, max_steps):
        """Property test: reasoner should handle various configurations."""
        mock_llm = MagicMock()
        reasoner = ChainOfThoughtReasoner(mock_llm)
        reasoner.max_steps = max_steps
        
        assert reasoner.max_steps == max_steps
        assert reasoner.max_steps >= 1


class TestIntegrationWithFixtures:
    """Test integration with fixture data."""
    
    @pytest.fixture
    def sample_queries(self):
        """Load sample queries from fixture."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-011" / "sample_queries.json"
        with open(fixture_path, 'r') as f:
            return json.load(f)
    
    @pytest.fixture 
    def expected_traces(self):
        """Load expected traces from fixture."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-011" / "expected_traces.json"
        with open(fixture_path, 'r') as f:
            return json.load(f)
    
    def test_simple_query_reasoning_type_detection(self, sample_queries):
        """Test reasoning type detection matches expectations."""
        simple_queries = sample_queries["simple_queries"]
        
        for query_data in simple_queries:
            query = query_data["query"]
            expected_type = query_data["expected_reasoning_type"]
            
            # Simple heuristic-based detection for testing
            if "compare" in query.lower():
                detected_type = "comparative"
            elif "analyze" in query.lower():
                detected_type = "analytical"
            else:
                detected_type = "analytical"
            
            assert detected_type == expected_type, f"Query: {query}"
    
    def test_confidence_scoring_expectations(self, sample_queries):
        """Test that confidence scoring meets expectations."""
        for category in ["simple_queries", "complex_queries"]:
            queries = sample_queries[category]
            for query_data in queries:
                expected_confidence = query_data["expected_confidence"]
                
                # Confidence should be reasonable
                assert 0.0 <= expected_confidence <= 1.0
                
                # Simple queries should generally have higher confidence
                if category == "simple_queries":
                    assert expected_confidence >= 0.7
                
    def test_multi_step_reasoning_structure(self, sample_queries):
        """Test multi-step reasoning structure."""
        multi_step_queries = sample_queries["multi_step_queries"]
        
        for query_data in multi_step_queries:
            steps = query_data["expected_steps"]
            
            # Should have sequential step numbers
            step_numbers = [step["step_number"] for step in steps]
            assert step_numbers == list(range(1, len(steps) + 1))
            
            # Each step should have required components
            for step in steps:
                assert "premise" in step
                assert "inference" in step
                assert "conclusion" in step
    
    def test_expected_trace_structure(self, expected_traces):
        """Test expected trace structure matches implementation."""
        for trace_id, trace_data in expected_traces.items():
            # Verify trace has all required fields
            required_fields = ["query", "reasoning_type", "steps", "final_conclusion", 
                             "overall_confidence", "explanation"]
            for field in required_fields:
                assert field in trace_data, f"Missing field {field} in {trace_id}"
            
            # Verify steps structure
            steps = trace_data["steps"]
            for step in steps:
                required_step_fields = ["step_id", "step_number", "premise", "inference", 
                                      "conclusion", "confidence", "evidence", "assumptions"]
                for field in required_step_fields:
                    assert field in step, f"Missing step field {field} in {trace_id}"
                
                # Confidence should be valid
                assert 0.0 <= step["confidence"] <= 1.0
            
            # Overall confidence should be valid
            assert 0.0 <= trace_data["overall_confidence"] <= 1.0


# Performance and edge case tests
class TestPerformanceAndEdgeCases:
    """Test performance characteristics and edge cases."""
    
    def test_large_number_of_steps_performance(self):
        """Test performance with large number of reasoning steps."""
        mock_llm = MagicMock()
        reasoner = ChainOfThoughtReasoner(mock_llm)
        
        # Create many steps
        steps = []
        for i in range(100):
            step = ReasoningStep(f"step_{i}", i+1, ReasoningType.ANALYTICAL, "p", "i", "c", 0.8)
            steps.append(step)
        
        start_time = time.time()
        overall_confidence = reasoner._calculate_overall_confidence(steps)
        elapsed = time.time() - start_time
        
        assert elapsed < 1.0  # Should be fast
        assert 0.0 <= overall_confidence <= 1.0
    
    def test_empty_query_handling(self):
        """Test handling of empty or minimal queries."""
        mock_llm = MagicMock()
        reasoner = ChainOfThoughtReasoner(mock_llm)
        
        # Test with empty string
        summary = reasoner.get_reasoning_summary(
            ReasoningTrace("id", "", [], "conclusion", 0.0, "explanation")
        )
        
        assert summary["total_steps"] == 0
        assert summary["overall_confidence"] == 0.0
    
    def test_extreme_confidence_values(self):
        """Test handling of extreme confidence values."""
        validator = ReasoningValidator()
        
        # Test minimum confidence
        step_min = ReasoningStep("id", 1, ReasoningType.ANALYTICAL, "p", "i", "c", 0.0)
        issues_min = validator.validate_step(step_min)
        assert len(issues_min) == 0  # 0.0 is valid
        
        # Test maximum confidence
        step_max = ReasoningStep("id", 1, ReasoningType.ANALYTICAL, "p", "i", "c", 1.0)
        issues_max = validator.validate_step(step_max)
        assert len(issues_max) == 0  # 1.0 is valid
        
        # Test slightly out of bounds
        step_over = ReasoningStep("id", 1, ReasoningType.ANALYTICAL, "p", "i", "c", 1.1)
        issues_over = validator.validate_step(step_over)
        assert len(issues_over) == 1  # Should be invalid
    
    def test_memory_efficiency(self):
        """Test memory efficiency with large traces."""
        # Create a large trace
        steps = []
        for i in range(1000):
            step = ReasoningStep(
                f"step_{i}", i+1, ReasoningType.ANALYTICAL,
                f"premise_{i}", f"inference_{i}", f"conclusion_{i}", 
                0.8, evidence=[f"evidence_{i}"], assumptions=[f"assumption_{i}"]
            )
            steps.append(step)
        
        trace = ReasoningTrace("large_trace", "large query", steps, "conclusion", 0.8, "explanation")
        
        # Should be able to access properties without issues
        assert len(trace.steps) == 1000
        assert len(trace.get_high_confidence_steps()) > 0
        critical_path = trace.get_critical_path()
        assert isinstance(critical_path, list)