"""Stub tool for transferring labels/parcellations across spaces."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class LabelTransferArgs(BaseModel):
    """Arguments for label transfer across spatial references."""

    source_labels: str = Field(description="Source parcellation/atlas volume")
    transform_matrix: str = Field(description="Transformation matrix to target space")
    reference_image: str = Field(description="Target space reference image")
    interpolation: str = Field(
        default="nearest", description="Interpolation method (nearest for labels)"
    )
    output_dir: str | None = Field(
        default=None, description="Directory to store transferred labels"
    )


class LabelTransferTool(NeuroToolWrapper):
    """Stub that pretends to transfer labels across spatial references."""

    def get_tool_name(self) -> str:
        return "label_transfer"

    def get_tool_description(self) -> str:
        return "Transfer parcellation labels from source space to target space using transformation."

    def get_args_schema(self):
        return LabelTransferArgs

    def _run(self, **kwargs) -> ToolResult:
        args = LabelTransferArgs(**kwargs)
        output_dir = Path(args.output_dir or Path.cwd() / "label_transfer")
        output_dir.mkdir(parents=True, exist_ok=True)

        transferred_path = output_dir / "labels_in_target_space.nii.gz"

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "transferred_labels": str(transferred_path),
                },
                "summary": {
                    "n_labels_preserved": 200,  # stub value
                    "interpolation": args.interpolation,
                    "source": args.source_labels,
                    "transform": args.transform_matrix,
                },
            },
        )


class LabelTransferTools:
    @staticmethod
    def get_all_tools():
        return [LabelTransferTool()]


__all__ = ["LabelTransferTool", "LabelTransferTools"]
