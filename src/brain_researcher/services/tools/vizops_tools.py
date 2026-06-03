"""Grandmaster Layer 6: Visualization & Ops tool wrappers.

Cohesive cluster of thin-wrapper Tool+Args class pairs covering:
- Brain-map and matrix plotting (PlotBrainMap, PlotMatrix)
- Interactive HTML visualization (VisualizeInteractive)
- Study-report generation (GenerateStudyReport)
- Human-review checkpoint (RequestUserReview)
- Directory archiving (CreateArchive)

These classes were extracted from grandmaster_tools.py and are re-exported
from there for backward compatibility.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

# ---------------------------------------------------------------------------
# PlotBrainMap
# ---------------------------------------------------------------------------


class PlotBrainMapArgs(BaseModel):
    stat_map: str = Field(description="Path to statistical map")
    output_file: str | None = Field(default=None, description="Output image path (png)")
    threshold: float | str | None = Field(
        default="auto", description="Threshold or 'auto'"
    )
    title: str | None = Field(default=None, description="Plot title")


class PlotBrainMapTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "plot_brain_map"

    def get_tool_description(self) -> str:
        return "Plot a statistical map (wrapper over viz_stat_maps)."

    def get_args_schema(self):
        return PlotBrainMapArgs

    def _run(
        self,
        stat_map: str,
        output_file: str | None = None,
        threshold: float | str | None = "auto",
        title: str | None = None,
        **_: Any,
    ) -> ToolResult:
        from brain_researcher.services.tools.grandmaster_tools import _call_wrapper
        from brain_researcher.services.tools.nilearn_viz import VizStatMapTool

        payload = {
            "stat_map": stat_map,
            "output_file": output_file,
            "threshold": threshold,
            "title": title,
        }
        return _call_wrapper(VizStatMapTool(), payload)


# ---------------------------------------------------------------------------
# PlotMatrix
# ---------------------------------------------------------------------------


class PlotMatrixArgs(BaseModel):
    matrix_file: str = Field(description="Path to connectivity matrix (.npy or CSV)")
    output_file: str | None = Field(default=None, description="Output PNG path")
    title: str | None = Field(default=None, description="Plot title")


class PlotMatrixTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "plot_matrix"

    def get_tool_description(self) -> str:
        return "Plot a matrix heatmap (connectivity, confusion matrix, etc.)."

    def get_args_schema(self):
        return PlotMatrixArgs

    def _run(
        self,
        matrix_file: str,
        output_file: str | None = None,
        title: str | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            import matplotlib
            import numpy as np

            matplotlib.use("Agg", force=True)
            import matplotlib.pyplot as plt

            path = Path(matrix_file)
            if path.suffix == ".npy":
                mat = np.load(path)
            else:
                mat = np.loadtxt(path, delimiter="," if path.suffix == ".csv" else None)
            out_path = Path(output_file) if output_file else Path.cwd() / "matrix.png"
            fig, ax = plt.subplots(figsize=(6, 5))
            im = ax.imshow(mat, aspect="auto", interpolation="nearest")
            fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            if title:
                ax.set_title(title)
            fig.tight_layout()
            fig.savefig(out_path, dpi=200)
            plt.close(fig)
            return ToolResult(
                status="success", data={"outputs": {"figure": str(out_path)}}
            )
        except Exception as exc:
            return ToolResult(
                status="error", error=str(exc), data={"matrix_file": matrix_file}
            )


# ---------------------------------------------------------------------------
# VisualizeInteractive
# ---------------------------------------------------------------------------


class VisualizeInteractiveArgs(BaseModel):
    matrix_file: str = Field(description="Path to matrix (.npy/.csv)")
    output_file: str | None = Field(default=None, description="Output HTML path")
    title: str | None = Field(default=None, description="Title")


class VisualizeInteractiveTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "visualize_interactive"

    def get_tool_description(self) -> str:
        return "Generate a simple interactive HTML visualization (Plotly heatmap)."

    def get_args_schema(self):
        return VisualizeInteractiveArgs

    def _run(
        self,
        matrix_file: str,
        output_file: str | None = None,
        title: str | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            import numpy as np
            import plotly.express as px

            path = Path(matrix_file)
            if path.suffix == ".npy":
                mat = np.load(path)
            else:
                mat = np.loadtxt(path, delimiter="," if path.suffix == ".csv" else None)
            fig = px.imshow(mat, color_continuous_scale="RdBu_r", title=title)
            out_path = Path(output_file) if output_file else Path.cwd() / "matrix.html"
            fig.write_html(str(out_path))
            return ToolResult(
                status="success", data={"outputs": {"html": str(out_path)}}
            )
        except Exception as exc:
            return ToolResult(
                status="error", error=str(exc), data={"matrix_file": matrix_file}
            )


# ---------------------------------------------------------------------------
# GenerateStudyReport
# ---------------------------------------------------------------------------


class GenerateStudyReportArgs(BaseModel):
    title: str = Field(default="Study Report", description="Report title")
    outputs: dict[str, Any] = Field(
        default_factory=dict, description="Outputs to summarize"
    )
    output_file: str | None = Field(default=None, description="Output Markdown path")


class GenerateStudyReportTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "generate_study_report"

    def get_tool_description(self) -> str:
        return "Generate a lightweight Markdown report summarizing outputs/provenance."

    def get_args_schema(self):
        return GenerateStudyReportArgs

    def _run(
        self,
        title: str = "Study Report",
        outputs: dict[str, Any] | None = None,
        output_file: str | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            out_path = (
                Path(output_file) if output_file else Path.cwd() / "study_report.md"
            )
            payload = outputs or {}
            lines = [f"# {title}", "", "## Outputs", ""]
            lines.append("```json")
            lines.append(json.dumps(payload, indent=2, default=str))
            lines.append("```")
            out_path.write_text("\n".join(lines), encoding="utf-8")
            return ToolResult(
                status="success", data={"outputs": {"report": str(out_path)}}
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


# ---------------------------------------------------------------------------
# RequestUserReview
# ---------------------------------------------------------------------------


class RequestUserReviewArgs(BaseModel):
    message: str = Field(description="What to review/confirm")
    artifacts: dict[str, str] | None = Field(
        default=None, description="Optional artifacts to inspect"
    )


class RequestUserReviewTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "request_user_review"

    def get_tool_description(self) -> str:
        return "Request a human review checkpoint (non-blocking marker tool)."

    def get_args_schema(self):
        return RequestUserReviewArgs

    def _run(
        self, message: str, artifacts: dict[str, str] | None = None, **_: Any
    ) -> ToolResult:
        return ToolResult(
            status="success",
            data={
                "requires_user_review": True,
                "message": message,
                "artifacts": artifacts or {},
            },
        )


# ---------------------------------------------------------------------------
# CreateArchive
# ---------------------------------------------------------------------------


class CreateArchiveArgs(BaseModel):
    input_dir: str = Field(description="Directory to archive")
    output_path: str | None = Field(
        default=None, description="Archive path without extension"
    )
    format: Literal["zip", "tar"] = Field(default="zip", description="Archive format")


class CreateArchiveTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "create_archive"

    def get_tool_description(self) -> str:
        return "Create an archive (zip/tar) of a directory."

    def get_args_schema(self):
        return CreateArchiveArgs

    def _run(
        self,
        input_dir: str,
        output_path: str | None = None,
        format: str = "zip",
        **_: Any,
    ) -> ToolResult:
        try:
            src = Path(input_dir)
            if not src.exists():
                return ToolResult(
                    status="error",
                    error="input_dir not found",
                    data={"input_dir": input_dir},
                )
            base = Path(output_path) if output_path else (Path.cwd() / src.name)
            archive = shutil.make_archive(str(base), format, root_dir=str(src))
            return ToolResult(status="success", data={"outputs": {"archive": archive}})
        except Exception as exc:
            return ToolResult(
                status="error", error=str(exc), data={"input_dir": input_dir}
            )


__all__ = [
    "PlotBrainMapArgs",
    "PlotBrainMapTool",
    "PlotMatrixArgs",
    "PlotMatrixTool",
    "VisualizeInteractiveArgs",
    "VisualizeInteractiveTool",
    "GenerateStudyReportArgs",
    "GenerateStudyReportTool",
    "RequestUserReviewArgs",
    "RequestUserReviewTool",
    "CreateArchiveArgs",
    "CreateArchiveTool",
]
