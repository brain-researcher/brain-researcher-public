"""
Shared helpers for FreeSurfer recon-all execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence, Tuple


def _as_tuple(values: Sequence[str] | str | None) -> Tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        value = values.strip()
        return (value,) if value else ()
    return tuple(str(v) for v in values if v is not None and str(v) != "")


@dataclass(frozen=True)
class FreeSurferReconAllParameters:
    """Normalised configuration for FreeSurfer recon-all."""

    subject_id: str
    subjects_dir: str
    t1_image: str | None = None
    stage: str = "all"
    t2_image: str | None = None
    flair_image: str | None = None
    expert_file: str | None = None
    hippocampal_subfields: bool = False
    brainstem: bool = False
    thalamus: bool = False
    parallel: bool = False
    n_threads: int | None = None
    use_gpu: bool = False
    license_file: str | None = None
    flags: Tuple[str, ...] = field(default_factory=tuple)
    inputs: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "flags", _as_tuple(self.flags))
        object.__setattr__(self, "inputs", _as_tuple(self.inputs))

    def command(self, include_executable: bool = True) -> list[str]:
        cmd: list[str] = []
        if include_executable:
            cmd.append("recon-all")

        if not self.subject_id:
            raise ValueError("subject_id is required for recon-all")
        if self.stage.lower() == "all":
            cmd.extend(["-all", "-subjid", self.subject_id])
        else:
            cmd.extend([f"-{self.stage}", "-subjid", self.subject_id])

        if self.t1_image:
            cmd.extend(["-i", self.t1_image])

        for input_path in self.inputs:
            cmd.extend(["-i", input_path])

        if self.t2_image:
            cmd.extend(["-T2", self.t2_image, "-T2pial"])
        if self.flair_image:
            cmd.extend(["-FLAIR", self.flair_image, "-FLAIRpial"])
        if self.expert_file:
            cmd.extend(["-expert", self.expert_file])
        if self.hippocampal_subfields:
            cmd.append("-hippocampal-subfields")
        if self.brainstem:
            cmd.append("-brainstem-structures")
        if self.thalamus:
            cmd.append("-thalamic-nuclei")
        if self.parallel:
            cmd.append("-parallel")
        if self.n_threads and self.n_threads > 0:
            cmd.extend(["-openmp", str(self.n_threads)])
        if self.use_gpu:
            cmd.append("-use-gpu")
        if self.flags:
            cmd.extend(self.flags)

        return cmd

    def env(self) -> Dict[str, str]:
        env: Dict[str, str] = {"SUBJECTS_DIR": self.subjects_dir}
        if self.license_file:
            env["FS_LICENSE"] = self.license_file
        if self.n_threads and self.n_threads > 0:
            env["OMP_NUM_THREADS"] = str(self.n_threads)
            env["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = str(self.n_threads)
        if self.use_gpu:
            env["FS_CUDA"] = "1"
        return env


def build_freesurfer_command(
    params: FreeSurferReconAllParameters, *, include_executable: bool = True
) -> list[str]:
    return params.command(include_executable=include_executable)


def build_freesurfer_env(params: FreeSurferReconAllParameters) -> Dict[str, str]:
    return params.env()


def freesurfer_from_payload(payload: Mapping[str, Any]) -> FreeSurferReconAllParameters:
    return FreeSurferReconAllParameters(
        subject_id=str(payload["subject_id"]),
        subjects_dir=str(
            payload.get("subjects_dir") or payload.get("subjects_dir_path") or ""
        ),
        t1_image=payload.get("t1_image"),
        stage=str(payload.get("stage", "all")),
        t2_image=payload.get("t2_image"),
        flair_image=payload.get("flair_image"),
        expert_file=payload.get("expert_file"),
        hippocampal_subfields=bool(payload.get("hippocampal_subfields", False)),
        brainstem=bool(payload.get("brainstem", False)),
        thalamus=bool(payload.get("thalamus", False)),
        parallel=bool(payload.get("parallel", False)),
        n_threads=_coerce_int(payload.get("n_threads")),
        use_gpu=bool(payload.get("use_gpu", False)),
        license_file=payload.get("license_file") or payload.get("fs_license_file"),
        flags=_as_tuple(payload.get("flags")),
        inputs=_as_tuple(payload.get("inputs")),
    )


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "FreeSurferReconAllParameters",
    "build_freesurfer_command",
    "build_freesurfer_env",
    "freesurfer_from_payload",
]
