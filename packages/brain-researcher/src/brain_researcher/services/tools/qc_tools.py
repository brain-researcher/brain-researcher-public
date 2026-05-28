"""Quality control tools for neuroimaging data."""

import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from brain_researcher.core.utils.svg_qc_gallery import (
    build_rasterized_records,
    detect_svg_rasterization_runtime,
    discover_svg_paths,
    svg_rasterization_error,
    write_gallery_html,
)
from brain_researcher.services.tools.pipelines import (
    build_mriqc_command,
    mriqc_from_payload,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult
from brain_researcher.services.tools.utils import run_subprocess

logger = logging.getLogger(__name__)


class MRIQCGroupArgs(BaseModel):
    """Arguments for MRIQC group report."""

    bids_dir: str = Field(description="BIDS directory path")
    mriqc_dir: str = Field(
        description="MRIQC derivatives directory containing participant outputs"
    )


class MRIQCGroupReportTool(NeuroToolWrapper):
    """Tool for generating MRIQC group reports."""

    def get_tool_name(self) -> str:
        return "mriqc_group_report"

    def get_tool_description(self) -> str:
        return "Generate a group-level MRIQC HTML report from participant outputs"

    def get_args_schema(self):
        return MRIQCGroupArgs

    def _run(self, bids_dir: str, mriqc_dir: str) -> ToolResult:
        try:
            payload = {
                "bids_dir": bids_dir,
                "output_dir": mriqc_dir,
                "analysis_level": "group",
            }
            params = mriqc_from_payload(payload)
            cmd = build_mriqc_command(params)
            run_subprocess(cmd)
            return ToolResult(
                status="success",
                data={
                    "command": cmd,
                    "report_path": f"{mriqc_dir}/group_bold.html",
                    "csv_path": f"{mriqc_dir}/group_bold.tsv",
                },
            )
        except Exception as e:
            logger.error(f"MRIQC group report failed: {e}")
            return ToolResult(status="error", error=str(e))


class VisualQCArgs(BaseModel):
    """Arguments for VisualQC."""

    bids_dir: str = Field(description="BIDS directory")
    deriv_dir: str = Field(description="Derivatives directory")
    modality: str = Field(
        default="func_mri",
        description="Modality to visualize (func_mri, T1_mri, freesurfer, etc.)",
    )


class VisualQCLaunchTool(NeuroToolWrapper):
    """Tool for launching VisualQC interface."""

    def get_tool_name(self) -> str:
        return "visual_qc_launch"

    def get_tool_description(self) -> str:
        return "Launch VisualQC interactive interface for manual quality control inspection"

    def get_args_schema(self):
        return VisualQCArgs

    def _run(
        self, bids_dir: str, deriv_dir: str, modality: str = "func_mri"
    ) -> ToolResult:
        try:
            # VisualQC command varies by modality
            if modality == "func_mri":
                cmd = ["visualqc_func_mri", "--bids_dir", bids_dir]
            elif modality == "T1_mri":
                cmd = ["visualqc_t1_mri", "--bids_dir", bids_dir]
            elif modality == "freesurfer":
                cmd = ["visualqc_freesurfer", "--fs_dir", deriv_dir]
            else:
                # Generic visualqc command
                cmd = ["visualqc", modality, bids_dir, deriv_dir]

            run_subprocess(cmd)
            return ToolResult(status="success", data={"command": cmd})
        except Exception as e:
            logger.error(f"VisualQC failed: {e}")
            return ToolResult(status="error", error=str(e))


class CoregQCGalleryArgs(BaseModel):
    """Arguments for building a portable coregistration QC gallery."""

    input_dir: str | None = Field(
        default=None,
        description="Directory containing fMRIPrep-style SVG QC figures.",
    )
    input_glob: str | None = Field(
        default=None,
        description="Optional glob pattern for SVG discovery when input_dir is not enough.",
    )
    output_dir: str = Field(
        description="Output directory for rasterized images and gallery HTML."
    )
    title: str = Field(
        default="Coregistration QC Gallery",
        description="Title shown in the generated HTML gallery.",
    )
    columns: int = Field(
        default=3,
        ge=1,
        description="Requested desktop grid column count in the HTML gallery.",
    )
    image_format: Literal["png", "jpeg", "jpg"] = Field(
        default="png",
        description="Raster image format. PNG is recommended for alignment QC.",
    )
    dpi: int = Field(default=144, ge=72, le=600, description="Rasterization DPI.")
    recursive: bool = Field(
        default=True,
        description="Whether to recurse under input_dir or input_glob matches.",
    )


class CoregQCGalleryTool(NeuroToolWrapper):
    """Rasterize SVG coreg QC assets and build a portable gallery."""

    def get_tool_name(self) -> str:
        return "coreg_qc_gallery"

    def get_tool_description(self) -> str:
        return (
            "Convert fMRIPrep-style coregistration SVGs into PNG/JPEG thumbnails and "
            "build a portable HTML gallery. Requires reportlab, svglib, and either "
            "pdftocairo or pdftoppm at runtime."
        )

    def get_args_schema(self):
        return CoregQCGalleryArgs

    def _run(
        self,
        input_dir: str | None = None,
        input_glob: str | None = None,
        output_dir: str = "",
        title: str = "Coregistration QC Gallery",
        columns: int = 3,
        image_format: str = "png",
        dpi: int = 144,
        recursive: bool = True,
    ) -> ToolResult:
        if not input_dir and not input_glob:
            return ToolResult(
                status="error",
                error="Provide at least one of input_dir or input_glob.",
            )

        runtime = detect_svg_rasterization_runtime()
        if not runtime["ok"]:
            return ToolResult(
                status="error",
                error=svg_rasterization_error(runtime),
                data={"runtime": runtime},
            )

        svg_paths = discover_svg_paths(
            input_dir=input_dir,
            input_glob=input_glob,
            recursive=recursive,
        )
        if not svg_paths:
            return ToolResult(
                status="error",
                error="No SVG files found.",
                data={
                    "input_dir": input_dir,
                    "input_glob": input_glob,
                    "recursive": recursive,
                },
            )

        out_dir = Path(output_dir).expanduser().resolve()
        image_dir = out_dir / "images"
        records = build_rasterized_records(
            svg_paths,
            output_dir=image_dir,
            input_root=input_dir,
            image_format=image_format,
            dpi=dpi,
        )
        html_path = write_gallery_html(
            records,
            out_dir / "index.html",
            title=title,
            columns=columns,
            copy_source_svgs=True,
        )

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "html": str(html_path),
                    "images_dir": str(image_dir),
                    "svgs_dir": str(out_dir / "svgs"),
                },
                "summary": {
                    "n_svg": len(svg_paths),
                    "image_format": image_format,
                    "rasterizer": runtime["rasterizer"],
                    "portable_gallery": True,
                },
                "runtime": runtime,
            },
        )


class QCTools:
    """Collection of quality control tools."""

    def __init__(self):
        self.mriqc_group_report = MRIQCGroupReportTool()
        self.visual_qc_launch = VisualQCLaunchTool()
        self.coreg_qc_gallery = CoregQCGalleryTool()

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        return [
            self.mriqc_group_report,
            self.visual_qc_launch,
            self.coreg_qc_gallery,
        ]

    def get_tool_by_name(self, name: str) -> NeuroToolWrapper | None:
        tool_map = {
            "mriqc_group_report": self.mriqc_group_report,
            "visual_qc_launch": self.visual_qc_launch,
            "coreg_qc_gallery": self.coreg_qc_gallery,
        }
        return tool_map.get(name)
