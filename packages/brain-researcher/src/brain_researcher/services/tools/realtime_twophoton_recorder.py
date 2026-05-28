"""Artifact writers for replayable real-time two-photon runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def write_json(path: str | Path, payload: dict[str, Any]) -> str:
    """Write a JSON payload to disk."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(output_path)


def write_jsonl(path: str | Path, records: list[dict[str, Any]]) -> str:
    """Write a list of records to JSONL."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return str(output_path)


def write_array(path: str | Path, array: np.ndarray) -> str:
    """Write an array to disk with numpy."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(output_path, array)
    return str(output_path)
