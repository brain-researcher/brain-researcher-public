"""
Unit tests for tool mapping and routing.

Tests the query->tool matching pipeline with real examples.
"""

import pytest
from unittest.mock import Mock, MagicMock

from brain_researcher.services.agent.tool_mapper import ToolMapper, get_tool_mapper
from brain_researcher.services.tools.arg_adapter import ToolArgumentAdapter


class MockTool:
    """Mock tool for testing."""
    def __init__(self, name):
        self.name = name
    
    def get_tool_name(self):
        return self.name


class MockRegistry:
    """Mock tool registry for testing."""
    def __init__(self, tool_names):
        self.tools = [MockTool(name) for name in tool_names]
    
    def get_all_tools(self):
        return self.tools


# Test data: registered tool names (from actual catalog)
REGISTERED_TOOLS = [
    "glm_analysis",
    "find_related_concepts", 
    "coordinate_to_concept",
    "concept_literature_search",
    "graph_query",
    "task_to_concept_mapping",
    "contrast_to_activation_map",
    "contrast_analysis",
    "encoding_model",
    "brain_similarity",
    "openneuro_download",
    "validate_bids",
    "query_bids_layout",
    "read_nwb",
    "write_nwb",
    "dandi_search",
    "neurovault_download_collection"
]


class TestToolMapping:
    """Test tool name mapping and resolution."""
    
    @pytest.fixture
    def mapper(self):
        """Create mapper with mock registry."""
        registry = MockRegistry(REGISTERED_TOOLS)
        return ToolMapper(registry)
    
    def test_exact_match(self, mapper):
        """Test exact tool name matching."""
        result, match_type = mapper.map_tool_name("glm_analysis")
        assert result == "glm_analysis"
        assert match_type == "exact"
    
    def test_alias_mapping(self, mapper):
        """Test alias resolution."""
        # Common aliases that should map correctly
        test_cases = [
            ("statistical_analysis", "glm_analysis"),
            ("literature_search", "concept_literature_search"),
            ("coord2concept", "coordinate_to_concept"),
            ("related_concepts", "find_related_concepts"),
        ]
        
        for alias, expected in test_cases:
            result, match_type = mapper.map_tool_name(alias)
            assert result == expected, f"Failed to map {alias} to {expected}"
            assert match_type in ["alias", "substring"]
    
    def test_fuzzy_matching(self, mapper):
        """Test fuzzy matching with threshold."""
        # These should fuzzy match
        test_cases = [
            ("find_concept", "find_related_concepts"),  # Missing 's' and 'related'
            ("glm_analisys", "glm_analysis"),  # Typo
            ("coordinate_concept", "coordinate_to_concept"),  # Missing 'to'
        ]
        
        for typo, expected in test_cases:
            result, match_type = mapper.map_tool_name(typo)
            assert result == expected, f"Failed to fuzzy match {typo} to {expected}"
    
    def test_whitelist_enforcement(self, mapper):
        """Test whitelist filtering."""
        whitelist = ["glm_analysis", "find_related_concepts"]
        
        # Allowed tool
        result, match_type = mapper.map_tool_name("glm_analysis", whitelist=whitelist)
        assert result == "glm_analysis"
        
        # Blocked tool (not in whitelist)
        result, match_type = mapper.map_tool_name("coordinate_to_concept", whitelist=whitelist)
        assert result is None
        assert match_type == "blocked"
    
    def test_denylist_enforcement(self, mapper):
        """Test denylist filtering."""
        denylist = ["glm_analysis"]
        
        # Blocked tool
        result, match_type = mapper.map_tool_name("glm_analysis", denylist=denylist)
        assert result is None
        assert match_type == "blocked"
        
        # Allowed tool
        result, match_type = mapper.map_tool_name("find_related_concepts", denylist=denylist)
        assert result == "find_related_concepts"
    
    def test_no_match(self, mapper):
        """Test handling of unknown tools."""
        result, match_type = mapper.map_tool_name("completely_unknown_tool")
        assert result is None
        assert match_type == "not_found"
    
    def test_query_suggestions(self, mapper):
        """Test tool suggestions based on query."""
        suggestions = mapper.suggest_tools_for_query("Find papers about hippocampus")
        assert "concept_literature_search" in suggestions or "find_related_concepts" in suggestions
        
        suggestions = mapper.suggest_tools_for_query("Run GLM analysis")
        assert "glm_analysis" in suggestions


