"""
Unit tests for the tool registry system.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

import pytest
from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import BRKGToolWrapper, ToolResult
from brain_researcher.services.tools.tool_registry import (
    DynamicToolLoader,
    ToolRegistry,
)


# Mock tools for testing
class MockToolArgs(BaseModel):
    param: str = Field(description="Test parameter")


class MockTool1(BRKGToolWrapper):
    def get_tool_name(self) -> str:
        return "mock_tool_1"

    def get_tool_description(self) -> str:
        return "A mock tool for testing GLM analysis and statistical processing"

    def get_args_schema(self):
        return MockToolArgs

    def _run(self, param: str) -> ToolResult:
        return ToolResult(status="success", data={"result": param})


class MockTool2(BRKGToolWrapper):
    def get_tool_name(self) -> str:
        return "mock_tool_2"

    def get_tool_description(self) -> str:
        return "A mock tool for coordinate mapping and brain regions"

    def get_args_schema(self):
        return MockToolArgs

    def _run(self, param: str) -> ToolResult:
        return ToolResult(status="success", data={"result": param})


class TestToolRegistry:
    """Test the tool registry functionality."""

    def test_registry_initialization_empty(self):
        """Test creating empty registry without auto-discovery."""
        registry = ToolRegistry(auto_discover=False)

        assert len(registry.tools) == 0
        assert len(registry.tool_descriptions) == 0

    def test_auto_discovery(self):
        """Test automatic tool discovery on initialization with real tools."""
        # Create registry with auto-discovery - uses real neuroimaging tools
        registry = ToolRegistry(auto_discover=True)

        # Should discover all real tools from various tool modules
        # We expect at least 25 tools from the current implementation
        assert (
            len(registry.tools) >= 25
        ), f"Expected at least 25 tools, got {len(registry.tools)}"

        # Verify some key real tools are present
        expected_tools = [
            "glm_analysis",  # From FMRITools
            "validate_bids",  # From BIDSTools
            "graph_query",  # From BRKGTools
            "openneuro_download",  # From ArchiveTools
            "run_fmriprep",  # From PipelineTools
            "mriqc_group_report",  # From QCTools
            "coreg_qc_gallery",  # From QCTools
        ]

        for tool_name in expected_tools:
            assert tool_name in registry.tools, f"Expected tool '{tool_name}' not found"

        # Verify tool descriptions are populated
        assert len(registry.tool_descriptions) == len(registry.tools)

        # Verify the search index was built
        assert len(registry.tool_documents) == len(registry.tools)

    def test_register_tool(self):
        """Test manual tool registration."""
        registry = ToolRegistry(auto_discover=False)
        tool = MockTool1()

        registry.register_tool(tool)

        assert "mock_tool_1" in registry.tools
        assert registry.tools["mock_tool_1"] == tool
        assert "GLM analysis" in registry.tool_descriptions["mock_tool_1"]

    def test_register_duplicate_tool(self):
        """Test registering a tool with duplicate name."""
        registry = ToolRegistry(auto_discover=False)
        tool1 = MockTool1()
        tool2 = MockTool1()  # Same name

        registry.register_tool(tool1)

        # Should log warning but still register
        with patch(
            "brain_researcher.services.tools.tool_registry.logger"
        ) as mock_logger:
            registry.register_tool(tool2)
            mock_logger.warning.assert_called_once()

        # Second tool should overwrite first
        assert registry.tools["mock_tool_1"] == tool2

    def test_get_tool(self):
        """Test getting tool by name."""
        registry = ToolRegistry(auto_discover=False)
        tool = MockTool1()
        registry.register_tool(tool)

        # Get existing tool
        retrieved = registry.get_tool("mock_tool_1")
        assert retrieved == tool

        # Get non-existent tool
        missing = registry.get_tool("non_existent")
        assert missing is None

    def test_get_all_tools(self):
        """Test getting all registered tools."""
        registry = ToolRegistry(auto_discover=False)
        tool1 = MockTool1()
        tool2 = MockTool2()

        registry.register_tool(tool1)
        registry.register_tool(tool2)

        all_tools = registry.get_all_tools()
        assert len(all_tools) == 2
        assert tool1 in all_tools
        assert tool2 in all_tools

    def test_get_langchain_tools(self):
        """Test converting to LangChain tools."""
        registry = ToolRegistry(auto_discover=False)
        registry.register_tool(MockTool1())

        lc_tools = registry.get_langchain_tools()
        assert len(lc_tools) == 1
        assert lc_tools[0].name == "mock_tool_1"
        assert hasattr(lc_tools[0], "func")

    def test_keyword_extraction(self):
        """Test keyword extraction for tool matching."""
        registry = ToolRegistry(auto_discover=False)

        # Test various texts
        text1 = "Run GLM analysis on fMRI data"
        keywords1 = registry._extract_keywords(text1)
        assert "glm" in keywords1

        text2 = "Map brain coordinates to concepts"
        keywords2 = registry._extract_keywords(text2)
        assert "coordinate" in keywords2
        assert "concept" in keywords2

        text3 = "Search literature and papers"
        keywords3 = registry._extract_keywords(text3)
        assert "literature" in keywords3

    def test_get_tools_for_task_keyword_matching(self):
        """Test tool selection based on task description."""
        registry = ToolRegistry(auto_discover=False)
        registry.register_tool(MockTool1())  # Has "GLM analysis" in description
        registry.register_tool(MockTool2())  # Has "coordinate mapping" in description

        # Build the search index after registering tools
        registry._build_tool_index()

        # Should match GLM tool
        glm_tools = registry.get_tools_for_task("I need to run GLM analysis", k=2)
        assert len(glm_tools) >= 1
        assert any(t.get_tool_name() == "mock_tool_1" for t in glm_tools)

        # Should match coordinate tool
        coord_tools = registry.get_tools_for_task(
            "Map these coordinates to brain regions", k=2
        )
        assert len(coord_tools) >= 1
        assert any(t.get_tool_name() == "mock_tool_2" for t in coord_tools)

        # Should return empty for unrelated task
        unrelated_tools = registry.get_tools_for_task("Make me a sandwich", k=2)
        assert len(unrelated_tools) == 0

    def test_get_tools_for_task_ranking(self):
        """Test that tools are ranked by relevance."""
        registry = ToolRegistry(auto_discover=False)

        # Create tools with different relevance levels
        class HighlyRelevantTool(BRKGToolWrapper):
            def get_tool_name(self) -> str:
                return "highly_relevant"

            def get_tool_description(self) -> str:
                return "Tool for GLM analysis, statistical GLM processing, and GLM visualization"

            def get_args_schema(self):
                return MockToolArgs

            def _run(self, **kwargs) -> ToolResult:
                return ToolResult(status="success")

        class SomewhatRelevantTool(BRKGToolWrapper):
            def get_tool_name(self) -> str:
                return "somewhat_relevant"

            def get_tool_description(self) -> str:
                return "Tool for general statistical analysis"

            def get_args_schema(self):
                return MockToolArgs

            def _run(self, **kwargs) -> ToolResult:
                return ToolResult(status="success")

        registry.register_tool(SomewhatRelevantTool())
        registry.register_tool(HighlyRelevantTool())

        # Build the search index after registering tools
        registry._build_tool_index()

        tools = registry.get_tools_for_task("Run GLM analysis", k=2)

        # Highly relevant should be first
        assert len(tools) >= 1
        assert tools[0].get_tool_name() == "highly_relevant"

    def test_get_tool_info(self):
        """Test getting registry information."""
        registry = ToolRegistry(auto_discover=False)
        registry.register_tool(MockTool1())
        registry.register_tool(MockTool2())

        info = registry.get_tool_info()

        assert info["n_tools"] == 2
        assert len(info["tools"]) == 2

        # Check tool info structure
        tool_info = info["tools"][0]
        assert "name" in tool_info
        assert "description" in tool_info
        assert "type" in tool_info

    def test_suggest_tools_sequence(self):
        """Test workflow sequence suggestions."""
        registry = ToolRegistry(auto_discover=False)

        # Test fMRI to concepts workflow
        sequences = registry.suggest_tools_sequence(
            "I want to analyze fMRI data and find related concepts"
        )
        assert len(sequences) >= 1
        assert "glm_analysis" in sequences[0]
        assert "coordinate_to_concept" in sequences[0]

        # Test literature search workflow
        sequences = registry.suggest_tools_sequence("Search for papers and literature")
        assert len(sequences) >= 1
        assert "concept_literature_search" in sequences[0]

        # Test full analysis workflow
        sequences = registry.suggest_tools_sequence("Run a complete full analysis")
        assert len(sequences) >= 1
        assert len(sequences[0]) > 3  # Should have multiple steps

        # Test task-based workflow
        sequences = registry.suggest_tools_sequence("Analyze a cognitive task")
        assert len(sequences) >= 1
        assert "task_to_concept_mapping" in sequences[0]

        # Test fallback for unclear request
        sequences = registry.suggest_tools_sequence("Do something with the data")
        assert len(sequences) >= 1
        assert len(sequences[0]) >= 2  # Should suggest at least 2 tools


class TestDynamicToolLoader(unittest.TestCase):
    """Test dynamic tool loading functionality."""

    def test_load_tools_from_module(self):
        """Test loading tools from a module."""
        # Create a mock module
        mock_module = MagicMock()
        mock_module.MockTool1 = MockTool1
        mock_module.MockTool2 = MockTool2
        mock_module.NotATool = str  # Should be ignored

        with patch("importlib.import_module", return_value=mock_module):
            tools = DynamicToolLoader.load_tools_from_module("mock.module")

        assert len(tools) == 2
        tool_names = [t.get_tool_name() for t in tools]
        assert "mock_tool_1" in tool_names
        assert "mock_tool_2" in tool_names

    def test_load_tools_from_module_error(self):
        """Test handling import errors."""
        with patch(
            "importlib.import_module", side_effect=ImportError("Module not found")
        ):
            tools = DynamicToolLoader.load_tools_from_module("non.existent")

        assert len(tools) == 0

    def test_load_tools_from_directory(self):
        """Test loading tools from a directory."""
        # Create temporary directory with tool files
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a tool file
            tool_file = os.path.join(temp_dir, "custom_tools.py")
            with open(tool_file, "w") as f:
                f.write(
                    """
