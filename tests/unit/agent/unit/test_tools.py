"""
Unit tests for tool wrapper base classes and implementations.
"""

from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import (
    BatchToolWrapper,
    CachedToolWrapper,
    BRKGToolWrapper,
    ToolResult,
)


# Test implementations of abstract classes
class TestToolArgs(BaseModel):
    """Test argument schema."""

    __test__ = False

    param1: str = Field(description="First parameter")
    param2: int = Field(default=42, description="Second parameter")


class MockTool(BRKGToolWrapper):
    """Mock implementation for testing."""

    def get_tool_name(self) -> str:
        return "mock_tool"

    def get_tool_description(self) -> str:
        return "A mock tool for testing"

    def get_args_schema(self):
        return TestToolArgs

    def _run(self, param1: str, param2: int = 42) -> ToolResult:
        if param1 == "error":
            return ToolResult(status="error", error="Simulated error")
        return ToolResult(
            status="success",
            data={"result": f"{param1}_{param2}"},
            metadata={"processed": True},
        )


class MockBatchTool(BatchToolWrapper):
    """Mock batch tool for testing."""

    def get_tool_name(self) -> str:
        return "mock_batch_tool"

    def get_tool_description(self) -> str:
        return "A mock batch tool"

    def get_args_schema(self):
        return TestToolArgs

    def _run(self, **kwargs) -> ToolResult:
        # Single item execution
        return ToolResult(status="success", data=kwargs)

    def _run_batch(self, items: list[dict[str, Any]]) -> list[ToolResult]:
        results = []
        for item in items:
            if item.get("param1") == "error":
                results.append(ToolResult(status="error", error="Batch item error"))
            else:
                results.append(ToolResult(status="success", data=item))
        return results


class MockCachedTool(CachedToolWrapper):
    """Mock cached tool for testing."""

    def __init__(self):
        super().__init__(cache_ttl=60)
        self.call_count = 0

    def get_tool_name(self) -> str:
        return "mock_cached_tool"

    def get_tool_description(self) -> str:
        return "A mock cached tool"

    def get_args_schema(self):
        return TestToolArgs

    def _run(self, param1: str, param2: int = 42) -> ToolResult:
        self.call_count += 1
        return ToolResult(
            status="success",
            data={"result": f"{param1}_{param2}", "calls": self.call_count},
        )


class TestToolResult:
    """Test ToolResult model."""

    def test_success_result(self):
        """Test creating a successful result."""
        result = ToolResult(
            status="success", data={"key": "value"}, metadata={"timing": 0.5}
        )

        assert result.status == "success"
        assert result.data["key"] == "value"
        assert result.error is None
        assert result.metadata["timing"] == 0.5

    def test_error_result(self):
        """Test creating an error result."""
        result = ToolResult(status="error", error="Something went wrong")

        assert result.status == "error"
        assert result.error == "Something went wrong"
        assert result.data is None

    def test_result_to_dict(self):
        """Test converting result to dictionary."""
        result = ToolResult(status="success", data={"test": True})
        result_dict = result.dict()

        assert isinstance(result_dict, dict)
        assert result_dict["status"] == "success"
        assert result_dict["data"]["test"] is True


class TestBRKGToolWrapper:
    """Test base tool wrapper functionality."""

    def test_tool_initialization(self):
        """Test tool initializes correctly."""
        tool = MockTool()

        assert tool.get_tool_name() == "mock_tool"
        assert tool.get_tool_description() == "A mock tool for testing"
        assert tool.get_args_schema() == TestToolArgs

    def test_successful_execution(self):
        """Test successful tool execution."""
        tool = MockTool()
        result = tool.run(param1="test", param2=100)

        assert result["status"] == "success"
        assert result["data"]["result"] == "test_100"
        assert result["metadata"]["processed"] is True

    def test_error_handling(self):
        """Test tool error handling."""
        tool = MockTool()
        result = tool.run(param1="error")

        assert result["status"] == "error"
        assert result["error"] == "Simulated error"
        assert result["data"] is None

    def test_exception_handling(self):
        """Test handling of unexpected exceptions."""
        tool = MockTool()

        # Mock _run to raise an exception
        with patch.object(tool, "_run", side_effect=ValueError("Unexpected error")):
            result = tool.run(param1="test")

        assert result["status"] == "error"
        assert "Unexpected error" in result["error"]

    def test_langchain_tool_conversion(self):
        """Test converting to LangChain tool."""
        tool = MockTool()
        lc_tool = tool.as_langchain_tool()

        assert lc_tool.name == "mock_tool"
        assert lc_tool.description == "A mock tool for testing"
        assert lc_tool.args_schema == TestToolArgs

        # Test execution through LangChain interface
        result = lc_tool.func(param1="langchain", param2=50)
        assert result["status"] == "success"
        assert result["data"]["result"] == "langchain_50"

    def test_logging(self):
        """Test that tool logs appropriately."""
        tool = MockTool()

        with patch.object(tool.logger, "info") as mock_info:
            with patch.object(tool.logger, "warning") as mock_warning:
                # Successful execution
                tool.run(param1="test")
                assert mock_info.call_count >= 2  # Start and complete

                # Failed execution
                tool.run(param1="error")
                assert mock_warning.call_count >= 1


