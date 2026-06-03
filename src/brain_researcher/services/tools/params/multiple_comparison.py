"""Multiple-comparison correction helpers used across execution layers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np


def _as_array(values: Optional[Any]) -> Optional[np.ndarray]:
    if values is None:
        return None
    array = np.asarray(values, dtype=float)
    if array.ndim == 0:
        array = array.reshape((1,))
    return array


@dataclass(frozen=True)
class MultipleComparisonParameters:
    """Configuration for lightweight multiple-comparison correction."""

    p_values_file: Optional[str] = None
    p_values_array: Optional[Any] = None
    statistic_file: Optional[str] = None
    method: str = "fdr_bh"
    alpha: float = 0.05
    fdr_method: str = "indep"
    two_stage: bool = False
    mask_file: Optional[str] = None
    smoothness: Optional[float] = None
    cluster_threshold: Optional[float] = None
    connectivity: str = "faces"
    min_cluster_size: int = 1
    tfce_e: float = 0.5
    tfce_h: float = 2.0
    output_dir: str = str(Path.cwd() / "multiple_comparison")
    save_corrected: bool = True
    save_mask: bool = True
    save_report: bool = True
    return_arrays: bool = False
    verbose: bool = True


def multiple_comparison_from_payload(payload: Dict[str, Any]) -> MultipleComparisonParameters:
    return MultipleComparisonParameters(
        p_values_file=payload.get("p_values_file"),
        p_values_array=_as_array(payload.get("p_values_array")),
        statistic_file=payload.get("statistic_file"),
        method=str(payload.get("method", "fdr_bh")),
        alpha=float(payload.get("alpha", 0.05)),
        fdr_method=str(payload.get("fdr_method", "indep")),
        two_stage=bool(payload.get("two_stage", False)),
        mask_file=payload.get("mask_file"),
        smoothness=payload.get("smoothness"),
        cluster_threshold=payload.get("cluster_threshold"),
        connectivity=str(payload.get("connectivity", "faces")),
        min_cluster_size=int(payload.get("min_cluster_size", 1)),
        tfce_e=float(payload.get("tfce_e", 0.5)),
        tfce_h=float(payload.get("tfce_h", 2.0)),
        output_dir=str(payload["output_dir"]) if payload.get("output_dir") else str(Path.cwd() / "multiple_comparison"),
        save_corrected=bool(payload.get("save_corrected", True)),
        save_mask=bool(payload.get("save_mask", True)),
        save_report=bool(payload.get("save_report", True)),
        return_arrays=bool(payload.get("return_arrays", False)),
        verbose=bool(payload.get("verbose", True)),
    )


def _load_p_values(params: MultipleComparisonParameters) -> np.ndarray:
    if params.p_values_array is not None:
        return np.asarray(params.p_values_array, dtype=float)

    if params.p_values_file:
        path = Path(params.p_values_file)
        if not path.exists():
            raise FileNotFoundError(params.p_values_file)
        if path.suffix in {".npy", ".npz"}:
            data = np.load(path)
            if isinstance(data, np.lib.npyio.NpzFile):
                first_key = data.files[0]
                data = data[first_key]
            return np.asarray(data, dtype=float)
        return np.loadtxt(path)

    raise ValueError("Multiple-comparison correction requires 'p_values_file' or 'p_values_array'.")


def _apply_method(p_values: np.ndarray, method: str, alpha: float) -> Tuple[np.ndarray, np.ndarray]:
    flat = p_values.ravel()
    n_tests = len(flat)
    method_key = method.lower()

    if method_key in {"fwe_bonferroni", "bonferroni"}:
        corrected = np.minimum(flat * n_tests, 1.0)
    elif method_key in {"fdr_by"}:
        weights = np.sum(1.0 / np.arange(1, n_tests + 1))
        corrected = np.minimum(flat * n_tests * weights, 1.0)
    else:
        order = np.argsort(flat)
        ranks = np.arange(1, n_tests + 1, dtype=float)
        adjusted = np.empty_like(flat, dtype=float)
        adjusted[order] = flat[order] * n_tests / ranks
        adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
        corrected = np.clip(adjusted, 0.0, 1.0)

    corrected = corrected.reshape(p_values.shape)
    mask = (corrected <= alpha).astype(np.uint8)
    return corrected, mask


def _summarise(values: np.ndarray) -> Dict[str, float]:
    return {
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
    }


def run_multiple_comparison(params: MultipleComparisonParameters) -> Dict[str, Any]:
    p_values = _load_p_values(params)
    corrected_p, mask = _apply_method(p_values, params.method, params.alpha)

    output_dir = Path(params.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs: Dict[str, Optional[str]] = {
        "summary": None,
        "corrected_p_values": None,
        "significance_mask": None,
    }

    if params.save_corrected:
        corrected_path = output_dir / "multiple_comparison_corrected.npy"
        np.save(corrected_path, corrected_p)
        outputs["corrected_p_values"] = str(corrected_path)

    if params.save_mask:
        mask_path = output_dir / "multiple_comparison_mask.npy"
        np.save(mask_path, mask)
        outputs["significance_mask"] = str(mask_path)

    summary = {
        "method": params.method,
        "alpha": float(params.alpha),
        "n_tests": int(p_values.size),
        "p_values": _summarise(p_values),
        "corrected_p_values": _summarise(corrected_p),
        "significant_voxels": int(np.count_nonzero(mask)),
        "used_full_backend": False,
    }

    summary_path = output_dir / "multiple_comparison_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    outputs["summary"] = str(summary_path)

    result: Dict[str, Any] = {
        "outputs": outputs,
        "summary": summary,
        "message": "Multiple comparison correction completed (fallback).",
    }

    if params.return_arrays:
        result["corrected_p_values"] = corrected_p
        result["significance_mask"] = mask

    return result


__all__ = [
    "MultipleComparisonParameters",
    "multiple_comparison_from_payload",
    "run_multiple_comparison",
]
