"""Registry-backed tool for resolving standard spatial templates."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.services.tools.neuroimage_asset_registry import (
    resolve_space_assets,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class ResolveSpaceArgs(BaseModel):
    """Arguments for spatial template resolution."""

    space_name: str = Field(
        description="Target space identifier (MNI152NLin2009cAsym, fsaverage, fsLR)."
    )
    resolution: str | None = Field(
        default=None,
        description="Volume resolution (1mm, 2mm) or surface density (10k, 41k, 164k).",
    )


def _compact_outputs(outputs: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in outputs.items() if value is not None}


class ResolveSpaceTool(NeuroToolWrapper):
    """Resolve standard spatial templates from the local neuroimage asset registry."""

    execution_backend = "python"

    def get_tool_name(self) -> str:
        return "resolve_space"

    def get_tool_description(self) -> str:
        return "Resolve standard spatial template assets from the local registry."

    def get_args_schema(self):
        return ResolveSpaceArgs

    def _run(self, **kwargs) -> ToolResult:
        args = ResolveSpaceArgs(**kwargs)

        try:
            resolved = resolve_space_assets(args.space_name, args.resolution)
        except Exception as exc:
            return ToolResult(
                status="error",
                error=str(exc),
                data={
                    "requested_space": args.space_name,
                    "requested_resolution": args.resolution,
                },
            )

        outputs = {
            "template_volume": resolved["template_volume"],
            "brain_mask": resolved["brain_mask"],
            **(resolved.get("extra_outputs") or {}),
        }
        summary = {
            "space": args.space_name,
            "canonical_space": resolved["canonical_space"],
            "space_kind": resolved["space_kind"],
            "resolution": resolved["resolved_resolution"],
            "template_source": resolved["template_source"],
            "registry_entry": resolved["registry_entry"],
            "registry_path": resolved["registry_path"],
        }

        return ToolResult(
            status="success",
            data={
                "outputs": _compact_outputs(outputs),
                "summary": summary,
            },
        )


class ResolveSpaceTools:
    @staticmethod
    def get_all_tools():
        return [ResolveSpaceTool()]


__all__ = ["ResolveSpaceTool", "ResolveSpaceTools"]
