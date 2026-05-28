"""ANTs registration helpers with lightweight fallbacks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ANTsRegistrationParameters:
    """Configuration for an antsRegistration invocation."""

    fixed_image: str
    moving_image: str
    output_prefix: str
    transform_type: str
    metric: str
    convergence: str
    shrink_factors: str
    smoothing_sigmas: str
    interpolation: str
    use_histogram_matching: bool
    dimension: int
    float_precision: bool
    verbose: bool
    num_threads: int
    extra_args: Tuple[str, ...]


def ants_registration_from_payload(payload: Dict[str, Any]) -> ANTsRegistrationParameters:
    """Create parameters from payload."""

    extra_args: Sequence[str] = payload.get("extra_args", [])
    if isinstance(extra_args, str):
        extra_args = [extra_args]

    return ANTsRegistrationParameters(
        fixed_image=str(payload["fixed_image"]),
        moving_image=str(payload["moving_image"]),
        output_prefix=str(payload.get("output_prefix", "ants_output")),
        transform_type=str(payload.get("transform_type", "SyN")),
        metric=str(payload.get("metric", "MI")),
        convergence=str(payload.get("convergence", "[1000x500x250x100,1e-6,10]")),
        shrink_factors=str(payload.get("shrink_factors", "8x4x2x1")),
        smoothing_sigmas=str(payload.get("smoothing_sigmas", "3x2x1x0vox")),
        interpolation=str(payload.get("interpolation", "Linear")),
        use_histogram_matching=bool(payload.get("use_histogram_matching", True)),
        dimension=int(payload.get("dimension", 3)),
        float_precision=bool(payload.get("float_precision", False)),
        verbose=bool(payload.get("verbose", True)),
        num_threads=int(payload.get("num_threads", 1)),
        extra_args=tuple(str(arg) for arg in extra_args),
    )


def _build_command(params: ANTsRegistrationParameters) -> list[str]:
    cmd = ["antsRegistration"]
    cmd.extend(["-d", str(params.dimension)])
    cmd.extend(["-o", f"[{params.output_prefix}_,{params.output_prefix}_Warped.nii.gz]"])
    cmd.extend(["-m", f"{params.metric}[{params.fixed_image},{params.moving_image},1,32]"])
    cmd.extend(["-t", f"{params.transform_type}[0.1]"])
    cmd.extend(["-c", params.convergence])
    cmd.extend(["-f", params.shrink_factors])
    cmd.extend(["-s", params.smoothing_sigmas])
    cmd.extend(["-n", params.interpolation])
    if params.use_histogram_matching:
        cmd.extend(["-w", "[0.01,0.99]"])
    if params.float_precision:
        cmd.append("--float")
    if params.verbose:
        cmd.append("-v")
    if params.extra_args:
        cmd.extend(params.extra_args)
    return cmd


def run_ants_registration(params: ANTsRegistrationParameters) -> Dict[str, Any]:
    """Return deterministic placeholder outputs for registration."""

    fixed_path = Path(params.fixed_image)
    moving_path = Path(params.moving_image)
    if not fixed_path.exists():
        raise FileNotFoundError(params.fixed_image)
    if not moving_path.exists():
        raise FileNotFoundError(params.moving_image)

    output_prefix_path = Path(params.output_prefix)
    output_dir = output_prefix_path.parent if output_prefix_path.parent != Path("") else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    warped_image = output_dir / f"{output_prefix_path.name}_Warped.nii.gz"
    inverse_warp = output_dir / f"{output_prefix_path.name}_InverseWarp.nii.gz"
    transform_txt = output_dir / f"{output_prefix_path.name}_0GenericAffine.mat"

    for path in (warped_image, inverse_warp, transform_txt):
        path.write_text("placeholder", encoding="utf-8")

    summary = {
        "fixed_image": str(fixed_path),
        "moving_image": str(moving_path),
        "output_prefix": str(output_prefix_path),
        "transform": params.transform_type,
        "metric": params.metric,
        "iterations": params.convergence,
        "used_ants_binary": False,
    }

    summary_path = output_dir / f"{output_prefix_path.name}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return {
        "outputs": {
            "summary": str(summary_path),
            "warped_image": str(warped_image),
            "inverse_warp": str(inverse_warp),
            "affine_transform": str(transform_txt),
        },
        "summary": summary,
        "command": _build_command(params),
        "message": "ANTs registration completed (fallback).",
    }


__all__ = [
    "ANTsRegistrationParameters",
    "ants_registration_from_payload",
    "run_ants_registration",
]
