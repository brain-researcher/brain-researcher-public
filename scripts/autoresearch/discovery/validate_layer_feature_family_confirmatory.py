#!/usr/bin/env python3
"""Confirmatory TRIBE layer-family permutation test.

This consumes a layer-feature sidecar manifest from
``extract_tribe_layer_features.py`` and tests the locked HCP-language
prediction:

``mean_score(late_attn) - mean_score(early_attn) > 0``

using within-pair story/math label swaps. Pair ids are read from
``row["labels"]["confirmatory_pair_id"]``.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_VERSION = "br.autoresearch.layer_feature_family_confirmatory.v1"

DEFAULT_LATE = ["encoder.layers.10.1", "encoder.layers.12.1", "encoder.layers.14.1"]
DEFAULT_EARLY = ["encoder.layers.0.1", "encoder.layers.2.1", "encoder.layers.4.1"]
DEFAULT_PROJECTORS = ["projectors.audio", "projectors.text"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve(raw_path: str, *, base_dir: Path) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else base_dir / path


def _load_matrix(path: Path) -> np.ndarray:
    if not path.exists():
        raise FileNotFoundError(f"feature matrix does not exist: {path}")
    loaded = np.load(path)
    if isinstance(loaded, np.lib.npyio.NpzFile):
        if len(loaded.files) == 1:
            matrix = loaded[loaded.files[0]]
        else:
            preferred = [key for key in ("features", "matrix", "arr_0") if key in loaded]
            if not preferred:
                raise ValueError(f"{path} contains multiple arrays and no standard matrix key")
            matrix = loaded[preferred[0]]
    else:
        matrix = loaded
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim != 2:
        raise ValueError(f"feature matrix must be 2D: {path} shape={tuple(matrix.shape)}")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"feature matrix contains non-finite values: {path}")
    return matrix


def _layer_specs(manifest: dict[str, Any], *, base_dir: Path) -> dict[str, dict[str, Any]]:
    layers = manifest.get("layers") or manifest.get("features") or []
    specs: dict[str, dict[str, Any]] = {}
    if not isinstance(layers, list):
        raise ValueError("feature manifest must contain list field 'layers'")
    for idx, value in enumerate(layers):
        if not isinstance(value, dict):
            raise ValueError(f"layers[{idx}] must be an object")
        layer_id = str(value.get("layer_id") or value.get("feature_id") or value.get("name") or "")
        if not layer_id:
            raise ValueError(f"layers[{idx}] is missing layer_id/feature_id")
        raw_path = value.get("matrix_path") or value.get("path")
        if not raw_path:
            raise ValueError(f"layer {layer_id} is missing matrix_path/path")
        item_row_indices = value.get("item_row_indices")
        if not isinstance(item_row_indices, list):
            raise ValueError(f"layer {layer_id} is missing item_row_indices list")
        specs[layer_id] = {
            "path": _resolve(str(raw_path), base_dir=base_dir),
            "item_row_indices": [int(row) for row in item_row_indices],
        }
    return specs


def _labels(row: dict[str, Any]) -> dict[str, Any]:
    labels = row.get("labels")
    return labels if isinstance(labels, dict) else {}


def _complete_pairs(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
    missing_pair: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") != "success":
            continue
        pair_id = _labels(row).get("confirmatory_pair_id")
        if pair_id:
            by_pair[str(pair_id)].append(row)
        else:
            missing_pair.append(row)

    complete: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for pair_id, pair_rows in sorted(by_pair.items()):
        story = [row for row in pair_rows if row.get("condition") == "story_audio"]
        math_rows = [row for row in pair_rows if row.get("condition") == "math_audio"]
        if len(story) == 1 and len(math_rows) == 1:
            complete.append({"pair_id": pair_id, "story": story[0], "math": math_rows[0]})
        else:
            dropped.append(
                {
                    "pair_id": pair_id,
                    "row_count": len(pair_rows),
                    "story_count": len(story),
                    "math_count": len(math_rows),
                    "reason": "incomplete_or_ambiguous_pair",
                }
            )
    for row in missing_pair:
        dropped.append(
            {
                "item_row_index": row.get("item_row_index"),
                "item_id": row.get("item_id"),
                "condition": row.get("condition"),
                "reason": "missing_confirmatory_pair_id",
            }
        )
    return complete, dropped


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


def _feature_payload(
    *,
    layer_id: str,
    spec: dict[str, Any],
    pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    matrix = _load_matrix(spec["path"])
    item_row_to_matrix_row = {
        int(item_row_index): matrix_row for matrix_row, item_row_index in enumerate(spec["item_row_indices"])
    }
    selected_rows: list[int] = []
    pair_local_indices: list[tuple[int, int]] = []
    for pair in pairs:
        story_idx = int(pair["story"]["item_row_index"])
        math_idx = int(pair["math"]["item_row_index"])
        if story_idx not in item_row_to_matrix_row or math_idx not in item_row_to_matrix_row:
            raise ValueError(f"layer {layer_id} is missing matrix rows for complete pair {pair['pair_id']}")
        story_local = len(selected_rows)
        selected_rows.append(item_row_to_matrix_row[story_idx])
        math_local = len(selected_rows)
        selected_rows.append(item_row_to_matrix_row[math_idx])
        pair_local_indices.append((story_local, math_local))
    return {
        "layer_id": layer_id,
        "path": str(spec["path"]),
        "matrix": matrix[selected_rows],
        "pair_local_indices": pair_local_indices,
    }


def _mean_layer_score(layer_scores: dict[str, float], layer_ids: list[str]) -> float:
    return float(sum(layer_scores[layer_id] for layer_id in layer_ids) / len(layer_ids))


def _statistic(
    feature_payloads: dict[str, dict[str, Any]],
    *,
    late_layers: list[str],
    early_layers: list[str],
    projectors: list[str],
    swaps: list[bool],
) -> dict[str, Any]:
    positive: list[int] = []
    negative: list[int] = []
    pair_indices = next(iter(feature_payloads.values()))["pair_local_indices"]
    for swap, (story_local, math_local) in zip(swaps, pair_indices, strict=True):
        if swap:
            positive.append(math_local)
            negative.append(story_local)
        else:
            positive.append(story_local)
            negative.append(math_local)

    per_layer: dict[str, dict[str, float]] = {}
    layer_scores: dict[str, float] = {}
    for layer_id, payload in feature_payloads.items():
        score = _score_for(payload["matrix"], positive, negative)
        per_layer[layer_id] = score
        layer_scores[layer_id] = score["score"]
    late_mean = _mean_layer_score(layer_scores, late_layers)
    early_mean = _mean_layer_score(layer_scores, early_layers)
    projector_mean = _mean_layer_score(layer_scores, projectors)
    return {
        "T_late_minus_early": late_mean - early_mean,
        "late_mean_score": late_mean,
        "early_mean_score": early_mean,
        "projector_mean_score": projector_mean,
        "secondary_ordering_late_gt_early_gt_projectors": bool(
            late_mean > early_mean > projector_mean
        ),
        "per_layer": per_layer,
    }


def _swap_assignments(n_pairs: int, *, max_exact: int, n_permutations: int, seed: int) -> tuple[str, int, list[list[bool]]]:
    total = 2**n_pairs
    if total <= max_exact:
        return (
            "exact",
            total,
            [list(bits) for bits in itertools.product([False, True], repeat=n_pairs)],
        )
    rng = np.random.default_rng(seed)
    assignments = [
        [bool(value) for value in rng.integers(0, 2, size=n_pairs)]
        for _ in range(n_permutations)
    ]
    return "monte_carlo", total, assignments


def _plus_one_p(null_values: np.ndarray, observed: float) -> float:
    return float((int(np.sum(null_values >= observed - 1e-12)) + 1) / (len(null_values) + 1))


def validate(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.rows).expanduser().resolve()
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("--rows must be a layer_feature_manifest.json object")
    rows = manifest.get("rows")
    if not isinstance(rows, list):
        raise ValueError("feature manifest must contain list field 'rows'")
    base_dir = manifest_path.parent
    specs = _layer_specs(manifest, base_dir=base_dir)

    late_layers = args.late_layer or list(DEFAULT_LATE)
    early_layers = args.early_layer or list(DEFAULT_EARLY)
    projector_layers = args.projector_layer or list(DEFAULT_PROJECTORS)
    locked_layers = list(dict.fromkeys(late_layers + early_layers + projector_layers))
    missing_layers = [layer_id for layer_id in locked_layers if layer_id not in specs]
    if missing_layers:
        raise ValueError(f"missing locked feature layer(s): {missing_layers}")

    pairs, dropped_pairs = _complete_pairs(rows)
    if len(pairs) < int(args.min_complete_pairs):
        raise ValueError(f"only {len(pairs)} complete pairs; minimum is {args.min_complete_pairs}")

    feature_payloads = {
        layer_id: _feature_payload(layer_id=layer_id, spec=specs[layer_id], pairs=pairs)
        for layer_id in locked_layers
    }
    observed = _statistic(
        feature_payloads,
        late_layers=late_layers,
        early_layers=early_layers,
        projectors=projector_layers,
        swaps=[False] * len(pairs),
    )
    mode, total_assignments, assignments = _swap_assignments(
        len(pairs),
        max_exact=int(args.max_exact_assignments),
        n_permutations=int(args.n_permutations),
        seed=int(args.seed),
    )
    null_t = np.zeros(len(assignments), dtype=float)
    null_by_layer = {layer_id: np.zeros(len(assignments), dtype=float) for layer_id in locked_layers}
    for idx, swaps in enumerate(assignments):
        stat = _statistic(
            feature_payloads,
            late_layers=late_layers,
            early_layers=early_layers,
            projectors=projector_layers,
            swaps=swaps,
        )
        null_t[idx] = stat["T_late_minus_early"]
        for layer_id, score in stat["per_layer"].items():
            null_by_layer[layer_id][idx] = score["score"]

    layer_results: list[dict[str, Any]] = []
    for layer_id in locked_layers:
        observed_score = observed["per_layer"][layer_id]["score"]
        null_values = null_by_layer[layer_id]
        layer_results.append(
            {
                "layer_id": layer_id,
                "family": (
                    "late_attn"
                    if layer_id in late_layers
                    else "early_attn"
                    if layer_id in early_layers
                    else "projectors"
                ),
                "observed": observed["per_layer"][layer_id],
                "raw_p_value": _plus_one_p(null_values, observed_score),
                "bonferroni_locked_family_p_value": min(
                    1.0, _plus_one_p(null_values, observed_score) * len(locked_layers)
                ),
                "null_summary": {
                    "mean": float(null_values.mean()),
                    "std": float(null_values.std(ddof=0)),
                    "quantiles": {
                        str(q): float(np.quantile(null_values, q))
                        for q in (0.0, 0.5, 0.9, 0.95, 0.975, 0.99, 1.0)
                    },
                },
            }
        )

    p_value = _plus_one_p(null_t, float(observed["T_late_minus_early"]))
    result = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": _utc_now(),
        "rows_path": str(manifest_path),
        "manifest_schema_version": manifest.get("schema_version"),
        "contrast_id": args.contrast_id,
        "primary_statistic": "mean_score(late_attn) - mean_score(early_attn)",
        "score_function": "diff_norm * max(1 - cosine(pos_centroid, neg_centroid), 1e-6)",
        "tail": "upper_one_sided_T_late_minus_early",
        "exchangeability_unit": "confirmatory_pair_id",
        "permutation_mode": mode,
        "n_total_assignments": int(total_assignments),
        "n_permutations_evaluated": int(len(assignments)),
        "seed": int(args.seed),
        "alpha": float(args.alpha),
        "late_layers": late_layers,
        "early_layers": early_layers,
        "projector_layers": projector_layers,
        "locked_family_size": len(locked_layers),
        "n_rows": len(rows),
        "n_complete_pairs": len(pairs),
        "n_dropped_pair_records": len(dropped_pairs),
        "observed": observed,
        "primary_p_value": p_value,
        "decision": (
            "confirmed"
            if p_value < float(args.alpha)
            and observed["T_late_minus_early"] > 0
            and observed["secondary_ordering_late_gt_early_gt_projectors"]
            else "not_confirmed"
        ),
        "null_summary": {
            "mean": float(null_t.mean()),
            "std": float(null_t.std(ddof=0)),
            "quantiles": {
                str(q): float(np.quantile(null_t, q))
                for q in (0.0, 0.5, 0.9, 0.95, 0.975, 0.99, 1.0)
            },
        },
        "layers": layer_results,
        "pairs": [
            {
                "pair_id": pair["pair_id"],
                "story_item_id": pair["story"].get("item_id"),
                "math_item_id": pair["math"].get("item_id"),
            }
            for pair in pairs
        ],
        "dropped_pairs": dropped_pairs,
        "caveats": [
            "This is an item-level model-feature confirmatory test, not subject-level fMRI inference.",
            "Because HCP source blocks are condition-pure, exchangeability is the precomputed matched story/math pair.",
            "Layer-family membership is locked by CLI/defaults; do not add layers after observing this result.",
        ],
    }
    out_path = Path(args.out).expanduser().resolve()
    _write_json(out_path, result)
    print(
        json.dumps(
            {
                "status": "ok",
                "out": str(out_path),
                "decision": result["decision"],
                "T_late_minus_early": observed["T_late_minus_early"],
                "primary_p_value": p_value,
                "n_complete_pairs": len(pairs),
                "n_permutations_evaluated": len(assignments),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", required=True, help="layer_feature_manifest.json from extractor.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--contrast-id", default="story_audio_vs_math_audio_layer_family_confirmatory")
    parser.add_argument("--late-layer", action="append")
    parser.add_argument("--early-layer", action="append")
    parser.add_argument("--projector-layer", action="append")
    parser.add_argument("--min-complete-pairs", type=int, default=10)
    parser.add_argument("--max-exact-assignments", type=int, default=250000)
    parser.add_argument("--n-permutations", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=20260426)
    parser.add_argument("--alpha", type=float, default=0.05)
    return parser.parse_args()


def main() -> int:
    try:
        validate(parse_args())
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
