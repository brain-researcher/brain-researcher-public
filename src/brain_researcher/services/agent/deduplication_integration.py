"""Backward-compatible re-export shim for the deduplication integration.

The implementation now lives in
``brain_researcher.services.tools.deduplication_integration``. It carries no
agent-layer dependencies and is instantiated by ``tools.tool_registry``;
relocating it to the tools layer removes a ``tools -> agent`` import back-edge.
Importing it here (``services.agent`` -> ``services.tools``) is a forward,
layer-respecting dependency. Existing callers that import from
``brain_researcher.services.agent.deduplication_integration`` continue to work
unchanged.
"""

from __future__ import annotations

from brain_researcher.services.tools.deduplication_integration import (  # noqa: F401
    AgentDataDeduplication,
    AgentDeduplicationConfig,
    DeduplicatedToolWrapper,
    QueryDeduplicationMiddleware,
    setup_agent_deduplication,
    wrap_tools_for_deduplication,
)

__all__ = [
    "AgentDataDeduplication",
    "AgentDeduplicationConfig",
    "DeduplicatedToolWrapper",
    "QueryDeduplicationMiddleware",
    "setup_agent_deduplication",
    "wrap_tools_for_deduplication",
]