class TestArgumentAdapter:
    """Test argument adaptation for tools."""
    
    def test_glm_adapter_demo_mode(self):
        """Test GLM adapter in demo mode."""
        llm_args = {"analysis_type": "glm"}
        adapted = ToolArgumentAdapter.adapt("glm_analysis", llm_args, demo=True)
        
        assert adapted["dataset_id"] == "ds000001"
        assert "contrasts" in adapted
        assert adapted.get("allow_mock") is True
    
    def test_glm_adapter_validation_error(self):
        """Test GLM adapter validation in non-demo mode."""
        llm_args = {"analysis_type": "glm"}
        
        with pytest.raises(Exception) as exc_info:
            ToolArgumentAdapter.adapt("glm_analysis", llm_args, demo=False)
        
        assert "requires" in str(exc_info.value).lower()
    
    def test_concept_adapter(self):
        """Test find_related_concepts adapter."""
        test_cases = [
            ({"concept": "hippocampus"}, {"concept": "hippocampus"}),
            ({"query": "working memory"}, {"concept": "working memory"}),
            ({"search_query": "attention"}, {"concept": "attention"}),
        ]
        
        for llm_args, expected in test_cases:
            adapted = ToolArgumentAdapter.adapt("find_related_concepts", llm_args)
            assert adapted == expected
    
    def test_coordinate_adapter(self):
        """Test coordinate_to_concept adapter."""
        test_cases = [
            ({"coordinates": [30, -25, -20]}, {"coordinates": [[30, -25, -20]]}),
            ({"x": 30, "y": -25, "z": -20}, {"coordinates": [[30, -25, -20]]}),
            (
                {"coordinates": [[30, -25, -20], [40, 10, 50]], "radius": 8},
                {"coordinates": [[30, -25, -20], [40, 10, 50]], "radius": 8},
            ),
            (
                {"coordinate": "30, -25, -20", "top_k": 3},
                {"coordinates": [[30.0, -25.0, -20.0]], "top_k": 3},
            ),
        ]
        
        for llm_args, expected in test_cases:
            adapted = ToolArgumentAdapter.adapt("coordinate_to_concept", llm_args)
            assert adapted == expected
    
    def test_pubmed_adapter(self):
        """Test PubMed search adapter."""
        llm_args = {"search_query": "hippocampus memory", "max_results": 5}
        adapted = ToolArgumentAdapter.adapt("pubmed_search", llm_args)
        
        assert adapted["query"] == "hippocampus memory"
        assert adapted["max_results"] == 5
    
    def test_passthrough_unknown_tool(self):
        """Test that unknown tools pass through unchanged."""
        llm_args = {"some_param": "value"}
        adapted = ToolArgumentAdapter.adapt("unknown_tool", llm_args)
        
        assert adapted == llm_args

    def test_contrast_to_activation_map_adapter(self):
        """Test contrast_to_activation_map adapter."""
        llm_args = {
            "contrast": "2-back > 0-back",
            "task": "n-back",
            "top_k_constructs": 6,
        }
        adapted = ToolArgumentAdapter.adapt("contrast_to_activation_map", llm_args)

        assert adapted["contrast_text"] == "2-back > 0-back"
        assert adapted["task_name"] == "n-back"
        assert adapted["top_k_constructs"] == 6


class TestQueryRouting:
    """Test complete query->tool routing pipeline."""
    
    @pytest.fixture
    def mapper(self):
        """Create mapper with mock registry."""
        registry = MockRegistry(REGISTERED_TOOLS)
        return ToolMapper(registry)
    
    def test_route_nback_query(self, mapper):
        """Test routing for n-back question."""
        query = "What is the n-back task?"
        suggestions = mapper.suggest_tools_for_query(query)
        # This should go to /chat (no tools), but mapper might suggest task mapping
        assert len(suggestions) == 0 or "task_to_concept_mapping" in suggestions
    
    def test_route_paper_search(self, mapper):
        """Test routing for paper search."""
        query = "Find papers about hippocampus memory"
        suggestions = mapper.suggest_tools_for_query(query)
        assert "concept_literature_search" in suggestions or "find_related_concepts" in suggestions
    
    def test_route_coordinate_query(self, mapper):
        """Test routing for coordinate mapping."""
        query = "What concept is at coordinates 30, -25, -20"
        
        # LLM might call it "coordinate_to_concept" or an alias
        tool_name, _ = mapper.map_tool_name("mni_to_concept")
        assert tool_name == "coordinate_to_concept"
        
        # Adapt the arguments
        llm_args = {"coordinates": "30, -25, -20"}
        adapted = ToolArgumentAdapter.adapt("coordinate_to_concept", llm_args)
        assert adapted == {"coordinates": [[30.0, -25.0, -20.0]]}
    
    def test_route_glm_request(self, mapper):
        """Test routing for GLM analysis request."""
        query = "Run GLM analysis on dataset"
        suggestions = mapper.suggest_tools_for_query(query)
        assert "glm_analysis" in suggestions
        
        # Test with demo mode
        llm_args = {"description": "analyze memory task"}
        adapted = ToolArgumentAdapter.adapt("glm_analysis", llm_args, demo=True)
        assert adapted["dataset_id"] == "ds000001"
        assert adapted.get("allow_mock") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
