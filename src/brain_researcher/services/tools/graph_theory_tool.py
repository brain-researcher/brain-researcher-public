"""Agent wrapper for graph theory fallback workflows."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    GraphTheoryParameters,
    graph_theory_from_payload,
    run_graph_theory,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class GraphTheoryArgs(BaseModel):
    """Arguments accepted by the graph theory fallback implementation."""

    model_config = ConfigDict(extra="ignore")

    connectivity_file: str = Field(description="Connectivity matrix path")
    output_dir: Optional[str] = Field(default=None, description="Directory for outputs")
    graph_type: str = Field(default="weighted", description="Graph interpretation")
    threshold_method: str = Field(default="proportional", description="Threshold strategy")
    threshold_value: Optional[float] = Field(default=0.1, description="Threshold parameter")
    compute_basic_metrics: bool = Field(default=True, description="Compute basic metrics")
    basic_metrics: list[str] = Field(default_factory=lambda: ["degree", "strength", "clustering", "path_length"], description="Basic metric list")
    compute_centrality: bool = Field(default=True, description="Compute centrality metrics")
    centrality_metrics: list[str] = Field(default_factory=lambda: ["betweenness", "eigenvector", "pagerank", "closeness"], description="Centrality metric list")
    detect_communities: bool = Field(default=True, description="Identify community structure")
    community_method: str = Field(default="louvain", description="Community algorithm label")
    detect_hubs: bool = Field(default=True, description="Identify hub nodes")
    hub_method: str = Field(default="degree", description="Hub metric")
    compute_rich_club: bool = Field(default=False, description="Compute rich-club coefficients")
    compute_small_world: bool = Field(default=True, description="Estimate small-worldness")
    compute_efficiency: bool = Field(default=True, description="Compute efficiency metrics")
    efficiency_types: list[str] = Field(default_factory=lambda: ["global", "local", "nodal"], description="Efficiency flavours")
    test_robustness: bool = Field(default=False, description="Simulate robustness scenarios")
    removal_fraction: float = Field(default=0.5, description="Node removal fraction for robustness")
    permutation_test: bool = Field(default=False, description="Perform permutation testing")
    n_permutations: int = Field(default=1000, description="Permutation count")
    save_metrics: bool = Field(default=True, description="Persist metrics to disk")
    save_communities: bool = Field(default=True, description="Persist community assignments")
    save_processed_graph: bool = Field(default=True, description="Persist thresholded graph")
    visualize: bool = Field(default=True, description="Generate static visualization")
    random_state: int = Field(default=42, description="Random seed")


class GraphTheoryTool(NeuroToolWrapper):
    """Delegates graph theory analysis to neurocore fallback implementation."""

    def get_tool_name(self) -> str:
        return "graph_theory"

    def get_tool_description(self) -> str:
        return "Fallback graph theory metrics and community analysis for connectivity matrices."

    def get_args_schema(self):
        return GraphTheoryArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = GraphTheoryArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "graph_theory")

            params: GraphTheoryParameters = graph_theory_from_payload(payload)
            results = run_graph_theory(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("Graph theory analysis failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class GraphTheoryTools:
    """Registry helper for graph theory tools."""

    @staticmethod
    def get_all_tools():
        return [GraphTheoryTool()]


__all__ = ["GraphTheoryTool", "GraphTheoryArgs", "GraphTheoryTools"]
