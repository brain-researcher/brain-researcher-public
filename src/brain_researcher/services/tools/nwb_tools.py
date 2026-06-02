"""NWB file utility tools for the agent."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class ReadNWBArgs(BaseModel):
    """Arguments for reading an NWB file."""

    file_path: str = Field(description="Path to the NWB file")


class WriteNWBArgs(BaseModel):
    """Arguments for writing an NWB file."""

    nwb: Any = Field(description="NWBFile object")
    out_path: str = Field(description="Destination path for the file")


class InspectNWBArgs(BaseModel):
    """Arguments for inspecting an NWB file."""

    file_path: str = Field(description="Path to the NWB file")


class ReadNWBTool(NeuroToolWrapper):
    """Tool for reading NWB files."""

    def get_tool_name(self) -> str:
        return "read_nwb"

    def get_tool_description(self) -> str:
        return "Read an NWB file and return the NWBFile object"

    def get_args_schema(self):
        return ReadNWBArgs

    def _run(self, file_path: str) -> ToolResult:
        try:
            from data_ingestion.nwb_api import read_nwb

            nwb = read_nwb(file_path)
            return ToolResult(status="success", data={"nwb": nwb})
        except Exception as e:  # pragma: no cover - mocked in tests
            logger.error(f"Failed to read NWB: {e}")
            return ToolResult(status="error", error=str(e))


class WriteNWBTool(NeuroToolWrapper):
    """Tool for writing NWB files."""

    def get_tool_name(self) -> str:
        return "write_nwb"

    def get_tool_description(self) -> str:
        return "Write an NWBFile object to disk"

    def get_args_schema(self):
        return WriteNWBArgs

    def _run(self, nwb: Any, out_path: str) -> ToolResult:
        try:
            from data_ingestion.nwb_api import write_nwb

            path = write_nwb(nwb, out_path)
            return ToolResult(status="success", data={"path": path})
        except Exception as e:  # pragma: no cover
            logger.error(f"Failed to write NWB: {e}")
            return ToolResult(status="error", error=str(e))


class InspectNWBTool(NeuroToolWrapper):
    """Tool for inspecting NWB file structure."""

    def get_tool_name(self) -> str:
        return "inspect_nwb"

    def get_tool_description(self) -> str:
        return "Inspect an NWB file and return basic info"

    def get_args_schema(self):
        return InspectNWBArgs

    def _run(self, file_path: str) -> ToolResult:
        try:
            from data_ingestion.nwb_api import inspect_nwb

            info = inspect_nwb(file_path)
            return ToolResult(status="success", data=info)
        except Exception as e:  # pragma: no cover
            logger.error(f"Failed to inspect NWB: {e}")
            return ToolResult(status="error", error=str(e))


class NWBTools:
    """Collection of NWB related tools."""

    def __init__(self):
        self.reader = ReadNWBTool()
        self.writer = WriteNWBTool()
        self.inspect = InspectNWBTool()

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        return [self.reader, self.writer, self.inspect]

    def get_tool_by_name(self, name: str) -> NeuroToolWrapper | None:
        tool_map = {
            "read_nwb": self.reader,
            "write_nwb": self.writer,
            "inspect_nwb": self.inspect,
        }
        return tool_map.get(name)
