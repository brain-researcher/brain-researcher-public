"""Public canonical-input manifest materializer for TRIBE v2.

The private counterpart copies protected recordings and model assets.  This
public counterpart intentionally materializes only logical row bindings and
explicit feature/runtime configuration.  Raw media and model assets remain
caller-injected dependencies.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from brain_researcher.research.discovery.programs.tribe_speech_tools_public import (
    write_json_new,
)

from .contracts import PROGRAM_ID, default_inference_config, validate_inference_config
from .execution_contract import MANIFEST_SCHEMA_VERSION

CANONICAL_INPUT_BUNDLE_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.canonical_input_bundle.v2"
)


class CanonicalInputBundleMaterializationError(ValueError):
    """A public v2 input manifest cannot be materialized safely."""


_OPAQUE_ROW_KEY = re.compile(r"^row-[0-9]{4}$")
_OPAQUE_COLLECTION_KEY = re.compile(r"^collection-[0-9]{2}$")


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


def _public_rows(
    *,
    selected_rows: Sequence[Mapping[str, Any]],
    reference_rows: Sequence[Mapping[str, Any]],
    execution_kind: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reference: list[dict[str, Any]] = []
    for index, row in enumerate(reference_rows):
        if not isinstance(row, Mapping):
            raise CanonicalInputBundleMaterializationError("reference rows must be objects")
        row_key = _text(row.get("row_key"), label="reference_rows.row_key")
        condition = _text(row.get("condition"), label="reference_rows.condition")
        if execution_kind == "governed_external_input" and (
            row_key != f"row-{index:04d}" or _OPAQUE_ROW_KEY.fullmatch(row_key) is None
        ):
            raise CanonicalInputBundleMaterializationError(
                "controlled reference rows must use ordered opaque row keys"
            )
        reference.append({"row_key": row_key, "condition": condition})
    selected: list[dict[str, Any]] = []
    for index, row in enumerate(selected_rows):
        if not isinstance(row, Mapping):
            raise CanonicalInputBundleMaterializationError("selected rows must be objects")
        row_key = _text(row.get("row_key"), label="selected_rows.row_key")
        collection_key = _text(
            row.get("collection_key"), label="selected_rows.collection_key"
        )
        condition = _text(row.get("condition"), label="selected_rows.condition")
        segment_count = row.get("whisperx_segment_count")
        if isinstance(segment_count, bool) or not isinstance(segment_count, int) or segment_count < 0:
            raise CanonicalInputBundleMaterializationError(
                "selected_rows.whisperx_segment_count must be a non-negative integer"
            )
        if execution_kind == "governed_external_input" and (
            row_key != f"row-{index:04d}"
            or _OPAQUE_ROW_KEY.fullmatch(row_key) is None
            or _OPAQUE_COLLECTION_KEY.fullmatch(collection_key) is None
        ):
            raise CanonicalInputBundleMaterializationError(
                "controlled selected rows must use opaque row and collection keys"
            )
        selected.append(
            {
                "row_key": row_key,
                "collection_key": collection_key,
                "condition": condition,
                "whisperx_segment_count": segment_count,
            }
        )
    return reference, selected


def materialize_canonical_input_bundle(
    *,
    bundle_directory: str | Path,
    materialization_label: str,
    selected_rows: Sequence[Mapping[str, Any]],
    reference_rows: Sequence[Mapping[str, Any]],
    runtime: Mapping[str, Any],
    reference_matrix_map_path: str | Path,
    evaluation_matrix_map_path: str | Path,
    execution_kind: str = "governed_external_input",
    compute_inference: bool = True,
    inference: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an explicit public input bundle without copying protected media."""

    if isinstance(selected_rows, str | bytes) or not isinstance(selected_rows, Sequence):
        raise CanonicalInputBundleMaterializationError("selected_rows must be an array")
    if isinstance(reference_rows, str | bytes) or not isinstance(reference_rows, Sequence):
        raise CanonicalInputBundleMaterializationError("reference_rows must be an array")
    if execution_kind not in {"synthetic_fixture", "governed_external_input"}:
        raise CanonicalInputBundleMaterializationError("execution_kind is unsupported")
    if not isinstance(compute_inference, bool):
        raise CanonicalInputBundleMaterializationError("compute_inference must be boolean")
    if execution_kind != "synthetic_fixture" and compute_inference is not True:
        raise CanonicalInputBundleMaterializationError(
            "controlled inputs must retain frozen inferential evaluation"
        )
    try:
        parsed_inference = validate_inference_config(
            default_inference_config() if inference is None else inference,
            execution_kind=execution_kind,
        )
    except ValueError as exc:
        raise CanonicalInputBundleMaterializationError("inference is not frozen") from exc
    reference, selected = _public_rows(
        selected_rows=selected_rows,
        reference_rows=reference_rows,
        execution_kind=execution_kind,
    )
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
    execution_manifest_path = root / "public_execution_manifest.json"
    write_json_new(
        execution_manifest_path,
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "program_id": PROGRAM_ID,
            "execution_kind": execution_kind,
            "runtime": parsed_runtime,
            "reference_rows": reference,
            "evaluation_rows": selected,
            "inference": parsed_inference,
            "compute_inference": compute_inference,
        },
        label="public_execution_manifest",
    )
    return {
        "bundle_directory": root.name,
        "input_manifest": input_path.name,
        "execution_manifest": execution_manifest_path.name,
        "raw_media_materialized": False,
        "model_assets_materialized": False,
    }


__all__ = [
    "CANONICAL_INPUT_BUNDLE_SCHEMA_VERSION",
    "CanonicalInputBundleMaterializationError",
    "materialize_canonical_input_bundle",
]
