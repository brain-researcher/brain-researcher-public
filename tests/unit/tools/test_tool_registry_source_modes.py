from __future__ import annotations

import pytest
from unittest.mock import patch

from brain_researcher.services.tools.tool_registry import ToolRegistry


def test_tool_registry_from_env_defaults_to_adapter(monkeypatch):
    monkeypatch.delenv("BR_TOOL_REGISTRY_BACKEND", raising=False)

    with (
        patch.object(ToolRegistry, "_discover_tools_from_canonical_adapter") as adapter,
        patch.object(ToolRegistry, "_discover_tools") as legacy,
        patch.object(ToolRegistry, "_build_tool_index"),
    ):
        registry = ToolRegistry.from_env(
            auto_discover=True,
            use_capabilities=False,
            enable_integrations=False,
            light_mode=True,
        )

    assert registry.source_backend == "adapter"
    adapter.assert_called_once()
    legacy.assert_not_called()


def test_tool_registry_from_env_respects_legacy_backend(monkeypatch):
    monkeypatch.setenv("BR_TOOL_REGISTRY_BACKEND", "legacy")

    with (
        patch.object(ToolRegistry, "_discover_tools_from_canonical_adapter") as adapter,
        patch.object(ToolRegistry, "_discover_tools") as legacy,
        patch.object(ToolRegistry, "_build_tool_index"),
    ):
        registry = ToolRegistry.from_env(
            auto_discover=True,
            use_capabilities=False,
            enable_integrations=False,
            light_mode=True,
        )

    assert registry.source_backend == "legacy"
    legacy.assert_called_once()
    adapter.assert_not_called()


def test_canonical_adapter_failure_falls_back_when_fail_open_enabled():
    registry = ToolRegistry(
        auto_discover=False,
        use_capabilities=False,
        enable_integrations=False,
        light_mode=True,
        source_backend="adapter",
    )
    registry.fail_open = True

    with (
        patch(
            "brain_researcher.services.tools.tool_registry.CanonicalRuntimeAdapter"
        ) as adapter_cls,
        patch.object(registry, "_discover_tools") as legacy_discover,
    ):
        adapter_cls.return_value.load_runtime_tools.side_effect = RuntimeError(
            "canonical load failure"
        )
        registry._discover_tools_from_canonical_adapter()

    legacy_discover.assert_called_once()


def test_canonical_adapter_failure_reraises_when_fail_open_disabled():
    registry = ToolRegistry(
        auto_discover=False,
        use_capabilities=False,
        enable_integrations=False,
        light_mode=True,
        source_backend="adapter",
    )
    registry.fail_open = False

    with patch(
        "brain_researcher.services.tools.tool_registry.CanonicalRuntimeAdapter"
    ) as adapter_cls:
        adapter_cls.return_value.load_runtime_tools.side_effect = RuntimeError(
            "canonical load failure"
        )
        with pytest.raises(RuntimeError, match="canonical load failure"):
            registry._discover_tools_from_canonical_adapter()
