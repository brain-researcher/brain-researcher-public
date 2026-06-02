"""Brain simulation helpers with compact fallbacks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np


@dataclass(frozen=True)
class BrainSimulationParameters:
    """Configuration for lightweight brain simulations."""

    model_type: str
    duration: float
    dt: float
    noise_level: float
    connectivity_strength: float
    seed: Optional[int]
    output_dir: str


def brain_simulation_from_payload(payload: Dict[str, Any]) -> BrainSimulationParameters:
    """Construct parameters from payload."""

    return BrainSimulationParameters(
        model_type=str(payload.get("model_type", "neural_mass")),
        duration=float(payload.get("duration", 10.0)),
        dt=float(payload.get("dt", 0.001)),
        noise_level=float(payload.get("noise_level", 0.01)),
        connectivity_strength=float(payload.get("connectivity_strength", 1.0)),
        seed=payload.get("seed"),
        output_dir=str(payload.get("output_dir", Path.cwd() / "brain_simulation")),
    )


def _simulate_activity(params: BrainSimulationParameters) -> Dict[str, np.ndarray]:
    rng = np.random.default_rng(params.seed)
    t = np.arange(0, params.duration, params.dt)

    if params.model_type == "neural_mass":
        activity = np.sin(2 * np.pi * 10 * t) * np.exp(-t / params.duration)
    elif params.model_type == "spiking_network":
        spikes = rng.random(t.shape) < (params.dt * 20)
        activity = np.convolve(spikes, np.exp(-np.linspace(0, 1, 100)), mode="same")
    elif params.model_type == "whole_brain":
        activity = np.sin(2 * np.pi * 0.5 * t) + np.sin(2 * np.pi * 0.8 * t + 1.2)
    else:
        activity = np.sin(2 * np.pi * 5 * t)

    noise = rng.normal(scale=params.noise_level, size=activity.shape)
    activity = activity + noise * params.connectivity_strength
    return {"time": t, "activity": activity}


def run_brain_simulation(params: BrainSimulationParameters) -> Dict[str, Any]:
    """Execute fallback brain simulation."""

    outputs = _simulate_activity(params)
    time = outputs["time"]
    activity = outputs["activity"]

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    time_path = out_dir / "time.npy"
    activity_path = out_dir / "activity.npy"
    np.save(time_path, time)
    np.save(activity_path, activity)

    summary = {
        "model_type": params.model_type,
        "duration": params.duration,
        "dt": params.dt,
        "noise_level": params.noise_level,
        "connectivity_strength": params.connectivity_strength,
        "mean_activity": float(np.mean(activity)),
        "std_activity": float(np.std(activity)),
        "peak_frequency": float(
            np.abs(np.fft.rfft(activity)).argmax() / params.duration
        ),
        "used_full_backend": False,
    }

    summary_path = out_dir / "simulation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return {
        "outputs": {
            "time": str(time_path),
            "activity": str(activity_path),
            "summary": str(summary_path),
        },
        "summary": summary,
        "message": "Brain simulation completed (fallback).",
    }


__all__ = [
    "BrainSimulationParameters",
    "brain_simulation_from_payload",
    "run_brain_simulation",
]
