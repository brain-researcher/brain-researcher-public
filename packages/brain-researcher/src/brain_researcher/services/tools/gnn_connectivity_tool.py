"""Agent wrapper for GNN connectivity fallback workflows."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    GNNConnectivityParameters,
    gnn_connectivity_from_payload,
    run_gnn_connectivity,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class GNNConnectivityArgs(BaseModel):
    """Arguments accepted by the GNN fallback implementation."""

    model_config = ConfigDict(extra="ignore")

    connectivity_file: Optional[str] = Field(default=None, description="Connectivity matrix path")
    timeseries_file: Optional[str] = Field(default=None, description="Optional ROI time series for adjacency construction")
    output_dir: Optional[str] = Field(default=None, description="Directory for outputs")
    graph_type: str = Field(default="functional", description="Graph type descriptor")
    threshold: Optional[float] = Field(default=None, description="Edge threshold")
    sparsity: Optional[float] = Field(default=None, description="Target sparsity fraction")
    model_type: str = Field(default="gcn", description="Fallback model label")
    n_layers: int = Field(default=2, description="Layer count")
    hidden_dim: int = Field(default=32, description="Embedding dimensionality")
    task: str = Field(default="node_classification", description="Intended downstream task")
    n_classes: Optional[int] = Field(default=2, description="Number of classes")
    mode: str = Field(default="train", description="Pipeline mode label")
    epochs: int = Field(default=10, description="Epochs for metadata")
    learning_rate: float = Field(default=0.01, description="Learning rate metadata")
    compute_metrics: bool = Field(default=True, description="Emit graph metrics")
    metrics: list[str] = Field(default_factory=lambda: ["degree", "clustering", "betweenness", "modularity"], description="Metric list")
    save_model: bool = Field(default=True, description="Persist model metadata")
    save_embeddings: bool = Field(default=True, description="Persist node embeddings")
    save_predictions: bool = Field(default=True, description="Persist prediction array")
    visualize: bool = Field(default=True, description="Generate visual artefacts")
    seed: int = Field(default=42, description="Random seed")
    use_real_gnn: bool = Field(default=False, description="Use real GNN backend when available")


class GNNConnectivityTool(NeuroToolWrapper):
    """Delegates graph neural network connectivity to neurocore fallback."""

    def get_tool_name(self) -> str:
        return "gnn_connectivity"

    def get_tool_description(self) -> str:
        return "Fallback GNN connectivity analytics with synthetic embeddings and metrics."

    def get_args_schema(self):
        return GNNConnectivityArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = GNNConnectivityArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "gnn_connectivity")

            params: GNNConnectivityParameters = gnn_connectivity_from_payload(payload)
            results = run_gnn_connectivity(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("GNN connectivity analysis failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})

    @property
    def torch_available(self) -> bool:
        try:
            from brain_researcher.services.neurokg.ml import gnn_models
        except Exception:
            return False
        return bool(getattr(gnn_models, "TORCH_AVAILABLE", False))


class GNNConnectivityTools:
    """Registry helper for GNN connectivity tools."""

    @staticmethod
    def get_all_tools():
        return [GNNConnectivityTool()]


__all__ = ["GNNConnectivityTool", "GNNConnectivityArgs", "GNNConnectivityTools"]
