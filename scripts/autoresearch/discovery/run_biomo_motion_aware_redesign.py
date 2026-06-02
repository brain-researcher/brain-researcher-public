#!/usr/bin/env python3
"""Score biological-motion redesign with motion-aware video features.

This is a cheap follow-up to the TRIBE biological-motion branch. It does not
run TRIBE or claim neural validation. It asks whether the already materialized
dynamic point-light videos contain an explicit motion-aware representation that
separates intact biological motion from spatial/phase-scrambled controls.

Inputs:
  - biological_motion_dynamic_all_walkers_manifest.json
  - the 18 rendered videos referenced by that manifest

Outputs:
  - per_item_motion_features.csv
  - motion_aware_feature_matrix.npy
  - biological_motion_motion_aware_score.json
  - biological_motion_motion_aware_scorecard.png/pdf
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-cache")

import cv2
import matplotlib.pyplot as plt
import numpy as np


DEFAULT_MANIFEST = Path(
    "docs/archive/operations/biological_motion_redesign_20260428/"
    "biological_motion_dynamic_all_walkers_manifest.json"
)
DEFAULT_OUTPUT_ROOT = Path(
    "docs/archive/operations/biological_motion_redesign_20260428/"
    "motion_aware_representation"
)
FLOW_MEAN_HIST_RANGE = (0.0, 4.0)
PROJECT_RELATIVE_ANCHOR = Path(
    "docs/archive/operations/biological_motion_redesign_20260428"
)
LEGACY_PROJECT_RELATIVE_ANCHOR = Path("docs/operations/biological_motion_redesign_20260428")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def resolve_manifest_video_path(raw_path: str, manifest_path: Path) -> Path:
    """Resolve manifests with historical absolute paths in a new checkout."""
    candidate = Path(raw_path)
    if candidate.exists():
        return candidate
    if not candidate.is_absolute():
        relative_candidate = (manifest_path.parent / candidate).resolve()
        if relative_candidate.exists():
            return relative_candidate
        return candidate

    parts = candidate.parts
    for anchor in (PROJECT_RELATIVE_ANCHOR, LEGACY_PROJECT_RELATIVE_ANCHOR):
        anchor_parts = anchor.parts
        for idx in range(0, len(parts) - len(anchor_parts) + 1):
            if parts[idx : idx + len(anchor_parts)] == anchor_parts:
                suffix = Path(*parts[idx + len(anchor_parts) :])
                relocated = (manifest_path.parent / suffix).resolve()
                if relocated.exists():
                    return relocated
    return candidate


def safe_float(value: float) -> float:
    if math.isfinite(value):
        return float(value)
    return 0.0


def summarize(values: list[float], prefix: str) -> dict[str, float]:
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return {
            f"{prefix}_mean": 0.0,
            f"{prefix}_std": 0.0,
            f"{prefix}_p10": 0.0,
            f"{prefix}_p50": 0.0,
            f"{prefix}_p90": 0.0,
            f"{prefix}_max": 0.0,
        }
    return {
        f"{prefix}_mean": safe_float(float(arr.mean())),
        f"{prefix}_std": safe_float(float(arr.std())),
        f"{prefix}_p10": safe_float(float(np.percentile(arr, 10))),
        f"{prefix}_p50": safe_float(float(np.percentile(arr, 50))),
        f"{prefix}_p90": safe_float(float(np.percentile(arr, 90))),
        f"{prefix}_max": safe_float(float(arr.max())),
    }


def normalized_hist(values: list[float], *, bins: int, value_range: tuple[float, float], prefix: str) -> dict[str, float]:
    if not values:
        return {f"{prefix}_{idx:02d}": 0.0 for idx in range(bins)}
    hist, _ = np.histogram(np.asarray(values, dtype=np.float64), bins=bins, range=value_range)
    denom = float(hist.sum())
    if denom <= 0.0:
        return {f"{prefix}_{idx:02d}": 0.0 for idx in range(bins)}
    return {f"{prefix}_{idx:02d}": safe_float(float(hist[idx] / denom)) for idx in range(bins)}


def fft_peak_ratio(values: list[float]) -> float:
    arr = np.asarray(values, dtype=np.float64)
    if arr.size < 8 or float(arr.std()) <= 1e-12:
        return 0.0
    arr = arr - arr.mean()
    spectrum = np.abs(np.fft.rfft(arr))
    if spectrum.size <= 2:
        return 0.0
    spectrum[0] = 0.0
    total = float(spectrum.sum())
    if total <= 0.0:
        return 0.0
    return safe_float(float(spectrum.max() / total))


def load_grayscale_frames(video_path: Path, *, resize: int) -> list[np.ndarray]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    frames: list[np.ndarray] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if resize > 0:
            gray = cv2.resize(gray, (resize, resize), interpolation=cv2.INTER_AREA)
        frames.append(gray.astype(np.uint8))
    capture.release()
    if len(frames) < 2:
        raise RuntimeError(f"Need at least 2 frames in {video_path}, got {len(frames)}")
    return frames


def extract_motion_features(video_path: Path, *, resize: int) -> dict[str, float]:
    frames = load_grayscale_frames(video_path, resize=resize)

    active_area: list[float] = []
    centroid_x: list[float] = []
    centroid_y: list[float] = []
    spread_x: list[float] = []
    spread_y: list[float] = []
    bbox_area: list[float] = []
    aspect: list[float] = []

    for frame in frames:
        mask = frame > 16
        coords = np.column_stack(np.nonzero(mask))
        active_area.append(float(mask.mean()))
        if coords.size == 0:
            centroid_y.append(0.0)
            centroid_x.append(0.0)
            spread_y.append(0.0)
            spread_x.append(0.0)
            bbox_area.append(0.0)
            aspect.append(0.0)
            continue
        y = coords[:, 0].astype(np.float64)
        x = coords[:, 1].astype(np.float64)
        centroid_y.append(float(y.mean() / max(frame.shape[0] - 1, 1)))
        centroid_x.append(float(x.mean() / max(frame.shape[1] - 1, 1)))
        spread_y.append(float(y.std() / max(frame.shape[0] - 1, 1)))
        spread_x.append(float(x.std() / max(frame.shape[1] - 1, 1)))
        height = float(y.max() - y.min() + 1.0) / max(frame.shape[0], 1)
        width = float(x.max() - x.min() + 1.0) / max(frame.shape[1], 1)
        bbox_area.append(width * height)
        aspect.append(width / max(height, 1e-9))

    flow_mean: list[float] = []
    flow_std: list[float] = []
    flow_p90: list[float] = []
    flow_max: list[float] = []
    flow_angles: list[float] = []
    flow_magnitudes_for_angles: list[float] = []
    frame_diff: list[float] = []
    centroid_speed: list[float] = []

    prev_centroid = np.array([centroid_x[0], centroid_y[0]], dtype=np.float64)
    for prev, curr, cx, cy in zip(frames[:-1], frames[1:], centroid_x[1:], centroid_y[1:], strict=False):
        flow = cv2.calcOpticalFlowFarneback(
            prev,
            curr,
            None,
            pyr_scale=0.5,
            levels=3,
            winsize=15,
            iterations=3,
            poly_n=5,
            poly_sigma=1.2,
            flags=0,
        )
        mag, ang = cv2.cartToPolar(flow[..., 0], flow[..., 1], angleInDegrees=False)
        motion_mask = (prev > 16) | (curr > 16) | (cv2.absdiff(prev, curr) > 8)
        selected_mag = mag[motion_mask]
        selected_ang = ang[motion_mask]
        if selected_mag.size == 0:
            selected_mag = mag.reshape(-1)
            selected_ang = ang.reshape(-1)
        flow_mean.append(float(selected_mag.mean()))
        flow_std.append(float(selected_mag.std()))
        flow_p90.append(float(np.percentile(selected_mag, 90)))
        flow_max.append(float(selected_mag.max()))
        keep = selected_mag > np.percentile(selected_mag, 75)
        if np.any(keep):
            flow_angles.extend(selected_ang[keep].astype(float).tolist())
            flow_magnitudes_for_angles.extend(selected_mag[keep].astype(float).tolist())
        frame_diff.append(float(cv2.absdiff(prev, curr).mean() / 255.0))
        centroid = np.array([cx, cy], dtype=np.float64)
        centroid_speed.append(float(np.linalg.norm(centroid - prev_centroid)))
        prev_centroid = centroid

    features: dict[str, float] = {
        "n_frames": float(len(frames)),
        "resize": float(resize),
        "centroid_path_length": float(np.sum(centroid_speed)),
        "centroid_x_fft_peak_ratio": fft_peak_ratio(centroid_x),
        "centroid_y_fft_peak_ratio": fft_peak_ratio(centroid_y),
        "flow_mean_fft_peak_ratio": fft_peak_ratio(flow_mean),
        "frame_diff_fft_peak_ratio": fft_peak_ratio(frame_diff),
    }
    features.update(summarize(active_area, "active_area"))
    features.update(summarize(centroid_x, "centroid_x"))
    features.update(summarize(centroid_y, "centroid_y"))
    features.update(summarize(spread_x, "spread_x"))
    features.update(summarize(spread_y, "spread_y"))
    features.update(summarize(bbox_area, "bbox_area"))
    features.update(summarize(aspect, "aspect"))
    features.update(summarize(flow_mean, "flow_mean"))
    features.update(summarize(flow_std, "flow_std"))
    features.update(summarize(flow_p90, "flow_p90"))
    features.update(summarize(flow_max, "flow_max"))
    features.update(summarize(frame_diff, "frame_diff"))
    features.update(summarize(centroid_speed, "centroid_speed"))

    if flow_angles and flow_magnitudes_for_angles:
        hist, _ = np.histogram(
            np.asarray(flow_angles, dtype=np.float64),
            bins=12,
            range=(0.0, 2.0 * math.pi),
            weights=np.asarray(flow_magnitudes_for_angles, dtype=np.float64),
        )
        denom = float(hist.sum())
        for idx in range(12):
            features[f"flow_angle_hist_{idx:02d}"] = safe_float(float(hist[idx] / denom)) if denom > 0 else 0.0
    else:
        features.update({f"flow_angle_hist_{idx:02d}": 0.0 for idx in range(12)})
    # Fixed bins keep the feature dimensions comparable across videos.
    features.update(normalized_hist(flow_mean, bins=8, value_range=FLOW_MEAN_HIST_RANGE, prefix="flow_mean_hist"))
    return features


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def branch_score(matrix: np.ndarray, positive: list[int], negative: list[int]) -> dict[str, float]:
    pos = matrix[positive]
    neg = matrix[negative]
    pos_centroid = pos.mean(axis=0)
    neg_centroid = neg.mean(axis=0)
    diff = pos_centroid - neg_centroid
    diff_norm = float(np.linalg.norm(diff))
    cosine_gap = float(1.0 - cosine(pos_centroid, neg_centroid))
    projection_axis = diff / diff_norm if diff_norm > 0 else diff
    pos_proj = float(np.dot(pos, projection_axis).mean()) if diff_norm > 0 else 0.0
    neg_proj = float(np.dot(neg, projection_axis).mean()) if diff_norm > 0 else 0.0
    return {
        "diff_norm": diff_norm,
        "cosine_gap": cosine_gap,
        "projection_gap": float(pos_proj - neg_proj),
        "score": float(diff_norm * max(cosine_gap, 1e-6)),
    }


def zscore_matrix(raw: np.ndarray) -> tuple[np.ndarray, dict[str, int]]:
    means = raw.mean(axis=0)
    stds = raw.std(axis=0)
    keep = stds > 1e-12
    z = (raw[:, keep] - means[keep]) / stds[keep]
    return z.astype(np.float64), {
        "n_raw_features": int(raw.shape[1]),
        "n_retained_features": int(z.shape[1]),
        "n_removed_zero_variance": int(raw.shape[1] - z.shape[1]),
    }


def global_label_null(matrix: np.ndarray, n_positive: int, observed_score: float) -> dict[str, Any]:
    n_items = matrix.shape[0]
    scores: list[float] = []
    indices = range(n_items)
    for positive_tuple in itertools.combinations(indices, n_positive):
        positive = list(positive_tuple)
        positive_set = set(positive)
        negative = [idx for idx in indices if idx not in positive_set]
        scores.append(branch_score(matrix, positive, negative)["score"])
    arr = np.asarray(scores, dtype=np.float64)
    ge = int(np.sum(arr >= observed_score - 1e-15))
    return {
        "null_type": "global_exact_label_enumeration",
        "n_assignments": int(arr.size),
        "n_ge_observed": ge,
        "exact_upper_tail_p": float(ge / arr.size),
        "plus_one_p": float((ge + 1) / (arr.size + 1)),
        "null_mean": float(arr.mean()),
        "null_std": float(arr.std()),
        "null_q95": float(np.quantile(arr, 0.95)),
        "null_q99": float(np.quantile(arr, 0.99)),
    }


def walker_block_null(matrix: np.ndarray, rows: list[dict[str, Any]], observed_score: float) -> dict[str, Any]:
    by_walker: dict[int, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        by_walker[int(row["walker_index"])].append(idx)
    blocks = [sorted(v) for _, v in sorted(by_walker.items())]
    scores: list[float] = []
    for block_choices in itertools.product(*(itertools.combinations(block, 2) for block in blocks)):
        positive = [idx for combo in block_choices for idx in combo]
        positive_set = set(positive)
        negative = [idx for block in blocks for idx in block if idx not in positive_set]
        scores.append(branch_score(matrix, positive, negative)["score"])
    arr = np.asarray(scores, dtype=np.float64)
    ge = int(np.sum(arr >= observed_score - 1e-15))
    return {
        "null_type": "walker_block_exact_label_enumeration",
        "n_assignments": int(arr.size),
        "n_ge_observed": ge,
        "exact_upper_tail_p": float(ge / arr.size),
        "plus_one_p": float((ge + 1) / (arr.size + 1)),
        "null_mean": float(arr.mean()),
        "null_std": float(arr.std()),
        "null_q95": float(np.quantile(arr, 0.95)),
        "null_q99": float(np.quantile(arr, 0.99)),
    }


def plot_scorecard(output_path: Path, summary: dict[str, Any]) -> None:
    labels = ["motion-aware", "TRIBE-video"]
    scores = [
        float(summary["observed"]["score"]),
        float(summary["comparison_to_previous"]["tribe_video_score"]),
    ]
    p_values = [
        float(summary["global_null"]["plus_one_p"]),
        float(summary["comparison_to_previous"]["tribe_video_plus_one_p"]),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.0), constrained_layout=True)
    colors = ["#4C78A8", "#9AA3B2"]
    axes[0].bar(labels, scores, color=colors, width=0.55)
    axes[0].set_ylabel("contrast score")
    axes[0].set_title("Branch score")
    axes[0].tick_params(axis="x", rotation=15)
    axes[1].bar(labels, p_values, color=colors, width=0.55)
    axes[1].axhline(0.05, color="#C44E52", linestyle="--", linewidth=1)
    axes[1].set_ylim(0.0, max(1.0, max(p_values) * 1.1))
    axes[1].set_ylabel("plus-one p")
    axes[1].set_title("Exact label null")
    axes[1].tick_params(axis="x", rotation=15)
    fig.suptitle("Biological-motion redesign: explicit motion features")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path.with_suffix(".png"), dpi=240)
    fig.savefig(output_path.with_suffix(".pdf"))
    plt.close(fig)


def run(manifest_path: Path, output_root: Path, *, resize: int) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    rows: list[dict[str, Any]] = []
    feature_dicts: list[dict[str, float]] = []
    for item in manifest["items"]:
        condition = str(item["condition"])
        if condition not in {"intact_biological_motion", "spatial_or_phase_scrambled_motion"}:
            continue
        labels = item.get("labels", {})
        video_path = resolve_manifest_video_path(str(item["tribe_args"]["video_path"]), manifest_path)
        features = extract_motion_features(video_path, resize=resize)
        row = {
            "item_id": str(item["item_id"]),
            "condition": condition,
            "video_path": str(video_path.resolve()),
            "walker_index": int(labels.get("walker_index", -1)),
            "scramble_kind": str(labels.get("scramble_kind", "unknown")),
            "azimuth_deg": int(labels.get("azimuth_deg", 0)),
        }
        rows.append(row)
        feature_dicts.append(features)

    feature_names = sorted(feature_dicts[0])
    raw_matrix = np.asarray([[features[name] for name in feature_names] for features in feature_dicts], dtype=np.float64)
    matrix, matrix_qc = zscore_matrix(raw_matrix)
    positive = [idx for idx, row in enumerate(rows) if row["condition"] == "intact_biological_motion"]
    negative = [idx for idx, row in enumerate(rows) if row["condition"] == "spatial_or_phase_scrambled_motion"]
    observed = branch_score(matrix, positive, negative)
    global_null = global_label_null(matrix, len(positive), observed["score"])
    block_null = walker_block_null(matrix, rows, observed["score"])

    output_root.mkdir(parents=True, exist_ok=True)
    np.save(output_root / "motion_aware_feature_matrix.npy", matrix)
    with (output_root / "per_item_motion_features.csv").open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(rows[0]) + feature_names
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row, features in zip(rows, feature_dicts, strict=True):
            writer.writerow({**row, **features})

    previous = {
        "tribe_video_score": 0.0013014522788429407,
        "tribe_video_diff_norm": 1.1384312719291019,
        "tribe_video_cosine_gap": 0.0011431979346786525,
        "tribe_video_exact_p": 0.14753568542957177,
        "tribe_video_plus_one_p": (2740 + 1) / (18564 + 1),
    }
    if block_null["plus_one_p"] <= 0.05 and global_null["plus_one_p"] > 0.05:
        decision = "candidate_under_walker_block_null_only"
        interpretation = (
            "Motion-aware features recover a design-blocked candidate signal, "
            "but the unblocked global label null remains marginal. Treat as a "
            "stimulus-representation recovery candidate, not as a confirmed branch."
        )
    elif global_null["plus_one_p"] <= 0.05:
        decision = "recovered_under_motion_aware_features"
        interpretation = (
            "Motion-aware features recover the intact-vs-scrambled contrast under "
            "the global exact label null."
        )
    else:
        decision = "not_recovered_under_motion_aware_features"
        interpretation = (
            "Motion-aware features do not recover the intact-vs-scrambled contrast "
            "under either exact null."
        )

    summary = {
        "created_at_utc": utc_now(),
        "manifest_path": str(manifest_path.resolve()),
        "output_root": str(output_root.resolve()),
        "representation": "motion_aware_video_features",
        "feature_extractor": "OpenCV Farneback optical flow + frame-difference + point-cloud shape/trajectory summaries",
        "resize": resize,
        "n_items": len(rows),
        "n_positive": len(positive),
        "n_negative": len(negative),
        "positive_condition": "intact_biological_motion",
        "negative_condition": "spatial_or_phase_scrambled_motion",
        "feature_names": feature_names,
        "matrix_qc": matrix_qc,
        "observed": observed,
        "global_null": global_null,
        "walker_block_null": block_null,
        "comparison_to_previous": previous,
        "decision": decision,
        "interpretation": interpretation,
        "claim_boundary": (
            "This is an explicit stimulus-motion representation test over rendered videos, "
            "not a TRIBE predicted-response result and not observed fMRI validation."
        ),
    }
    write_json(output_root / "biological_motion_motion_aware_score.json", summary)
    plot_scorecard(output_root / "biological_motion_motion_aware_scorecard", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--resize", type=int, default=128)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run(
        args.manifest_path.expanduser().resolve(),
        args.output_root.expanduser().resolve(),
        resize=int(args.resize),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
