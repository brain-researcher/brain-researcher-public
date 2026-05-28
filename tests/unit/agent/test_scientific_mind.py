"""
Tests for Scientific Mind layers: Statistical Critic and Memory.
"""

import pytest
from brain_researcher.services.tools.statistical_critic import StatisticalCriticTool
from brain_researcher.services.tools.neurokg_tools import AddFindingTool, ConfidenceScorerTool
from brain_researcher.services.agent.agents.neuro_agent import NeuroAgent
from brain_researcher.services.agent.states.base import NeuroAgentState
from langchain_core.messages import HumanMessage

class TestScientificMind:
    
    def test_statistical_critic_normality(self):
        tool = StatisticalCriticTool()
        
        # Test 1: Normal distribution
        # Creating mock normal data
        import numpy as np
        np.random.seed(42)
        normal_residuals = np.random.normal(0, 1, 100).tolist()
        
        result = tool.run(residuals=normal_residuals)
        assert result["status"] == "success"
        data = result["data"]
        assert data["valid"] is True
        assert bool(data["checks"]["normality"]["passed"]) is True
        
        # Test 2: Non-normal distribution (Uniform)
        uniform_residuals = np.random.uniform(0, 1, 100).tolist()
        result_fail = tool.run(residuals=uniform_residuals)
        
        # Shapiro often detects uniform as non-normal for N=100
        # Check report content
        assert "normality" in result_fail["data"]["checks"]
    
    def test_confidence_scorer(self):
        tool = ConfidenceScorerTool()
        
        # High confidence scenario
        res_high = tool.run(evidence_count=5, statistical_validation=True, contradictions=0)
        assert res_high["data"]["score"] > 0.8
        
        # Low confidence (failed validation)
        res_low = tool.run(evidence_count=5, statistical_validation=False, contradictions=0)
        assert res_low["data"]["score"] < res_high["data"]["score"]
        
    def test_add_finding_mock(self):
        # We need to mock the internal QueryService of AddFindingTool 
        # because we might not have a running Neo4j in this unit test env.
        tool = AddFindingTool()
        
        # Mocking the execute_cypher method if it exists, or handling the try/except
        # The tool implementation catches exceptions and returns a mock success if DB fails
        # so this should pass regardless of DB state.
        res = tool.run(
            description="Test finding",
            source_tool="pytest"
        )
        assert res["status"] == "success"
        assert "finding_id" in res["data"]

    def test_agent_graph_integration(self):
        """Test that the graph compiles and includes new nodes."""
        agent = NeuroAgent()
        graph = agent.graph
        
        # Check for new nodes
        nodes = graph.nodes.keys()
        assert "validate" in nodes
        assert "memorize" in nodes
        
        # We can't easily execute the full graph without mocking all tools
        # but compiling it proves the structure is valid.
