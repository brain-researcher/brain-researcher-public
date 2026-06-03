"""Stub tool for exporting FreeSurfer surfaces into visualization formats."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class SMRISurfaceExportArgs(BaseModel):
    """Arguments for surface export."""

    surfaces_dir: str = Field(description="FreeSurfer surfaces directory")
    hemi: str = Field(default="lh", description="Hemisphere to export (lh, rh, both)")
    surface_type: str = Field(
        default="pial", description="Surface type (pial, inflated, white, midthickness)"
    )
    output_dir: str | None = Field(
        default=None, description="Directory for exported surface meshes"
    )


class SMRISurfaceExportTool(NeuroToolWrapper):
    """Stub exporter that emits mesh paths for visualization."""

    def get_tool_name(self) -> str:
        return "smri_surface_export"

    def get_tool_description(self) -> str:
        return "Export FreeSurfer surfaces (lh/rh) to formats like GIFTI for visualization."

    def get_args_schema(self):
        return SMRISurfaceExportArgs

    def _run(self, **kwargs) -> ToolResult:
        args = SMRISurfaceExportArgs(**kwargs)
        output_dir = Path(args.output_dir or Path(args.surfaces_dir) / "exports")
        output_dir.mkdir(parents=True, exist_ok=True)

        hemi_tag = args.hemi if args.hemi != "both" else "lh-rh"
        mesh_path = output_dir / f"{hemi_tag}.{args.surface_type}.gii"

        outputs = {"surface_mesh": str(mesh_path)}
        summary = {
            "hemi": args.hemi,
            "surface_type": args.surface_type,
        }

        return ToolResult(
            status="success", data={"outputs": outputs, "summary": summary}
        )


class SMRISurfaceExportTools:
    @staticmethod
    def get_all_tools():
        return [SMRISurfaceExportTool()]


__all__ = ["SMRISurfaceExportTool", "SMRISurfaceExportTools"]
