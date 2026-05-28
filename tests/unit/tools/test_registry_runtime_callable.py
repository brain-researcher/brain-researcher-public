from __future__ import annotations

from unittest.mock import patch

from brain_researcher.services.tools.registry import (
    UnifiedToolRegistry,
    _workflow_runtime_registry,
)
from brain_researcher.services.tools.spec import ToolSpec


def test_workflow_runtime_callable_uses_cached_light_registry():
    _workflow_runtime_registry.cache_clear()
    spec = ToolSpec(
        name="workflow_visual_decoding",
        description="workflow",
        backend="python",
        python_class=None,
    )

    class _RuntimeRegistry:
        def get_tool(self, _name: str):
            return object()

    with (
        patch(
            "brain_researcher.services.tools.catalog_loader.is_workflow_tool_id",
            return_value=True,
        ),
        patch(
            "brain_researcher.services.tools.tool_registry.ToolRegistry.from_env",
            return_value=_RuntimeRegistry(),
        ) as mocked_from_env,
    ):
        reg = UnifiedToolRegistry()
        assert reg.is_toolspec_runtime_callable(spec) is True
        assert reg.is_toolspec_runtime_callable(spec) is True

    mocked_from_env.assert_called_once_with(
        light_mode=True,
        use_capabilities=False,
        enable_integrations=False,
    )


def test_non_workflow_runtime_callable_does_not_touch_runtime_registry():
    _workflow_runtime_registry.cache_clear()
    spec = ToolSpec(
        name="python.non_workflow_tool",
        description="not workflow",
        backend="python",
        python_class=None,
    )

    with (
        patch(
            "brain_researcher.services.tools.catalog_loader.is_workflow_tool_id",
            return_value=False,
        ),
        patch(
            "brain_researcher.services.tools.tool_registry.ToolRegistry.from_env",
        ) as mocked_from_env,
    ):
        reg = UnifiedToolRegistry()
        assert reg.is_toolspec_runtime_callable(spec) is False

    mocked_from_env.assert_not_called()
