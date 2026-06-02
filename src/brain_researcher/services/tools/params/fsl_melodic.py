"""
Shared helpers for FSL MELODIC execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence, Tuple


def _tuple(values: Sequence[str] | str | None) -> Tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        value = values.strip()
        if not value:
            return ()
        return tuple(part for part in value.split(",") if part)
    return tuple(str(v) for v in values if v is not None and str(v) != "")


@dataclass(frozen=True)
class FSLMELODICParameters:
    """Normalised configuration for FSL MELODIC."""

    input_files: Tuple[str, ...]
    output_dir: str
    tr: float
    approach: str = "concat"
    dimensionality: str = "automatic"
    n_components: int | None = None
    mask: str | None = None
    bg_threshold: float = 10.0
    var_norm: bool = True
    output_all: bool = True
    report: bool = True
    extra_args: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.input_files:
            raise ValueError("At least one input file is required for MELODIC")
        object.__setattr__(self, "input_files", _tuple(self.input_files))
        object.__setattr__(self, "extra_args", _tuple(self.extra_args))

    def command(self, include_executable: bool = True) -> list[str]:
        cmd: list[str] = []
        if include_executable:
            cmd.append("melodic")

        input_arg = ",".join(self.input_files)
        cmd.extend(["-i", input_arg, "-o", self.output_dir, "--tr", str(self.tr)])

        # Approach
        if self.approach and self.approach != "concat":
            cmd.extend(["-a", self.approach])

        # Dimensionality
        dim = self.dimensionality.lower()
        if dim == "manual" and self.n_components:
            cmd.extend(["-d", str(self.n_components)])
        elif dim == "automatic":
            cmd.extend(["-d", "0"])
        elif dim in {"laplace", "lap"}:
            cmd.append("--dim_est=lap")
        elif dim == "bic":
            cmd.append("--dim_est=bic")
        elif dim == "mdl":
            cmd.append("--dim_est=mdl")
        elif dim == "aic":
            cmd.append("--dim_est=aic")

        if self.mask:
            cmd.extend(["-m", self.mask])
        if self.bg_threshold is not None:
            cmd.extend(["--bgthreshold", str(self.bg_threshold)])

        # Variance normalisation
        cmd.append("--vn" if self.var_norm else "--no_vn")
        if self.output_all:
            cmd.append("--Oall")
        if self.report:
            cmd.append("--report")
        if self.extra_args:
            cmd.extend(self.extra_args)
        return cmd


def build_fsl_melodic_command(
    params: FSLMELODICParameters, *, include_executable: bool = True
) -> list[str]:
    return params.command(include_executable=include_executable)


def fsl_melodic_from_payload(payload: Mapping[str, Any]) -> FSLMELODICParameters:
    extra_args = payload.get("extra_args")
    return FSLMELODICParameters(
        input_files=_tuple(payload.get("input_files") or payload.get("input_file")),
        output_dir=str(payload["output_dir"]),
        tr=float(payload["tr"]),
        approach=str(payload.get("approach", "concat")),
        dimensionality=str(payload.get("dimensionality", "automatic")),
        n_components=_coerce_int(payload.get("n_components")),
        mask=payload.get("mask"),
        bg_threshold=float(payload.get("bg_threshold", 10.0)),
        var_norm=bool(payload.get("var_norm", True)),
        output_all=bool(payload.get("output_all", True)),
        report=bool(
            payload.get("report", True) or payload.get("generate_report", True)
        ),
        extra_args=_tuple(extra_args),
    )


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "FSLMELODICParameters",
    "build_fsl_melodic_command",
    "fsl_melodic_from_payload",
]
