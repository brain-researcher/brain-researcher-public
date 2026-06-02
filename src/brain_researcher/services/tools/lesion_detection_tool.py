"""Lesion detection agent wrapper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    LesionDetectionParameters,
    lesion_detection_from_payload,
    run_lesion_detection,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class LesionDetectionArgs(BaseModel):
    """Arguments for lesion detection workflows."""

    model_config = ConfigDict(extra="ignore")

    flair_image: Optional[str] = Field(
        default=None, description="Primary lesion-sensitive modality"
    )
    t1_image: Optional[str] = Field(default=None, description="T1-weighted image")
    dwi_image: Optional[str] = Field(
        default=None, description="Diffusion-weighted image"
    )
    output_dir: Optional[str] = Field(default=None, description="Output directory")
    lesion_type: str = Field(default="wmh", description="Type of lesion to detect")
    min_lesion_size: int = Field(default=3, description="Minimum lesion size (voxels)")
    threshold_method: str = Field(
        default="adaptive", description="Thresholding strategy"
    )
    random_state: Optional[int] = Field(default=42, description="Random seed")
    save_masks: bool = Field(default=True, description="Persist lesion masks")
    save_report: bool = Field(default=True, description="Persist lesion summary report")


class LesionDetectionTool(NeuroToolWrapper):
    """Delegates lesion detection to neurocore implementation."""

    def get_tool_name(self) -> str:
        return "lesion_detection"

    def get_tool_description(self) -> str:
        return "Detect lesions with neurocore fallback segmentation."

    def get_args_schema(self):
        return LesionDetectionArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = LesionDetectionArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "lesion_detection")

            params: LesionDetectionParameters = lesion_detection_from_payload(payload)
            results = run_lesion_detection(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("Lesion detection failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class LesionDetectionTools:
    """Registry helper."""

    @staticmethod
    def get_all_tools():
        return [LesionDetectionTool()]


__all__ = ["LesionDetectionTool", "LesionDetectionArgs", "LesionDetectionTools"]
