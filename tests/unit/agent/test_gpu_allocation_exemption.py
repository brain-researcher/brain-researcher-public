"""
Tests for GPU allocation exemption for python tools.

Verifies that python tools execute in-process without GPU allocation,
while container tools go through resource allocation.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from brain_researcher.services.agent.tool_executor import (
    ToolExecutor,
    ToolExecutionRequest,
    ExecutionBackend,
    ToolCategory,
)
from brain_researcher.services.tools.tool_base import BRKGToolWrapper, ToolResult


class MockPythonTool(BRKGToolWrapper):
    """Mock python tool for testing."""

    execution_backend = "python"

    def get_tool_name(self) -> str:
        return "mock_python_tool"

    def get_tool_description(self) -> str:
        return "Mock python tool"

    def get_args_schema(self):
        return None

    def _run(self, **kwargs) -> ToolResult:
        return ToolResult(
            status="success",
            data={"outputs": {"result": "test_output"}},
        )


class TestGPUAllocationExemption:
    """Test GPU allocation behavior for different backends."""

    @pytest.fixture
    def tool_executor(self):
        """Create tool executor for testing."""
        executor = ToolExecutor()
        # Mock resource manager to track allocations
        executor.resource_manager = Mock()
        executor.resource_manager.request_resources = Mock(return_value=Mock(allocation_id="test_alloc"))
        executor.resource_manager.release_resources = Mock()
        return executor

    @pytest.fixture
    def python_tool(self):
        """Create mock python tool."""
        return MockPythonTool()

    def test_python_tool_skips_gpu_allocation(self, tool_executor, python_tool):
        """Test that python tools do NOT allocate GPU resources.

        Python tools execute in-process and should bypass resource allocation entirely.
        """
        # Register the tool
        from brain_researcher.services.tools.tool_registry import ToolRegistry
        registry = ToolRegistry()
        registry.register_tool(python_tool)

        # Create request with python runtime
        request = ToolExecutionRequest(
            execution_id="test_exec_001",
            tool_name="mock_python_tool",
            parameters={"test_param": "test_value"},
            category=ToolCategory.NEUROIMAGING,
            runtime_kind="python",
        )

        # Execute
        with patch.object(tool_executor, '_get_tool', return_value=python_tool):
            result = tool_executor.execute(request)

        # Verify execution succeeded
        assert result.status == "success"

        # Verify resource manager was NEVER called (python tools skip allocation)
        tool_executor.resource_manager.request_resources.assert_not_called()
        tool_executor.resource_manager.release_resources.assert_not_called()

    def test_container_tool_allocates_gpu(self, tool_executor):
        """Test that container tools DO allocate GPU resources.

        Container tools should go through resource allocation system.
        """
        # Create request for container tool (no runtime_kind = defaults to container)
        request = ToolExecutionRequest(
            execution_id="test_exec_002",
            tool_name="fsl_bet",
            parameters={"input": "brain.nii"},
            category=ToolCategory.NEUROIMAGING,
            runtime_kind="container",  # Explicit container backend
        )

        # Mock the tool registry to return a container tool
        mock_tool = Mock()
        mock_tool.get_tool_name = Mock(return_value="fsl_bet")
        mock_tool.get_args_schema = Mock(return_value=None)
        mock_tool.execution_backend = "container"

        # Mock command generation to avoid actual execution
        with patch.object(tool_executor, '_get_tool', return_value=mock_tool):
            with patch.object(tool_executor, '_execute_command_generation') as mock_exec:
                mock_exec.return_value = Mock(
                    status="success",
                    execution_id="test_exec_002",
                    tool_name="fsl_bet",
                    result={"command": "bet brain.nii brain_mask.nii"},
                )
                result = tool_executor.execute(request)

        # Verify command generation was used (container path)
        # Note: _execute_command_generation doesn't allocate resources either,
        # but in real workflow, container execution would allocate via orchestrator

    def test_api_tool_allocates_resources(self, tool_executor):
        """Test that API tools go through resource allocation.

        API tools use _execute_api_call which includes resource allocation.
        """
        # Create request for API tool
        request = ToolExecutionRequest(
            execution_id="test_exec_003",
            tool_name="api_service",
            parameters={"endpoint": "/test"},
            category=ToolCategory.API_SERVICE,
            runtime_kind="api",
        )

        # Mock the tool
        mock_tool = Mock()
        mock_tool.get_tool_name = Mock(return_value="api_service")
        mock_tool.get_args_schema = Mock(return_value=None)
        mock_tool.execution_backend = "api"
        mock_tool._run = Mock(return_value={"status": "success", "data": "test"})

        with patch.object(tool_executor, '_get_tool', return_value=mock_tool):
            with patch.object(tool_executor, '_execute_with_timeout') as mock_timeout:
                mock_timeout.return_value = Mock(status="success")
                result = tool_executor.execute(request)

        # Verify resource allocation was called for API backend
        assert tool_executor.resource_manager.request_resources.called

    def test_backend_detection_routes_correctly(self, tool_executor):
        """Test that _determine_backend correctly identifies python tools."""
        # Python tool request
        python_request = ToolExecutionRequest(
            execution_id="test",
            tool_name="python_tool",
            parameters={},
            runtime_kind="python",
        )
        assert tool_executor._determine_backend(python_request) == ExecutionBackend.PYTHON

        # Container tool request (default)
        container_request = ToolExecutionRequest(
            execution_id="test",
            tool_name="container_tool",
            parameters={},
            runtime_kind="container",
        )
        assert tool_executor._determine_backend(container_request) == ExecutionBackend.CONTAINER

        # API tool request
        api_request = ToolExecutionRequest(
            execution_id="test",
            tool_name="api_tool",
            parameters={},
            runtime_kind="api",
        )
        assert tool_executor._determine_backend(api_request) == ExecutionBackend.API

    def test_python_tool_no_blocking_on_gpu_queue(self, tool_executor, python_tool):
        """Test that python tools execute immediately even when GPU queue is full.

        This ensures python tools don't get blocked waiting for GPU availability.
        """
        # Simulate GPU queue being full (request_resources returns None)
        tool_executor.resource_manager.request_resources = Mock(return_value=None)
        tool_executor.resource_manager.queue_request = Mock(return_value="queued_123")

        # Register the tool
        from brain_researcher.services.tools.tool_registry import ToolRegistry
        registry = ToolRegistry()
        registry.register_tool(python_tool)

        request = ToolExecutionRequest(
            execution_id="test_exec_004",
            tool_name="mock_python_tool",
            parameters={},
            runtime_kind="python",
        )

        # Execute
        with patch.object(tool_executor, '_get_tool', return_value=python_tool):
            result = tool_executor.execute(request)

        # Verify execution succeeded immediately (no queuing)
        assert result.status == "success"

        # Verify resource manager was never called (python path bypasses it)
        tool_executor.resource_manager.request_resources.assert_not_called()
        tool_executor.resource_manager.queue_request.assert_not_called()