class TestBatchToolWrapper:
    """Test batch tool functionality."""

    def test_batch_execution_success(self):
        """Test successful batch execution."""
        tool = MockBatchTool()

        items = [
            {"param1": "item1", "param2": 1},
            {"param1": "item2", "param2": 2},
            {"param1": "item3", "param2": 3},
        ]

        results = tool.run_batch(items)

        assert len(results) == 3
        assert all(r["status"] == "success" for r in results)
        assert results[0]["data"]["param1"] == "item1"
        assert results[2]["data"]["param2"] == 3

    def test_batch_execution_mixed_results(self):
        """Test batch execution with some failures."""
        tool = MockBatchTool()

        items = [
            {"param1": "good", "param2": 1},
            {"param1": "error", "param2": 2},
            {"param1": "also_good", "param2": 3},
        ]

        results = tool.run_batch(items)

        assert len(results) == 3
        assert results[0]["status"] == "success"
        assert results[1]["status"] == "error"
        assert results[2]["status"] == "success"

    def test_batch_exception_handling(self):
        """Test batch execution exception handling."""
        tool = MockBatchTool()

        with patch.object(tool, "_run_batch", side_effect=RuntimeError("Batch failed")):
            results = tool.run_batch([{"param1": "test"}])

        assert len(results) == 1
        assert results[0]["status"] == "error"
        assert "Batch failed" in results[0]["error"]

    def test_single_execution_through_batch_tool(self):
        """Test that batch tools can still execute single items."""
        tool = MockBatchTool()
        result = tool.run(param1="single", param2=42)

        assert result["status"] == "success"
        assert result["data"]["param1"] == "single"


class TestCachedToolWrapper:
    """Test cached tool functionality."""

    def test_cache_miss_and_hit(self):
        """Test cache miss followed by cache hit."""
        tool = MockCachedTool()

        # First call - cache miss
        result1 = tool.run(param1="test", param2=42)
        assert result1["status"] == "success"
        assert result1["data"]["calls"] == 1
        assert result1.get("metadata", {}).get("from_cache") is not True

        # Second call with same args - cache hit
        result2 = tool.run(param1="test", param2=42)
        assert result2["status"] == "success"
        assert result2["data"]["calls"] == 1  # Same as before (cached)
        assert result2["metadata"]["from_cache"] is True

        # Verify tool was only called once
        assert tool.call_count == 1

    def test_cache_key_generation(self):
        """Test that different arguments generate different cache keys."""
        tool = MockCachedTool()

        # Different arguments should not hit cache
        result1 = tool.run(param1="test1", param2=42)
        result2 = tool.run(param1="test2", param2=42)
        result3 = tool.run(param1="test1", param2=43)

        assert result1["data"]["calls"] == 1
        assert result2["data"]["calls"] == 2
        assert result3["data"]["calls"] == 3

        # Same arguments should hit cache
        result4 = tool.run(param1="test1", param2=42)
        assert result4["data"]["calls"] == 1  # Cached from first call
        assert result4["metadata"]["from_cache"] is True

    def test_error_results_not_cached(self):
        """Test that error results are not cached."""
        tool = MockCachedTool()

        # Mock to return error
        with patch.object(
            tool, "_run", return_value=ToolResult(status="error", error="Failed")
        ):
            result1 = tool.run(param1="error_test")
            assert result1["status"] == "error"

        # Remove mock - should execute again (not cached)
        result2 = tool.run(param1="error_test")
        assert result2["status"] == "success"
        assert result2["data"]["calls"] == 1

    def test_success_result_with_cacheable_false_not_cached(self):
        """Test opt-out metadata prevents caching even on success."""
        tool = MockCachedTool()

        with patch.object(
            tool,
            "_run",
            side_effect=[
                ToolResult(status="success", data={"calls": 1}, metadata={"cacheable": False}),
                ToolResult(status="success", data={"calls": 2}, metadata={"cacheable": False}),
            ],
        ) as mock_run:
            result1 = tool.run(param1="no_cache")
            result2 = tool.run(param1="no_cache")

        assert result1["status"] == "success"
        assert result2["status"] == "success"
        assert result1["data"]["calls"] == 1
        assert result2["data"]["calls"] == 2
        assert result1.get("metadata", {}).get("from_cache") is not True
        assert result2.get("metadata", {}).get("from_cache") is not True
        assert mock_run.call_count == 2

    def test_cache_ttl_setting(self):
        """Test cache TTL is set correctly."""
        tool = MockCachedTool()
        assert tool.cache_ttl == 60

        # Test with custom TTL
        custom_tool = CachedToolWrapper(cache_ttl=300)
        assert custom_tool.cache_ttl == 300


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""

    def test_tool_with_complex_args(self):
        """Test tool with complex argument types."""

        class ComplexArgs(BaseModel):
            coordinates: list[list[float]]
            options: dict[str, Any]
            threshold: float = 0.5

        class ComplexTool(BRKGToolWrapper):
            def get_tool_name(self) -> str:
                return "complex_tool"

            def get_tool_description(self) -> str:
                return "Tool with complex arguments"

            def get_args_schema(self):
                return ComplexArgs

            def _run(self, coordinates, options, threshold=0.5) -> ToolResult:
                return ToolResult(
                    status="success",
                    data={
                        "n_coords": len(coordinates),
                        "threshold": threshold,
                        "option_keys": list(options.keys()),
                    },
                )

        tool = ComplexTool()
        result = tool.run(
            coordinates=[[-42, -22, 54], [42, -22, 54]],
            options={"method": "peak", "radius": 10},
            threshold=0.7,
        )

        assert result["status"] == "success"
        assert result["data"]["n_coords"] == 2
        assert result["data"]["threshold"] == 0.7
        assert "method" in result["data"]["option_keys"]

    def test_tool_chaining_scenario(self):
        """Test using multiple tools in sequence."""
        tool1 = MockTool()
        tool2 = MockCachedTool()

        # First tool generates input for second
        result1 = tool1.run(param1="step1", param2=10)
        assert result1["status"] == "success"

        # Use output as input to second tool
        param_from_tool1 = result1["data"]["result"]
        result2 = tool2.run(param1=param_from_tool1)

        assert result2["status"] == "success"
        assert "step1_10" in result2["data"]["result"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
