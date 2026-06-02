"""Backward-compatible re-export shim for the plugin integration.

The implementation now lives in
``brain_researcher.services.tools.plugin_integration``. It carries no
agent-layer dependencies and is instantiated by ``tools.tool_registry``;
relocating it to the tools layer removes a ``tools -> agent`` import back-edge.
Importing it here (``services.agent`` -> ``services.tools``) is a forward,
layer-respecting dependency. Existing callers that import from
``brain_researcher.services.agent.plugin_integration`` continue to work
unchanged.
"""

from __future__ import annotations

from brain_researcher.services.tools.plugin_integration import (  # noqa: F401
    AgentPluginConfig,
    AgentPluginManager,
    ExampleAPIPlugin,
    PluginDataSourceTool,
    PluginToolRegistry,
    register_plugins_with_tools,
    setup_agent_plugins,
)

__all__ = [
    "AgentPluginConfig",
    "AgentPluginManager",
    "ExampleAPIPlugin",
    "PluginDataSourceTool",
    "PluginToolRegistry",
    "register_plugins_with_tools",
    "setup_agent_plugins",
]
