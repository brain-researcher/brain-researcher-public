#!/usr/bin/env python3
"""
Test cases for the enhanced /chat endpoint with tool context awareness.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock

from brain_researcher.services.agent import web_service
from brain_researcher.services.agent.router import LLMChatResult, LLMRouteMetadata
from brain_researcher.services.agent.web_service import (
    _build_context_for_query,
    _extract_keywords,
    _get_relevant_tool_context,
    app,
)


def _mock_router_result(text: str) -> LLMChatResult:
    return LLMChatResult(
        text=text,
        metadata=LLMRouteMetadata(
            provider="test",
            model="test-model",
            route="test",
            transport="mock",
        ),
    )


class TestToolContextHelpers:
    """Test the tool context helper functions."""
    
    def test_extract_keywords(self):
        """Test keyword extraction from tool metadata."""
        keywords = _extract_keywords(
            "FSL BET Tool", 
            "Brain extraction tool for fMRI preprocessing",
            "preprocessing"
        )
        
        expected_keywords = {"fsl", "tool", "fmri", "preprocessing"}
        assert expected_keywords.issubset(set(keywords))
    
    def test_build_context_for_general_query(self):
        """Test context building for general tool queries."""
        mock_tools = [
            {"name": "FSL BET", "description": "Brain extraction", "category": "preprocessing", "keywords": ["fsl", "preprocessing"]},
            {"name": "Nilearn GLM", "description": "Statistical analysis", "category": "analysis", "keywords": ["nilearn", "glm"]},
            {"name": "FreeSurfer", "description": "Surface reconstruction", "category": "structural", "keywords": ["freesurfer", "structural"]},
        ]
        
        context = _build_context_for_query("what tools are available?", mock_tools, max_tools=10)
        
        assert "3 specialized tools" in context
        assert "Tool Categories:" in context
        assert "FSL" in context or "Nilearn" in context or "FreeSurfer" in context
    
    def test_build_context_for_specific_query(self):
        """Test context building for specific tool queries."""
        mock_tools = [
            {"name": "FSL BET", "description": "Brain extraction tool", "category": "preprocessing", "keywords": ["fsl", "preprocessing", "brain"]},
            {"name": "Nilearn GLM", "description": "GLM analysis", "category": "analysis", "keywords": ["nilearn", "glm", "statistical"]},
        ]
        
        context = _build_context_for_query("I need brain extraction", mock_tools, max_tools=10)
        
        assert "neuroimaging tools available" in context
        assert "FSL BET" in context
        assert "Brain extraction" in context
    
    @patch("brain_researcher.services.agent.web_service.get_agent")
    def test_get_relevant_tool_context_success(self, mock_get_agent):
        """Test successful tool context retrieval."""
        # Mock agent and tools
        mock_tool = Mock()
        mock_tool.get_tool_name.return_value = "FSL BET"
        mock_tool.get_tool_description.return_value = "Brain extraction tool for fMRI preprocessing"
        mock_tool.CATEGORY = "preprocessing"
        
        mock_agent = Mock()
        mock_agent.tool_registry.get_all_tools.return_value = [mock_tool]
        mock_get_agent.return_value = mock_agent
        
        context = _get_relevant_tool_context("what tools do you have?")
        
        assert context
        assert "specialized tools" in context
        assert mock_get_agent.called
    
    @patch("brain_researcher.services.agent.web_service.get_agent")
    def test_get_relevant_tool_context_failure(self, mock_get_agent):
        """Test graceful failure when tool context retrieval fails."""
        web_service._tool_context_cache = []
        web_service._tool_context_cache_time = 0
        mock_get_agent.side_effect = Exception("Agent initialization failed")

        context = _get_relevant_tool_context("what tools do you have?")
        
        # Should return empty string on failure, not raise exception
        assert context == ""


class TestChatEndpoint:
    """Test the enhanced /chat endpoint."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client
    
    @patch("brain_researcher.services.agent.web_service._get_relevant_tool_context")
    @patch("brain_researcher.services.agent.web_service._LLM_ROUTER.route_chat")
    def test_chat_with_tool_context_enabled(self, mock_route_chat, mock_get_context, client):
        """Test chat endpoint with tool context enabled."""
        # Mock context retrieval
        mock_get_context.return_value = "I have 160 neuroimaging tools including FSL BET for brain extraction."
        
        # Mock router response
        mock_route_chat.return_value = _mock_router_result(
            "I can help you with neuroimaging analysis using my 160 specialized tools!"
        )
        
        # Test request
        response = client.post('/chat', 
                             json={"message": "what tools are available?", "tool_context": True})
        
        assert response.status_code == 200
        data = response.get_json()
        
        # Check response structure
        assert "message" in data
        assert "runCard" in data
        assert data["message"]["role"] == "assistant"
        
        # Check tool context was used
        assert data["runCard"]["execution"]["tool_context_enabled"] is True
        assert data["runCard"]["execution"]["tool_context_length"] > 0
        
        # Verify LLM was called with contextualized query
        mock_route_chat.assert_called_once()
        call_args = mock_route_chat.call_args[0][0]
        assert "I have 160 neuroimaging tools" in call_args
        assert "what tools are available?" in call_args
    
    @patch("brain_researcher.services.agent.web_service._get_relevant_tool_context")
    @patch("brain_researcher.services.agent.web_service._LLM_ROUTER.route_chat")
    def test_chat_with_tool_context_disabled(self, mock_route_chat, mock_get_context, client):
        """Test chat endpoint with tool context disabled."""
        # Mock router response
        mock_route_chat.return_value = _mock_router_result(
            "What kind of tools are you looking for?"
        )
        
        # Test request with tool context disabled
        response = client.post('/chat', 
                             json={"message": "what tools are available?", "tool_context": False})
        
        assert response.status_code == 200
        data = response.get_json()
        
        # Check tool context was not used
        assert data["runCard"]["execution"]["tool_context_enabled"] is False
        assert data["runCard"]["execution"]["tool_context_length"] == 0
        
        # Verify context retrieval was not called
        mock_get_context.assert_not_called()
        
        # Verify LLM was called with original query
        mock_route_chat.assert_called_once()
        call_args = mock_route_chat.call_args[0][0]
        assert call_args == "what tools are available?"
    
    @patch("brain_researcher.services.agent.web_service._get_relevant_tool_context")
    @patch("brain_researcher.services.agent.web_service._LLM_ROUTER.route_chat")
    def test_chat_graceful_failure(self, mock_route_chat, mock_get_context, client):
        """Test chat endpoint handles tool context failures gracefully."""
        # Mock context retrieval failure
        mock_get_context.return_value = ""  # Empty context on failure
        
        # Mock router response
        mock_route_chat.return_value = _mock_router_result("How can I help you?")
        
        # Test request
        response = client.post('/chat', 
                             json={"message": "what tools are available?"})
        
        assert response.status_code == 200
        data = response.get_json()
        
        # Should still work, just without tool context
        assert data["message"]["content"] == "How can I help you?"
        assert data["runCard"]["execution"]["tool_context_enabled"] is False
    
    def test_chat_missing_message(self, client):
        """Test chat endpoint with missing message parameter."""
        response = client.post('/chat', json={})
        
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data


