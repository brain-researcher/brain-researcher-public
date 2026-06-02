"""Stub iEEG preprocessing tool (CAR, filtering, referencing)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class IEEGPreprocessArgs(BaseModel):
    """Arguments for iEEG preprocessing."""

    raw_ieeg: str = Field(description="Path to raw iEEG recording (BIDS compatible)")
    reference: str = Field(
        default="car", description="Referencing scheme (car, bipolar, average)"
    )
    l_freq: Optional[float] = Field(default=0.5, description="High-pass frequency")
    h_freq: Optional[float] = Field(default=250.0, description="Low-pass frequency")
    notch_freq: Optional[float] = Field(default=60.0, description="Line noise notch")
    output_dir: Optional[str] = Field(
        default=None, description="Directory to store cleaned iEEG data"
    )


class IEEGPreprocessTool(NeuroToolWrapper):
    """Stub that pretends to preprocess iEEG signals."""

    def get_tool_name(self) -> str:
        return "ieeg_preprocess"

    def get_tool_description(self) -> str:
        return "Apply basic filtering and referencing to iEEG recordings."

    def get_args_schema(self):
        return IEEGPreprocessArgs

    def _run(self, **kwargs) -> ToolResult:
        args = IEEGPreprocessArgs(**kwargs)
        output_dir = Path(args.output_dir or Path.cwd() / "ieeg_preprocess")
        output_dir.mkdir(parents=True, exist_ok=True)
        cleaned_path = output_dir / "clean_ieeg.fif"

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "clean_ieeg": str(cleaned_path),
                    "referencing": args.reference,
                },
                "summary": {
                    "filters": {
                        "l_freq": args.l_freq,
                        "h_freq": args.h_freq,
                        "notch_freq": args.notch_freq,
                    },
                },
            },
        )


class IEEGPreprocessTools:
    @staticmethod
    def get_all_tools():
        return [IEEGPreprocessTool()]


__all__ = ["IEEGPreprocessTool", "IEEGPreprocessTools"]
