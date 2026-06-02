"""NiWrap tools package.

Provides access to ~1900 neuroimaging tools via Boutiques descriptors.

NiWrap is retained primarily as a metadata/descriptor provider. Runtime-facing
Brain Researcher execution should prefer Neurodesk recipes and canonical
runtime tool IDs; versioned NiWrap descriptor names remain an internal
compatibility detail.

This package includes:
- catalog.py: Tool discovery and caching
- executor.py: Command rendering and containerized execution
- boutiques.py: Boutiques descriptor parsing
- tools.py: Agent-facing tool wrappers (search, schema, execute)

Usage:
    from brain_researcher.services.tools.niwrap import (
        get_niwrap_tools,
        get_tool_by_name,
        execute_niwrap_tool,
        preview_niwrap_tool,
    )

    # Search for tools
    tools = get_niwrap_tools(packages=["fsl"], limit=10)

    # Get specific tool (runtime canonical ids are accepted too)
    tool = get_tool_by_name("fsl_bet")

    # Preview execution
    preview = preview_niwrap_tool(tool, {"infile": "/data/brain.nii"})

    # Execute tool
    result = execute_niwrap_tool(tool, {"infile": "/data/brain.nii"})
"""

from brain_researcher.services.tools.niwrap.catalog import (
    clear_cache,
    get_niwrap_tools,
    get_tool_by_name,
)
from brain_researcher.services.tools.niwrap.executor import (
    execute_niwrap_tool,
    preview_niwrap_tool,
    render_boutiques_command,
)

__all__ = [
    "get_niwrap_tools",
    "get_tool_by_name",
    "clear_cache",
    "execute_niwrap_tool",
    "preview_niwrap_tool",
    "render_boutiques_command",
]
