"""Segmentation agent wrapper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    SegmentationParameters,
    segmentation_from_payload,
    run_segmentation,
)
from brain_researcher.services.tools.qc_rendering import render_label_overlay_png
from brain_researcher.services.tools.spec import (
    ToolQCPrecheckConfig,
    ToolQCRenderContract,
    ToolQCRetryRule,
    ToolQCSpec,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class SegmentationArgs(BaseModel):
    """Arguments for segmentation workflows."""

    model_config = ConfigDict(extra="ignore")

    input_image: str = Field(description="Input brain image path")
    output_dir: Optional[str] = Field(default=None, description="Output directory")
    modality: str = Field(default="T1", description="Imaging modality")
    segmentation_type: str = Field(default="tissue", description="Segmentation type")
    n_classes: int = Field(default=3, description="Number of classes")
    threshold_method: str = Field(default="adaptive", description="Thresholding strategy")
    min_lesion_size: int = Field(default=3, description="Minimum lesion size")
    random_state: Optional[int] = Field(default=42, description="Random seed")
    save_masks: bool = Field(default=True, description="Persist segmentation masks")
    save_probabilities: bool = Field(default=True, description="Persist probability maps")
    save_volumes: bool = Field(default=True, description="Persist volume summary")
    output_format: str = Field(default="nifti", description="Output format")


QC_SPEC = ToolQCSpec(
    artifact_output_keys=["qc_png"],
    checklist=[
        "Confirm tissue or lesion labels remain within the brain envelope.",
        "Look for obvious under-segmentation where large brain regions are unlabeled.",
        "Look for obvious over-segmentation where background or skull is labeled as tissue.",
    ],
    failure_modes=["under_segmented", "over_segmented", "output_missing", "uncertain"],
    render_contract=ToolQCRenderContract(
        kind="label_overlay",
        layout="tri_planar_montage",
        notes="Review the label overlay for missing tissue coverage or background spillover.",
    ),
    prechecks=ToolQCPrecheckConfig(
        required_outputs={
            "segmentation": "output_missing",
            "qc_png": "output_missing",
        }
    ),
    retry_rules=[
        ToolQCRetryRule(
            match_any_failure_modes=["under_segmented"],
            min_attempt=0,
            max_attempt=0,
            param_updates={"threshold_method": "liberal"},
            notes="Retry with a more liberal threshold when the mask misses tissue.",
        ),
        ToolQCRetryRule(
            match_any_failure_modes=["over_segmented"],
            min_attempt=0,
            max_attempt=0,
            param_updates={"threshold_method": "conservative"},
            notes="Retry with a more conservative threshold when labels spill into background.",
        ),
    ],
)


class SegmentationTool(NeuroToolWrapper):
    """Delegates segmentation to shared neurocore implementation."""

    QC_SPEC = QC_SPEC

    def get_tool_name(self) -> str:
        return "brain_segmentation"

    def get_tool_description(self) -> str:
        return "Perform fallback brain segmentation for tissue/lesion tasks."

    def get_args_schema(self):
        return SegmentationArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = SegmentationArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "segmentation")

            params: SegmentationParameters = segmentation_from_payload(payload)
            results = run_segmentation(params)
            outputs = results.get("outputs") if isinstance(results, dict) else None
            segmentation_path = (
                outputs.get("segmentation")
                if isinstance(outputs, dict)
                else None
            )
            if segmentation_path and Path(segmentation_path).exists():
                try:
                    qc_png = render_label_overlay_png(
                        params.input_image,
                        segmentation_path,
                        Path(params.output_dir) / "segmentation_qc.png",
                        title="Segmentation QC",
                    )
                    if isinstance(outputs, dict):
                        outputs["qc_png"] = qc_png
                except Exception as exc:
                    logger.warning("Failed to render segmentation QC PNG: %s", exc)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("Segmentation failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class SegmentationTools:
    """Registry helper."""

    @staticmethod
    def get_all_tools():
        return [SegmentationTool()]


__all__ = ["SegmentationTool", "SegmentationArgs", "SegmentationTools"]
