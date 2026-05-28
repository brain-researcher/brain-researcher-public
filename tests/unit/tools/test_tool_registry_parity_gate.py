from __future__ import annotations

from unittest.mock import patch

from brain_researcher.services.tools.tool_registry import ToolRegistry


class _FakeTool:
    def __init__(self, name: str):
        self._name = name

    def get_tool_name(self) -> str:
        return self._name

    def get_tool_description(self) -> str:
        return self._name


class _FakeLegacyRegistry:
    def __init__(self, tools):
        self._tools = list(tools)

    def get_all_tools(self):
        return list(self._tools)


def test_shadow_compare_emits_collision_report(monkeypatch):
    monkeypatch.setenv("BR_TOOL_REGISTRY_BACKEND", "adapter")
    monkeypatch.setenv("BR_TOOL_REGISTRY_MUTATION_MODE", "compat")
    monkeypatch.setenv("BR_TOOL_REGISTRY_SHADOW_COMPARE", "1")

    with (
        patch(
            "brain_researcher.services.tools.tool_registry.CanonicalRuntimeAdapter.load_runtime_tools",
            return_value=[_FakeTool("dup.tool"), _FakeTool("canon.only")],
        ),
        patch.object(
            ToolRegistry,
            "_build_legacy_supplement_registry",
            return_value=_FakeLegacyRegistry(
                [_FakeTool("dup.tool"), _FakeTool("legacy.only")]
            ),
        ),
        patch.object(ToolRegistry, "_register_grandmaster_tools"),
        patch.object(ToolRegistry, "_register_prefixed_stub_tools"),
        patch.object(ToolRegistry, "_build_tool_index"),
        patch.object(ToolRegistry, "_emit_shadow_compare") as emit_shadow,
    ):
        ToolRegistry(
            auto_discover=True,
            use_capabilities=False,
            enable_integrations=False,
            light_mode=True,
        )

    emit_shadow.assert_called_once()
    collision_ids = emit_shadow.call_args.args[-1]
    assert "dup.tool" in collision_ids
