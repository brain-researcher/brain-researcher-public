"""
Shared helpers for XCP-D command construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple


def _tuple(values: Iterable[str] | str | None) -> Tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        value = values.strip()
        return (value,) if value else ()
    return tuple(str(v) for v in values if v is not None and str(v) != "")


@dataclass(frozen=True)
class XCPDParameters:
    """Normalised configuration for XCP-D invocation."""

    fmriprep_dir: str
    output_dir: str
    analysis_level: str = "participant"
    participant_label: Tuple[str, ...] = field(default_factory=tuple)
    work_dir: str | None = None
    denoising_strategy: str = "36P"
    parcellation: str | None = None
    smoothing: str = "6"
    fd_threshold: float = 0.5
    despike: bool = True
    bandpass_filter: Tuple[float, float] | None = (0.01, 0.1)
    output_type: str = "full"
    cifti: bool = False
    n_cpus: int | None = None
    mem_gb: float | None = None
    extra_args: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "participant_label", _tuple(self.participant_label))
        object.__setattr__(self, "extra_args", _tuple(self.extra_args))

    def command(self, include_executable: bool = True) -> list[str]:
        cmd: list[str] = []
        if include_executable:
            cmd.append("xcp_d")

        cmd.extend([self.fmriprep_dir, self.output_dir, self.analysis_level])

        for label in self.participant_label:
            cmd.extend(["--participant-label", label])

        if self.work_dir:
            cmd.extend(["-w", self.work_dir])

        if self.denoising_strategy:
            cmd.extend(["--nuisance-regressors", self.denoising_strategy])

        if self.parcellation:
            cmd.extend(["--atlases", self.parcellation])

        if self.smoothing:
            cmd.extend(["--smoothing", self.smoothing])

        cmd.extend(["--fd-thresh", str(self.fd_threshold)])

        if self.despike:
            cmd.append("--despike")

        if self.bandpass_filter:
            lower, upper = self.bandpass_filter
            cmd.extend(["--lower-bpf", str(lower), "--upper-bpf", str(upper)])
        else:
            cmd.append("--disable-bandpass-filter")

        if self.output_type and self.output_type.lower() != "full":
            cmd.extend(["--output-type", self.output_type])

        if self.cifti:
            cmd.append("--cifti")

        if self.n_cpus is not None:
            cmd.extend(["--nprocs", str(self.n_cpus)])

        if self.mem_gb is not None:
            cmd.extend(["--mem-gb", str(self.mem_gb)])

        cmd.append("--notrack")

        if self.extra_args:
            cmd.extend(self.extra_args)

        return cmd

    def env(self) -> Dict[str, str]:
        return {}


def build_xcpd_command(
    params: XCPDParameters, *, include_executable: bool = True
) -> list[str]:
    return params.command(include_executable=include_executable)


def build_xcpd_env(params: XCPDParameters) -> Dict[str, str]:
    return params.env()


def xcpd_from_payload(payload: Mapping[str, Any]) -> XCPDParameters:
    def _get_sequence(name: str) -> Sequence[str]:
        value = payload.get(name)
        if value is None:
            return ()
        if isinstance(value, (list, tuple, set)):
            return tuple(str(v) for v in value)
        return (str(value),)

    extra_args = payload.get("extra_args") or ()
    if isinstance(extra_args, (list, tuple, set)):
        extra_args_tuple = tuple(str(v) for v in extra_args)
    else:
        extra_args_tuple = (str(extra_args),)

    bandpass = payload.get("bandpass_filter", (0.01, 0.1))
    if bandpass is None:
        bandpass_filter = None
    elif isinstance(bandpass, (list, tuple)) and len(bandpass) == 2:
        bandpass_filter = (float(bandpass[0]), float(bandpass[1]))
    else:
        bandpass_filter = None

    denoising = payload.get("denoising_strategy", "36P")
    if isinstance(denoising, str):
        denoising_strategy = denoising
    else:
        denoising_strategy = str(denoising)

    parcellation = payload.get("parcellation")
    parcellation_str = str(parcellation) if parcellation is not None else None

    smoothing = payload.get("smoothing", "6")
    smoothing_str = str(smoothing) if smoothing is not None else "6"

    output_type = payload.get("output_type", "full")
    output_type_str = str(output_type) if output_type is not None else "full"

    return XCPDParameters(
        fmriprep_dir=str(payload["fmriprep_dir"]),
        output_dir=str(payload["output_dir"]),
        analysis_level=str(payload.get("analysis_level", "participant")),
        participant_label=_get_sequence("participant_label"),
        work_dir=payload.get("work_dir") or None,
        denoising_strategy=denoising_strategy,
        parcellation=parcellation_str,
        smoothing=smoothing_str,
        fd_threshold=float(payload.get("fd_threshold", 0.5)),
        despike=bool(payload.get("despike", True)),
        bandpass_filter=bandpass_filter,
        output_type=output_type_str,
        cifti=bool(payload.get("cifti", False)),
        n_cpus=_coerce_int(payload.get("n_cpus")),
        mem_gb=_coerce_float(payload.get("mem_gb")),
        extra_args=extra_args_tuple,
    )


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "XCPDParameters",
    "build_xcpd_command",
    "build_xcpd_env",
    "xcpd_from_payload",
]
