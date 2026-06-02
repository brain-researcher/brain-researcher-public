"""Backward-compatible re-export shim for the streaming integration.

The implementation now lives in
``brain_researcher.services.tools.streaming_integration``. It carries no
agent-layer dependencies and is instantiated by ``tools.tool_registry``;
relocating it to the tools layer removes a ``tools -> agent`` import back-edge.
Importing it here (``services.agent`` -> ``services.tools``) is a forward,
layer-respecting dependency. Existing callers that import from
``brain_researcher.services.agent.streaming_integration`` continue to work
unchanged.
"""

from __future__ import annotations

from brain_researcher.services.tools.streaming_integration import (  # noqa: F401
    AgentStreamingManager,
    AgentStreamMessage,
    AgentStreamProcessor,
    AgentStreamType,
    StreamingToolWrapper,
    setup_agent_streaming,
    wrap_tools_for_streaming,
)

__all__ = [
    "AgentStreamMessage",
    "AgentStreamProcessor",
    "AgentStreamType",
    "AgentStreamingManager",
    "StreamingToolWrapper",
    "setup_agent_streaming",
    "wrap_tools_for_streaming",
]
