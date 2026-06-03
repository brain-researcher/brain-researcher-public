"""Tool wrapper for fixed-HRF literature scoping."""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    FixedHrfLiteratureScopingParameters,
    build_fixed_hrf_scoping_query,
    fixed_hrf_literature_scoping_from_payload,
    gather_fixed_hrf_static_refs,
    run_fixed_hrf_literature_scoping,
    summarize_fixed_hrf_hits,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class FixedHrfLiteratureScopingArgs(BaseModel):
    """Arguments for a fixed-HRF scoping review."""

    model_config = ConfigDict(extra="ignore")

    query: str | None = Field(
        default=None,
        description="Optional user query to bias the scoping review.",
    )
    scope_label: str = Field(
        default="fixed-HRF fMRI methods",
        description="Human-readable label for the scoping review.",
    )
    task: str | None = Field(
        default=None,
        description="Optional task or paradigm label to contextualize the query.",
    )
    top_k: int = Field(default=8, ge=1, le=50, description="Max hits to return")
    store: str | None = Field(
        default=None,
        description="Optional file-search store override.",
    )
    model: str | None = Field(
        default=None,
        description="Optional Gemini model override for file search.",
    )
    gfs_enabled: bool = Field(
        default=True,
        description="Enable Google file search retrieval.",
    )
    include_static: bool = Field(
        default=True,
        description="Include static HRF anchors from the local references table.",
    )
    max_calls: int = Field(
        default=2,
        ge=1,
        le=4,
        description="Maximum number of file-search calls when auto-routing.",
    )


class FixedHrfLiteratureScopingTool(NeuroToolWrapper):
    """Scoping-review style literature tool for fixed-HRF fMRI methods."""

    TAGS = ["literature", "fMRI", "scoping_review"]

    def get_tool_name(self) -> str:
        return "literature.fixed_hrf_scoping"

    def get_tool_description(self) -> str:
        return (
            "Run a scoping review for fixed-HRF fMRI methods. The output is "
            "explicitly review-oriented and not intended as an unbiased census."
        )

    def get_args_schema(self):
        return FixedHrfLiteratureScopingArgs

    def _run(
        self,
        query: str | None = None,
        scope_label: str = "fixed-HRF fMRI methods",
        task: str | None = None,
        top_k: int = 8,
        store: str | None = None,
        model: str | None = None,
        gfs_enabled: bool = True,
        include_static: bool = True,
        max_calls: int = 2,
    ) -> ToolResult:
        try:
            args = FixedHrfLiteratureScopingArgs(
                query=query,
                scope_label=scope_label,
                task=task,
                top_k=top_k,
                store=store,
                model=model,
                gfs_enabled=gfs_enabled,
                include_static=include_static,
                max_calls=max_calls,
            )
            params: FixedHrfLiteratureScopingParameters = (
                fixed_hrf_literature_scoping_from_payload(args.model_dump())
            )
            payload = run_fixed_hrf_literature_scoping(params)
            payload["review_strategy"] = {
                "query": build_fixed_hrf_scoping_query(params),
                "static_anchor_count": (
                    len(gather_fixed_hrf_static_refs()) if params.include_static else 0
                ),
                "hit_bucket_counts": payload.get("hit_summary", {}).get(
                    "bucket_counts", {}
                ),
                "top_titles": payload.get("hit_summary", {}).get("top_titles", []),
            }
            payload["hit_summary"] = summarize_fixed_hrf_hits(
                payload.get("hits") or [], top_k=params.top_k
            )
            return ToolResult(status="success", data={"outputs": payload})
        except Exception as exc:  # pragma: no cover - defensive wrapper
            logger.exception("Fixed-HRF literature scoping failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class FixedHrfLiteratureScopingTools:
    """Registry helper for the fixed-HRF scoping review tool."""

    @staticmethod
    def get_all_tools():
        return [FixedHrfLiteratureScopingTool()]


__all__ = [
    "FixedHrfLiteratureScopingArgs",
    "FixedHrfLiteratureScopingTool",
    "FixedHrfLiteratureScopingTools",
]
