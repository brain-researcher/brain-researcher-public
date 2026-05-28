"""Time-frequency power estimation stub tool."""

from __future__ import annotations

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class TimeFreqArgs(BaseModel):
    epochs: str = Field(description="Epochs file")
    method: str = Field(default="morlet", description="Spectral estimation method")


class TimeFreqTFRTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "timefreq_tfr"

    def get_tool_description(self) -> str:
        return "Compute time-frequency representations for EEG epochs."

    def get_args_schema(self):
        return TimeFreqArgs

    def _run(self, epochs: str, method: str = "morlet", **kwargs) -> ToolResult:
        power_path = epochs.replace("_epo.fif", "_tfr.h5")
        return ToolResult(
            status="success",
            data={
                "outputs": {"power_spectra": power_path},
                "summary": {"method": method, "freq_range": kwargs.get("freq_range", [1, 40])},
            },
        )


__all__ = ["TimeFreqTFRTool"]
