"""Tool wrapper for reproducibility bundle assembly."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    ReproducibilityBundleParameters,
    build_reproducibility_bundle_payload,
    reproducibility_bundle_from_payload,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class ReproducibilityBundleArgs(BaseModel):
    """Arguments for a reproducibility bundle request."""

    model_config = ConfigDict(extra="ignore")

    run_id: str = Field(description="Run identifier to assemble")
    run_dir: str | None = Field(
        default=None,
        description="Optional explicit run directory override.",
    )


class ReproducibilityBundleTool(NeuroToolWrapper):
    """Assemble a native analysis bundle and reproducibility score."""

    TAGS = ["reproducibility", "bundle", "analysis_bundle"]

    def get_tool_name(self) -> str:
        return "reproducibility.bundle"

    def get_tool_description(self) -> str:
        return (
            "Build a reproducibility bundle from run artifacts, including native "
            "analysis/observation/execution manifests and a reproducibility score. "
            "This is an engineering reproducibility check, not peer review."
        )

    def get_args_schema(self):
        return ReproducibilityBundleArgs

    def _run(self, run_id: str, run_dir: str | None = None) -> ToolResult:
        try:
            args = ReproducibilityBundleArgs(run_id=run_id, run_dir=run_dir)
            params: ReproducibilityBundleParameters = reproducibility_bundle_from_payload(
                args.model_dump()
            )
            payload = build_reproducibility_bundle_payload(
                params.run_id,
                run_dir=Path(params.run_dir) if params.run_dir else None,
            )
            return ToolResult(status="success", data={"outputs": payload})
        except Exception as exc:  # pragma: no cover - defensive wrapper
            logger.exception("Reproducibility bundle assembly failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class ReproducibilityBundleTools:
    """Registry helper for reproducibility bundle tools."""

    @staticmethod
    def get_all_tools():
        return [ReproducibilityBundleTool()]


__all__ = [
    "ReproducibilityBundleArgs",
    "ReproducibilityBundleTool",
    "ReproducibilityBundleTools",
]
