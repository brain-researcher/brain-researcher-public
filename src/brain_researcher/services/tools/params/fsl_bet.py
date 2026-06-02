"""Shared helpers for FSL BET brain extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence, Tuple


def _split_args(values: Sequence[str] | str | None) -> Tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        stripped = values.strip()
        if not stripped:
            return ()
        return tuple(part for part in stripped.split() if part)
    return tuple(str(v) for v in values if v is not None)


@dataclass(frozen=True)
class FSLBETParameters:
    """Normalised configuration for FSL BET."""

    input_file: str
    output_file: str
    fractional_intensity: float = 0.5
    gradient_threshold: float = 0.0
    generate_mask: bool = True
    generate_skull: bool = False
    generate_surface: bool = False
    apply_to_4d: bool = False
    reduce_bias: bool = False
    robust_center: bool = False
    surface_estimation: str | None = None
    center_coordinates: Tuple[float, float, float] | None = None
    radius: float | None = None
    extra_flags: Tuple[str, ...] = field(default_factory=tuple)

    def command(
        self, include_executable: bool = True, executable: str = "bet"
    ) -> list[str]:
        cmd: list[str] = []
        if include_executable:
            cmd.append(executable)

        cmd.extend([self.input_file, self.output_file])
        cmd.extend(["-f", str(self.fractional_intensity)])

        if self.gradient_threshold:
            cmd.extend(["-g", str(self.gradient_threshold)])
        if self.generate_mask:
            cmd.append("-m")
        if self.generate_skull:
            cmd.append("-s")
        if self.generate_surface:
            cmd.append("-o")

        surface = (self.surface_estimation or "").upper()
        if surface in {"-R", "-S", "-B"}:
            cmd.append(surface)

        if self.apply_to_4d:
            cmd.append("-F")
        if self.reduce_bias and "-B" not in cmd:
            cmd.append("-B")
        if self.robust_center and "-R" not in cmd:
            cmd.append("-R")

        if self.center_coordinates:
            x, y, z = self.center_coordinates
            cmd.extend(["-c", str(x), str(y), str(z)])
        if self.radius is not None:
            cmd.extend(["-r", str(self.radius)])

        if self.extra_flags:
            cmd.extend(self.extra_flags)
        return cmd


def build_fsl_bet_command(
    params: FSLBETParameters,
    *,
    include_executable: bool = True,
    executable: str = "bet",
) -> list[str]:
    return params.command(include_executable=include_executable, executable=executable)


def fsl_bet_from_payload(payload: Mapping[str, Any]) -> FSLBETParameters:
    center = payload.get("center_coordinates")
    if center is not None and len(center) == 3:
        center_tuple = tuple(float(c) for c in center)
    else:
        center_tuple = None

    return FSLBETParameters(
        input_file=str(payload["input_file"]),
        output_file=str(payload["output_file"]),
        fractional_intensity=float(payload.get("fractional_intensity", 0.5)),
        gradient_threshold=float(payload.get("gradient_threshold", 0.0)),
        generate_mask=bool(payload.get("generate_mask", True)),
        generate_skull=bool(payload.get("generate_skull", False)),
        generate_surface=bool(payload.get("generate_surface", False)),
        apply_to_4d=bool(payload.get("apply_to_4d", False)),
        reduce_bias=bool(payload.get("reduce_bias", False)),
        robust_center=bool(payload.get("robust_center", False)),
        surface_estimation=payload.get("surface_estimation"),
        center_coordinates=center_tuple,
        radius=float(payload["radius"]) if payload.get("radius") is not None else None,
        extra_flags=_split_args(payload.get("extra_flags")),
    )


__all__ = [
    "FSLBETParameters",
    "build_fsl_bet_command",
    "fsl_bet_from_payload",
]
