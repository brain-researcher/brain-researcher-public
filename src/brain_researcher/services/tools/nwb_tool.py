"""NWB (Neurodata Without Borders) tool for the BR-KG LangGraph system.

Implements reading, writing, and inspection of NWB files for
neurophysiology and electrophysiology data.
"""

import logging
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Dict, List, Optional

import numpy as np
from pydantic import BaseModel, Field

from brain_researcher.services.tools.spec import ToolSpec
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


def _ensure_pynwb_cache_dir() -> None:
    """Ensure PyNWB cache resolves to a writable location.

    PyNWB creates a platform cache directory at import time. In restricted
    environments, ``~/.cache`` may be unwritable and import will fail. We
    redirect to a temp-backed cache root when needed.
    """

    env_cache = os.getenv("XDG_CACHE_HOME")
    if env_cache:
        cache_path = Path(env_cache)
        try:
            cache_path.mkdir(parents=True, exist_ok=True)
            if os.access(cache_path, os.W_OK):
                return
        except Exception:
            pass

    fallback_root = Path(
        os.getenv("BR_PYNWB_CACHE_DIR", Path(gettempdir()) / "br_pynwb_cache")
    )
    fallback_root.mkdir(parents=True, exist_ok=True)
    os.environ["XDG_CACHE_HOME"] = str(fallback_root)
    # Skip typemap pickle cache writes when running in constrained sandboxes.
    os.environ.setdefault("PYNWB_NO_CACHE_DIR", "1")


class NWBOperation(str, Enum):
    """NWB file operations."""

    INSPECT = "inspect"  # Inspect NWB file structure
    READ = "read"  # Read data from NWB file
    WRITE = "write"  # Write data to NWB file
    VALIDATE = "validate"  # Validate NWB file


class NWBToolArgs(BaseModel):
    """Arguments for NWB file operations."""

    operation: NWBOperation = Field(description="NWB operation to perform")
    input_file: Optional[str] = Field(
        default=None, description="Path to input NWB file (for inspect/read/validate)"
    )
    output_file: Optional[str] = Field(
        default=None, description="Path to output NWB file (for write)"
    )
    data_path: Optional[str] = Field(
        default=None, description="Path within NWB file to read/write data"
    )
    data: Optional[Dict[str, Any]] = Field(
        default=None, description="Data to write to NWB file"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Metadata for new NWB file"
    )


def _model_required(model_cls) -> List[str]:
    try:
        schema = model_cls.model_json_schema()
    except AttributeError:
        schema = model_cls.schema()
    return schema.get("required", [])


def _model_defaults(model_cls) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {}
    if hasattr(model_cls, "model_fields"):
        for name, field in model_cls.model_fields.items():
            if field.default is not None:
                defaults[name] = field.default
    elif hasattr(model_cls, "__fields__"):
        for name, field in model_cls.__fields__.items():
            if field.default is not None:
                defaults[name] = field.default
    return defaults


try:
    _NWB_SCHEMA = NWBToolArgs.model_json_schema()
except AttributeError:
    _NWB_SCHEMA = NWBToolArgs.schema()


TOOL_SPEC = ToolSpec(
    name="nwb_tool",
    description="NWB file operations: inspect, read, write, and validate.",
    json_schema=_NWB_SCHEMA,
    required=_model_required(NWBToolArgs),
    defaults=_model_defaults(NWBToolArgs),
    category="electrophysiology",
)


