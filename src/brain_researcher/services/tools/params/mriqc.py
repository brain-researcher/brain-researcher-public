"""
Shared helpers for MRIQC configuration and command building.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


def _tupleize(values: Iterable[str] | str | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        value = values.strip()
        return (value,) if value else ()
    return tuple(str(v) for v in values if v is not None and str(v) != "")


@dataclass(frozen=True)
class MRIQCParameters:
    """Normalised configuration for MRIQC CLI invocation."""

    bids_dir: str
    output_dir: str
    analysis_level: str = "participant"
    participant_label: tuple[str, ...] = field(default_factory=tuple)
    session_id: tuple[str, ...] = field(default_factory=tuple)
    run_id: tuple[str, ...] = field(default_factory=tuple)
    modalities: tuple[str, ...] = field(default_factory=tuple)
    work_dir: str | None = None
    bids_filter_file: str | None = None
    dsname: str | None = None
    n_procs: int | None = None
    mem_gb: float | None = None
    float32: bool = False
    clean_workdir: bool = False
    verbose_reports: bool = False
    no_sub: bool = False
    random_seed: int | None = None
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "participant_label", _tupleize(self.participant_label))
        object.__setattr__(self, "session_id", _tupleize(self.session_id))
        object.__setattr__(self, "run_id", _tupleize(self.run_id))
        object.__setattr__(self, "modalities", _tupleize(self.modalities))
        object.__setattr__(self, "extra_args", _tupleize(self.extra_args))

    def command(self, include_executable: bool = True) -> list[str]:
        cmd: list[str] = []
        if include_executable:
            cmd.append("mriqc")

        cmd.extend([self.bids_dir, self.output_dir, self.analysis_level])

        if self.participant_label:
            cmd.extend(["--participant-label", *self.participant_label])
        if self.session_id:
            cmd.extend(["--session-id", *self.session_id])
        if self.run_id:
            cmd.extend(["--run-id", *self.run_id])
        if self.modalities:
            cmd.extend(["--modalities", *self.modalities])
        if self.work_dir:
            cmd.extend(["-w", self.work_dir])
        if self.bids_filter_file:
            cmd.extend(["--bids-filter-file", self.bids_filter_file])
        if self.dsname:
            cmd.extend(["--dsname", self.dsname])
        if self.n_procs is not None:
            cmd.extend(["--n_procs", str(self.n_procs)])
        if self.mem_gb is not None:
            cmd.extend(["--mem_gb", str(self.mem_gb)])
        if self.float32:
            cmd.append("--float32")
        if self.clean_workdir:
            cmd.append("--clean-workdir")
        if self.verbose_reports:
            cmd.append("--verbose-reports")
        if self.no_sub:
            cmd.append("--no-sub")
        if self.random_seed is not None:
            cmd.extend(["--random-seed", str(self.random_seed)])
        if self.extra_args:
            cmd.extend(self.extra_args)

        return cmd

    def env(self) -> dict[str, str]:
        return {}


def build_mriqc_command(
    params: MRIQCParameters, *, include_executable: bool = True
) -> list[str]:
    return params.command(include_executable=include_executable)


def build_mriqc_env(params: MRIQCParameters) -> dict[str, str]:
    return params.env()


def mriqc_from_payload(payload: Mapping[str, Any]) -> MRIQCParameters:
    def _seq(name: str, default: Sequence[str] | None = None) -> Sequence[str]:
        value = payload.get(name, default)
        if value is None:
            return ()
        if isinstance(value, list | tuple | set):
            return tuple(str(v) for v in value)
        return (str(value),)

    extra_args = payload.get("extra_args") or ()
    if isinstance(extra_args, list | tuple | set):
        extra_args_tuple = tuple(str(v) for v in extra_args)
    else:
        extra_args_tuple = (str(extra_args),)

    random_seed = payload.get("random_seed")
    if random_seed is not None:
        try:
            random_seed = int(random_seed)
        except (TypeError, ValueError):
            random_seed = None

    mem_gb = payload.get("mem_gb")
    if mem_gb is not None:
        try:
            mem_gb = float(mem_gb)
        except (TypeError, ValueError):
            mem_gb = None

    return MRIQCParameters(
        bids_dir=str(payload["bids_dir"]),
        output_dir=str(payload["output_dir"]),
        analysis_level=str(payload.get("analysis_level", "participant")),
        participant_label=_seq("participant_label"),
        session_id=_seq("session_id"),
        run_id=_seq("run_id"),
        modalities=_seq("modalities"),
        work_dir=payload.get("work_dir") or None,
        bids_filter_file=payload.get("bids_filter_file") or None,
        dsname=payload.get("dsname") or None,
        n_procs=_coerce_int(payload.get("n_procs")),
        mem_gb=mem_gb,
        float32=bool(payload.get("float32", False)),
        clean_workdir=bool(payload.get("clean_workdir", False)),
        verbose_reports=bool(payload.get("verbose_reports", False)),
        no_sub=bool(payload.get("no_sub", False)),
        random_seed=random_seed,
        extra_args=extra_args_tuple,
    )


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "MRIQCParameters",
    "build_mriqc_command",
    "build_mriqc_env",
    "mriqc_from_payload",
]
