"""Advanced visualization helpers with lightweight fallbacks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np


@dataclass(frozen=True)
class AdvancedVisualizationParameters:
    """Minimal parameters describing a visualization request."""

    data_file: str
    output_dir: str
    data_type: str
    plot_type: str
    figure_format: str
    interactive_backend: str
    glass_display_mode: Optional[str]
    seed: Optional[int]


def advanced_visualization_from_payload(
    payload: Dict[str, Any],
) -> AdvancedVisualizationParameters:
    """Create parameters from payload dict."""

    return AdvancedVisualizationParameters(
        data_file=str(payload["data_file"]),
        output_dir=str(payload.get("output_dir", Path.cwd() / "visualizations")),
        data_type=str(payload.get("data_type", "auto")),
        plot_type=str(payload.get("plot_type", "auto")),
        figure_format=str(payload.get("figure_format", "png")),
        interactive_backend=str(payload.get("interactive_backend", "plotly")),
        glass_display_mode=payload.get("glass_display_mode"),
        seed=payload.get("seed"),
    )


def _load_array(path: Path) -> np.ndarray:
    if path.suffix == ".npy":
        return np.load(path)
    if path.suffix == ".npz":
        data = np.load(path)
        return data[data.files[0]]
    # For other formats, return placeholder array using file size as heuristic
    return np.asarray([[path.stat().st_size]])


def run_advanced_visualization(
    params: AdvancedVisualizationParameters,
) -> Dict[str, Any]:
    """Generate placeholder visualization artefacts and summary metadata."""

    data_path = Path(params.data_file)
    if not data_path.exists():
        raise FileNotFoundError(params.data_file)

    output_dir = Path(params.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(params.seed)

    try:
        data_array = _load_array(data_path)
        summary_stats = {
            "shape": list(data_array.shape),
            "dtype": str(data_array.dtype),
            "mean": float(np.mean(data_array)),
            "std": float(np.std(data_array)),
        }
    except Exception:
        summary_stats = {
            "shape": [],
            "dtype": "unknown",
            "mean": None,
            "std": None,
        }

    ext = params.figure_format.lower()
    if ext not in {"png", "jpg", "jpeg", "svg", "html"}:
        ext = "png"

    viz_path = output_dir / f"visualization.{ext}"
    if ext == "html":
        viz_path.write_text(
            "<html><body><h1>Visualization Placeholder</h1></body></html>",
            encoding="utf-8",
        )
    else:
        # Write a small binary placeholder to mimic an image file.
        payload = f"Visualization placeholder for {params.plot_type}".encode("utf-8")
        viz_path.write_bytes(payload)

    metadata_path = output_dir / "visualization_summary.json"
    summary = {
        "data_type": params.data_type,
        "plot_type": params.plot_type,
        "figure_format": ext,
        "interactive_backend": params.interactive_backend,
        "glass_display_mode": params.glass_display_mode,
        "summary_stats": summary_stats,
        "sample_preview": float(rng.random()),
        "used_full_backend": False,
    }
    metadata_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return {
        "outputs": {
            "visualization": str(viz_path),
            "summary": str(metadata_path),
        },
        "summary": summary,
        "message": "Visualization generated (fallback).",
    }


__all__ = [
    "AdvancedVisualizationParameters",
    "advanced_visualization_from_payload",
    "run_advanced_visualization",
]
