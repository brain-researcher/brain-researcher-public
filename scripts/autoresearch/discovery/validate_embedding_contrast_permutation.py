#!/usr/bin/env python3
"""Permutation validation for a single embedding contrast.

This is the generic counterpart to ``validate_embedding_permutation.py``. It
recomputes the current embedding autoresearch contrast score and tests whether
the observed condition split is unusually large under item-label relabeling.
Exact enumeration is used when the balanced label space is small; otherwise the
script falls back to seeded Monte Carlo permutations.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from collections import Counter
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
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


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


def _contrast_record(
    analysis_dir: Path,
    *,
    task_id: str,
    contrast_id: str,
) -> dict[str, Any] | None:
    path = analysis_dir / "contrast_findings.jsonl"
    if not path.exists():
        return None
    for row in _read_jsonl(path):
        if row.get("task_id") == task_id and row.get("contrast_id") == contrast_id:
            return row
    return None


def _bonferroni(p_value: float, family_size: int) -> float:
    return min(1.0, float(p_value) * max(1, int(family_size)))


def _stable_group_value(value: Any) -> str:
    if value is None:
        raise ValueError("missing value")
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError("empty string")
        return normalized
    if isinstance(value, bool | int | float):
        return str(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _lookup_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _row_group_value(row: dict[str, Any], key: str) -> str:
    value = _lookup_path(row, key) if "." in key else row.get(key, _MISSING)
    if value is _MISSING and "." not in key:
        for container_key in ("labels", "metadata"):
            container = row.get(container_key)
            if isinstance(container, dict) and key in container:
                value = container[key]
                break
    if value is _MISSING:
        raise KeyError(key)
    return _stable_group_value(value)


def _merge_metadata_manifest(
    rows: list[dict[str, Any]],
    manifest_path: Path | None,
) -> dict[str, Any]:
    if manifest_path is None:
        return {
            "path": None,
            "status": "not_requested",
            "n_manifest_rows": 0,
            "n_rows_matched": 0,
            "n_rows_unmatched": 0,
            "duplicate_item_ids": [],
        }

    payload = _read_json(manifest_path)
    manifest_rows = payload.get("rows")
    if not isinstance(manifest_rows, list):
        raise ValueError(f"metadata manifest {manifest_path} does not contain a list field named 'rows'")

    by_item_id: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for entry in manifest_rows:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("item_id")
        if item_id is None:
            continue
        key = str(item_id)
        if key in by_item_id:
            duplicates.append(key)
            continue
        by_item_id[key] = entry

    n_matched = 0
    n_unmatched = 0
    for row in rows:
        item_id = row.get("item_id")
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            row["metadata"] = metadata
        extra = by_item_id.get(str(item_id)) if item_id is not None else None
        if extra is None:
            n_unmatched += 1
            continue
        # Keep raw rows unchanged except for a metadata sidecar namespace. This
        # lets unqualified --exchangeability-key lookups resolve through metadata
        # without mutating condition labels or item identity.
        metadata.update({key: value for key, value in extra.items() if key != "item_id"})
        metadata["metadata_manifest_item_id"] = extra.get("item_id")
        n_matched += 1

    return {
        "path": str(manifest_path),
        "schema_version": payload.get("schema_version"),
        "status": "used",
        "n_manifest_rows": len(manifest_rows),
        "n_unique_manifest_item_ids": len(by_item_id),
        "n_rows_matched": n_matched,
        "n_rows_unmatched": n_unmatched,
        "duplicate_item_ids": sorted(duplicates),
        "caveats": payload.get("caveats", []),
    }


def _condition_side(
    condition: Any,
    *,
    positive_conditions: set[Any],
    negative_conditions: set[Any],
) -> str:
    if condition in positive_conditions:
        return "positive"
    if condition in negative_conditions:
        return "negative"
    raise ValueError(f"condition {condition!r} is outside the selected contrast")


def _build_exchangeability_groups(
    rows: list[dict[str, Any]],
    selected_indices: list[int],
    *,
    group_keys: list[str],
    positive_conditions: set[Any],
    negative_conditions: set[Any],
) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    ordered_keys: list[tuple[str, ...]] = []
    missing: list[dict[str, Any]] = []

    for local_idx, global_idx in enumerate(selected_indices):
        row = rows[global_idx]
        try:
            key_values = tuple(_row_group_value(row, key) for key in group_keys)
        except (KeyError, ValueError) as exc:
            missing.append(
                {
                    "item_id": row.get("item_id"),
                    "row_index": global_idx,
                    "missing_or_invalid_key": str(exc).strip("'"),
                }
            )
            continue

        if key_values not in by_key:
            by_key[key_values] = {
                "key_values": key_values,
                "local_indices": [],
                "global_indices": [],
                "conditions": Counter(),
            }
            ordered_keys.append(key_values)
        group = by_key[key_values]
        group["local_indices"].append(local_idx)
        group["global_indices"].append(global_idx)
        group["conditions"][str(row.get("condition"))] += 1

    if missing:
        examples = missing[:5]
        raise ValueError(
            "grouped permutation requires all selected rows to have non-empty group key values; "
            f"{len(missing)} rows failed, examples={examples}"
        )

    groups: list[dict[str, Any]] = []
    mixed_groups: list[dict[str, Any]] = []
    for key_values in ordered_keys:
        raw_group = by_key[key_values]
        side_counts = Counter(
            _condition_side(
                rows[global_idx].get("condition"),
                positive_conditions=positive_conditions,
                negative_conditions=negative_conditions,
            )
            for global_idx in raw_group["global_indices"]
        )
        if len(side_counts) != 1:
            mixed_groups.append(
                {
                    "key_values": list(key_values),
                    "side_counts": dict(side_counts),
                    "condition_counts": dict(raw_group["conditions"]),
                }
            )
            continue
        side = next(iter(side_counts))
        groups.append(
            {
                "key_values": key_values,
                "side": side,
                "local_indices": list(raw_group["local_indices"]),
                "global_indices": list(raw_group["global_indices"]),
                "conditions": dict(raw_group["conditions"]),
            }
        )

    if mixed_groups:
        examples = mixed_groups[:5]
        raise ValueError(
            "grouped permutation requires each exchangeability group to be fully positive "
            f"or fully negative; {len(mixed_groups)} mixed groups found, examples={examples}"
        )

    positive_groups = [group for group in groups if group["side"] == "positive"]
    negative_groups = [group for group in groups if group["side"] == "negative"]
    if not positive_groups or not negative_groups:
        raise ValueError(
            "grouped permutation requires at least one positive and one negative group; "
            f"found {len(positive_groups)} positive and {len(negative_groups)} negative groups"
        )
    if len(groups) < 2:
        raise ValueError(f"grouped permutation requires at least two groups; found {len(groups)}")
    return groups


def _group_size_counts(groups: list[dict[str, Any]]) -> Counter[int]:
    return Counter(len(group["local_indices"]) for group in groups)


def _exchangeability_group_counts(groups: list[dict[str, Any]]) -> dict[str, Any]:
    group_size_counts = _group_size_counts(groups)
    n_positive_groups = sum(1 for group in groups if group["side"] == "positive")
    return {
        "n_groups": len(groups),
        "n_positive_groups": n_positive_groups,
        "n_negative_groups": len(groups) - n_positive_groups,
        "group_size_counts": {
            str(size): count for size, count in sorted(group_size_counts.items())
        },
        "condition_counts_by_side": {
            "positive": dict(
                Counter(
                    condition
                    for group in groups
                    if group["side"] == "positive"
                    for condition, count in group["conditions"].items()
                    for _ in range(count)
                )
            ),
            "negative": dict(
                Counter(
                    condition
                    for group in groups
                    if group["side"] == "negative"
                    for condition, count in group["conditions"].items()
                    for _ in range(count)
                )
            ),
        },
    }


def _require_equal_sized_groups(groups: list[dict[str, Any]]) -> None:
    group_size_counts = _group_size_counts(groups)
    if len(group_size_counts) != 1:
        raise ValueError(
            "row_weighted grouped permutation requires equal-sized exchangeability groups "
            "because the BR/TRIBE contrast score weights rows; observed group sizes="
            f"{dict(sorted(group_size_counts.items()))}. Use --group-statistic group_mean "
            "to aggregate each pure-condition group to one equally weighted centroid."
        )


def _group_centroid_embeddings(
    embeddings: np.ndarray,
    groups: list[dict[str, Any]],
) -> np.ndarray:
    return np.vstack([embeddings[group["local_indices"]].mean(axis=0) for group in groups])


def _centroid_scoring_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **group,
            "local_indices": [group_idx],
        }
        for group_idx, group in enumerate(groups)
    ]


def _caveats_for(group_statistic: str, group_keys: list[str]) -> list[str]:
    if not group_keys:
        return [
            "Row-level item-label permutation was used; no exchangeability groups were requested.",
        ]
    if group_statistic == "group_mean":
        return [
            "Each pure-condition exchangeability group was aggregated to one centroid "
            "before scoring.",
            "Permutation labels are assigned to group centroids, so every group has equal "
            "weight regardless of row count.",
            "Within-group row-level variance and group-size information do not affect the "
            "permutation score.",
        ]
    return [
        "Grouped row_weighted scoring preserves row-level weights and requires equal-sized "
        "pure-condition groups.",
        "Unequal natural groups should use --group-statistic group_mean to avoid row-size "
        "weighting artifacts.",
    ]


def _score_for_group_assignment(
    embeddings: np.ndarray,
    groups: list[dict[str, Any]],
    positive_group_positions: list[int],
) -> float:
    positive_group_set = set(positive_group_positions)
    positive_indices = [
        idx
        for group_idx, group in enumerate(groups)
        if group_idx in positive_group_set
        for idx in group["local_indices"]
    ]
    negative_indices = [
        idx
        for group_idx, group in enumerate(groups)
        if group_idx not in positive_group_set
        for idx in group["local_indices"]
    ]
    if not positive_indices or not negative_indices:
        raise ValueError("group assignment produced an empty positive or negative side")
    return _score_for(embeddings, positive_indices, negative_indices)["score"]


def _null_scores_group_exact(
    embeddings: np.ndarray,
    groups: list[dict[str, Any]],
    *,
    n_positive_groups: int,
) -> list[float]:
    scores: list[float] = []
    all_group_positions = range(len(groups))
    for combo in itertools.combinations(all_group_positions, n_positive_groups):
        scores.append(_score_for_group_assignment(embeddings, groups, list(combo)))
    return scores


def _null_scores_group_monte_carlo(
    embeddings: np.ndarray,
    groups: list[dict[str, Any]],
    *,
    n_positive_groups: int,
    n_permutations: int,
    seed: int,
) -> list[float]:
    rng = np.random.default_rng(seed)
    group_positions = np.arange(len(groups))
    scores: list[float] = []
    for _ in range(int(n_permutations)):
        permuted = rng.permutation(group_positions)
        positive_group_positions = permuted[:n_positive_groups].astype(int).tolist()
        scores.append(_score_for_group_assignment(embeddings, groups, positive_group_positions))
    return scores


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


def validate(args: argparse.Namespace) -> dict[str, Any]:
    prediction_dir = Path(args.prediction_dir).expanduser().resolve()
    analysis_dir = Path(args.analysis_dir).expanduser().resolve() if args.analysis_dir else None
    metadata_manifest_path = (
        Path(args.metadata_manifest).expanduser().resolve() if args.metadata_manifest else None
    )
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_path = out_dir / f"{args.claim_id}.json"
    positive_conditions = set(args.positive_condition)
    negative_conditions = set(args.negative_condition)
    group_statistic = str(args.group_statistic)

    rows = _read_jsonl(prediction_dir / "embedding_rows.jsonl")
    metadata_manifest_summary = _merge_metadata_manifest(rows, metadata_manifest_path)
    embeddings = np.load(prediction_dir / "embeddings_matrix.npy")
    if len(rows) != int(embeddings.shape[0]):
        raise ValueError(
            f"row/matrix mismatch: {len(rows)} rows vs matrix shape {tuple(embeddings.shape)}"
        )

    selected_indices = [
        idx
        for idx, row in enumerate(rows)
        if row.get("task_id") == args.task_id
        and (row.get("condition") in positive_conditions or row.get("condition") in negative_conditions)
    ]
    positive_original = [
        idx for idx in selected_indices if rows[idx].get("condition") in positive_conditions
    ]
    negative_original = [
        idx for idx in selected_indices if rows[idx].get("condition") in negative_conditions
    ]
    if not positive_original or not negative_original:
        raise ValueError(
            f"empty selected contrast: {len(positive_original)} positive, "
            f"{len(negative_original)} negative for {args.task_id}:{args.contrast_id}"
        )

    local_lookup = {global_idx: local_idx for local_idx, global_idx in enumerate(selected_indices)}
    positive_local = [local_lookup[idx] for idx in positive_original]
    negative_local = [local_lookup[idx] for idx in negative_original]
    selected_embeddings = embeddings[selected_indices]
    observed = _score_for(selected_embeddings, positive_local, negative_local)

    n_items = int(selected_embeddings.shape[0])
    n_positive = len(positive_local)
    group_keys = list(args.exchangeability_keys or [])
    if group_statistic == "group_mean" and not group_keys:
        raise ValueError("--group-statistic group_mean requires at least one --exchangeability-key")

    groups: list[dict[str, Any]] = []
    group_counts: dict[str, Any] | None = None
    rows_aggregated_to_group_means = False
    caveats = _caveats_for(group_statistic, group_keys)
    n_scored_units = n_items
    n_positive_scoring_units = n_positive
    n_negative_scoring_units = len(negative_local)
    n_permutation_units = n_items
    if group_keys:
        try:
            groups = _build_exchangeability_groups(
                rows,
                selected_indices,
                group_keys=group_keys,
                positive_conditions=positive_conditions,
                negative_conditions=negative_conditions,
            )
            group_counts = _exchangeability_group_counts(groups)
            if group_statistic == "row_weighted":
                _require_equal_sized_groups(groups)
        except ValueError as exc:
            failure = {
                "schema_version": "br.autoresearch.single_contrast_permutation.v1",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "claim_id": args.claim_id,
                "prediction_dir": str(prediction_dir),
                "analysis_dir": str(analysis_dir) if analysis_dir else None,
                "metadata_manifest": metadata_manifest_summary,
                "task_id": args.task_id,
                "contrast_id": args.contrast_id,
                "positive_conditions": sorted(positive_conditions),
                "negative_conditions": sorted(negative_conditions),
                "score_function": "diff_norm * max(1 - cosine(pos_centroid, neg_centroid), 1e-6)",
                "permutation_unit": (
                    "exchangeability group centroid"
                    if group_statistic == "group_mean"
                    else "exchangeability group"
                ),
                "group_statistic": group_statistic,
                "rows_aggregated_to_group_means": False,
                "exchangeability_group_keys": group_keys,
                "exchangeability_group_status": "failed",
                "exchangeability_group_fallback_used": False,
                "exchangeability_group_counts": group_counts,
                "n_permutation_units": len(groups) if groups else None,
                "n_scored_units": n_scored_units,
                "n_positive_scoring_units": n_positive_scoring_units,
                "n_negative_scoring_units": n_negative_scoring_units,
                "caveats": caveats,
                "error": str(exc),
                "n_positive": len(positive_original),
                "n_negative": len(negative_original),
                "n_items": n_items,
                "observed": observed,
                "items": [
                    {
                        "item_id": rows[idx].get("item_id"),
                        "condition": rows[idx].get("condition"),
                        "labels": rows[idx].get("labels", {}),
                        "metadata": rows[idx].get("metadata", {}),
                    }
                    for idx in selected_indices
                ],
                "exchangeability_groups": [
                    {
                        "key": {
                            key: value
                            for key, value in zip(group_keys, group["key_values"], strict=True)
                        },
                        "side": group["side"],
                        "n_rows": len(group["local_indices"]),
                        "condition_counts": group["conditions"],
                        "item_ids": [rows[idx].get("item_id") for idx in group["global_indices"]],
                    }
                    for group in groups
                ],
            }
            _write_json(out_path, failure)
            print(json.dumps(failure, indent=2, ensure_ascii=False))
            raise ValueError(f"grouped permutation failed: {exc}") from None

        n_positive_groups = sum(1 for group in groups if group["side"] == "positive")
        total_combinations = math.comb(len(groups), n_positive_groups)
        scoring_embeddings = selected_embeddings
        scoring_groups = groups
        n_positive_scoring_units = n_positive_groups
        n_negative_scoring_units = len(groups) - n_positive_groups
        n_permutation_units = len(groups)
        if group_statistic == "group_mean":
            scoring_embeddings = _group_centroid_embeddings(selected_embeddings, groups)
            scoring_groups = _centroid_scoring_groups(groups)
            positive_centroids = [
                group_idx for group_idx, group in enumerate(groups) if group["side"] == "positive"
            ]
            negative_centroids = [
                group_idx for group_idx, group in enumerate(groups) if group["side"] == "negative"
            ]
            observed = _score_for(scoring_embeddings, positive_centroids, negative_centroids)
            rows_aggregated_to_group_means = True
            n_scored_units = len(groups)

        if total_combinations <= int(args.max_exact_combinations):
            null_scores = _null_scores_group_exact(
                scoring_embeddings,
                scoring_groups,
                n_positive_groups=n_positive_groups,
            )
            permutation_mode = "exact"
        else:
            null_scores = _null_scores_group_monte_carlo(
                scoring_embeddings,
                scoring_groups,
                n_positive_groups=n_positive_groups,
                n_permutations=int(args.n_permutations),
                seed=int(args.seed),
            )
            permutation_mode = "monte_carlo"
        permutation_unit = (
            "exchangeability group centroid"
            if group_statistic == "group_mean"
            else "exchangeability group"
        )
    else:
        total_combinations = math.comb(n_items, n_positive)
        if total_combinations <= int(args.max_exact_combinations):
            null_scores = _null_scores_exact(selected_embeddings, n_positive=n_positive)
            permutation_mode = "exact"
        else:
            null_scores = _null_scores_monte_carlo(
                selected_embeddings,
                n_positive=n_positive,
                n_permutations=int(args.n_permutations),
                seed=int(args.seed),
            )
            permutation_mode = "monte_carlo"
        permutation_unit = "item embedding row"

    null = np.asarray(null_scores, dtype=float)
    n_extreme = int(np.sum(null >= observed["score"] - 1e-12))
    empirical_p = float(n_extreme / len(null))
    plus_one_p = float((n_extreme + 1) / (len(null) + 1))
    corrected_p = _bonferroni(plus_one_p if permutation_mode == "monte_carlo" else empirical_p, args.family_size)
    contrast_record = (
        _contrast_record(analysis_dir, task_id=args.task_id, contrast_id=args.contrast_id)
        if analysis_dir
        else None
    )

    result = {
        "schema_version": "br.autoresearch.single_contrast_permutation.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_id": args.claim_id,
        "prediction_dir": str(prediction_dir),
        "analysis_dir": str(analysis_dir) if analysis_dir else None,
        "metadata_manifest": metadata_manifest_summary,
        "task_id": args.task_id,
        "contrast_id": args.contrast_id,
        "positive_conditions": sorted(positive_conditions),
        "negative_conditions": sorted(negative_conditions),
        "score_function": "diff_norm * max(1 - cosine(pos_centroid, neg_centroid), 1e-6)",
        "permutation_unit": permutation_unit,
        "group_statistic": group_statistic,
        "rows_aggregated_to_group_means": rows_aggregated_to_group_means,
        "exchangeability_group_keys": group_keys,
        "exchangeability_group_status": "used" if group_keys else "not_requested",
        "exchangeability_group_fallback_used": False,
        "exchangeability_group_counts": group_counts,
        "n_permutation_units": n_permutation_units,
        "n_scored_units": n_scored_units,
        "n_positive_scoring_units": n_positive_scoring_units,
        "n_negative_scoring_units": n_negative_scoring_units,
        "caveats": caveats,
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
        "observed": observed,
        "analysis_record_score": (
            {
                "score": contrast_record.get("score"),
                "diff_norm": contrast_record.get("diff_norm"),
                "cosine_gap": contrast_record.get("cosine_gap"),
                "n_positive": contrast_record.get("n_positive"),
                "n_negative": contrast_record.get("n_negative"),
            }
            if contrast_record
            else None
        ),
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
                "metadata": rows[idx].get("metadata", {}),
            }
            for idx in selected_indices
        ],
        "exchangeability_groups": [
            {
                "key": {
                    key: value for key, value in zip(group_keys, group["key_values"], strict=True)
                },
                "side": group["side"],
                "n_rows": len(group["local_indices"]),
                "condition_counts": group["conditions"],
                "item_ids": [rows[idx].get("item_id") for idx in group["global_indices"]],
            }
            for group in groups
        ],
    }

    _write_json(out_path, result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claim-id", required=True)
    parser.add_argument("--prediction-dir", required=True)
    parser.add_argument("--analysis-dir")
    parser.add_argument(
        "--metadata-manifest",
        help=(
            "Optional JSON manifest with a rows[] list keyed by item_id. Matching "
            "entries are merged into each embedding row's metadata namespace before "
            "exchangeability-key lookup."
        ),
    )
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--contrast-id", required=True)
    parser.add_argument("--positive-condition", action="append", required=True)
    parser.add_argument("--negative-condition", action="append", required=True)
    parser.add_argument(
        "--exchangeability-key",
        "--group-key",
        dest="exchangeability_keys",
        action="append",
        help=(
            "Metadata/label key defining an exchangeability group. Repeat for composite groups. "
            "Unqualified keys are read from the row, then labels, then metadata; dotted keys "
            "such as labels.subject_id require that exact nested path."
        ),
    )
    parser.add_argument(
        "--group-statistic",
        choices=("row_weighted", "group_mean"),
        default="row_weighted",
        help=(
            "Scoring statistic for grouped permutation. row_weighted preserves existing "
            "row-level scoring and requires equal-sized groups. group_mean aggregates each "
            "pure-condition exchangeability group to one centroid before scoring so unequal "
            "group sizes have equal weight."
        ),
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
