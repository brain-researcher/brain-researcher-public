#!/usr/bin/env python3
"""Covariate-adjusted permutation validation for one embedding contrast.

This is a sensitivity check, not a replacement for a locked subject-level
analysis. It residualizes row-aligned embedding vectors against precomputed
numeric nuisance covariates, then runs the same item-label permutation score
used by ``validate_embedding_contrast_permutation.py`` on the residual vectors.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


_MISSING = object()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom <= 0:
        return 0.0
    return float(np.dot(left, right) / denom)


def _score_for(
    embeddings: np.ndarray,
    positive_indices: list[int],
    negative_indices: list[int],
) -> dict[str, float]:
    pos = embeddings[positive_indices].mean(axis=0)
    neg = embeddings[negative_indices].mean(axis=0)
    diff = pos - neg
    diff_norm = float(np.linalg.norm(diff))
    cosine_gap = float(1.0 - _cosine(pos, neg))
    projection_gap = 0.0
    if diff_norm > 0:
        axis = diff / diff_norm
        projection_gap = float(np.dot(embeddings[positive_indices], axis).mean()) - float(
            np.dot(embeddings[negative_indices], axis).mean()
        )
    return {
        "score": float(diff_norm * max(cosine_gap, 1e-6)),
        "diff_norm": diff_norm,
        "cosine_gap": cosine_gap,
        "projection_gap": projection_gap,
    }


def _lookup_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _load_sidecar_rows(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = _read_json(path)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"sidecar {path} must contain a rows[] list")
    clean_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"sidecar row {idx} is not an object")
        clean_rows.append(row)
    metadata = {key: value for key, value in payload.items() if key != "rows"}
    return clean_rows, metadata


def _numeric_value(row: dict[str, Any], key: str) -> float | None:
    value = _lookup_path(row, key) if "." in key else row.get(key, _MISSING)
    if value is _MISSING:
        covariates = row.get("covariates")
        if isinstance(covariates, dict):
            value = _lookup_path(covariates, key) if "." in key else covariates.get(key, _MISSING)
    if value is _MISSING or value is None or value == "":
        return None
    if isinstance(value, bool):
        return float(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _bonferroni(p_value: float, family_size: int) -> float:
    return min(1.0, float(p_value) * max(1, int(family_size)))


def _null_scores_exact(
    embeddings: np.ndarray,
    *,
    n_positive: int,
) -> list[float]:
    n_items = int(embeddings.shape[0])
    scores: list[float] = []
    all_indices = range(n_items)
    for combo in itertools.combinations(all_indices, n_positive):
        pos = list(combo)
        pos_set = set(pos)
        neg = [idx for idx in all_indices if idx not in pos_set]
        scores.append(_score_for(embeddings, pos, neg)["score"])
    return scores


def _null_scores_monte_carlo(
    embeddings: np.ndarray,
    *,
    n_positive: int,
    n_permutations: int,
    seed: int,
) -> list[float]:
    rng = np.random.default_rng(seed)
    n_items = int(embeddings.shape[0])
    scores: list[float] = []
    all_indices = np.arange(n_items)
    for _ in range(int(n_permutations)):
        permuted = rng.permutation(all_indices)
        pos = permuted[:n_positive].astype(int).tolist()
        neg = permuted[n_positive:].astype(int).tolist()
        scores.append(_score_for(embeddings, pos, neg)["score"])
    return scores


def _standardize_covariates(matrix: np.ndarray, names: list[str]) -> tuple[np.ndarray, dict[str, Any]]:
    means = matrix.mean(axis=0)
    stds = matrix.std(axis=0, ddof=0)
    keep = stds > 1e-12
    dropped = [name for name, is_kept in zip(names, keep, strict=True) if not is_kept]
    if not np.any(keep):
        raise ValueError("all requested covariates are constant over the selected rows")
    standardized = (matrix[:, keep] - means[keep]) / stds[keep]
    kept_names = [name for name, is_kept in zip(names, keep, strict=True) if is_kept]
    summary = {
        "requested_covariates": names,
        "used_covariates": kept_names,
        "dropped_constant_covariates": dropped,
        "means": {name: float(value) for name, value in zip(names, means, strict=True)},
        "stds": {name: float(value) for name, value in zip(names, stds, strict=True)},
    }
    return standardized, summary


def _residualize_embeddings(embeddings: np.ndarray, covariates: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    design = np.column_stack([np.ones(covariates.shape[0]), covariates])
    rank = int(np.linalg.matrix_rank(design))
    beta, *_ = np.linalg.lstsq(design, embeddings, rcond=None)
    fitted = design @ beta
    residual = embeddings - fitted
    return residual, {
        "design_shape": list(design.shape),
        "design_rank": rank,
        "embedding_shape": list(embeddings.shape),
    }


def validate(args: argparse.Namespace) -> dict[str, Any]:
    prediction_dir = Path(args.prediction_dir).expanduser().resolve()
    sidecar_path = Path(args.covariate_sidecar).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_path = out_dir / f"{args.claim_id}.json"
    positive_conditions = set(args.positive_condition)
    negative_conditions = set(args.negative_condition)

    rows = _read_jsonl(prediction_dir / "embedding_rows.jsonl")
    embeddings = np.load(prediction_dir / "embeddings_matrix.npy")
    if len(rows) != int(embeddings.shape[0]):
        raise ValueError(
            f"row/matrix mismatch: {len(rows)} rows vs matrix shape {tuple(embeddings.shape)}"
        )

    sidecar_rows, sidecar_metadata = _load_sidecar_rows(sidecar_path)
    sidecar_by_item: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for row in sidecar_rows:
        item_id = row.get("item_id")
        if item_id is None:
            continue
        key = str(item_id)
        if key in sidecar_by_item:
            duplicates.append(key)
            continue
        sidecar_by_item[key] = row
    if duplicates:
        raise ValueError(f"covariate sidecar has duplicate item_id values: {sorted(duplicates)[:5]}")

    selected_indices = [
        idx
        for idx, row in enumerate(rows)
        if row.get("task_id") == args.task_id
        and (row.get("condition") in positive_conditions or row.get("condition") in negative_conditions)
    ]
    missing_items: list[str] = []
    covariate_rows: list[list[float]] = []
    kept_indices: list[int] = []
    dropped_for_covariates: list[dict[str, Any]] = []
    for idx in selected_indices:
        item_id = rows[idx].get("item_id")
        sidecar_row = sidecar_by_item.get(str(item_id)) if item_id is not None else None
        if sidecar_row is None:
            missing_items.append(str(item_id))
            continue
        values = [_numeric_value(sidecar_row, key) for key in args.covariate]
        missing_keys = [
            key for key, value in zip(args.covariate, values, strict=True) if value is None
        ]
        if missing_keys:
            dropped_for_covariates.append(
                {
                    "item_id": item_id,
                    "condition": rows[idx].get("condition"),
                    "missing_covariates": missing_keys,
                }
            )
            continue
        covariate_rows.append([float(value) for value in values if value is not None])
        kept_indices.append(idx)

    if missing_items:
        raise ValueError(f"{len(missing_items)} selected prediction rows are absent from sidecar")
    if dropped_for_covariates and not args.drop_missing_covariates:
        examples = dropped_for_covariates[:5]
        raise ValueError(
            "selected rows have missing covariates; rerun with --drop-missing-covariates "
            f"to exclude them. examples={examples}"
        )

    local_lookup = {global_idx: local_idx for local_idx, global_idx in enumerate(kept_indices)}
    positive_original = [
        idx for idx in kept_indices if rows[idx].get("condition") in positive_conditions
    ]
    negative_original = [
        idx for idx in kept_indices if rows[idx].get("condition") in negative_conditions
    ]
    if not positive_original or not negative_original:
        raise ValueError(
            f"empty adjusted contrast after covariate filtering: "
            f"{len(positive_original)} positive, {len(negative_original)} negative"
        )
    positive_local = [local_lookup[idx] for idx in positive_original]
    negative_local = [local_lookup[idx] for idx in negative_original]

    selected_embeddings = embeddings[kept_indices]
    covariate_matrix = np.asarray(covariate_rows, dtype=float)
    standardized_covariates, covariate_summary = _standardize_covariates(
        covariate_matrix, list(args.covariate)
    )
    residual_embeddings, residualization_summary = _residualize_embeddings(
        selected_embeddings, standardized_covariates
    )

    raw_observed = _score_for(selected_embeddings, positive_local, negative_local)
    adjusted_observed = _score_for(residual_embeddings, positive_local, negative_local)
    n_items = int(residual_embeddings.shape[0])
    n_positive = len(positive_local)
    total_combinations = math.comb(n_items, n_positive)
    if total_combinations <= int(args.max_exact_combinations):
        null_scores = _null_scores_exact(residual_embeddings, n_positive=n_positive)
        permutation_mode = "exact"
    else:
        null_scores = _null_scores_monte_carlo(
            residual_embeddings,
            n_positive=n_positive,
            n_permutations=int(args.n_permutations),
            seed=int(args.seed),
        )
        permutation_mode = "monte_carlo"

    null = np.asarray(null_scores, dtype=float)
    n_extreme = int(np.sum(null >= adjusted_observed["score"] - 1e-12))
    empirical_p = float(n_extreme / len(null))
    plus_one_p = float((n_extreme + 1) / (len(null) + 1))
    p_for_correction = plus_one_p if permutation_mode == "monte_carlo" else empirical_p
    corrected_p = _bonferroni(p_for_correction, args.family_size)

    result = {
        "schema_version": "br.autoresearch.covariate_adjusted_contrast_permutation.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_id": args.claim_id,
        "prediction_dir": str(prediction_dir),
        "covariate_sidecar": {
            "path": str(sidecar_path),
            "metadata": sidecar_metadata,
            "n_rows": len(sidecar_rows),
        },
        "task_id": args.task_id,
        "contrast_id": args.contrast_id,
        "positive_conditions": sorted(positive_conditions),
        "negative_conditions": sorted(negative_conditions),
        "score_function": "diff_norm * max(1 - cosine(pos_centroid, neg_centroid), 1e-6)",
        "adjustment": {
            "method": "linear_residualization_of_embedding_dimensions",
            "covariate_summary": covariate_summary,
            "residualization_summary": residualization_summary,
            "dropped_for_missing_covariates": dropped_for_covariates,
            "caveats": [
                "This is an item-level nuisance sensitivity check, not subject-level fMRI inference.",
                "Embedding dimensions are residualized against nuisance covariates before label permutation.",
                "Permutation labels are not restricted by source family in this validator.",
            ],
        },
        "permutation_unit": "covariate-residualized item embedding row",
        "tail": "upper_one_sided_score_separation",
        "permutation_mode": permutation_mode,
        "n_total_combinations": int(total_combinations),
        "n_permutations_evaluated": int(len(null)),
        "n_extreme_ge_observed": n_extreme,
        "exact_or_empirical_p_value": empirical_p,
        "conservative_plus_one_p_value": plus_one_p,
        "family_size": int(args.family_size),
        "bonferroni_p_value": corrected_p,
        "decision": (
            "significant_after_bonferroni"
            if corrected_p <= float(args.alpha)
            else "not_significant_after_bonferroni"
        ),
        "alpha": float(args.alpha),
        "n_positive": len(positive_original),
        "n_negative": len(negative_original),
        "n_items": n_items,
        "raw_observed": raw_observed,
        "adjusted_observed": adjusted_observed,
        "null_summary": {
            "mean": float(null.mean()),
            "std": float(null.std(ddof=0)),
            "quantiles": {
                str(q): float(np.quantile(null, q))
                for q in (0.0, 0.5, 0.9, 0.95, 0.975, 0.99, 1.0)
            },
        },
        "items": [
            {
                "item_id": rows[idx].get("item_id"),
                "condition": rows[idx].get("condition"),
                "labels": rows[idx].get("labels", {}),
            }
            for idx in kept_indices
        ],
    }
    _write_json(out_path, result)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claim-id", required=True)
    parser.add_argument("--prediction-dir", required=True)
    parser.add_argument("--covariate-sidecar", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--contrast-id", required=True)
    parser.add_argument("--positive-condition", action="append", required=True)
    parser.add_argument("--negative-condition", action="append", required=True)
    parser.add_argument(
        "--covariate",
        action="append",
        required=True,
        help=(
            "Numeric covariate to residualize. Reads top-level sidecar row fields, "
            "then covariates.<name>; dotted paths are supported."
        ),
    )
    parser.add_argument(
        "--drop-missing-covariates",
        action="store_true",
        help="Drop selected rows with missing requested covariates instead of failing.",
    )
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--family-size", type=int, default=1)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--max-exact-combinations", type=int, default=250000)
    parser.add_argument("--n-permutations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=1729)
    return parser.parse_args()


def main() -> None:
    try:
        validate(parse_args())
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from None


if __name__ == "__main__":
    main()
