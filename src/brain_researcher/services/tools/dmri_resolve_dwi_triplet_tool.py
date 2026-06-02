"""Stub resolver to collect DWI + bvals + bvecs triplets."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class DMRIResolveDwiTripletArgs(BaseModel):
    """Arguments for locating diffusion imaging triplets."""

    subject_id: str = Field(description="Subject identifier")
    session_id: Optional[str] = Field(default=None, description="Session label")
    bids_root: str = Field(description="Path to BIDS root directory")


class DMRIResolveDwiTripletTool(NeuroToolWrapper):
    """Return canonical paths for DWI, bvals, bvecs files."""

    def get_tool_name(self) -> str:
        return "dmri_resolve_dwi_triplet"

    def get_tool_description(self) -> str:
        return "Resolve diffusion image + bvals + bvecs for downstream processing."

    def get_args_schema(self):
        return DMRIResolveDwiTripletArgs

    def _run(self, **kwargs) -> ToolResult:
        args = DMRIResolveDwiTripletArgs(**kwargs)
        base = Path(args.bids_root) / f"sub-{args.subject_id}"
        if args.session_id:
            base /= f"ses-{args.session_id}"
        dwi_dir = base / "dwi"

        outputs = {
            "dwi_image": str(dwi_dir / f"sub-{args.subject_id}_dwi.nii.gz"),
            "bvals": str(dwi_dir / f"sub-{args.subject_id}_dwi.bval"),
            "bvecs": str(dwi_dir / f"sub-{args.subject_id}_dwi.bvec"),
        }

        return ToolResult(
            status="success",
            data={"outputs": outputs, "summary": {"session": args.session_id}},
        )


class DMRIResolveDwiTripletTools:
    @staticmethod
    def get_all_tools():
        return [DMRIResolveDwiTripletTool()]


__all__ = ["DMRIResolveDwiTripletTool", "DMRIResolveDwiTripletTools"]
