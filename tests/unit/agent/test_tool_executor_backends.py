"""
Unit tests for ToolExecutor backend determination and backward compatibility.

Tests verify that:
1. Missing runtime_kind defaults to CONTAINER backend
2. Explicit runtime_kind values are respected
3. Old ToolExecutionRequests without runtime_kind use container path
"""

from unittest.mock import Mock, patch

import pytest

from brain_researcher.services.agent.tool_executor import (
    ExecutionBackend,
    ExecutionMode,
    ToolCategory,
    ToolExecutionRequest,
    ToolExecutor,
)


class TestBackendDetermination:
    """Tests for _determine_backend() method."""

    def test_determine_backend_defaults_to_container_when_runtime_kind_none(self):
        """Backward compatibility: missing runtime_kind should default to CONTAINER backend."""
        # Create mock ToolExecutor
        mock_registry = Mock()
        executor = ToolExecutor(tool_registry=mock_registry)

        # Request without runtime_kind (old format)
        request = ToolExecutionRequest(
            tool_name="fsl.bet",
            parameters={"frac": 0.5},
            category=ToolCategory.NEUROIMAGING,
            # runtime_kind=None  # Explicitly NOT set
        )

        # Verify runtime_kind is None
        assert request.runtime_kind is None

        # _determine_backend should return CONTAINER as default
        backend = executor._determine_backend(request)

        assert backend == ExecutionBackend.CONTAINER

    def test_determine_backend_respects_explicit_python_runtime_kind(self):
        """Explicit runtime_kind='python' should return PYTHON backend."""
        mock_registry = Mock()
        executor = ToolExecutor(tool_registry=mock_registry)

        request = ToolExecutionRequest(
            tool_name="nilearn_connectivity",
            parameters={"atlas": "schaefer"},
            runtime_kind="python",
        )

        backend = executor._determine_backend(request)

        assert backend == ExecutionBackend.PYTHON

    def test_determine_backend_respects_explicit_api_runtime_kind(self):
        """Explicit runtime_kind='api' should return API backend."""
        mock_registry = Mock()
        executor = ToolExecutor(tool_registry=mock_registry)

        request = ToolExecutionRequest(
            tool_name="neurostore_query",
            parameters={"query": "motor cortex"},
            runtime_kind="api",
        )

        backend = executor._determine_backend(request)

        assert backend == ExecutionBackend.API

    def test_determine_backend_maps_mcp_runtime_kind_to_api(self):
        """runtime_kind='mcp' should normalize to API backend."""
        mock_registry = Mock()
        executor = ToolExecutor(tool_registry=mock_registry)

        request = ToolExecutionRequest(
            tool_name="mcp.tool_search",
            parameters={"query": "workflow"},
            runtime_kind="mcp",
        )

        backend = executor._determine_backend(request)

        assert backend == ExecutionBackend.API

    def test_determine_backend_from_context_runtime_kind(self):
        """runtime_kind from context should be respected."""
        mock_registry = Mock()
        executor = ToolExecutor(tool_registry=mock_registry)

        request = ToolExecutionRequest(
            tool_name="custom_tool",
            parameters={},
            context={"runtime_kind": "python"},
        )

        backend = executor._determine_backend(request)

        assert backend == ExecutionBackend.PYTHON

    def test_determine_backend_api_category_returns_api(self):
        """API_SERVICE category should return API backend even without runtime_kind."""
        mock_registry = Mock()
        executor = ToolExecutor(tool_registry=mock_registry)

        request = ToolExecutionRequest(
            tool_name="api_tool",
            parameters={},
            category=ToolCategory.API_SERVICE,
            # No runtime_kind specified
        )

        backend = executor._determine_backend(request)

        assert backend == ExecutionBackend.API

    def test_determine_backend_ignores_invalid_runtime_kind(self):
        """Invalid runtime_kind should be ignored and default to CONTAINER."""
        mock_registry = Mock()
        executor = ToolExecutor(tool_registry=mock_registry)

        request = ToolExecutionRequest(
            tool_name="some_tool",
            parameters={},
            runtime_kind="invalid_backend",  # Invalid value
            category=ToolCategory.NEUROIMAGING,  # Ensure it's not auto-detected as API
        )

        backend = executor._determine_backend(request)

        # Should fall back to CONTAINER (line 641 in tool_executor.py)
        # Note: Invalid runtime_kind is caught by ValueError exception (line 636-637)
        # and execution falls through to line 639-641 logic
        assert backend == ExecutionBackend.CONTAINER