class TestIntegrationScenarios:
    """Integration test scenarios for common use cases."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client
    
    @patch("brain_researcher.services.agent.web_service.get_agent")
    @patch("brain_researcher.services.agent.web_service._LLM_ROUTER.route_chat")
    def test_list_tools_query(self, mock_route_chat, mock_get_agent, client):
        """Test the specific issue: 'list available tools' query."""
        # Mock tools
        mock_tools = []
        tool_names = ["FSL BET", "Nilearn GLM", "FreeSurfer Recon", "ANTs Registration", "fMRIPrep"]
        for name in tool_names:
            mock_tool = Mock()
            mock_tool.get_tool_name.return_value = name
            mock_tool.get_tool_description.return_value = f"{name} for neuroimaging analysis"
            mock_tool.CATEGORY = "analysis"
            mock_tools.append(mock_tool)
        
        mock_agent = Mock()
        mock_agent.tool_registry.get_all_tools.return_value = mock_tools
        mock_get_agent.return_value = mock_agent
        
        # Mock router to give a tool-aware response
        mock_route_chat.return_value = _mock_router_result(
            "I have 5 specialized neuroimaging tools available including FSL BET, Nilearn GLM, and FreeSurfer Recon for various analysis tasks."
        )
        
        # Test the problematic query
        response = client.post('/chat', json={"message": "list available tools"})
        
        assert response.status_code == 200
        data = response.get_json()
        
        # Should NOT get a generic response
        content = data["message"]["content"]
        assert "what kind of tools" not in content.lower()
        assert "hardware" not in content.lower()
        assert "software" not in content.lower()
        
        # SHOULD get a neuroimaging-specific response
        assert "neuroimaging" in content.lower() or "analysis" in content.lower()
        
        # Verify tool context was provided to LLM
        mock_route_chat.assert_called_once()
        llm_input = mock_route_chat.call_args[0][0]
        assert "5 specialized tools" in llm_input or "neuroimaging" in llm_input


class TestAgentMetricsEndpoint:
    """Validate the Flask /metrics route exposed by web_service."""

    def test_metrics_endpoint_disabled(self, monkeypatch):
        monkeypatch.setattr(web_service, "_AGENT_METRICS_ENABLED", False)
        monkeypatch.setattr(
            web_service,
            "_get_agent_monitoring_for_metrics",
            lambda: None,
        )
        client = web_service.app.test_client()
        response = client.get("/metrics")

        assert response.status_code == 404
        assert "metrics" in response.get_data(as_text=True)

    def test_metrics_endpoint_success(self, monkeypatch):
        monkeypatch.setattr(web_service, "_AGENT_METRICS_ENABLED", True)
        class DummyCollector:
            def export_prometheus(self):
                return "dummy_metric 1\n"

        dummy_monitoring = type(
            "Monitor", (), {"metrics_collector": DummyCollector()}
        )()
        monkeypatch.setattr(
            web_service,
            "_get_agent_monitoring_for_metrics",
            lambda: dummy_monitoring,
        )

        client = web_service.app.test_client()
        response = client.get("/metrics")

        assert response.status_code == 200
        assert "dummy_metric" in response.get_data(as_text=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
