"""Public canonical-input manifest materializer for TRIBE v2.

The private counterpart copies protected recordings and model assets.  This
public counterpart intentionally materializes only logical row bindings and
explicit feature/runtime configuration.  Raw media and model assets remain
caller-injected dependencies.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from brain_researcher.research.discovery.programs.tribe_speech_tools_public import (
    write_json_new,
)

from .contracts import PROGRAM_ID

CANONICAL_INPUT_BUNDLE_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.canonical_input_bundle.v2"
)


class CanonicalInputBundleMaterializationError(ValueError):
    """A public v2 input manifest cannot be materialized safely."""


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanonicalInputBundleMaterializationError(f"{label} must be non-empty text")
    return value.strip()


def _new_directory(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        raise CanonicalInputBundleMaterializationError(
            "bundle directory must be a new path beneath an existing directory"
        )
    path.mkdir(mode=0o700)
    return path


def _runtime(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {"mode", "data_root", "model_root", "checkpoint", "command", "seed"}
    if set(value) != expected:
        raise CanonicalInputBundleMaterializationError(
            "runtime must explicitly name every runtime input"
        )
    mode = value.get("mode")
    if mode not in {"precomputed_feature_matrices", "injected_adapter"}:
        raise CanonicalInputBundleMaterializationError("runtime mode is unsupported")
    parsed = {"mode": mode}
    for field in ("data_root", "model_root", "checkpoint", "command"):
        raw = value.get(field)
        if raw is not None and (not isinstance(raw, str) or not raw.strip()):
            raise CanonicalInputBundleMaterializationError(
                f"runtime.{field} must be text or null"
            )
        parsed[field] = raw.strip() if isinstance(raw, str) else None
    seed = value.get("seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise CanonicalInputBundleMaterializationError("runtime.seed must be an integer or null")
    parsed["seed"] = seed
    return parsed


def materialize_canonical_input_bundle(
    *,
    bundle_directory: str | Path,
    materialization_label: str,
    selected_rows: Sequence[Mapping[str, Any]],
    reference_rows: Sequence[Mapping[str, Any]],
    runtime: Mapping[str, Any],
    reference_matrix_map_path: str | Path,
    evaluation_matrix_map_path: str | Path,
) -> dict[str, Any]:
    """Create an explicit public input bundle without copying protected media."""

    if isinstance(selected_rows, str | bytes) or not isinstance(selected_rows, Sequence):
        raise CanonicalInputBundleMaterializationError("selected_rows must be an array")
    if isinstance(reference_rows, str | bytes) or not isinstance(reference_rows, Sequence):
        raise CanonicalInputBundleMaterializationError("reference_rows must be an array")
    selected = [dict(row) for row in selected_rows if isinstance(row, Mapping)]
    reference = [dict(row) for row in reference_rows if isinstance(row, Mapping)]
    if len(selected) != len(selected_rows) or len(reference) != len(reference_rows):
        raise CanonicalInputBundleMaterializationError("input rows must be objects")
    root = _new_directory(bundle_directory)
    parsed_runtime = _runtime(runtime)
    for matrix_map, label in (
        (reference_matrix_map_path, "reference_matrix_map"),
        (evaluation_matrix_map_path, "evaluation_matrix_map"),
    ):
        path = Path(matrix_map).expanduser()
        if not path.is_file() or path.is_symlink():
            raise CanonicalInputBundleMaterializationError(f"{label} must be a regular file")
    manifest = {
        "schema_version": CANONICAL_INPUT_BUNDLE_SCHEMA_VERSION,
        "program_id": PROGRAM_ID,
        "materialization_label": _text(materialization_label, label="materialization_label"),
        "raw_media_materialized": False,
        "model_assets_materialized": False,
        "runtime": parsed_runtime,
        "reference_rows": reference,
        "evaluation_rows": selected,
        "feature_artifacts": {
            "reference_matrix_map": Path(reference_matrix_map_path).name,
            "evaluation_matrix_map": Path(evaluation_matrix_map_path).name,
        },
    }
    input_path = root / "public_input_bundle.json"
    write_json_new(input_path, manifest, label="public_input_bundle")
    return {
        "bundle_directory": root.name,
        "input_manifest": input_path.name,
        "raw_media_materialized": False,
        "model_assets_materialized": False,
    }


__all__ = [
    "CANONICAL_INPUT_BUNDLE_SCHEMA_VERSION",
    "CanonicalInputBundleMaterializationError",
    "materialize_canonical_input_bundle",
]
