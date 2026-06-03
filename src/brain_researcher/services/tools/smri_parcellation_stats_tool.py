"""Stub tool for extracting FreeSurfer parcellation statistics."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class SMRIParcellationStatsArgs(BaseModel):
    """Arguments for parcellation statistics extraction."""

    surfaces_dir: str = Field(description="Path to FreeSurfer surfaces directory")
    stats_type: str = Field(
        default="thickness",
        description="Statistic to compute (thickness, volume, area)",
    )
    parcellation: str = Field(
        default="aparc",
        description="Parcellation scheme (aparc, aparc.a2009s, DKT, etc.)",
    )
    output_dir: str | None = Field(
        default=None, description="Directory for exported statistics"
    )


class SMRIParcellationStatsTool(NeuroToolWrapper):
    """Stub that pretends to export ROI statistics."""

    def get_tool_name(self) -> str:
        return "smri_parcellation_stats"

    def get_tool_description(self) -> str:
        return "Compute ROI-level morphometry tables (thickness/volume) from FreeSurfer outputs."

    def get_args_schema(self):
        return SMRIParcellationStatsArgs

    def _run(self, **kwargs) -> ToolResult:
        args = SMRIParcellationStatsArgs(**kwargs)
        output_dir = Path(args.output_dir or Path(args.surfaces_dir).parent / "stats")
        output_dir.mkdir(parents=True, exist_ok=True)

        thickness_path = output_dir / f"{args.parcellation}_thickness.csv"
        volume_path = output_dir / f"{args.parcellation}_volume.csv"

        outputs = {
            "thickness_table": str(thickness_path),
            "volume_table": str(volume_path),
        }

        summary = {
            "n_regions": 68,
            "parcellation": args.parcellation,
            "stats_type": args.stats_type,
        }

        return ToolResult(
            status="success", data={"outputs": outputs, "summary": summary}
        )


class SMRIParcellationStatsTools:
    @staticmethod
    def get_all_tools():
        return [SMRIParcellationStatsTool()]


__all__ = ["SMRIParcellationStatsTool", "SMRIParcellationStatsTools"]
