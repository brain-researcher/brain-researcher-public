"""IBL table and array I/O helpers.

Pure read/write utilities shared across IBL tool wrappers:
reading tabular data (CSV, Parquet, JSON) and writing
Parquet/CSV, JSON, and NumPy ``.npy`` outputs.

No brain_researcher imports; stdlib + numpy + pandas only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _load_table(path: str | None) -> pd.DataFrame | None:
    if not path:
        return None
    table_path = Path(path).expanduser()
    if not table_path.exists():
        return None
    suffix = table_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(table_path)
    if suffix in {".parquet", ".pqt"}:
        return pd.read_parquet(table_path)
    if suffix == ".json":
        payload = json.loads(table_path.read_text())
        if isinstance(payload, list):
            return pd.DataFrame(payload)
        if isinstance(payload, dict):
            return pd.DataFrame([payload])
    raise ValueError(f"Unsupported table format: {table_path}")


def _write_table_output(df: pd.DataFrame, output_dir: Path, stem: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / f"{stem}.parquet"
    try:
        df.to_parquet(parquet_path, index=False)
        path = parquet_path
        fmt = "parquet"
    except Exception:
        csv_path = output_dir / f"{stem}.csv"
        df.to_csv(csv_path, index=False)
        path = csv_path
        fmt = "csv"
    return {
        "path": str(path),
        "format": fmt,
        "rows": int(len(df)),
        "columns": list(df.columns),
    }


def _write_json_output(payload: dict[str, Any], output_dir: Path, stem: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return {"path": str(path), "format": "json"}


def _write_npy_output(array: np.ndarray, output_dir: Path, stem: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}.npy"
    np.save(path, array)
    return {
        "path": str(path),
        "format": "npy",
        "shape": [int(dim) for dim in array.shape],
        "dtype": str(array.dtype),
    }
