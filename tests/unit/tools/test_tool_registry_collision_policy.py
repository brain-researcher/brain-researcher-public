from __future__ import annotations

from unittest.mock import patch

from brain_researcher.services.tools.tool_registry import ToolRegistry


class _FakeTool:
    def __init__(self, name: str):
        self._name = name

    def get_tool_name(self) -> str:
        return self._name

    def get_tool_description(self) -> str:
        return f"desc:{self._name}"


class _FakeLegacyRegistry:
    def __init__(self, tools):
        self._tools = list(tools)

    def get_all_tools(self):
        return list(self._tools)


def test_adapter_mode_prefers_canonical_tool_on_collision(monkeypatch):
    monkeypatch.setenv("BR_TOOL_REGISTRY_BACKEND", "adapter")
    monkeypatch.setenv("BR_TOOL_REGISTRY_MUTATION_MODE", "compat")

    canonical_dup = _FakeTool("dup.tool")
    legacy_dup = _FakeTool("dup.tool")
    legacy_only = _FakeTool("legacy.only")

    with (
        patch(
            "brain_researcher.services.tools.tool_registry.CanonicalRuntimeAdapter.load_runtime_tools",
            return_value=[canonical_dup],
        ),
        patch.object(
            ToolRegistry,
            "_build_legacy_supplement_registry",
            return_value=_FakeLegacyRegistry([legacy_dup, legacy_only]),
        ),
        patch.object(ToolRegistry, "_register_grandmaster_tools"),
        patch.object(ToolRegistry, "_register_prefixed_stub_tools"),
        patch.object(ToolRegistry, "_build_tool_index"),
    ):
        registry = ToolRegistry(
            auto_discover=True,
            use_capabilities=False,
            enable_integrations=False,
            light_mode=True,
        )

    assert registry.get_tool("dup.tool") is canonical_dup
    assert registry.get_tool("legacy.only") is legacy_only
