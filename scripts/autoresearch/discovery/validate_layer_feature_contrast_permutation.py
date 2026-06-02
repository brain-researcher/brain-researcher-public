#!/usr/bin/env python3
"""Layer-wise permutation validation for feature-sidecar contrasts.

This validator is intentionally local and bounded. It consumes a feature
sidecar manifest or row table plus one or more layer feature matrices, tests
``story_audio`` vs ``math_audio`` by default, and writes per-layer observed
scores with raw and familywise max-stat permutation p-values.

Accepted input contract:
- rows: JSONL, JSON list, or JSON object with ``rows``/``items``.
- row fields: ``condition`` is required; ``item_id`` and ``task_id`` are
  optional but reported/used when present.
- layers: pass repeated ``--feature-layer layer_id=path.npy`` arguments, or
  provide manifest ``layers`` as either a mapping of layer_id to path/object or
  a list of objects with ``layer_id``/``name`` and ``path``/``matrix_path``.
- matrices: 2D ``.npy`` or ``.npz`` arrays whose first dimension equals the
  number of rows before contrast/task filtering.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_VERSION = "br.autoresearch.layer_feature_contrast_permutation.v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {path} line {line_number}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"expected object in {path} line {line_number}, got {type(row).__name__}")
        rows.append(row)
    return rows


def _load_rows(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not path.exists():
        raise FileNotFoundError(f"rows/manifest path does not exist: {path}")
    if path.suffix.lower() == ".jsonl":
        return _read_jsonl(path), None

    payload = _read_json(path)
    if isinstance(payload, dict):
        rows = payload.get("rows") or payload.get("items")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)], payload
        if "condition" in payload:
            return [payload], payload
        raise ValueError(f"{path} must contain a list field named 'rows' or 'items'")
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)], None
    raise ValueError(f"{path} must be JSONL, a JSON list, or a JSON object")


def _manifest_layer_specs(manifest: dict[str, Any] | None, *, base_dir: Path) -> list[tuple[str, Path]]:
    if not manifest:
        return []
    layers = manifest.get("layers") or manifest.get("feature_layers") or manifest.get("matrices")
    if layers is None:
        return []

    specs: list[tuple[str, Path]] = []
    if isinstance(layers, dict):
        iterable: Iterable[tuple[Any, Any]] = layers.items()
        for layer_id_raw, value in iterable:
            layer_id = str(layer_id_raw)
            path_value = value
            if isinstance(value, dict):
                layer_id = str(value.get("layer_id") or value.get("name") or layer_id)
                path_value = (
                    value.get("path")
                    or value.get("matrix_path")
                    or value.get("features_path")
                    or value.get("feature_matrix")
                )
            if not path_value:
                raise ValueError(f"manifest layer {layer_id!r} is missing a matrix path")
            specs.append((layer_id, _resolve_path(str(path_value), base_dir=base_dir)))
        return specs

    if isinstance(layers, list):
        for idx, value in enumerate(layers):
            if not isinstance(value, dict):
                raise ValueError(f"manifest layers[{idx}] must be an object")
            layer_id = str(
                value.get("layer_id")
                or value.get("feature_id")
                or value.get("name")
                or value.get("layer")
                or f"layer_{idx}"
            )
            path_value = (
                value.get("path")
                or value.get("matrix_path")
                or value.get("features_path")
                or value.get("feature_matrix")
            )
            if not path_value:
                raise ValueError(f"manifest layer {layer_id!r} is missing a matrix path")
            specs.append((layer_id, _resolve_path(str(path_value), base_dir=base_dir)))
        return specs

    raise ValueError("manifest layers must be a mapping or list")


def _resolve_path(raw_path: str, *, base_dir: Path) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else base_dir / path


def _parse_feature_layer(value: str, *, base_dir: Path) -> tuple[str, Path]:
    if "=" in value:
        layer_id, raw_path = value.split("=", 1)
        if not layer_id.strip() or not raw_path.strip():
            raise ValueError(f"invalid --feature-layer value {value!r}; expected layer_id=path")
        return layer_id.strip(), _resolve_path(raw_path.strip(), base_dir=base_dir)
    path = _resolve_path(value, base_dir=base_dir)
    return path.stem, path


def _load_matrix(path: Path) -> np.ndarray:
    if not path.exists():
        raise FileNotFoundError(f"feature matrix does not exist: {path}")
    loaded = np.load(path)
    if isinstance(loaded, np.lib.npyio.NpzFile):
        keys = list(loaded.files)
        preferred = [key for key in ("features", "features_matrix", "feature_matrix", "matrix", "arr_0") if key in loaded]
        if preferred:
            matrix = loaded[preferred[0]]
        elif len(keys) == 1:
            matrix = loaded[keys[0]]
        else:
            raise ValueError(f"{path} contains multiple arrays; use one of the standard keys or save as .npy")
    else:
        matrix = loaded
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim != 2:
        raise ValueError(f"feature matrix {path} must be 2D, got shape {tuple(matrix.shape)}")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"feature matrix {path} contains NaN or infinite values")
    return matrix


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom <= 0:
        return 0.0
    return float(np.dot(left, right) / denom)


def _score_for(matrix: np.ndarray, positive_indices: list[int], negative_indices: list[int]) -> dict[str, float]:
    pos = matrix[positive_indices].mean(axis=0)
    neg = matrix[negative_indices].mean(axis=0)
    diff = pos - neg
    diff_norm = float(np.linalg.norm(diff))
    cosine_gap = float(1.0 - _cosine(pos, neg))
    projection_gap = 0.0
    if diff_norm > 0:
        axis = diff / diff_norm
        projection_gap = float(np.dot(matrix[positive_indices], axis).mean()) - float(
            np.dot(matrix[negative_indices], axis).mean()
        )
    return {
        "score": float(diff_norm * max(cosine_gap, 1e-6)),
        "diff_norm": diff_norm,
        "cosine_gap": cosine_gap,
        "projection_gap": projection_gap,
    }


def _benjamini_hochberg(p_values: list[float]) -> list[float]:
    n = len(p_values)
    order = sorted(range(n), key=lambda idx: p_values[idx], reverse=True)
    adjusted = [1.0] * n
    running = 1.0
    for rank_from_end, idx in enumerate(order, start=1):
        rank = n - rank_from_end + 1
        running = min(running, p_values[idx] * n / rank)
        adjusted[idx] = min(1.0, running)
    return adjusted


def _bonferroni(p_value: float, family_size: int) -> float:
    return min(1.0, float(p_value) * max(1, int(family_size)))


def _permutation_assignments(
    *,
    n_items: int,
    n_positive: int,
    max_exact_combinations: int,
    n_permutations: int,
    seed: int,
) -> tuple[str, int, list[list[int]]]:
    total_combinations = math.comb(n_items, n_positive)
    if total_combinations <= max_exact_combinations:
        return (
            "exact",
            total_combinations,
            [list(combo) for combo in itertools.combinations(range(n_items), n_positive)],
        )

    rng = np.random.default_rng(seed)
    positions = np.arange(n_items)
    assignments: list[list[int]] = []
    for _ in range(n_permutations):
        assignments.append(rng.permutation(positions)[:n_positive].astype(int).tolist())
    return "monte_carlo", total_combinations, assignments


def _selected_indices(
    rows: list[dict[str, Any]],
    *,
    task_id: str | None,
    positive_conditions: set[str],
    negative_conditions: set[str],
) -> tuple[list[int], list[int], list[int]]:
    selected: list[int] = []
    positive: list[int] = []
    negative: list[int] = []
    for idx, row in enumerate(rows):
        if task_id is not None and str(row.get("task_id")) != task_id:
            continue
        condition = str(row.get("condition")) if row.get("condition") is not None else None
        if condition in positive_conditions:
            selected.append(idx)
            positive.append(idx)
        elif condition in negative_conditions:
            selected.append(idx)
            negative.append(idx)
    if not positive or not negative:
        raise ValueError(
            "empty selected contrast: "
            f"{len(positive)} positive and {len(negative)} negative rows after filtering"
        )
    return selected, positive, negative


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate(args: argparse.Namespace) -> dict[str, Any]:
    rows_path = Path(args.rows).expanduser().resolve()
    rows, manifest = _load_rows(rows_path)
    base_dir = rows_path.parent
    layer_specs = _manifest_layer_specs(manifest, base_dir=base_dir)
    layer_specs.extend(
        _parse_feature_layer(value, base_dir=base_dir) for value in (args.feature_layer or [])
    )
    if not layer_specs:
        raise ValueError("no feature layers provided; use --feature-layer or manifest layers[]")

    seen_layers: set[str] = set()
    matrices: list[tuple[str, Path, np.ndarray]] = []
    for layer_id, path in layer_specs:
        if layer_id in seen_layers:
            raise ValueError(f"duplicate layer_id {layer_id!r}")
        seen_layers.add(layer_id)
        matrix = _load_matrix(path)
        if matrix.shape[0] != len(rows):
            raise ValueError(
                f"row/matrix mismatch for {layer_id}: {len(rows)} rows vs matrix shape {tuple(matrix.shape)}"
            )
        matrices.append((layer_id, path, matrix))

    positive_conditions = {str(value) for value in (args.positive_condition or ["story_audio"])}
    negative_conditions = {str(value) for value in (args.negative_condition or ["math_audio"])}
    selected, positive_global, negative_global = _selected_indices(
        rows,
        task_id=args.task_id,
        positive_conditions=positive_conditions,
        negative_conditions=negative_conditions,
    )
    local_lookup = {global_idx: local_idx for local_idx, global_idx in enumerate(selected)}
    positive_local = [local_lookup[idx] for idx in positive_global]
    negative_local = [local_lookup[idx] for idx in negative_global]
    selected_matrices = [(layer_id, path, matrix[selected]) for layer_id, path, matrix in matrices]

    observed_by_layer = [
        {
            "layer_id": layer_id,
            "matrix_path": str(path),
            "n_features": int(matrix.shape[1]),
            "observed": _score_for(matrix, positive_local, negative_local),
        }
        for layer_id, path, matrix in selected_matrices
    ]
    observed_scores = np.asarray([row["observed"]["score"] for row in observed_by_layer], dtype=float)

    mode, total_combinations, assignments = _permutation_assignments(
        n_items=len(selected),
        n_positive=len(positive_local),
        max_exact_combinations=int(args.max_exact_combinations),
        n_permutations=int(args.n_permutations),
        seed=int(args.seed),
    )
    null_by_layer = np.zeros((len(assignments), len(selected_matrices)), dtype=float)
    all_positions = set(range(len(selected)))
    for assignment_idx, positive_assignment in enumerate(assignments):
        positive_set = set(positive_assignment)
        negative_assignment = [idx for idx in all_positions if idx not in positive_set]
        for layer_idx, (_, _, matrix) in enumerate(selected_matrices):
            null_by_layer[assignment_idx, layer_idx] = _score_for(
                matrix,
                positive_assignment,
                negative_assignment,
            )["score"]

    max_null = null_by_layer.max(axis=1)
    raw_p_values: list[float] = []
    max_stat_p_values: list[float] = []
    for layer_idx, observed_score in enumerate(observed_scores):
        raw_extreme = int(np.sum(null_by_layer[:, layer_idx] >= observed_score - 1e-12))
        max_extreme = int(np.sum(max_null >= observed_score - 1e-12))
        if mode == "monte_carlo":
            raw_p = float((raw_extreme + 1) / (len(assignments) + 1))
            max_p = float((max_extreme + 1) / (len(assignments) + 1))
        else:
            raw_p = float(raw_extreme / len(assignments))
            max_p = float(max_extreme / len(assignments))
        raw_p_values.append(raw_p)
        max_stat_p_values.append(max_p)

    bh_values = _benjamini_hochberg(raw_p_values)
    for layer_idx, layer_result in enumerate(observed_by_layer):
        null_scores = null_by_layer[:, layer_idx]
        layer_result.update(
            {
                "raw_p_value": raw_p_values[layer_idx],
                "bonferroni_p_value": _bonferroni(raw_p_values[layer_idx], len(observed_by_layer)),
                "bh_fdr_p_value": bh_values[layer_idx],
                "max_stat_familywise_p_value": max_stat_p_values[layer_idx],
                "decision": (
                    "significant_after_max_stat_familywise"
                    if max_stat_p_values[layer_idx] <= float(args.alpha)
                    else "not_significant_after_max_stat_familywise"
                ),
                "null_summary": {
                    "mean": float(null_scores.mean()),
                    "std": float(null_scores.std(ddof=0)),
                    "quantiles": {
                        str(q): float(np.quantile(null_scores, q))
                        for q in (0.0, 0.5, 0.9, 0.95, 0.975, 0.99, 1.0)
                    },
                },
            }
        )

    result = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": _utc_now(),
        "rows_path": str(rows_path),
        "manifest_schema_version": manifest.get("schema_version") if isinstance(manifest, dict) else None,
        "task_id": args.task_id,
        "contrast_id": args.contrast_id,
        "positive_conditions": sorted(positive_conditions),
        "negative_conditions": sorted(negative_conditions),
        "score_function": "diff_norm * max(1 - cosine(pos_centroid, neg_centroid), 1e-6)",
        "tail": "upper_one_sided_score_separation",
        "permutation_unit": "selected feature row label",
        "permutation_mode": mode,
        "n_total_combinations": int(total_combinations),
        "n_permutations_evaluated": int(len(assignments)),
        "n_layers_tested": len(observed_by_layer),
        "correction_contract": {
            "primary": "max_stat_familywise_p_value",
            "secondary": ["bonferroni_p_value", "bh_fdr_p_value"],
            "family": "all feature layers supplied to this invocation",
        },
        "alpha": float(args.alpha),
        "n_rows": len(rows),
        "n_selected": len(selected),
        "n_positive": len(positive_local),
        "n_negative": len(negative_local),
        "layers": observed_by_layer,
        "selected_items": [
            {
                "row_index": idx,
                "item_id": rows[idx].get("item_id"),
                "task_id": rows[idx].get("task_id"),
                "condition": rows[idx].get("condition"),
            }
            for idx in selected
        ],
        "caveats": [
            "Permutation exchangeability is row-label based; use only when selected feature rows are exchangeable under the null.",
            "Corrected p-values are valid for the family of layers supplied in this single run, not for unreported exploratory layers.",
        ],
    }

    out_path = Path(args.out).expanduser().resolve()
    _write_json(out_path, result)
    print(json.dumps({"status": "ok", "out": str(out_path), "n_layers_tested": len(observed_by_layer)}, indent=2))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rows",
        required=True,
        help="Feature sidecar manifest/rows path: JSONL, JSON list, or JSON object with rows/items.",
    )
    parser.add_argument(
        "--feature-layer",
        action="append",
        help="Feature layer matrix as layer_id=path.npy/.npz. Repeat for multiple layers.",
    )
    parser.add_argument("--out", required=True, help="Output JSON validation report path.")
    parser.add_argument("--task-id", help="Optional task_id filter.")
    parser.add_argument("--contrast-id", default="story_audio_vs_math_audio")
    parser.add_argument(
        "--positive-condition",
        action="append",
        help="Positive-side condition. Defaults to story_audio; repeat for aliases.",
    )
    parser.add_argument(
        "--negative-condition",
        action="append",
        help="Negative-side condition. Defaults to math_audio; repeat for aliases.",
    )
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--max-exact-combinations", type=int, default=250000)
    parser.add_argument("--n-permutations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=1729)
    return parser.parse_args()


def main() -> None:
    try:
        validate(parse_args())
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from None


if __name__ == "__main__":
    main()