from brain_researcher.services.tools.tool_base import BRKGToolWrapper, ToolResult
from pydantic import BaseModel

class CustomTool(BRKGToolWrapper):
    def get_tool_name(self):
        return "custom_tool"
    def get_tool_description(self):
        return "A custom tool"
    def get_args_schema(self):
        return BaseModel
    def _run(self, **kwargs):
        return ToolResult(status="success")
"""
                )

            # Mock the import to avoid actual module loading issues
            mock_module = MagicMock()

            class CustomTool(BRKGToolWrapper):
                def get_tool_name(self):
                    return "custom_tool"

                def get_tool_description(self):
                    return "A custom tool"

                def get_args_schema(self):
                    return BaseModel

                def _run(self, **kwargs):
                    return ToolResult(status="success")

            mock_module.CustomTool = CustomTool

            with patch("importlib.import_module", return_value=mock_module):
                tools = DynamicToolLoader.load_tools_from_directory(temp_dir)

            assert len(tools) >= 1
            assert any(t.get_tool_name() == "custom_tool" for t in tools)

    def test_load_tools_from_nonexistent_directory(self):
        """Test loading from non-existent directory."""
        tools = DynamicToolLoader.load_tools_from_directory("/non/existent/path")
        assert len(tools) == 0

    def test_tool_instantiation_error(self):
        """Test handling tool instantiation errors."""

        # Create a tool that fails to instantiate
        class FailingTool(BRKGToolWrapper):
            def __init__(self):
                raise ValueError("Initialization failed")

            def get_tool_name(self):
                return "failing_tool"

            def get_tool_description(self):
                return "A failing tool"

            def get_args_schema(self):
                return BaseModel

            def _run(self, **kwargs):
                return ToolResult(status="error")

        mock_module = MagicMock()
        mock_module.FailingTool = FailingTool
        mock_module.GoodTool = MockTool1

        with patch("importlib.import_module", return_value=mock_module):
            # Capture log output to verify error was logged
            with self.assertLogs(
                "brain_researcher.services.tools.tool_registry", level="ERROR"
            ) as log_context:
                tools = DynamicToolLoader.load_tools_from_module("mock.module")

                # Should have logged an error for the failing tool
                assert any(
                    "Failed to instantiate FailingTool" in msg
                    for msg in log_context.output
                )

                # Should still load the good tool
                assert len(tools) == 1
                assert tools[0].get_tool_name() == "mock_tool_1"


class TestRegistryIntegration:
    """Test registry integration with actual tools."""

    def test_full_registry_workflow(self):
        """Test complete registry workflow with real tools."""
        # Create registry with real tools from Neurodesk/CVMFS integration
        registry = ToolRegistry(auto_discover=True)

        # Test 1: Verify registry has real tools
        assert (
            len(registry.tools) >= 25
        ), f"Expected at least 25 tools, got {len(registry.tools)}"

        # Test 2: Tool selection for GLM analysis task
        task = "I need to run GLM analysis on fMRI data"
        selected_tools = registry.get_tools_for_task(task, k=3)

        # Should find relevant tools based on keyword matching
        assert (
            len(selected_tools) >= 1
        ), "Should find at least one tool for GLM analysis"
        tool_names = [t.get_tool_name() for t in selected_tools]

        # GLM analysis tool should be in the results
        assert "glm_analysis" in tool_names, f"Expected 'glm_analysis' in {tool_names}"

        # Test 3: Tool selection for knowledge graph task
        kg_task = "Find related concepts in the knowledge graph"
        kg_tools = registry.get_tools_for_task(kg_task, k=3)

        assert len(kg_tools) >= 1, "Should find at least one knowledge graph tool"
        kg_tool_names = [t.get_tool_name() for t in kg_tools]

        # Should find concept-related tools
        expected_kg_tools = [
            "find_related_concepts",
            "coordinate_to_concept",
            "graph_query",
        ]
        assert any(
            tool in kg_tool_names for tool in expected_kg_tools
        ), f"Expected at least one of {expected_kg_tools} in {kg_tool_names}"

        # Test 4: Complex workflow with multiple steps
        complex_task = "Run GLM analysis, then find concepts related to the activation, and search literature"
        workflow_tools = registry.get_tools_for_task(complex_task, k=5)

        assert (
            len(workflow_tools) >= 3
        ), "Should find multiple tools for complex workflow"
        workflow_names = [t.get_tool_name() for t in workflow_tools]

        # Test 5: Workflow suggestion
        sequences = registry.suggest_tools_sequence(complex_task)
        assert len(sequences) >= 1, "Should suggest at least one tool sequence"

        # Test 6: Get all tools as LangChain tools
        lc_tools = registry.get_langchain_tools()
        assert len(lc_tools) == len(
            registry.tools
        ), "Should convert all tools to LangChain format"

        # Test 7: Tool info retrieval
        info = registry.get_tool_info()
        assert info is not None, "Should get tool registry info"
        assert "n_tools" in info
        assert info["n_tools"] == len(registry.tools)

        # Test 8: Get specific tool
        glm_tool = registry.get_tool("glm_analysis")
        assert glm_tool is not None, "Should get GLM analysis tool"
        assert glm_tool.get_tool_name() == "glm_analysis"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
