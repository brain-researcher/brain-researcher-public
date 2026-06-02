#!/usr/bin/env python3
"""Validate predicted-fMRI contrast stability across independent folds.

This is a bridge check, not subject-level BOLD validation. It consumes existing
TRIBE prediction-run artifacts (``embedding_rows.jsonl`` plus
``embeddings_matrix.npy``), computes a condition contrast map per fold, and
tests whether the across-fold contrast-map correlation is larger than expected
under item-label permutations inside each fold.

Use this only when observed subject fMRI/BOLD targets are not available. The
output explicitly records that limitation.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_VERSION = "br.autoresearch.predicted_fmri_fold_stability.v1"


@dataclass(frozen=True)
class FoldInput:
    name: str
    prediction_dir: Path


@dataclass
class FoldData:
    name: str
    prediction_dir: Path
    rows: list[dict[str, Any]]
    matrix: np.ndarray
    selected_indices: list[int]
    positive_local: list[int]
    negative_local: list[int]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            raise ValueError(f"expected JSON object in {path} line {line_number}")
        rows.append(row)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_fold(value: str) -> FoldInput:
    if "=" not in value:
        raise ValueError(f"invalid --fold {value!r}; expected name=/path/to/prediction_dir")
    name, raw_path = value.split("=", 1)
    name = name.strip()
    if not name:
        raise ValueError(f"invalid --fold {value!r}; empty fold name")
    return FoldInput(name=name, prediction_dir=Path(raw_path).expanduser().resolve())


def _load_fold(
    fold: FoldInput,
    *,
    task_id: str | None,
    positive_conditions: set[str],
    negative_conditions: set[str],
) -> FoldData:
    rows_path = fold.prediction_dir / "embedding_rows.jsonl"
    matrix_path = fold.prediction_dir / "embeddings_matrix.npy"
    if not rows_path.exists():
        raise FileNotFoundError(f"missing {rows_path}")
    if not matrix_path.exists():
        raise FileNotFoundError(f"missing {matrix_path}")
    rows = _read_jsonl(rows_path)
    matrix = np.asarray(np.load(matrix_path), dtype=np.float64)
    if matrix.ndim != 2:
        raise ValueError(f"{matrix_path} must be 2D, got shape={tuple(matrix.shape)}")
    if len(rows) != int(matrix.shape[0]):
        raise ValueError(f"row/matrix mismatch for {fold.name}: {len(rows)} vs {matrix.shape}")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"matrix contains non-finite values: {matrix_path}")

    selected: list[int] = []
    positive: list[int] = []
    negative: list[int] = []
    for idx, row in enumerate(rows):
        if task_id is not None and str(row.get("task_id")) != task_id:
            continue
        condition = str(row.get("condition")) if row.get("condition") is not None else ""
        if condition in positive_conditions:
            positive.append(len(selected))
            selected.append(idx)
        elif condition in negative_conditions:
            negative.append(len(selected))
            selected.append(idx)
    if not positive or not negative:
        raise ValueError(
            f"fold {fold.name} has empty contrast after filtering: "
            f"{len(positive)} positive, {len(negative)} negative"
        )
    return FoldData(
        name=fold.name,
        prediction_dir=fold.prediction_dir,
        rows=rows,
        matrix=matrix[selected],
        selected_indices=selected,
        positive_local=positive,
        negative_local=negative,
    )


def _contrast(matrix: np.ndarray, positive: list[int], negative: list[int]) -> np.ndarray:
    return matrix[positive].mean(axis=0) - matrix[negative].mean(axis=0)


def _score_for(matrix: np.ndarray, positive: list[int], negative: list[int]) -> dict[str, float]:
    pos = matrix[positive].mean(axis=0)
    neg = matrix[negative].mean(axis=0)
    diff = pos - neg
    diff_norm = float(np.linalg.norm(diff))
    denom = float(np.linalg.norm(pos) * np.linalg.norm(neg))
    cosine = float(np.dot(pos, neg) / denom) if denom > 0 else 0.0
    cosine_gap = float(1.0 - cosine)
    return {
        "score": float(diff_norm * max(cosine_gap, 1e-6)),
        "diff_norm": diff_norm,
        "cosine_gap": cosine_gap,
    }


def _rowwise_pearson(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    left_centered = left - left.mean(axis=1, keepdims=True)
    right_centered = right - right.mean(axis=1, keepdims=True)
    denom = np.linalg.norm(left_centered, axis=1) * np.linalg.norm(right_centered, axis=1)
    out = np.zeros(left.shape[0], dtype=np.float64)
    valid = denom > 0
    out[valid] = np.einsum("ij,ij->i", left_centered[valid], right_centered[valid]) / denom[valid]
    return out


def _pairwise_mean_pearson(contrasts: list[np.ndarray]) -> tuple[float, list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    values: list[float] = []
    for left_idx in range(len(contrasts)):
        for right_idx in range(left_idx + 1, len(contrasts)):
            left = contrasts[left_idx][None, :]
            right = contrasts[right_idx][None, :]
            value = float(_rowwise_pearson(left, right)[0])
            values.append(value)
            records.append({"left_fold_index": left_idx, "right_fold_index": right_idx, "pearson_r": value})
    return float(sum(values) / len(values)), records


def _contrast_batch(matrix: np.ndarray, masks: np.ndarray, n_positive: int) -> np.ndarray:
    n_items = matrix.shape[0]
    n_negative = n_items - n_positive
    positive_sum = masks @ matrix
    total = matrix.sum(axis=0, keepdims=True)
    negative_sum = total - positive_sum
    return positive_sum / float(n_positive) - negative_sum / float(n_negative)


def _null_distribution(
    folds: list[FoldData],
    *,
    n_permutations: int,
    seed: int,
    batch_size: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    values: list[np.ndarray] = []
    remaining = n_permutations
    while remaining > 0:
        batch = min(batch_size, remaining)
        batch_contrasts: list[np.ndarray] = []
        for fold in folds:
            n_items = int(fold.matrix.shape[0])
            n_positive = len(fold.positive_local)
            # Assign exactly n_positive labels per permutation by ranking random
            # scores. This avoids Python loops over item indices.
            random_scores = rng.random((batch, n_items))
            positive_positions = np.argpartition(random_scores, n_positive - 1, axis=1)[
                :, :n_positive
            ]
            masks = np.zeros((batch, n_items), dtype=np.float64)
            rows = np.arange(batch)[:, None]
            masks[rows, positive_positions] = 1.0
            batch_contrasts.append(_contrast_batch(fold.matrix, masks, n_positive))

        pair_values: list[np.ndarray] = []
        for left_idx in range(len(batch_contrasts)):
            for right_idx in range(left_idx + 1, len(batch_contrasts)):
                pair_values.append(_rowwise_pearson(batch_contrasts[left_idx], batch_contrasts[right_idx]))
        values.append(np.vstack(pair_values).mean(axis=0))
        remaining -= batch
    return np.concatenate(values)


def validate(args: argparse.Namespace) -> dict[str, Any]:
    folds_in = [_parse_fold(value) for value in args.fold]
    if len(folds_in) < 2:
        raise ValueError("at least two --fold arguments are required")
    fold_names = [fold.name for fold in folds_in]
    if len(set(fold_names)) != len(fold_names):
        raise ValueError(f"duplicate fold names: {fold_names}")

    positive_conditions = set(args.positive_condition or ["story_audio"])
    negative_conditions = set(args.negative_condition or ["math_audio"])
    folds = [
        _load_fold(
            fold,
            task_id=args.task_id,
            positive_conditions=positive_conditions,
            negative_conditions=negative_conditions,
        )
        for fold in folds_in
    ]
    vertex_counts = {int(fold.matrix.shape[1]) for fold in folds}
    if len(vertex_counts) != 1:
        raise ValueError(f"folds have inconsistent vertex dimensions: {sorted(vertex_counts)}")

    observed_contrasts = [
        _contrast(fold.matrix, fold.positive_local, fold.negative_local) for fold in folds
    ]
    observed_mean_r, pair_records = _pairwise_mean_pearson(observed_contrasts)
    null = _null_distribution(
        folds,
        n_permutations=int(args.n_permutations),
        seed=int(args.seed),
        batch_size=int(args.batch_size),
    )
    p_value = float((int(np.sum(null >= observed_mean_r - 1e-12)) + 1) / (len(null) + 1))

    result = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": _utc_now(),
        "claim_scope": "fold_level_predicted_fmri_stability_not_subject_bold",
        "task_id": args.task_id,
        "contrast_id": args.contrast_id,
        "positive_conditions": sorted(positive_conditions),
        "negative_conditions": sorted(negative_conditions),
        "statistic": "mean pairwise Pearson correlation between fold contrast maps",
        "tail": "upper_one_sided_stability",
        "surface_space": "fsaverage5_predicted_vertices",
        "n_vertices": int(next(iter(vertex_counts))),
        "n_folds": len(folds),
        "folds": [
            {
                "name": fold.name,
                "prediction_dir": str(fold.prediction_dir),
                "n_rows_total": len(fold.rows),
                "n_selected": int(fold.matrix.shape[0]),
                "n_positive": len(fold.positive_local),
                "n_negative": len(fold.negative_local),
                "contrast_score": _score_for(fold.matrix, fold.positive_local, fold.negative_local),
                "selected_items": [
                    {
                        "row_index": idx,
                        "item_id": fold.rows[idx].get("item_id"),
                        "condition": fold.rows[idx].get("condition"),
                    }
                    for idx in fold.selected_indices
                ],
            }
            for fold in folds
        ],
        "observed_mean_pairwise_pearson_r": observed_mean_r,
        "observed_pairwise": [
            {
                **record,
                "left_fold": folds[record["left_fold_index"]].name,
                "right_fold": folds[record["right_fold_index"]].name,
            }
            for record in pair_records
        ],
        "permutation": {
            "mode": "monte_carlo_item_label_permutation_within_each_fold",
            "n_permutations": int(len(null)),
            "seed": int(args.seed),
            "batch_size": int(args.batch_size),
            "plus_one_p_value": p_value,
            "null_summary": {
                "mean": float(null.mean()),
                "std": float(null.std(ddof=0)),
                "quantiles": {
                    str(q): float(np.quantile(null, q))
                    for q in (0.0, 0.5, 0.9, 0.95, 0.975, 0.99, 1.0)
                },
            },
        },
        "decision": (
            "stable_predicted_fmri_fold_contrast"
            if p_value < float(args.alpha) and observed_mean_r > 0
            else "not_stable_predicted_fmri_fold_contrast"
        ),
        "alpha": float(args.alpha),
        "blockers_to_subject_level_fmri": [
            "No observed subject-level BOLD, CIFTI, NIfTI, beta, contrast, or stat-map targets were found in the inspected discovery/tribe validation artifacts.",
            "Prediction rows do not include subject_id or fold_id fields; folds here are independent stimulus splits, not subject folds.",
            "This test validates predicted-response map stability only; it cannot estimate subject-level encoding accuracy or group fMRI significance.",
        ],
        "required_inputs_for_subject_level_upgrade": [
            "subject_id/run-aligned observed HCP LANGUAGE BOLD or beta/stat maps in the same surface/volume space as TRIBE predictions",
            "stimulus-to-time/run design matrix linking story/math items to observed responses",
            "predeclared subject or run folds and ROI/vertex correction family",
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
                "observed_mean_pairwise_pearson_r": observed_mean_r,
                "p_value": p_value,
                "n_folds": len(folds),
                "n_permutations": int(len(null)),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fold",
        action="append",
        required=True,
        help="Named prediction fold as name=/path/to/prediction_dir. Repeat at least twice.",
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--task-id", default="ibc_hcp_language")
    parser.add_argument("--contrast-id", default="story_audio_vs_math_audio")
    parser.add_argument("--positive-condition", action="append", default=None)
    parser.add_argument("--negative-condition", action="append", default=None)
    parser.add_argument("--n-permutations", type=int, default=10000)
    parser.add_argument("--batch-size", type=int, default=256)
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
