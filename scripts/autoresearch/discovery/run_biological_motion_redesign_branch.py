#!/usr/bin/env python3
"""Run and score the redesigned biological-motion TRIBE branch.

Inputs:
  - A condition-resolved manifest from ``materialize_biomo_runtime.py``.
  - TRIBE v2 plus a transformers build that supports the V-JEPA2 video extractor.

Outputs:
  - ``run_summary.json``
  - ``embedding_rows.jsonl``
  - ``embeddings_matrix.npy``
  - per-item prediction matrices under ``item_matrices/``
  - ``biological_motion_dynamic_score.json``
  - ``qc/biological_motion_motion_energy_balance.json``
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import imageio.v2 as imageio
import numpy as np


SCHEMA_VERSION = "br.autoresearch.biological_motion_redesign_branch.v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "items" not in payload:
        raise ValueError(f"manifest must contain an items array: {path}")
    return payload


def select_items(
    manifest: dict[str, Any],
    *,
    positive_conditions: set[str],
    negative_conditions: set[str],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in manifest.get("items") or []:
        if not isinstance(item, dict):
            continue
        condition = str(item.get("condition") or "")
        if condition in positive_conditions or condition in negative_conditions:
            video_path = ((item.get("tribe_args") or {}).get("video_path") or "").strip()
            if not video_path:
                raise ValueError(f"selected item lacks tribe_args.video_path: {item.get('item_id')}")
            selected.append(item)
    if not selected:
        raise ValueError("no manifest items matched the requested contrast conditions")
    return selected


def motion_energy(video_path: Path) -> dict[str, Any]:
    reader = imageio.get_reader(str(video_path))
    previous: np.ndarray | None = None
    diffs: list[float] = []
    frame_count = 0
    try:
        for frame in reader:
            frame_count += 1
            gray = np.asarray(frame, dtype=np.float32).mean(axis=2) / 255.0
            if previous is not None:
                diffs.append(float(np.mean(np.abs(gray - previous))))
            previous = gray
    finally:
        reader.close()
    return {
        "video_path": str(video_path),
        "frame_count": frame_count,
        "mean_abs_frame_difference": float(np.mean(diffs)) if diffs else 0.0,
        "std_abs_frame_difference": float(np.std(diffs, ddof=0)) if diffs else 0.0,
    }


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom == 0.0:
        return 0.0
    return float(np.dot(left, right) / denom)


def contrast_score(matrix: np.ndarray, labels: np.ndarray, positive_label: int = 1) -> dict[str, float]:
    positive = matrix[labels == positive_label]
    negative = matrix[labels != positive_label]
    pos_centroid = positive.mean(axis=0)
    neg_centroid = negative.mean(axis=0)
    diff_norm = float(np.linalg.norm(pos_centroid - neg_centroid))
    cos = cosine_similarity(pos_centroid, neg_centroid)
    cosine_gap = float(1.0 - cos)
    score = float(diff_norm * max(cosine_gap, 1e-6))
    return {
        "diff_norm": diff_norm,
        "cosine_similarity": cos,
        "cosine_gap": cosine_gap,
        "score": score,
    }


def exact_or_sampled_null(
    matrix: np.ndarray,
    labels: np.ndarray,
    *,
    observed_score: float,
    max_exact_combinations: int,
    n_permutations: int,
    seed: int,
) -> dict[str, Any]:
    n_items = int(labels.shape[0])
    n_positive = int(labels.sum())
    n_combinations = math.comb(n_items, n_positive)
    null_scores: list[float] = []
    method: str
    if n_combinations <= max_exact_combinations:
        method = "exact_label_enumeration"
        iterator = itertools.combinations(range(n_items), n_positive)
    else:
        method = "sampled_label_permutation"
        rng = np.random.default_rng(seed)

        def sampled_iterator():
            for _ in range(n_permutations):
                yield tuple(sorted(rng.choice(n_items, size=n_positive, replace=False).tolist()))

        iterator = sampled_iterator()
    for positive_indices in iterator:
        permuted = np.zeros(n_items, dtype=np.int8)
        permuted[list(positive_indices)] = 1
        null_scores.append(contrast_score(matrix, permuted)["score"])
    null = np.asarray(null_scores, dtype=np.float64)
    p_value = float((int(np.sum(null >= observed_score - 1e-12)) + 1) / (null.size + 1))
    return {
        "method": method,
        "n_null": int(null.size),
        "p_value_plus_one": p_value,
        "mean": float(null.mean()),
        "std": float(null.std(ddof=0)),
        "q50": float(np.quantile(null, 0.50)),
        "q95": float(np.quantile(null, 0.95)),
        "q99": float(np.quantile(null, 0.99)),
    }


def setup_readonly_safe_env(cache_root: Path) -> None:
    os.environ.setdefault("MNE_DONTWRITE_HOME", "true")
    os.environ.setdefault("MNE_HOME", str((cache_root / "mne_home").resolve()))
    os.environ.setdefault("MPLCONFIGDIR", str((cache_root / "mpl_config").resolve()))
    Path(os.environ["MNE_HOME"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_root = args.out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    setup_readonly_safe_env(out_root / "cache")

    from brain_researcher.services.tools.tribe_tool import TribePredictTool

    manifest = load_manifest(args.manifest)
    positive_conditions = set(args.positive_condition)
    negative_conditions = set(args.negative_condition)
    selected = select_items(
        manifest,
        positive_conditions=positive_conditions,
        negative_conditions=negative_conditions,
    )
    tool = TribePredictTool()
    rows: list[dict[str, Any]] = []
    vectors: list[np.ndarray] = []
    qc_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    item_matrix_root = out_root / "item_matrices"

    for item in selected:
        item_id = str(item.get("item_id"))
        condition = str(item.get("condition"))
        video_path = Path(str((item.get("tribe_args") or {}).get("video_path"))).expanduser().resolve()
        matrix_path = item_matrix_root / f"{item_id}.npy"
        result = tool.run(
            video_path=str(video_path),
            checkpoint_dir=args.checkpoint_dir,
            checkpoint_name=args.checkpoint_name,
            cache_folder=str(args.cache_folder.resolve()) if args.cache_folder else str((out_root / "tribev2_cache").resolve()),
            device=args.device,
            verbose=bool(args.verbose),
            remove_empty_segments=True,
            save_matrix_path=str(matrix_path),
        )
        if result.get("status") != "success":
            failures.append({"item_id": item_id, "condition": condition, "video_path": str(video_path), "result": result})
            continue
        matrix = np.asarray(np.load(matrix_path), dtype=np.float64)
        if matrix.ndim != 2 or matrix.shape[1] != 20484:
            failures.append({"item_id": item_id, "condition": condition, "video_path": str(video_path), "error": f"bad_matrix_shape:{matrix.shape}"})
            continue
        vector = matrix.mean(axis=0)
        vectors.append(vector)
        energy = motion_energy(video_path)
        qc_rows.append({"item_id": item_id, "condition": condition, **energy})
        rows.append(
            {
                "item_id": item_id,
                "condition": condition,
                "video_path": str(video_path),
                "matrix_path": str(matrix_path.resolve()),
                "n_timesteps": int(matrix.shape[0]),
                "n_vertices": int(matrix.shape[1]),
                "vector_l2": float(np.linalg.norm(vector)),
                "source_walker_index": (item.get("labels") or {}).get("walker_index"),
                "scramble_kind": (item.get("labels") or {}).get("scramble_kind"),
                "azimuth_deg": (item.get("labels") or {}).get("azimuth_deg"),
            }
        )

    run_summary = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": utc_now(),
        "manifest": str(args.manifest.resolve()),
        "out_root": str(out_root),
        "tool_id": "tribe_predict",
        "checkpoint_dir": args.checkpoint_dir,
        "checkpoint_name": args.checkpoint_name,
        "device": args.device,
        "positive_conditions": sorted(positive_conditions),
        "negative_conditions": sorted(negative_conditions),
        "n_requested": len(selected),
        "n_success": len(rows),
        "n_failures": len(failures),
        "failures": failures,
    }
    write_json(out_root / "run_summary.json", run_summary)
    write_jsonl(out_root / "embedding_rows.jsonl", rows)

    if failures:
        payload = {
            **run_summary,
            "status": "failed_incomplete_prediction_run",
        }
        write_json(out_root / "biological_motion_dynamic_score.json", payload)
        return payload

    embeddings = np.vstack(vectors)
    np.save(out_root / "embeddings_matrix.npy", embeddings)
    labels = np.asarray([1 if row["condition"] in positive_conditions else 0 for row in rows], dtype=np.int8)
    observed = contrast_score(embeddings, labels)
    null = exact_or_sampled_null(
        embeddings,
        labels,
        observed_score=observed["score"],
        max_exact_combinations=args.max_exact_combinations,
        n_permutations=args.n_permutations,
        seed=args.seed,
    )

    qc_by_condition: dict[str, dict[str, float]] = {}
    for condition in sorted({row["condition"] for row in qc_rows}):
        values = np.asarray(
            [row["mean_abs_frame_difference"] for row in qc_rows if row["condition"] == condition],
            dtype=np.float64,
        )
        qc_by_condition[condition] = {
            "n": int(values.size),
            "mean_abs_frame_difference_mean": float(values.mean()),
            "mean_abs_frame_difference_std": float(values.std(ddof=0)),
        }
    positive_energy = np.mean([row["mean_abs_frame_difference"] for row in qc_rows if row["condition"] in positive_conditions])
    negative_energy = np.mean([row["mean_abs_frame_difference"] for row in qc_rows if row["condition"] in negative_conditions])
    qc_payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": utc_now(),
        "status": "descriptive_motion_energy_qc_no_predeclared_numeric_threshold",
        "by_item": qc_rows,
        "by_condition": qc_by_condition,
        "positive_mean_abs_frame_difference": float(positive_energy),
        "negative_mean_abs_frame_difference": float(negative_energy),
        "positive_minus_negative": float(positive_energy - negative_energy),
        "positive_over_negative": float(positive_energy / negative_energy) if negative_energy else None,
    }
    write_json(out_root / "qc" / "biological_motion_motion_energy_balance.json", qc_payload)

    alpha_pass = null["p_value_plus_one"] < args.alpha
    score_payload = {
        **run_summary,
        "status": "completed",
        "contrast_id": "intact_motion_vs_scrambled_motion_dynamic_redesign",
        "n_positive": int(labels.sum()),
        "n_negative": int(labels.shape[0] - labels.sum()),
        "observed": observed,
        "null": null,
        "alpha": float(args.alpha),
        "motion_energy_qc": {
            "path": str((out_root / "qc" / "biological_motion_motion_energy_balance.json").resolve()),
            "status": qc_payload["status"],
            "positive_over_negative": qc_payload["positive_over_negative"],
        },
        "decision": (
            "recovered_model_tier_candidate_requires_motion_energy_gate"
            if alpha_pass
            else "not_recovered_under_dynamic_redesign"
        ),
        "interpretation_boundary": (
            "TRIBE-predicted response / model-tier evidence only; not observed subject-level fMRI."
        ),
    }
    write_json(out_root / "biological_motion_dynamic_score.json", score_payload)
    return score_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--positive-condition", action="append", default=["intact_biological_motion"])
    parser.add_argument("--negative-condition", action="append", default=["spatial_or_phase_scrambled_motion"])
    parser.add_argument("--checkpoint-dir", default="facebook/tribev2")
    parser.add_argument("--checkpoint-name", default="best.ckpt")
    parser.add_argument("--cache-folder", type=Path, default=None)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--n-permutations", type=int, default=20000)
    parser.add_argument("--max-exact-combinations", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=20260428)
    parser.add_argument("--alpha", type=float, default=0.05)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps({"status": payload["status"], "decision": payload.get("decision"), "out_root": payload["out_root"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
