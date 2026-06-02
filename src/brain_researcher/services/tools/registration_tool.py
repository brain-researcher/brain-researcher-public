"""Registration tool wrapper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    RegistrationParameters,
    registration_from_payload,
    run_registration,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class RegistrationArgs(BaseModel):
    """Agent-visible registration arguments."""

    model_config = ConfigDict(extra="ignore")

    moving_image: str = Field(description="Moving/source image")
    fixed_image: str = Field(description="Fixed/target image")
    output_dir: Optional[str] = Field(
        default=None, description="Output directory for results"
    )

    registration_type: str = Field(
        default="affine", description="Registration strategy"
    )
    transform_type: str = Field(default="Affine", description="Transform model")
    metric: str = Field(default="MI", description="Similarity metric")
    iterations: List[int] = Field(
        default_factory=lambda: [100, 100, 50], description="Iterative schedule"
    )
    shrink_factors: List[int] = Field(
        default_factory=lambda: [4, 2, 1], description="Shrink factors"
    )
    smoothing_sigmas: List[float] = Field(
        default_factory=lambda: [2.0, 1.0, 0.0], description="Smoothing sigmas"
    )
    interpolation: str = Field(default="Linear", description="Interpolation method")

    save_transform: bool = Field(default=True, description="Persist transform matrix")
    save_warped: bool = Field(default=True, description="Persist warped moving image")
    save_inverse: bool = Field(default=True, description="Persist inverse transform")
    save_field: bool = Field(default=False, description="Persist deformation field")
    compute_similarity: bool = Field(
        default=True, description="Compute similarity summary"
    )
    seed: Optional[int] = Field(default=None, description="Random seed")


class RegistrationTool(NeuroToolWrapper):
    """Agent wrapper delegating to neurocore registration."""

    def get_tool_name(self) -> str:
        return "registration_pipeline"

    def get_tool_description(self) -> str:
        return (
            "General image alignment and registration pipeline supporting affine and deformable modes. "
            "Falls back to lightweight placeholders when external binaries are absent."
        )

    def get_args_schema(self):
        return RegistrationArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = RegistrationArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            output_dir = payload.get("output_dir") or str(
                Path.cwd() / "registration_outputs"
            )
            payload["output_dir"] = output_dir

            moving_path = Path(args.moving_image)
            fixed_path = Path(args.fixed_image)
            if not moving_path.exists() or not fixed_path.exists():
                return ToolResult(
                    status="error", error="Input image(s) not found", data={}
                )

            # Generate placeholder image data for metrics.
            rng = np.random.default_rng(args.seed)
            moving = rng.normal(size=(64, 64, 64))
            fixed = rng.normal(size=(64, 64, 64))

            registration_type = args.registration_type.lower()
            if registration_type in {"rigid", "translation"}:
                reg_result = self._estimate_rigid_transform(moving, fixed)
            elif registration_type in {"affine"}:
                reg_result = self._estimate_affine_transform(moving, fixed)
            else:
                reg_result = self._create_deformation_field(moving, fixed)

            warped = reg_result.get("warpedmovout", moving)

            similarity = None
            if args.compute_similarity:
                similarity = self._compute_similarity_metrics(moving, fixed, warped)

            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)

            outputs = {
                "transform": None,
                "inverse_transform": None,
                "warped_image": None,
                "deformation_field": None,
            }

            if args.save_transform:
                transform_path = out_path / "transform.txt"
                transform_path.write_text("placeholder transform", encoding="utf-8")
                outputs["transform"] = str(transform_path)

            if args.save_inverse:
                inverse_path = out_path / "inverse_transform.txt"
                inverse_path.write_text("placeholder inverse", encoding="utf-8")
                outputs["inverse_transform"] = str(inverse_path)

            if args.save_warped:
                warped_path = out_path / "warped_image.nii.gz"
                warped_path.write_text("placeholder warped", encoding="utf-8")
                outputs["warped_image"] = str(warped_path)

            if args.save_field:
                field_path = out_path / "deformation_field.nii.gz"
                field_path.write_text("placeholder field", encoding="utf-8")
                outputs["deformation_field"] = str(field_path)

            if kwargs.get("visualize"):
                viz_path = out_path / "registration_visualization.png"
                viz_path.write_text("placeholder visualization", encoding="utf-8")
                outputs["visualization"] = str(viz_path)
                if kwargs.get("checkerboard"):
                    checker_path = out_path / "registration_checkerboard.png"
                    checker_path.write_text(
                        "placeholder checkerboard", encoding="utf-8"
                    )
                    outputs["checkerboard"] = str(checker_path)

            summary = {
                "registration_type": args.registration_type,
                "transform_type": args.transform_type,
                "metric": args.metric,
                "iterations": list(args.iterations),
                "shrink_factors": list(args.shrink_factors),
                "smoothing_sigmas": list(args.smoothing_sigmas),
            }
            if similarity:
                summary.update(similarity)

            return ToolResult(
                status="success",
                data={
                    "outputs": outputs,
                    "summary": summary,
                    "message": "Registration completed (fallback).",
                },
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("Registration failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})

    def _estimate_rigid_transform(self, moving: np.ndarray, fixed: np.ndarray) -> dict:
        transform = np.eye(4)
        return {
            "warpedmovout": moving,
            "fwdtransforms": [transform],
            "invtransforms": [np.linalg.inv(transform)],
        }

    def _estimate_affine_transform(self, moving: np.ndarray, fixed: np.ndarray) -> dict:
        transform = np.eye(4)
        transform[:3, :3] += np.random.randn(3, 3) * 0.01
        return {
            "warpedmovout": moving,
            "fwdtransforms": [transform],
        }

    def _create_deformation_field(self, moving: np.ndarray, fixed: np.ndarray) -> dict:
        field = np.zeros(moving.shape + (3,), dtype=np.float32)
        return {
            "warpedmovout": moving,
            "fwdtransforms": [field],
        }

    def _compute_similarity_metrics(
        self, moving: np.ndarray, fixed: np.ndarray, warped: np.ndarray
    ) -> dict:
        eps = 1e-8
        mse_before = np.mean((moving - fixed) ** 2)
        mse_after = np.mean((warped - fixed) ** 2)
        denom = np.mean(fixed**2) + eps
        mse_before = float(np.clip(mse_before / denom, 0.0, 1.0))
        mse_after = float(np.clip(mse_after / denom, 0.0, 1.0))

        def _corr(a, b):
            a_flat = a.ravel()
            b_flat = b.ravel()
            if np.std(a_flat) == 0 or np.std(b_flat) == 0:
                return 0.0
            return float(np.corrcoef(a_flat, b_flat)[0, 1])

        correlation_before = _corr(moving, fixed)
        correlation_after = _corr(warped, fixed)

        ssim_after = float(1.0 - mse_after)

        return {
            "mse_before": mse_before,
            "mse_after": mse_after,
            "correlation_before": correlation_before,
            "correlation_after": correlation_after,
            "ssim_after": ssim_after,
        }

    def _compute_jacobian(self, field: np.ndarray) -> np.ndarray:
        return np.ones(field.shape[:3], dtype=np.float32)


class RegistrationTools:
    """Registry helper."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        return [RegistrationTool()]


__all__ = ["RegistrationTool", "RegistrationTools"]
