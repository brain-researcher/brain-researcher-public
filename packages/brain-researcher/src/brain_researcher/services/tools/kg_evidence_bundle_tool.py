"""Tool wrapper for lens evidence bundles from BR-KG."""

from __future__ import annotations

import os
from typing import Any

import requests
from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import CachedToolWrapper, ToolResult


class KGEvidenceBundleArgs(BaseModel):
    """Arguments for retrieving merged evidence bundles from BR-KG."""

    lens: str = Field(
        default="task",
        description="Lens name (task, disease, population, onvoc)",
    )
    entity_id: str = Field(
        ...,
        description="Entity identifier under the selected lens",
    )
    limit: int = Field(default=50, description="Maximum items per evidence group")
    types: list[str] | None = Field(
        default=None,
        description="Optional evidence groups to request (papers,studies,statmaps,datasets,...)",
    )
    include_mediated: bool = Field(
        default=True,
        description="Include mediated evidence paths where available",
    )
    verified_only: bool = Field(
        default=False,
        description="Only return verified/high-confidence evidence",
    )
    confidence_min: float = Field(
        default=0.0,
        description="Minimum confidence threshold in [0,1]",
    )
    source_mode: str = Field(
        default="graph_plus_live",
        description="Evidence source mode (graph_only, graph_plus_live)",
    )
    include_paths: bool = Field(
        default=True,
        description="Annotate evidence with support from discovered paths",
    )
    include_path_details: bool = Field(
        default=False,
        description="Also fetch explicit evidence path records",
    )
    task_scope: str = Field(
        default="aliases",
        description="Task lens scope (aliases, neighbors, all)",
    )
    include_task_neighbors: bool = Field(
        default=False,
        description="Include neighboring tasks in task lens outputs",
    )


class KGEvidenceBundleTool(CachedToolWrapper):
    """Fetch merged BR-KG lens evidence suitable for agent reasoning."""

    def __init__(self, api_url: str | None = None):
        super().__init__(cache_ttl=180)
        self.api_url = api_url or os.environ.get("NEUROKG_API_URL", "http://localhost:5000")

    def get_tool_name(self) -> str:
        return "kg_evidence_bundle"

    def get_tool_description(self) -> str:
        return (
            "Retrieve merged BR-KG evidence bundle for a lens entity, with optional "
            "path support and live evidence enrichment."
        )

    def get_args_schema(self):
        return KGEvidenceBundleArgs

    def _build_evidence_params(self, args: KGEvidenceBundleArgs) -> dict[str, str]:
        params: dict[str, str] = {
            "limit": str(max(1, min(int(args.limit), 200))),
            "include_mediated": "true" if args.include_mediated else "false",
            "verified_only": "true" if args.verified_only else "false",
            "confidence_min": str(max(0.0, min(float(args.confidence_min), 1.0))),
            "source_mode": args.source_mode,
            "include_paths": "true" if args.include_paths else "false",
        }
        if args.types:
            clean = [str(token).strip() for token in args.types if str(token).strip()]
            if clean:
                params["types"] = ",".join(clean)
        if args.lens == "task":
            params["task_scope"] = args.task_scope
            params["include_task_neighbors"] = (
                "true" if args.include_task_neighbors else "false"
            )
        return params

    def _run(self, **kwargs: Any) -> ToolResult:
        try:
            args = KGEvidenceBundleArgs(**kwargs)
        except Exception as exc:
            return ToolResult(status="error", error=f"Invalid arguments: {exc}")

        lens = str(args.lens or "task").strip().lower()
        entity_id = str(args.entity_id).strip()
        if not entity_id:
            return ToolResult(status="error", error="entity_id is required")

        evidence_url = f"{self.api_url}/api/kg/lens/{lens}/entity/{entity_id}/evidence"
        try:
            evidence_resp = requests.get(
                evidence_url,
                params=self._build_evidence_params(args),
                timeout=20,
            )
        except requests.RequestException as exc:
            return ToolResult(
                status="error",
                error=f"Failed to call BR-KG evidence endpoint: {exc}",
            )

        if not evidence_resp.ok:
            detail = evidence_resp.text
            return ToolResult(
                status="error",
                error=f"BR-KG evidence endpoint returned {evidence_resp.status_code}: {detail}",
            )

        payload = evidence_resp.json()
        result: dict[str, Any] = {
            "lens": lens,
            "entity_id": entity_id,
            "evidence": payload,
        }

        if args.include_path_details:
            path_url = f"{self.api_url}/api/kg/lens/{lens}/entity/{entity_id}/evidence/paths"
            path_params = {
                "limit": str(max(1, min(int(args.limit), 200))),
                "include_mediated": "true" if args.include_mediated else "false",
                "verified_only": "true" if args.verified_only else "false",
                "confidence_min": str(max(0.0, min(float(args.confidence_min), 1.0))),
            }
            try:
                path_resp = requests.get(path_url, params=path_params, timeout=20)
                if path_resp.ok:
                    result["paths"] = path_resp.json()
                else:
                    result["paths_error"] = (
                        f"status={path_resp.status_code} body={path_resp.text}"
                    )
            except requests.RequestException as exc:
                result["paths_error"] = str(exc)

        return ToolResult(
            status="success",
            data=result,
            metadata={"tool": self.get_tool_name(), "api_url": self.api_url},
        )


__all__ = ["KGEvidenceBundleTool", "KGEvidenceBundleArgs"]
