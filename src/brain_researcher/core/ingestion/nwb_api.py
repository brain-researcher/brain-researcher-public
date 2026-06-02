from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ._utils import _run, tool

logger = logging.getLogger(__name__)


@tool
def read_nwb(file_path: str) -> Any:
    """Read an NWB file."""
    try:
        from pynwb import NWBHDF5IO
    except Exception as e:
        raise NotImplementedError("pynwb required") from e
    io = NWBHDF5IO(Path(file_path).resolve().as_posix(), "r")
    nwb = io.read()
    io.close()
    return nwb


@tool
def write_nwb(nwb: Any, out_path: str) -> str:
    """Write an NWB file."""
    try:
        from pynwb import NWBHDF5IO
    except Exception as e:
        raise NotImplementedError("pynwb required") from e
    io = NWBHDF5IO(Path(out_path).resolve().as_posix(), "w")
    io.write(nwb)
    io.close()
    return Path(out_path).resolve().as_posix()


@tool
def inspect_nwb(file_path: str) -> dict[str, Any]:
    """Inspect NWB structure."""
    nwb = read_nwb(file_path)
    return {"session_description": nwb.session_description, "subject": str(nwb.subject)}


@tool
def add_timeseries(nwb_path: str, name: str, data: Any, rate: float, unit: str) -> str:
    """Add a time series to an NWB file."""
    try:
        from pynwb import NWBHDF5IO
        from pynwb.ecephys import ElectricalSeries
    except Exception as e:
        raise NotImplementedError("pynwb required") from e
    io = NWBHDF5IO(Path(nwb_path).resolve().as_posix(), "r+")
    nwb = io.read()
    ts = ElectricalSeries(name=name, data=data, rate=rate, unit=unit)
    nwb.add_acquisition(ts)
    io.write(nwb)
    io.close()
    return Path(nwb_path).resolve().as_posix()


@tool
def export_nwb_to_zarr(nwb_path: str, out_dir: str) -> str:
    """Export NWB file to Zarr."""
    cmd = [
        "nwb2zarr",
        Path(nwb_path).resolve().as_posix(),
        Path(out_dir).resolve().as_posix(),
    ]
    _run(cmd)
    return Path(out_dir).resolve().as_posix()
