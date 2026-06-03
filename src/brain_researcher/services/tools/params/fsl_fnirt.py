"""Shared helpers for FSL FNIRT non-linear registration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FSLFNIRTParameters:
    in_file: str
    ref_file: str
    output_dir: str
    out_file: str | None = None
    field_file: str | None = None
    jacobian_file: str | None = None
    affine_file: str | None = None
    in_intensitymap_file: str | None = None
    config_file: str | None = None
    warp_resolution: str | None = None
    spline_order: int | None = None
    regularization_lambda: str | None = None
    regularization_model: str | None = None
    max_iterations: str | None = None
    subsample_levels: str | None = None
    intensity_mapping: bool = False
    intensity_mapping_order: int | None = None
    ref_mask: str | None = None
    in_mask: str | None = None
    apply_ref_mask: int | None = None
    apply_in_mask: int | None = None
    in_smoothing: str | None = None
    ref_smoothing: str | None = None
    use_gradient_images: bool = False
    jacobian_range: str | None = None
    derive_from_ref: bool = False
    verbose: bool = False
    debug: bool = False
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    def command(
        self, include_executable: bool = True, executable: str = "fnirt"
    ) -> list[str]:
        cmd: list[str] = []
        if include_executable:
            cmd.append(executable)

        cmd.extend(["--in=" + self.in_file, "--ref=" + self.ref_file])
        if self.out_file:
            cmd.append("--iout=" + self.out_file)
        if self.field_file:
            cmd.append("--fout=" + self.field_file)
        if self.jacobian_file:
            cmd.append("--jout=" + self.jacobian_file)
        if self.affine_file:
            cmd.append("--aff=" + self.affine_file)
        if self.in_intensitymap_file:
            cmd.append("--intin=" + self.in_intensitymap_file)
        if self.config_file:
            cmd.append("--config=" + self.config_file)
        if self.warp_resolution:
            cmd.append("--warpres=" + self.warp_resolution)
        if self.spline_order is not None:
            cmd.append("--splineorder=" + str(self.spline_order))
        if self.regularization_lambda:
            cmd.append("--lambda=" + self.regularization_lambda)
        if self.regularization_model:
            cmd.append("--regmod=" + self.regularization_model)
        if self.max_iterations:
            cmd.append("--miter=" + self.max_iterations)
        if self.subsample_levels:
            cmd.append("--subsamp=" + self.subsample_levels)
        if self.intensity_mapping:
            cmd.extend(
                [
                    "--intmod=global_non_linear",
                    "--intorder=" + str(self.intensity_mapping_order or 0),
                ]
            )
        if self.ref_mask:
            cmd.append("--refmask=" + self.ref_mask)
        if self.in_mask:
            cmd.append("--inmask=" + self.in_mask)
        if self.apply_ref_mask is not None:
            cmd.append("--applyrefmask=" + str(self.apply_ref_mask))
        if self.apply_in_mask is not None:
            cmd.append("--applyinmask=" + str(self.apply_in_mask))
        if self.in_smoothing:
            cmd.append("--infwhm=" + self.in_smoothing)
        if self.ref_smoothing:
            cmd.append("--reffwhm=" + self.ref_smoothing)
        if self.use_gradient_images:
            cmd.extend(["--refderiv", "--inderiv"])
        if self.jacobian_range:
            cmd.append("--jacrange=" + self.jacobian_range)
        if self.derive_from_ref:
            cmd.append("--refout")
        if self.verbose:
            cmd.append("--verbose")
        if self.debug:
            cmd.append("--debug")
        if self.extra_args:
            cmd.extend(self.extra_args)
        return cmd


def build_fsl_fnirt_command(
    params: FSLFNIRTParameters,
    *,
    include_executable: bool = True,
    executable: str = "fnirt",
) -> list[str]:
    return params.command(include_executable=include_executable, executable=executable)


def fsl_fnirt_from_payload(payload: Mapping[str, Any]) -> FSLFNIRTParameters:
    return FSLFNIRTParameters(
        in_file=str(payload["in_file"]),
        ref_file=str(payload["ref_file"]),
        output_dir=str(payload.get("output_dir", "")),
        out_file=payload.get("out_file"),
        field_file=payload.get("field_file"),
        jacobian_file=payload.get("jacobian_file"),
        affine_file=payload.get("affine_file"),
        in_intensitymap_file=payload.get("in_intensitymap_file"),
        config_file=payload.get("config_file"),
        warp_resolution=payload.get("warp_resolution"),
        spline_order=(
            int(payload["spline_order"])
            if payload.get("spline_order") is not None
            else None
        ),
        regularization_lambda=payload.get("regularization_lambda"),
        regularization_model=payload.get("regularization_model"),
        max_iterations=payload.get("max_iterations"),
        subsample_levels=payload.get("subsample_levels"),
        intensity_mapping=bool(payload.get("intensity_mapping", False)),
        intensity_mapping_order=(
            int(payload["intensity_mapping_order"])
            if payload.get("intensity_mapping_order") is not None
            else None
        ),
        ref_mask=payload.get("ref_mask"),
        in_mask=payload.get("in_mask"),
        apply_ref_mask=(
            int(payload["apply_ref_mask"])
            if payload.get("apply_ref_mask") is not None
            else None
        ),
        apply_in_mask=(
            int(payload["apply_in_mask"])
            if payload.get("apply_in_mask") is not None
            else None
        ),
        in_smoothing=payload.get("in_smoothing"),
        ref_smoothing=payload.get("ref_smoothing"),
        use_gradient_images=bool(payload.get("use_gradient_images", False)),
        jacobian_range=payload.get("jacobian_range"),
        derive_from_ref=bool(payload.get("derive_from_ref", False)),
        verbose=bool(payload.get("verbose", False)),
        debug=bool(payload.get("debug", False)),
        extra_args=(
            tuple(str(arg) for arg in (payload.get("extra_args") or []))
            if isinstance(payload.get("extra_args"), list | tuple)
            else (
                tuple(str(payload.get("extra_args")))
                if payload.get("extra_args")
                else ()
            )
        ),
    )


__all__ = [
    "FSLFNIRTParameters",
    "build_fsl_fnirt_command",
    "fsl_fnirt_from_payload",
]
