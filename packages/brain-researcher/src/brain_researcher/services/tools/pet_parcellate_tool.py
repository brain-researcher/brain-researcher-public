"""PET ROI parcellation tool stub for pipeline planning.

This module provides a stub implementation of ROI-based SUVR extraction from
PET images using parcellation atlases. Returns deterministic file paths for
planning phase validation.
"""

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class PETParcellateArgs(BaseModel):
    """Arguments for PET ROI parcellation."""

    suvr_map: str = Field(description="Path to SUVR statistical map")
    parcellation_labels: str = Field(
        description="Path to parcellation atlas volume with integer ROI labels"
    )
    atlas_name: str = Field(
        description="Atlas identifier (e.g., 'Schaefer2018_200', 'AAL', 'DKT')"
    )
    output_dir: Optional[str] = Field(
        default=None, description="Directory to store parcellation outputs"
    )


class PETParcellateTool(NeuroToolWrapper):
    """Extract ROI-wise SUVR values from PET SUVR map.

    This stub tool simulates extracting mean SUVR values for each ROI defined
    in a parcellation atlas. In production, this would compute statistics
    (mean, median, std) for each labeled region.

    Returns:
        - roi_suvr_table: CSV/TSV table with ROI labels and SUVR values
    """

    def get_tool_name(self) -> str:
        return "pet_parcellate"

    def get_tool_description(self) -> str:
        return (
            "Extract ROI-wise SUVR values from PET SUVR map using atlas parcellation."
        )

    def get_args_schema(self):
        return PETParcellateArgs

    def _run(self, **kwargs) -> ToolResult:
        """Execute PET ROI parcellation stub.

        Args:
            **kwargs: Arguments matching PETParcellateArgs schema

        Returns:
            ToolResult with outputs dictionary containing:
                - roi_suvr_table: Path to CSV/TSV table with ROI SUVR values
        """
        args = PETParcellateArgs(**kwargs)

        # Determine output directory
        output_root = Path(args.output_dir or Path.cwd() / "pet_parcellate")
        output_root.mkdir(parents=True, exist_ok=True)

        # Extract number of regions from atlas name (e.g., Schaefer2018_200 -> 200)
        n_regions = 200  # Default
        if "_" in args.atlas_name:
            try:
                n_regions = int(args.atlas_name.split("_")[-1])
            except ValueError:
                pass  # Use default

        # Generate deterministic output paths
        roi_table_path = output_root / f"{args.atlas_name}_roi_suvr.csv"

        outputs = {
            "roi_suvr_table": str(roi_table_path),
        }

        summary = {
            "atlas_name": args.atlas_name,
            "n_regions": n_regions,
            "output_format": "csv",
            "columns": ["roi_id", "roi_label", "mean_suvr", "std_suvr", "volume_mm3"],
        }

        return ToolResult(
            status="success",
            data={"outputs": outputs, "summary": summary},
            message=f"Extracted SUVR values for {n_regions} ROIs from {args.atlas_name}",
        )


class PETParcellateTools:
    """Factory class for PET parcellation tools."""

    @staticmethod
    def get_pet_parcellate() -> PETParcellateTool:
        """Get PET parcellation tool instance."""
        return PETParcellateTool()
