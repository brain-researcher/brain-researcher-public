"""Stub sMRI reconstruction tool (FreeSurfer/FastSurfer)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class SMRIReconArgs(BaseModel):
    """Arguments for structural MRI reconstruction."""

    t1w_image: str = Field(description="Path to T1-weighted input volume")
    subject_id: str = Field(description="Subject identifier string")
    use_fastsurfer: bool = Field(
        default=False, description="Use FastSurfer implementation instead of recon-all"
    )
    output_dir: str | None = Field(
        default=None, description="Directory to store reconstruction outputs"
    )


class SMRIReconTool(NeuroToolWrapper):
    """Stub tool that pretends to run cortical reconstruction."""

    def get_tool_name(self) -> str:
        return "smri_recon"

    def get_tool_description(self) -> str:
        return "Run FreeSurfer/FastSurfer-style reconstruction to produce surfaces and segmentations."

    def get_args_schema(self):
        return SMRIReconArgs

    def _run(self, **kwargs) -> ToolResult:
        args = SMRIReconArgs(**kwargs)
        output_root = Path(
            args.output_dir or Path.cwd() / "smri_recon" / args.subject_id
        )
        surf_dir = output_root / "surf"
        mri_dir = output_root / "mri"
        surf_dir.mkdir(parents=True, exist_ok=True)
        mri_dir.mkdir(parents=True, exist_ok=True)

        outputs = {
            "surfaces_dir": str(surf_dir),
            "aseg_volume": str(mri_dir / "aseg.mgz"),
            "aparcaseg_volume": str(mri_dir / "aparc+aseg.mgz"),
        }

        summary = {
            "subject_id": args.subject_id,
            "backend": "fastsurfer" if args.use_fastsurfer else "freesurfer",
            "input_t1w": args.t1w_image,
        }

        return ToolResult(
            status="success", data={"outputs": outputs, "summary": summary}
        )


class SMRIReconTools:
    @staticmethod
    def get_all_tools():
        return [SMRIReconTool()]


__all__ = ["SMRIReconTool", "SMRIReconTools"]
