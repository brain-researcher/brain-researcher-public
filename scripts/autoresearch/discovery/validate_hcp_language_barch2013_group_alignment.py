#!/usr/bin/env python3
"""Preflight and run the TRIBE-vs-Barch-2013 HCP language group-map gate.

This is the cheap intermediate Sec. 5.1 gate from the TRIBE stimulus-discovery
report. It compares a TRIBE-predicted story_audio-minus-math_audio fsaverage5
contrast vector against a published Barch-2013 HCP LANGUAGE group activation
map after both have been projected to the same 20484-vertex fsaverage5 space.

The script is intentionally conservative. If the Barch group map or predeclared
ROI masks are missing, it writes a blocked preflight JSON rather than silently
running a weaker test.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_VERSION = "br.autoresearch.hcp_language_barch2013_group_alignment.v1"
DEFAULT_EXPANDED = Path(
    "/data/brain_researcher/research/discovery/docs/operations/figures/"
    "remote_prediction_inputs_20260428/hcp_language_expanded20_audio_v5"
)
DEFAULT_HELDOUT = Path(
    "/data/brain_researcher/research/discovery/docs/operations/figures/"
    "remote_prediction_inputs_20260428/hcp_language_heldout21_audio_v1"
)
LANGUAGE_ROIS = ("STGa", "STGp", "IFGo", "IFGr", "TGd", "TGv", "PGa", "PGp")
CONTROL_ROIS = ("A1", "V1")


@dataclass(frozen=True)
class PredictionInput:
    name: str
    path: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
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


def parse_named_path(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError(f"expected name=/path, got {value!r}")
    name, raw_path = value.split("=", 1)
    name = name.strip()
    if not name:
        raise ValueError(f"empty name in {value!r}")
    return name, Path(raw_path).expanduser().resolve()


def parse_prediction(value: str) -> PredictionInput:
    name, path = parse_named_path(value)
    return PredictionInput(name=name, path=path)


def load_prediction_contrast(
    prediction: PredictionInput,
    *,
    positive_condition: str,
    negative_condition: str,
) -> dict[str, Any]:
    rows_path = prediction.path / "embedding_rows.jsonl"
    matrix_path = prediction.path / "embeddings_matrix.npy"
    if not rows_path.exists():
        raise FileNotFoundError(f"missing {rows_path}")
    if not matrix_path.exists():
        raise FileNotFoundError(f"missing {matrix_path}")
    rows = read_jsonl(rows_path)
    matrix = np.asarray(np.load(matrix_path), dtype=np.float64)
    if matrix.ndim != 2:
        raise ValueError(f"{matrix_path} must be 2D, got shape={matrix.shape}")
    if len(rows) != matrix.shape[0]:
        raise ValueError(f"row/matrix mismatch for {prediction.name}: {len(rows)} vs {matrix.shape}")
    if matrix.shape[1] != 20484:
        raise ValueError(f"expected fsaverage5 20484-vector predictions, got {matrix.shape[1]}")
    positive = [idx for idx, row in enumerate(rows) if row.get("condition") == positive_condition]
    negative = [idx for idx, row in enumerate(rows) if row.get("condition") == negative_condition]
    if not positive or not negative:
        raise ValueError(
            f"{prediction.name} missing contrast items: "
            f"{positive_condition}={len(positive)}, {negative_condition}={len(negative)}"
        )
    contrast = matrix[positive].mean(axis=0) - matrix[negative].mean(axis=0)
    return {
        "name": prediction.name,
        "path": str(prediction.path),
        "n_rows": len(rows),
        "n_positive": len(positive),
        "n_negative": len(negative),
        "contrast": contrast,
        "contrast_mean": float(contrast.mean()),
        "contrast_std": float(contrast.std(ddof=0)),
        "contrast_l2": float(np.linalg.norm(contrast)),
    }


def load_vector(path: Path) -> np.ndarray:
    suffix = "".join(path.suffixes)
    if suffix.endswith(".npy"):
        vector = np.asarray(np.load(path), dtype=np.float64)
    elif suffix.endswith(".npz"):
        archive = np.load(path)
        if len(archive.files) != 1:
            raise ValueError(f"{path} must contain exactly one vector array, found {archive.files}")
        vector = np.asarray(archive[archive.files[0]], dtype=np.float64)
    elif suffix.endswith(".txt") or suffix.endswith(".csv"):
        vector = np.asarray(np.loadtxt(path, delimiter="," if suffix.endswith(".csv") else None), dtype=np.float64)
    else:
        try:
            import nibabel as nib
        except ImportError as exc:
            raise ValueError(
                f"{path} is not a NumPy/text vector and nibabel is not installed for image loading"
            ) from exc
        vector = np.asarray(nib.load(str(path)).get_fdata(), dtype=np.float64)
    vector = np.ravel(vector)
    if vector.shape[0] != 20484:
        raise ValueError(f"{path} must be a 20484-element fsaverage5 vector, got {vector.shape[0]}")
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{path} contains non-finite values")
    return vector


def load_named_masks(values: list[str] | None) -> dict[str, np.ndarray]:
    masks: dict[str, np.ndarray] = {}
    for value in values or []:
        name, path = parse_named_path(value)
        mask = load_vector(path).astype(bool)
        if int(mask.sum()) == 0:
            raise ValueError(f"mask {name} at {path} is empty")
        masks[name] = mask
    return masks


def pearson(left: np.ndarray, right: np.ndarray) -> float:
    left = np.asarray(left, dtype=np.float64) - float(np.mean(left))
    right = np.asarray(right, dtype=np.float64) - float(np.mean(right))
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denom) if denom else 0.0


def permutation_p(
    predicted: np.ndarray,
    observed: np.ndarray,
    *,
    n_permutations: int,
    seed: int,
) -> tuple[float, dict[str, float]]:
    rng = np.random.default_rng(seed)
    observed_r = pearson(predicted, observed)
    null = np.empty(n_permutations, dtype=np.float64)
    for idx in range(n_permutations):
        null[idx] = pearson(predicted, rng.permutation(observed))
    p_value = float((int(np.sum(null >= observed_r - 1e-12)) + 1) / (n_permutations + 1))
    return p_value, {
        "mean": float(null.mean()),
        "std": float(null.std(ddof=0)),
        "q50": float(np.quantile(null, 0.50)),
        "q95": float(np.quantile(null, 0.95)),
        "q99": float(np.quantile(null, 0.99)),
    }


def missing_required_roi_masks(language_masks: dict[str, np.ndarray], control_masks: dict[str, np.ndarray]) -> list[str]:
    missing = [f"language:{name}" for name in LANGUAGE_ROIS if name not in language_masks]
    missing.extend(f"control:{name}" for name in CONTROL_ROIS if name not in control_masks)
    return missing


def blocked_payload(
    *,
    status: str,
    reason: str,
    prediction_records: list[dict[str, Any]],
    out_path: Path,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": utc_now(),
        "status": status,
        "reason": reason,
        "out": str(out_path),
        "claim_scope": "cheap_intermediate_group_map_gate_not_subject_level_fmri",
        "prediction_side_status": "ready",
        "prediction_records": prediction_records,
        "predeclared_test": {
            "statistic": "Pearson r between TRIBE story_audio-minus-math_audio vector and Barch-2013 story-minus-math group map within HCP-MMP language ROIs",
            "language_rois": list(LANGUAGE_ROIS),
            "control_rois": list(CONTROL_ROIS),
            "null": "vertex-label permutation within the pooled language ROI mask",
            "n_permutations": 20000,
            "pass_criteria": [
                "language ROI pooled correlation r >= 0.20 with plus-one permutation p < 0.05",
                "language-minus-control ROI-class contrast must pass the pre-registered specificity rule",
            ],
        },
        "next_required_input": [
            "Barch-2013 HCP LANGUAGE story-minus-math group activation map projected to 20484-vertex fsaverage5 vector",
            "HCP-MMP fsaverage5 masks for STGa, STGp, IFGo, IFGr, TGd, TGv, PGa, PGp, A1, and V1",
        ],
    }
    if extra:
        payload.update(extra)
    return payload


def run(args: argparse.Namespace) -> dict[str, Any]:
    predictions = [parse_prediction(value) for value in args.prediction]
    prediction_records = [
        load_prediction_contrast(
            prediction,
            positive_condition=args.positive_condition,
            negative_condition=args.negative_condition,
        )
        for prediction in predictions
    ]
    mean_predicted_map = np.mean([record["contrast"] for record in prediction_records], axis=0)
    summary_records: list[dict[str, Any]] = []
    for record in prediction_records:
        summary_records.append({key: value for key, value in record.items() if key != "contrast"})

    out_path = Path(args.out).expanduser().resolve()
    if args.barch_group_map is None:
        payload = blocked_payload(
            status="blocked_missing_barch2013_group_map",
            reason="No Barch-2013 group activation vector was supplied.",
            prediction_records=summary_records,
            out_path=out_path,
            extra={
                "mean_predicted_map_summary": {
                    "n_vertices": int(mean_predicted_map.shape[0]),
                    "mean": float(mean_predicted_map.mean()),
                    "std": float(mean_predicted_map.std(ddof=0)),
                    "l2_norm": float(np.linalg.norm(mean_predicted_map)),
                }
            },
        )
        write_json(out_path, payload)
        return payload

    barch_path = Path(args.barch_group_map).expanduser().resolve()
    if not barch_path.exists():
        payload = blocked_payload(
            status="blocked_missing_barch2013_group_map",
            reason=f"Barch-2013 group activation vector not found: {barch_path}",
            prediction_records=summary_records,
            out_path=out_path,
        )
        write_json(out_path, payload)
        return payload

    language_masks = load_named_masks(args.language_roi_mask)
    control_masks = load_named_masks(args.control_roi_mask)
    missing_masks = missing_required_roi_masks(language_masks, control_masks)
    if missing_masks:
        payload = blocked_payload(
            status="blocked_missing_predeclared_roi_masks",
            reason="The Barch map is present, but the strict Sec. 5.1 ROI-mask set is incomplete.",
            prediction_records=summary_records,
            out_path=out_path,
            extra={"missing_roi_masks": missing_masks, "barch_group_map": str(barch_path)},
        )
        write_json(out_path, payload)
        return payload

    barch = load_vector(barch_path)
    language_mask = np.logical_or.reduce([language_masks[name] for name in LANGUAGE_ROIS])
    control_mask = np.logical_or.reduce([control_masks[name] for name in CONTROL_ROIS])
    language_r = pearson(mean_predicted_map[language_mask], barch[language_mask])
    control_r = pearson(mean_predicted_map[control_mask], barch[control_mask])
    p_value, null_summary = permutation_p(
        mean_predicted_map[language_mask],
        barch[language_mask],
        n_permutations=int(args.n_permutations),
        seed=int(args.seed),
    )
    per_roi = {
        "language": {
            name: pearson(mean_predicted_map[language_masks[name]], barch[language_masks[name]])
            for name in LANGUAGE_ROIS
        },
        "control": {
            name: pearson(mean_predicted_map[control_masks[name]], barch[control_masks[name]])
            for name in CONTROL_ROIS
        },
    }
    # The paired ROI specificity test requires a strict ROI-pairing plan. Until
    # that plan is supplied, the script reports pooled language/control contrast
    # but does not mark the full Sec. 5.1 gate as passed.
    pooled_difference = float(language_r - control_r)
    language_pass = language_r >= float(args.min_language_r) and p_value < float(args.alpha)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": utc_now(),
        "out": str(out_path),
        "status": "roi_specificity_pairing_plan_required" if language_pass else "failed_group_map_alignment_gate",
        "claim_scope": "cheap_intermediate_group_map_gate_not_subject_level_fmri",
        "barch_group_map": str(barch_path),
        "prediction_records": summary_records,
        "mean_predicted_map_summary": {
            "n_vertices": int(mean_predicted_map.shape[0]),
            "mean": float(mean_predicted_map.mean()),
            "std": float(mean_predicted_map.std(ddof=0)),
            "l2_norm": float(np.linalg.norm(mean_predicted_map)),
        },
        "statistics": {
            "pooled_language_r": float(language_r),
            "pooled_control_r": float(control_r),
            "language_minus_control_r": pooled_difference,
            "language_plus_one_permutation_p": p_value,
            "language_null_summary": null_summary,
            "per_roi_r": per_roi,
        },
        "decision": {
            "language_r_threshold": float(args.min_language_r),
            "alpha": float(args.alpha),
            "language_alignment_pass": bool(language_pass),
            "full_gate_pass": False,
            "reason_full_gate_not_passed": "strict paired ROI specificity plan must be supplied before Sec. 5.1 can be confirmatory",
        },
    }
    write_json(out_path, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prediction",
        action="append",
        default=[f"expanded20={DEFAULT_EXPANDED}", f"heldout21={DEFAULT_HELDOUT}"],
        help="Named TRIBE prediction directory as name=/path. Repeat to average folds.",
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--barch-group-map", type=Path, default=None)
    parser.add_argument("--language-roi-mask", action="append", default=None, help="Named mask as ROI=/path/to/fsaverage5_bool.npy")
    parser.add_argument("--control-roi-mask", action="append", default=None, help="Named mask as ROI=/path/to/fsaverage5_bool.npy")
    parser.add_argument("--positive-condition", default="story_audio")
    parser.add_argument("--negative-condition", default="math_audio")
    parser.add_argument("--n-permutations", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=20260428)
    parser.add_argument("--min-language-r", type=float, default=0.20)
    parser.add_argument("--alpha", type=float, default=0.05)
    return parser.parse_args()


def main() -> int:
    try:
        payload = run(parse_args())
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from None
    print(json.dumps({"status": payload["status"], "out": payload["out"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
