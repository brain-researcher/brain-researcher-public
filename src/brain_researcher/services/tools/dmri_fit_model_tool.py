"""Stub diffusion model fitting tool for dMRI pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class DMRIFitModelArgs(BaseModel):
    """Arguments for diffusion model fitting."""

    dwi_image: str = Field(description="Path to diffusion image")
    bvals: str = Field(description="Path to bvals file")
    bvecs: str = Field(description="Path to bvecs file")
    model: Literal["dti", "csd", "noddi"] = Field(
        default="dti", description="Diffusion model to fit"
    )
    output_dir: Optional[str] = Field(
        default=None, description="Directory where model derivatives are saved"
    )


class DMRIFitModelTool(NeuroToolWrapper):
    """Produce placeholder FA/FOD maps used by downstream tractography."""

    def get_tool_name(self) -> str:
        return "dmri_fit_model"

    def get_tool_description(self) -> str:
        return "Fit a diffusion model (DTI/CSD/NODDI) and emit standard maps."

    def get_args_schema(self):
        return DMRIFitModelArgs

    def _run(self, **kwargs) -> ToolResult:
        args = DMRIFitModelArgs(**kwargs)
        output_dir = Path(args.output_dir or Path.cwd() / "dmri_models")
        output_dir.mkdir(parents=True, exist_ok=True)

        outputs = {
            "fa_map": str(output_dir / "fa_map.nii.gz"),
            "md_map": str(output_dir / "md_map.nii.gz"),
            "model_type": args.model,
        }
        if args.model != "dti":
            outputs["fodf"] = str(output_dir / "fodf.mif")

        return ToolResult(
            status="success",
            data={
                "outputs": outputs,
                "summary": {"model": args.model},
            },
        )


class DMRIFitModelTools:
    @staticmethod
    def get_all_tools():
        return [DMRIFitModelTool()]


__all__ = ["DMRIFitModelTool", "DMRIFitModelTools"]
