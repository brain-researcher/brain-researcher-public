"""General registration helpers with deterministic fallbacks."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RegistrationParameters:
    """Minimal configuration for image registration."""

    moving_image: str
    fixed_image: str
    output_dir: str
    registration_type: str
    transform_type: str
    metric: str
    iterations: tuple[int, ...]
    shrink_factors: tuple[int, ...]
    smoothing_sigmas: tuple[float, ...]
    interpolation: str
    save_transform: bool
    save_warped: bool
    save_inverse: bool
    save_field: bool
    compute_similarity: bool
    seed: int | None


def _coerce_sequence(
    values: Sequence[Any] | None, default: Sequence[Any]
) -> tuple[Any, ...]:
    if not values:
        values = default
    return tuple(values)


def registration_from_payload(payload: dict[str, Any]) -> RegistrationParameters:
    """Construct parameters from JSON-like payload."""

    return RegistrationParameters(
        moving_image=str(payload["moving_image"]),
        fixed_image=str(payload["fixed_image"]),
        output_dir=str(payload.get("output_dir", Path.cwd() / "registration")),
        registration_type=str(payload.get("registration_type", "affine")),
        transform_type=str(payload.get("transform_type", "Affine")),
        metric=str(payload.get("metric", "MI")),
        iterations=_coerce_sequence(payload.get("iterations"), [100, 100, 50]),
        shrink_factors=_coerce_sequence(payload.get("shrink_factors"), [4, 2, 1]),
        smoothing_sigmas=_coerce_sequence(
            payload.get("smoothing_sigmas"), [2.0, 1.0, 0.0]
        ),
        interpolation=str(payload.get("interpolation", "Linear")),
        save_transform=bool(payload.get("save_transform", True)),
        save_warped=bool(payload.get("save_warped", True)),
        save_inverse=bool(payload.get("save_inverse", True)),
        save_field=bool(payload.get("save_field", False)),
        compute_similarity=bool(payload.get("compute_similarity", True)),
        seed=payload.get("seed"),
    )


def run_registration(params: RegistrationParameters) -> dict[str, Any]:
    """
    Execute registration with placeholders.

    This fallback simply validates inputs, writes informational summaries, and
    produces placeholder outputs so downstream tooling can operate without
    heavyweight dependencies.
    """

    moving_path = Path(params.moving_image)
    fixed_path = Path(params.fixed_image)
    if not moving_path.exists():
        raise FileNotFoundError(params.moving_image)
    if not fixed_path.exists():
        raise FileNotFoundError(params.fixed_image)

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, str | None] = {
        "summary": None,
        "transform": None,
        "warped_image": None,
        "inverse_transform": None,
        "deformation_field": None,
    }

    transform_path = out_dir / "registration_transform.txt"
    if params.save_transform:
        transform_path.write_text("placeholder transform", encoding="utf-8")
        outputs["transform"] = str(transform_path)

    warped_path = out_dir / "warped_image.nii.gz"
    if params.save_warped:
        warped_path.write_text("placeholder warped image", encoding="utf-8")
        outputs["warped_image"] = str(warped_path)

    inverse_path = out_dir / "inverse_transform.txt"
    if params.save_inverse:
        inverse_path.write_text("placeholder inverse", encoding="utf-8")
        outputs["inverse_transform"] = str(inverse_path)

    field_path = out_dir / "deformation_field.nii.gz"
    if params.save_field:
        field_path.write_text("placeholder deformation field", encoding="utf-8")
        outputs["deformation_field"] = str(field_path)

    summary = {
        "moving_image": str(moving_path),
        "fixed_image": str(fixed_path),
        "registration_type": params.registration_type,
        "transform_type": params.transform_type,
        "metric": params.metric,
        "iterations": list(params.iterations),
        "shrink_factors": list(params.shrink_factors),
        "smoothing_sigmas": list(params.smoothing_sigmas),
        "interpolation": params.interpolation,
        "compute_similarity": params.compute_similarity,
        "used_full_backend": False,
    }

    summary_path = out_dir / "registration_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    outputs["summary"] = str(summary_path)

    return {
        "outputs": outputs,
        "summary": summary,
        "message": "Registration completed (fallback).",
    }


__all__ = [
    "RegistrationParameters",
    "registration_from_payload",
    "run_registration",
]