class TestBackendExecution:
    """Tests for backend-specific execution routing."""

    def test_backend_routing_container_for_missing_runtime_kind(self):
        """Missing runtime_kind should route through CONTAINER backend path."""
        mock_registry = Mock()
        executor = ToolExecutor(tool_registry=mock_registry)

        request = ToolExecutionRequest(
            tool_name="fsl.bet",
            parameters={"frac": 0.5},
            category=ToolCategory.NEUROIMAGING,
            # No runtime_kind - simulates old plan
        )

        # Verify backend is determined as CONTAINER
        backend = executor._determine_backend(request)
        assert backend == ExecutionBackend.CONTAINER

        # For CONTAINER backend + NEUROIMAGING category:
        # - mode will be COMMAND_GENERATION (auto-detected)
        # - execute() will call _execute_command_generation()
        assert request.mode == ExecutionMode.COMMAND_GENERATION

    def test_backend_routing_python_for_explicit_runtime_kind(self):
        """Explicit runtime_kind='python' should route through PYTHON backend path."""
        mock_registry = Mock()
        executor = ToolExecutor(tool_registry=mock_registry)

        request = ToolExecutionRequest(
            tool_name="nilearn_connectivity",
            parameters={"atlas": "schaefer"},
            runtime_kind="python",
        )

        # Verify backend is determined as PYTHON
        backend = executor._determine_backend(request)
        assert backend == ExecutionBackend.PYTHON

        # For PYTHON backend, execute() will call _execute_python() (line 612-613)

    def test_backend_routing_api_for_api_category(self):
        """API_SERVICE category should route through API backend even without runtime_kind."""
        mock_registry = Mock()
        executor = ToolExecutor(tool_registry=mock_registry)

        request = ToolExecutionRequest(
            tool_name="neurostore_query",
            parameters={"query": "motor"},
            category=ToolCategory.API_SERVICE,
        )

        # Verify backend is determined as API
        backend = executor._determine_backend(request)
        assert backend == ExecutionBackend.API

        # For API backend, mode will be API_CALL (line 616-617)


class TestBackwardCompatibilityIntegration:
    """Integration tests for backward compatibility scenarios."""

    def test_old_tool_execution_request_serialization(self):
        """Old ToolExecutionRequest JSON without runtime_kind should deserialize correctly."""
        # Simulate old request format (before runtime_kind was added)
        old_request_data = {
            "tool_name": "fsl.bet",
            "parameters": {"frac": 0.5, "input": "t1.nii.gz"},
            "category": "neuroimaging",
            "mode": "command_generation",
        }

        # ToolExecutionRequest uses @dataclass, not Pydantic, so we test direct construction
        request = ToolExecutionRequest(
            tool_name=old_request_data["tool_name"],
            parameters=old_request_data["parameters"],
            # runtime_kind not provided - should default to None
        )

        # Verify it constructs successfully with runtime_kind=None (backward compatible)
        assert request.runtime_kind is None
        assert request.tool_name == "fsl.bet"
        assert request.parameters == {"frac": 0.5, "input": "t1.nii.gz"}

    def test_mixed_plan_with_and_without_runtime_kind(self):
        """Plan with mix of old (no runtime_kind) and new steps should work."""
        mock_registry = Mock()
        executor = ToolExecutor(tool_registry=mock_registry)

        # Old step (no runtime_kind)
        old_request = ToolExecutionRequest(
            tool_name="fsl.bet",
            parameters={"frac": 0.5},
        )

        # New step (with runtime_kind)
        new_request = ToolExecutionRequest(
            tool_name="nilearn_connectivity",
            parameters={"atlas": "schaefer"},
            runtime_kind="python",
        )

        # Verify both determine correct backend
        old_backend = executor._determine_backend(old_request)
        new_backend = executor._determine_backend(new_request)

        assert old_backend == ExecutionBackend.CONTAINER  # Default for missing
        assert new_backend == ExecutionBackend.PYTHON  # Explicit value
