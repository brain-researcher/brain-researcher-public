"""Bridge utilities for accessing MCP tool metadata within the agent layer.

Implementation relocated to ``services/shared/toolsagent_tool_metadata_bridge``
so that ``services/tools`` can depend on the metadata helpers without a
tools -> agent back-edge. This module re-exports the public API for callers.
"""

from __future__ import annotations

from brain_researcher.services.shared.toolsagent_tool_metadata_bridge import (
    TOOL_METADATA,
    get_example_payload,
    get_output_examples,
    get_resource_hints,
    get_tool_metadata,
    iter_tool_definitions,
)

__all__ = [
    "TOOL_METADATA",
    "get_example_payload",
    "get_output_examples",
    "get_resource_hints",
    "get_tool_metadata",
    "iter_tool_definitions",
]
