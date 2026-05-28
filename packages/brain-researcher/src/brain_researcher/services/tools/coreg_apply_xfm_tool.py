"""Stub coregistration tool for applying transformations."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class CoregApplyXfmArgs(BaseModel):
    """Arguments for applying spatial transformations."""

    input_volume: str = Field(description="Volume to transform")
    transform_matrix: str = Field(
        description="Transformation matrix from coreg_register"
    )
    reference_image: str = Field(
        description="Reference image defining target space"
    )
    interpolation: str = Field(
        default="trilinear", description="Interpolation method (trilinear, nearest, spline)"
    )
    output_dir: Optional[str] = Field(
        default=None, description="Directory to store transformed volume"
    )


class CoregApplyXfmTool(NeuroToolWrapper):
    """Stub that pretends to apply spatial transformations to volumes."""

    def get_tool_name(self) -> str:
        return "coreg_apply_xfm"

    def get_tool_description(self) -> str:
        return "Apply transformation matrix to resample volume into target space."

    def get_args_schema(self):
        return CoregApplyXfmArgs

    def _run(self, **kwargs) -> ToolResult:
        args = CoregApplyXfmArgs(**kwargs)
        output_dir = Path(args.output_dir or Path.cwd() / "coreg_apply_xfm")
        output_dir.mkdir(parents=True, exist_ok=True)

        transformed_path = output_dir / "transformed.nii.gz"

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "transformed_volume": str(transformed_path),
                },
                "summary": {
                    "interpolation": args.interpolation,
                    "transform": args.transform_matrix,
                    "reference": args.reference_image,
                },
            },
        )


class CoregApplyXfmTools:
    @staticmethod
    def get_all_tools():
        return [CoregApplyXfmTool()]


__all__ = ["CoregApplyXfmTool", "CoregApplyXfmTools"]
