"""Agent wrapper for a deterministic qBOLD FABBER scaffold."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    QBoldFabberParameters,
    qbold_fabber_from_payload,
    run_qbold_fabber,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class QBoldFabberArgs(BaseModel):
    """Arguments accepted by the qBOLD FABBER scaffold."""

    model_config = ConfigDict(extra="ignore")

    input_file: str = Field(description="4D multi-echo GRE or ASE series")
    mask_file: str | None = Field(
        default=None, description="Optional brain or tissue mask"
    )
    output_dir: str | None = Field(default=None, description="Output directory")
    dry_run: bool = Field(
        default=True,
        description="If true, only plan the run; if false, execute when FABBER is available",
    )

    model: str = Field(default="qbold", description="FABBER model name")
    method: str = Field(default="vb", description="Inference method")
    te: float | None = Field(default=None, description="Echo time in seconds")
    echo_times: list[float] = Field(
        default_factory=list, description="Echo times in seconds"
    )
    tau_list: list[float] = Field(
        default_factory=list, description="Spin-echo offsets in seconds"
    )
    infer_oef: bool = Field(
        default=True, description="Infer oxygen extraction fraction"
    )
    infer_dbv: bool = Field(default=True, description="Infer deoxygenated blood volume")
    infer_r2p: bool = Field(default=True, description="Infer R2' term")
    priors: dict[str, object] = Field(
        default_factory=dict, description="Optional prior overrides"
    )
    fabber_bin: str | None = Field(
        default=None, description="Explicit FABBER qBOLD binary path"
    )
    extra_args: list[str] = Field(
        default_factory=list, description="Extra FABBER command-line arguments"
    )


class QBoldFabberTool(NeuroToolWrapper):
    """Deterministic wrapper around FABBER qBOLD command planning."""

    def get_tool_name(self) -> str:
        return "qbold_fabber"

    def get_tool_description(self) -> str:
        return (
            "Plan or optionally execute a FABBER qBOLD run for multi-echo GRE or ASE data. "
            "This scaffold validates inputs, reports environment availability, and writes a "
            "deterministic command preview; execution remains opt-in."
        )

    def get_args_schema(self):
        return QBoldFabberArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = QBoldFabberArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "qbold_fabber")

            params: QBoldFabberParameters = qbold_fabber_from_payload(payload)
            results = run_qbold_fabber(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover - defensive wrapper
            logger.exception("qBOLD FABBER scaffold failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class QBoldFabberTools:
    """Registry helper for qBOLD FABBER tools."""

    @staticmethod
    def get_all_tools():
        return [QBoldFabberTool()]


__all__ = ["QBoldFabberTool", "QBoldFabberArgs", "QBoldFabberTools"]
