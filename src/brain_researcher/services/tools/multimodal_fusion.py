"""Multimodal fusion agent wrapper."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    MultimodalFusionParameters,
    multimodal_fusion_from_payload,
    run_multimodal_fusion,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class MultimodalFusionArgs(BaseModel):
    """Arguments for multimodal fusion."""

    model_config = ConfigDict(extra="ignore")

    structural_file: str | None = Field(
        default=None, description="Structural modality path"
    )
    functional_file: str | None = Field(
        default=None, description="Functional modality path"
    )
    output_dir: str | None = Field(default=None, description="Output directory")
    fusion_method: str = Field(default="intermediate", description="Fusion strategy")
    n_components: int = Field(default=10, description="Number of fused components")
    random_state: int | None = Field(default=42, description="Random seed")
    save_fused: bool = Field(default=True, description="Persist fused features")
    save_components: bool = Field(default=True, description="Persist component weights")


class MultimodalFusionTool(NeuroToolWrapper):
    """Delegates multimodal fusion to neurocore implementation."""

    def get_tool_name(self) -> str:
        return "multimodal_fusion"

    def get_tool_description(self) -> str:
        return "Integrate structural and functional features via fallback fusion."

    def get_args_schema(self):
        return MultimodalFusionArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = MultimodalFusionArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "multimodal_fusion")

            params: MultimodalFusionParameters = multimodal_fusion_from_payload(payload)
            results = run_multimodal_fusion(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("Multimodal fusion failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class MultimodalFusionTools:
    """Registry helper."""

    @staticmethod
    def get_all_tools():
        return [MultimodalFusionTool()]


__all__ = ["MultimodalFusionTool", "MultimodalFusionArgs", "MultimodalFusionTools"]
