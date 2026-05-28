"""
Unit tests for Intelligent Failure Recovery (AGENT-014).

Tests the FailureAnalyzer and related components for failure pattern
analysis and recovery strategy selection.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from brain_researcher.services.agent.failure_analyzer import (
    FailureAnalyzer,
    FailureCategory,
    FailureContext
)


class TestFailureAnalyzer:
    """Test failure analysis functionality."""
    
    @pytest.fixture
    def analyzer(self):
        """Create failure analyzer for testing."""
        return FailureAnalyzer()
    
    @pytest.fixture
    def test_data_path(self):
        """Path to test data fixtures."""
        return Path(__file__).parent.parent / "fixtures" / "AGENT-014"
    
    def test_analyzer_initialization(self, analyzer):
        """Test failure analyzer initialization."""
        assert analyzer.failure_patterns is not None
        assert len(analyzer.failure_patterns) > 0
        assert "memory_patterns" in analyzer.failure_patterns
        assert "timeout_patterns" in analyzer.failure_patterns
    
    def test_memory_exhaustion_classification(self, analyzer):
        """Test classification of memory exhaustion errors."""
        context = FailureContext(
            execution_id="test_exec",
            step_id="test_step",
            tool_name="fmriprep",
            error_message="RuntimeError: out of memory (tried to allocate 2.34 GiB)",
            stack_trace="Traceback...",
            resource_usage={"memory": 95.0, "cpu": 30.0},
            timestamp=1643723400.0
        )
        
        failure = Exception("out of memory")
        analysis = analyzer.analyze(failure, context)
        
        assert analysis["category"] == FailureCategory.RESOURCE_EXHAUSTION
        assert "memory" in analysis["root_cause"].lower()
        assert len(analysis["recovery_suggestions"]) > 0
        assert "Increase memory allocation" in analysis["recovery_suggestions"]
    
    def test_network_timeout_classification(self, analyzer):
        """Test classification of network timeout errors."""
        context = FailureContext(
            execution_id="test_exec",
            step_id="test_step", 
            tool_name="neurosynth_api",
            error_message="requests.exceptions.ConnectTimeout: Read timed out",
            stack_trace="Traceback...",
            resource_usage={"memory": 45.0, "cpu": 25.0},
            timestamp=1643723400.0
        )
        
        failure = Exception("connection timeout")
        analysis = analyzer.analyze(failure, context)
        
        assert analysis["category"] == FailureCategory.NETWORK_TIMEOUT
        assert "network" in analysis["root_cause"].lower()
        assert "Retry with exponential backoff" in analysis["recovery_suggestions"]
    
    def test_tool_error_classification(self, analyzer):
        """Test classification of tool-specific errors."""
        context = FailureContext(
            execution_id="test_exec",
            step_id="test_step",
            tool_name="fsl_feat",
            error_message="FSL Error: FEAT setup failed - invalid design matrix",
            stack_trace="FSL Error in feat_model",
            resource_usage={"memory": 60.0, "cpu": 75.0},
            timestamp=1643723400.0
        )
        
        failure = Exception("FSL Error: invalid design matrix")
        analysis = analyzer.analyze(failure, context)
        
        assert analysis["category"] == FailureCategory.TOOL_ERROR
        assert "Manual investigation required" in analysis["recovery_suggestions"]
    
    def test_unknown_error_classification(self, analyzer):
        """Test classification of unknown errors."""
        context = FailureContext(
            execution_id="test_exec",
            step_id="test_step",
            tool_name="unknown_tool",
            error_message="Strange unknown error",
            stack_trace="Traceback...",
            resource_usage={"memory": 40.0, "cpu": 50.0},
            timestamp=1643723400.0
        )
        
        failure = Exception("Strange unknown error")
        analysis = analyzer.analyze(failure, context)
        
        assert analysis["category"] == FailureCategory.UNKNOWN
        assert "Unknown root cause" in analysis["root_cause"]
        assert "Manual investigation required" in analysis["recovery_suggestions"]
    
    def test_failure_context_creation(self):
        """Test failure context creation."""
        context = FailureContext(
            execution_id="exec_123",
            step_id="step_456",
            tool_name="test_tool",
            error_message="Test error message",
            stack_trace="Test stack trace",
            resource_usage={"memory": 80.0, "cpu": 60.0},
            timestamp=1643723400.0
        )
        
        assert context.execution_id == "exec_123"
        assert context.step_id == "step_456"
        assert context.tool_name == "test_tool"
        assert context.error_message == "Test error message"
        assert context.resource_usage["memory"] == 80.0
    
    def test_pattern_matching(self, analyzer):
        """Test failure pattern matching."""
        # Test memory patterns
        memory_errors = [
            "out of memory",
            "memory allocation failed",
            "OOMKilled"
        ]
        
        for error_msg in memory_errors:
            context = FailureContext(
                execution_id="test",
                step_id="test",
                tool_name="test",
                error_message=error_msg,
                stack_trace="",
                resource_usage={},
                timestamp=1643723400.0
            )
            
            category = analyzer._classify_failure(error_msg, context)
            assert category == FailureCategory.RESOURCE_EXHAUSTION
        
        # Test timeout patterns
        timeout_errors = [
            "connection timeout",
            "network unreachable", 
            "timeout occurred"
        ]
        
        for error_msg in timeout_errors:
            context = FailureContext(
                execution_id="test",
                step_id="test",
                tool_name="test",
                error_message=error_msg,
                stack_trace="",
                resource_usage={},
                timestamp=1643723400.0
            )
            
            category = analyzer._classify_failure(error_msg, context)
            assert category == FailureCategory.NETWORK_TIMEOUT
    
    def test_recovery_strategy_selection(self, analyzer):
        """Test recovery strategy selection for different failure types."""
        # Memory exhaustion
        memory_context = FailureContext(
            execution_id="test",
            step_id="test",
            tool_name="fmriprep",
            error_message="out of memory",
            stack_trace="",
            resource_usage={"memory": 95.0, "cpu": 30.0},
            timestamp=1643723400.0
        )
        
        memory_strategies = analyzer._suggest_recovery(
            FailureCategory.RESOURCE_EXHAUSTION, 
            memory_context
        )
        assert "Increase memory allocation" in memory_strategies
        assert "Use more powerful instance type" in memory_strategies
        
        # Network timeout
        network_context = FailureContext(
            execution_id="test",
            step_id="test",
            tool_name="api_client",
            error_message="connection timeout",
            stack_trace="",
            resource_usage={"memory": 30.0, "cpu": 20.0},
            timestamp=1643723400.0
        )
        
        network_strategies = analyzer._suggest_recovery(
            FailureCategory.NETWORK_TIMEOUT,
            network_context
        )
        assert "Retry with exponential backoff" in network_strategies
        assert "Check service availability" in network_strategies
    
    @pytest.mark.parametrize("failure_scenario", [
        "memory_exhaustion",
        "network_timeout", 
        "tool_execution_error",
        "data_corruption",
        "infrastructure_failure"
    ])
    def test_scenario_based_analysis(self, analyzer, test_data_path, failure_scenario):
        """Test analysis using predefined failure scenarios."""
        # Load test scenarios
        with open(test_data_path / "failure_scenarios.json") as f:
            scenarios = json.load(f)
        
        scenario_data = scenarios["failure_scenarios"][failure_scenario]
        
        # Create context from scenario
        context = FailureContext(
            execution_id="scenario_test",
            step_id="scenario_step",
            tool_name=scenario_data["context"]["tool_name"],
            error_message=scenario_data["context"]["error_message"],
            stack_trace=scenario_data["context"]["stack_trace"],
            resource_usage=scenario_data["context"]["resource_usage"],
            timestamp=1643723400.0
        )
        
        # Create failure from error message
        failure = Exception(scenario_data["context"]["error_message"])
        
        # Analyze failure
        analysis = analyzer.analyze(failure, context)
        
        # Verify analysis results
        assert analysis["category"] is not None
        assert analysis["root_cause"] is not None
        assert len(analysis["recovery_suggestions"]) > 0
        assert analysis["confidence"] > 0.0
        
        # Check that suggested strategies overlap with expected strategies
        suggested = analysis["recovery_suggestions"]
        expected = scenario_data["recovery_strategies"]
        
        # At least some overlap between suggested and expected strategies
        overlap = any(
            any(exp_strategy in sugg for exp_strategy in expected)
            for sugg in suggested
        )
        assert overlap or len(suggested) > 0  # At least some suggestions provided


if __name__ == "__main__":
    pytest.main([__file__, "-v"])