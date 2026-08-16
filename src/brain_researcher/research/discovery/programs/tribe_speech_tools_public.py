"""Small shared I/O helpers for public TRIBE evaluation programs.

These helpers deliberately keep paths at the caller boundary.  Evaluation
artifacts contain only scientific results and logical artifact names, never
absolute data locations, model locations, or source-record identifiers.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np


class PublicTribeChainError(ValueError):
    """A public evaluator input or artifact is structurally invalid."""


def require_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PublicTribeChainError(f"{label} must be a JSON object")
    return value


def require_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicTribeChainError(f"{label} must be non-empty text")
    return value.strip()


def require_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise PublicTribeChainError(f"{label} must be a boolean")
    return value


def read_json_object(path: str | Path, *, label: str) -> dict[str, Any]:
    candidate = Path(path).expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise PublicTribeChainError(f"{label} must be a regular file")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicTribeChainError(f"{label} must contain valid JSON") from exc
    if not isinstance(payload, dict):
        raise PublicTribeChainError(f"{label} must contain a JSON object")
    return payload


def load_matrix(path: str | Path, *, label: str) -> np.ndarray:
    candidate = Path(path).expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise PublicTribeChainError(f"{label} must be a regular matrix file")
    try:
        matrix = np.load(candidate, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise PublicTribeChainError(f"{label} is not a readable NumPy matrix") from exc
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] == 0 or not np.all(np.isfinite(matrix)):
        raise PublicTribeChainError(f"{label} must be a finite, non-empty 2D matrix")
    return matrix


def load_matrix_map(path: str | Path, *, label: str) -> dict[str, np.ndarray]:
    """Load a caller-supplied layer-to-NumPy-file map.

    Relative matrix paths are resolved only against the mapping file itself.
    They are not copied into evaluator artifacts.
    """

    mapping_path = Path(path).expanduser()
    payload = read_json_object(mapping_path, label=label)
    matrices: dict[str, np.ndarray] = {}
    for layer, raw_path in payload.items():
        layer_name = require_text(layer, label=f"{label} layer")
        relative_or_absolute = require_text(
            raw_path, label=f"{label}[{layer_name}]"
        )
        matrix_path = Path(relative_or_absolute).expanduser()
        if not matrix_path.is_absolute():
            matrix_path = mapping_path.parent / matrix_path
        matrices[layer_name] = load_matrix(
            matrix_path, label=f"{label}[{layer_name}]"
        )
    if not matrices:
        raise PublicTribeChainError(f"{label} must contain at least one layer")
    return matrices


def write_json_new(path: str | Path, payload: Mapping[str, Any], *, label: str) -> Path:
    """Write an explicit output path once, refusing accidental replacement."""

    destination = Path(path).expanduser()
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise PublicTribeChainError(
            f"{label} parent must be an existing non-symlink directory"
        )
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise FileExistsError(f"refusing to overwrite {label}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(dict(payload), handle, indent=2, sort_keys=True)
        handle.write("\n")
    return destination


def replace_json(path: str | Path, payload: Mapping[str, Any], *, label: str) -> Path:
    """Replace one already-declared state artifact without creating a new root."""

    destination = Path(path).expanduser()
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise PublicTribeChainError(
            f"{label} parent must be an existing non-symlink directory"
        )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def artifact_name(path: str | Path, *, label: str) -> str:
    """Return a logical filename after rejecting a path-bearing value."""

    value = Path(path).name
    if not value or value in {".", ".."}:
        raise PublicTribeChainError(f"{label} must name a file")
    return value
