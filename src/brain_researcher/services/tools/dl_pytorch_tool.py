"""PyTorch deep learning agent wrapper."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    DLPyTorchParameters,
    dl_pytorch_from_payload,
    run_dl_pytorch,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class PyTorchModelArgs(BaseModel):
    """Arguments accepted by the PyTorch deep learning tool."""

    model_config = ConfigDict(extra="ignore")

    data_file: str = Field(description="Input data file (numpy/npz)")
    labels_file: str | None = Field(
        default=None, description="Labels file for supervised learning"
    )
    output_dir: str | None = Field(default=None, description="Output directory")

    model_type: str = Field(default="3dcnn", description="Model architecture")
    task: str = Field(default="classification", description="Task type")
    n_classes: int | None = Field(default=None, description="Number of classes")
    mode: str = Field(default="train", description="Mode: train/evaluate/predict")
    epochs: int = Field(default=10, description="Training epochs")
    batch_size: int = Field(default=32, description="Batch size")
    learning_rate: float = Field(default=0.001, description="Learning rate")
    use_pretrained: bool = Field(default=False, description="Use pre-trained weights")
    save_model: bool = Field(default=True, description="Persist trained model")
    save_predictions: bool = Field(default=True, description="Persist predictions")
    save_features: bool = Field(default=False, description="Persist extracted features")
    seed: int | None = Field(default=None, description="Random seed")


class PyTorchDeepLearningTool(NeuroToolWrapper):
    """Delegates PyTorch operations to neurocore fallbacks."""

    def __init__(self) -> None:
        super().__init__()
        self.torch_available = False  # Maintained for backward compatibility

    def get_tool_name(self) -> str:
        return "dl_pytorch"

    def get_tool_description(self) -> str:
        return "PyTorch-based deep learning workflows with fallback simulation."

    def get_args_schema(self):
        return PyTorchModelArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = PyTorchModelArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "dl_pytorch")

            params: DLPyTorchParameters = dl_pytorch_from_payload(payload)
            results = run_dl_pytorch(params)
            results.setdefault("message", "PyTorch fallback executed.")
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("PyTorch tool failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class DLPyTorchTools:
    """Registry helper."""

    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        return [PyTorchDeepLearningTool()]


__all__ = ["PyTorchDeepLearningTool", "PyTorchModelArgs", "DLPyTorchTools"]
