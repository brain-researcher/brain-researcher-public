"""Stub coregistration tool for image registration."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class CoregRegisterArgs(BaseModel):
    """Arguments for image coregistration."""

    moving_image: str = Field(description="Path to moving image (CT, fMRI, etc.)")
    fixed_image: str = Field(
        description="Path to fixed/reference image (T1w, MNI template)"
    )
    cost_function: str = Field(
        default="mi", description="Cost function (mi, nmi, corratio)"
    )
    output_dir: Optional[str] = Field(
        default=None, description="Directory to store registration outputs"
    )


class CoregRegisterTool(NeuroToolWrapper):
    """Stub that pretends to register images across modalities."""

    def get_tool_name(self) -> str:
        return "coreg_register"

    def get_tool_description(self) -> str:
        return "Compute transformation matrix to register moving image to fixed image."

    def get_args_schema(self):
        return CoregRegisterArgs

    def _run(self, **kwargs) -> ToolResult:
        args = CoregRegisterArgs(**kwargs)
        output_dir = Path(args.output_dir or Path.cwd() / "coreg_register")
        output_dir.mkdir(parents=True, exist_ok=True)

        transform_path = output_dir / "transform.mat"
        registered_path = output_dir / "registered.nii.gz"

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "transform_matrix": str(transform_path),
                    "registered_image": str(registered_path),
                },
                "summary": {
                    "cost_function": args.cost_function,
                    "cost_value": 0.85,
                    "moving": args.moving_image,
                    "fixed": args.fixed_image,
                },
            },
        )


class CoregRegisterTools:
    @staticmethod
    def get_all_tools():
        return [CoregRegisterTool()]


__all__ = ["CoregRegisterTool", "CoregRegisterTools"]
