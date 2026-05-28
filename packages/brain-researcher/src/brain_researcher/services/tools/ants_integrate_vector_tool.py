"""ANTs IntegrateVectorField thin wrapper backed by NiWrap (ants.ANTSIntegrateVectorField.run)."""

from pathlib import Path
from typing import List

from pydantic import BaseModel

from brain_researcher.services.tools.niwrap.executor import execute_niwrap_tool
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class ANTsIntegrateVectorFieldArgs(BaseModel):
    """Pass-through args for IntegrateVectorField; NiWrap schema is source of truth."""

    model_config = dict(extra="allow")


class ANTsIntegrateVectorFieldTool(NeuroToolWrapper):
    """Thin wrapper delegating to NiWrap ants.ANTSIntegrateVectorField.run."""

    def get_tool_name(self) -> str:
        return "ants_integrate_vector_field"

    def get_tool_description(self) -> str:
        return "ANTs IntegrateVectorField delegated to NiWrap Boutiques definition ants.ANTSIntegrateVectorField.run (descriptor pending)."

    def get_args_schema(self):
        return ANTsIntegrateVectorFieldArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            ANTsIntegrateVectorFieldArgs(**kwargs)
        except Exception as exc:  # pragma: no cover
            return ToolResult(status="error", error=str(exc), data={})

        output = kwargs.get("output") or kwargs.get("output_prefix")
        if output:
            try:
                Path(output).parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

        try:
            data = execute_niwrap_tool(
                tool_definition=None,
                tool_name="ants.ANTSIntegrateVectorField.run",
                parameters=kwargs,
            )
            return ToolResult(status="success", data=data)
        except Exception as exc:
            return ToolResult(status="error", error=str(exc), data={})


def get_all_tools() -> List[NeuroToolWrapper]:
    """Public factory for registry discovery."""
    return [ANTsIntegrateVectorFieldTool()]


class ANTsIntegrateVectorFieldTools:
    """Back-compat collection wrapper."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        return get_all_tools()


__all__ = [
    "ANTsIntegrateVectorFieldTool",
    "ANTsIntegrateVectorFieldTools",
    "ANTsIntegrateVectorFieldArgs",
]