class NWBTool(NeuroToolWrapper):
    """NWB file operations tool."""

    def __init__(self):
        """Initialize NWB tool."""
        super().__init__()

    def get_tool_name(self) -> str:
        return "nwb_tool"

    def get_tool_description(self) -> str:
        return (
            "Perform NWB file operations: inspect structure, read data, "
            "write data, and validate NWB files for neurophysiology data."
        )

    def get_args_schema(self):
        return NWBToolArgs

    def _run(
        self,
        operation: NWBOperation,
        input_file: Optional[str] = None,
        output_file: Optional[str] = None,
        data_path: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> ToolResult:
        """Execute NWB file operation."""
        _ensure_pynwb_cache_dir()
        try:
            from pynwb import NWBFile, TimeSeries, validate
        except Exception as exc:  # pragma: no cover - dependency missing
            return ToolResult(status="error", error=f"pynwb required: {exc}", data={})

        from brain_researcher.core.ingestion.nwb_api import (
            inspect_nwb,
            read_nwb,
            write_nwb,
        )

        op = operation.value if hasattr(operation, "value") else operation
        if op == NWBOperation.INSPECT:
            if not input_file:
                return ToolResult(status="error", error="input_file required", data={})
            info = inspect_nwb(input_file)
            return ToolResult(status="success", data={"summary": info})

        if op == NWBOperation.READ:
            if not input_file:
                return ToolResult(status="error", error="input_file required", data={})
            from pynwb import NWBHDF5IO

            with NWBHDF5IO(Path(input_file).resolve().as_posix(), "r") as io:
                nwb = io.read()
                if data_path:
                    parts = data_path.strip("/").split("/")
                    payload: Any = None
                    if parts[0] == "acquisition" and len(parts) > 1:
                        ts = nwb.acquisition.get(parts[1])
                        if ts is None:
                            return ToolResult(
                                status="error",
                                error=f"acquisition '{parts[1]}' not found",
                                data={},
                            )
                        payload = np.asarray(ts.data).tolist()
                    else:
                        return ToolResult(
                            status="error",
                            error=f"Unsupported data_path '{data_path}'",
                            data={},
                        )
                    return ToolResult(
                        status="success",
                        data={"data_path": data_path, "data": payload},
                    )
                summary = {
                    "session_description": nwb.session_description,
                    "identifier": nwb.identifier,
                    "session_start_time": str(nwb.session_start_time),
                }
                return ToolResult(status="success", data={"summary": summary})

        if op == NWBOperation.WRITE:
            if not output_file:
                return ToolResult(status="error", error="output_file required", data={})

            meta = metadata or {}
            session_description = meta.get(
                "session_description", "Brain Researcher NWB"
            )
            identifier = meta.get("identifier", f"br-{datetime.now().timestamp()}")
            session_start = meta.get("session_start_time")
            if session_start is None:
                session_start_time = datetime.now(timezone.utc)
            elif isinstance(session_start, datetime):
                session_start_time = session_start
            else:
                session_start_time = datetime.fromisoformat(str(session_start))

            nwb = NWBFile(
                session_description=session_description,
                identifier=identifier,
                session_start_time=session_start_time,
            )

            if data:
                name = data.get("name", "timeseries")
                series_data = data.get("data", [])
                rate = float(data.get("rate", 1.0))
                unit = data.get("unit", "unit")
                ts = TimeSeries(name=name, data=series_data, rate=rate, unit=unit)
                nwb.add_acquisition(ts)

            path = write_nwb(nwb, output_file)
            return ToolResult(
                status="success",
                data={
                    "outputs": {"nwb_file": path},
                    "summary": {"identifier": identifier},
                },
            )

        if op == NWBOperation.VALIDATE:
            if not input_file:
                return ToolResult(status="error", error="input_file required", data={})
            errors = validate(Path(input_file))
            return ToolResult(status="success", data={"errors": errors})

        return ToolResult(status="error", error=f"Unknown operation: {op}", data={})

    def inspect(self, input_file: str) -> ToolResult:
        """Inspect NWB file structure."""
        return self._run(operation=NWBOperation.INSPECT, input_file=input_file)

    def read(self, input_file: str, data_path: str) -> ToolResult:
        """Read data from NWB file."""
        return self._run(
            operation=NWBOperation.READ, input_file=input_file, data_path=data_path
        )

    def write(
        self,
        output_file: str,
        data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        """Write data to NWB file."""
        return self._run(
            operation=NWBOperation.WRITE,
            output_file=output_file,
            data=data,
            metadata=metadata,
        )

    def validate(self, input_file: str) -> ToolResult:
        """Validate NWB file."""
        return self._run(operation=NWBOperation.VALIDATE, input_file=input_file)
