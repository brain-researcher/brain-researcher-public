"""NiWrap agent tools for accessing ~1900 neuroimaging tools.

This module provides three agent-facing tools for interacting with NiWrap:
- NiWrapSearchTool: Search for tools by keyword/description
- NiWrapSchemaTool: Get parameter schema for a specific tool
- NiWrapExecuteTool: Execute a tool with given parameters

These tools wrap the unified tools package (services/tools/niwrap/).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic schemas for tool arguments
# ============================================================================


class NiWrapSearchArgs(BaseModel):
    """Arguments for NiWrap tool search."""

    query: str = Field(
        description="Search query (keywords like 'brain extraction', 'registration', 'smoothing')"
    )
    package: Optional[str] = Field(
        default=None,
        description="Filter by package name (e.g., 'afni', 'fsl', 'ants', 'freesurfer')",
    )
    limit: int = Field(
        default=8, ge=1, le=50, description="Maximum number of results to return"
    )


class NiWrapSchemaArgs(BaseModel):
    """Arguments for getting NiWrap tool schema."""

    tool_name: str = Field(
        description=(
            "Runtime canonical tool id or full NiWrap tool name "
            "(e.g., 'fsl_bet', 'spm12_vbm', or 'fsl.6.0.7.bet.run')"
        )
    )


class NiWrapExecuteArgs(BaseModel):
    """Arguments for executing a NiWrap tool."""

    tool_name: str = Field(
        description=(
            "Runtime canonical tool id or full NiWrap tool name. "
            "Legacy compatibility only; prefer Neurodesk execution recipes for execution."
        )
    )
    parameters: Dict[str, Any] = Field(
        description="Parameter name-value mapping for the tool"
    )
    preview: bool = Field(
        default=False, description="If true, only return the command without executing"
    )
    execute: Optional[bool] = Field(
        default=None,
        description="If explicitly true, execute; if false, force preview. If None, inferred from preview flag.",
    )


# ============================================================================
# Tool implementations
# ============================================================================


class NiWrapSearchTool(NeuroToolWrapper):
    """Search for neuroimaging tools in the NiWrap catalog.

    Use this tool to find tools for specific tasks like brain extraction,
    registration, smoothing, etc.
    """

    def get_tool_name(self) -> str:
        return "niwrap_search"

    def get_tool_description(self) -> str:
        return (
            "Search the NiWrap catalog of ~1900 neuroimaging tools. "
            "Use keywords to find tools for tasks like 'brain extraction', "
            "'registration', 'smoothing', 'segmentation', etc. "
            "Optionally filter by package (afni, fsl, ants, freesurfer, mrtrix)."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return NiWrapSearchArgs

    def _run(
        self,
        query: str,
        package: Optional[str] = None,
        limit: int = 8,
    ) -> ToolResult:
        """Search for tools matching the query."""
        try:
            from brain_researcher.services.tools.niwrap import (
                get_niwrap_tools,
            )
        except ImportError as e:
            return ToolResult(
                status="error",
                error=f"NiWrap tools not available: {e}",
                data={"query": query},
            )

        try:
            # Get all tools (uses cache)
            all_tools = get_niwrap_tools()

            if not all_tools:
                return ToolResult(
                    status="success",
                    data={
                        "matches": [],
                        "query": query,
                        "message": "No tools loaded. Check NiWrap installation.",
                    },
                )

            # Search logic
            query_lower = query.lower()
            matches = []

            for tool_def in all_tools:
                # Filter by package if specified
                if package and not tool_def["name"].startswith(f"{package}."):
                    continue

                # Search in name, description, and tags
                name = tool_def.get("name", "").lower()
                description = tool_def.get("description", "").lower()
                tags = [t.lower() for t in tool_def.get("tags", [])]

                if (
                    query_lower in name
                    or query_lower in description
                    or any(query_lower in tag for tag in tags)
                ):

                    # Extract summary info
                    metadata = tool_def.get("metadata", {})
                    matches.append(
                        {
                            "name": tool_def["name"],
                            "package": metadata.get("package", "unknown"),
                            "description": tool_def.get("description", "")[:200],
                            "tags": tool_def.get("tags", []),
                        }
                    )

                    if len(matches) >= limit:
                        break

            if not matches:
                return ToolResult(
                    status="success",
                    data={
                        "matches": [],
                        "query": query,
                        "package": package,
                        "message": f"No tools found matching '{query}'",
                    },
                )

            return ToolResult(
                status="success",
                data={
                    "matches": matches,
                    "query": query,
                    "package": package,
                    "total_found": len(matches),
                },
            )

        except Exception as e:
            logger.error(f"NiWrap search failed: {e}", exc_info=True)
            return ToolResult(
                status="error",
                error=str(e),
                data={"query": query},
            )


class NiWrapSchemaTool(NeuroToolWrapper):
    """Get parameter schema for a specific NiWrap tool.

    Use this after searching to get the required and optional parameters
    for a tool before executing it.
    """

    def get_tool_name(self) -> str:
        return "niwrap_schema"

    def get_tool_description(self) -> str:
        return (
            "Get the parameter schema for a NiWrap tool. "
            "Returns required and optional parameters with their types and descriptions. "
            "Accepts runtime canonical IDs such as 'fsl_bet' and 'spm12_vbm'."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return NiWrapSchemaArgs

    def _run(self, tool_name: str) -> ToolResult:
        """Get schema for a specific tool."""
        try:
            from brain_researcher.services.tools.niwrap import get_tool_by_name
        except ImportError as e:
            return ToolResult(
                status="error",
                error=f"NiWrap tools not available: {e}",
                data={"tool_name": tool_name},
            )

        try:
            tool_def = get_tool_by_name(tool_name)

            if not tool_def:
                return ToolResult(
                    status="error",
                    error=f"Tool '{tool_name}' not found in catalog",
                    data={"tool_name": tool_name},
                )

            # Extract schema information
            metadata = tool_def.get("metadata", {})
            boutiques_inputs = metadata.get("boutiques_inputs", [])
            resources = metadata.get("resources", {})

            # Separate required and optional parameters
            required_params = []
            optional_params = []

            for input_spec in boutiques_inputs:
                input_id = input_spec.get("id")
                if not input_id:
                    continue

                param_info = {
                    "id": input_id,
                    "type": input_spec.get("type", "String"),
                    "description": input_spec.get("description", ""),
                    "command_flag": input_spec.get("command-line-flag"),
                }

                # Add constraints if present
                if "minimum" in input_spec:
                    param_info["minimum"] = input_spec["minimum"]
                if "maximum" in input_spec:
                    param_info["maximum"] = input_spec["maximum"]
                if "value-choices" in input_spec:
                    param_info["choices"] = input_spec["value-choices"]
                if "default-value" in input_spec:
                    param_info["default"] = input_spec["default-value"]

                # Categorize
                is_optional = input_spec.get("optional", False)
                if input_spec.get("type") == "Flag":
                    is_optional = True

                if is_optional:
                    optional_params.append(param_info)
                else:
                    required_params.append(param_info)

            return ToolResult(
                status="success",
                data={
                    "tool": tool_name,
                    "description": tool_def.get("description", ""),
                    "package": metadata.get("package"),
                    "version": metadata.get("version"),
                    "required": required_params,
                    "optional": optional_params,
                    "resource_hints": resources,
                    "command_template": metadata.get("command_line", ""),
                },
            )

        except Exception as e:
            logger.error(f"NiWrap schema retrieval failed: {e}", exc_info=True)
            return ToolResult(
                status="error",
                error=str(e),
                data={"tool_name": tool_name},
            )


class NiWrapExecuteTool(NeuroToolWrapper):
    """Execute a NiWrap tool with given parameters.

    Use this after getting the schema to execute a tool with the required parameters.
    Use preview=True to see the command without executing.
    """

    def get_tool_name(self) -> str:
        return "niwrap_execute"

    def get_tool_description(self) -> str:
        return (
            "Legacy NiWrap execution compatibility path. "
            "Accepts runtime canonical IDs or NiWrap descriptors, but prefer "
            "Neurodesk execution recipes for primary execution. "
            "Set preview=True to see the command without executing."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return NiWrapExecuteArgs

    def _run(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        preview: bool = False,
        execute: Optional[bool] = None,
    ) -> ToolResult:
        """Execute a tool with given parameters."""
        try:
            from brain_researcher.services.tools.niwrap import (
                execute_niwrap_tool,
                get_tool_by_name,
                preview_niwrap_tool,
            )
        except ImportError as e:
            return ToolResult(
                status="error",
                error=f"NiWrap tools not available: {e}",
                data={"tool_name": tool_name},
            )

        try:
            tool_def = get_tool_by_name(tool_name)

            if not tool_def:
                return ToolResult(
                    status="error",
                    error=f"Tool '{tool_name}' not found in catalog",
                    data={"tool_name": tool_name},
                )

            # decide preview vs execute (preview takes precedence if execute not explicitly True)
            if execute is None:
                execute = not preview

            if not execute:
                # Preview mode - just render the command
                preview_result = preview_niwrap_tool(tool_def, parameters)
                return ToolResult(
                    status="success",
                    data={
                        **preview_result,
                        "preview": True,
                        "execute": False,
                    },
                )

            # Execute the tool
            exec_result = execute_niwrap_tool(tool_def, parameters)

            # Check for execution errors
            if exec_result.get("exit_code", -1) != 0:
                error_msg = exec_result.get("error") or exec_result.get(
                    "stderr", "Unknown error"
                )
                return ToolResult(
                    status="error",
                    error=error_msg,
                    data=exec_result,
                )

            return ToolResult(
                status="success",
                data=exec_result,
            )

        except Exception as e:
            logger.error(f"NiWrap execution failed: {e}", exc_info=True)
            return ToolResult(
                status="error",
                error=str(e),
                data={"tool_name": tool_name, "parameters": parameters},
            )


# ============================================================================
# Tool collection for registry
# ============================================================================


class NiWrapTools:
    """Collection of NiWrap agent tools.

    Provides the three NiWrap tools: search, schema, and execute.
    """

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Return all NiWrap agent tools."""
        return [
            NiWrapSearchTool(),
            NiWrapSchemaTool(),
            NiWrapExecuteTool(),
        ]


__all__ = [
    "NiWrapSearchTool",
    "NiWrapSchemaTool",
    "NiWrapExecuteTool",
    "NiWrapTools",
]
