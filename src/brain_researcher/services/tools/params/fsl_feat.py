"""
Shared helpers for FSL FEAT execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence, Tuple


@dataclass(frozen=True)
class FSLFEATParameters:
    """Normalised configuration for invoking FSL FEAT."""

    fsf_path: str
    working_dir: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    extra_args: Tuple[str, ...] = field(default_factory=tuple)

    def command(self, include_executable: bool = True) -> list[str]:
        cmd: list[str] = []
        if include_executable:
            cmd.append("feat")
        cmd.append(self.fsf_path)
        if self.extra_args:
            cmd.extend(self.extra_args)
        return cmd

    def merged_env(self) -> Dict[str, str]:
        return dict(self.env)


def build_fsl_feat_command(
    params: FSLFEATParameters, *, include_executable: bool = True
) -> list[str]:
    return params.command(include_executable=include_executable)


def build_fsl_feat_env(params: FSLFEATParameters) -> Dict[str, str]:
    return params.merged_env()


def fsl_feat_from_payload(payload: Mapping[str, Any]) -> FSLFEATParameters:
    extra_args = payload.get("extra_args") or ()
    if isinstance(extra_args, str):
        extra_args_tuple = tuple(arg for arg in extra_args.split() if arg)
    else:
        extra_args_tuple = tuple(str(v) for v in extra_args)

    env = payload.get("env") or {}
    if not isinstance(env, Mapping):
        raise TypeError("env must be a mapping if provided")

    return FSLFEATParameters(
        fsf_path=str(payload["fsf_path"]),
        working_dir=payload.get("working_dir") or payload.get("cwd"),
        env=dict(env),
        extra_args=extra_args_tuple,
    )


__all__ = [
    "FSLFEATParameters",
    "build_fsl_feat_command",
    "build_fsl_feat_env",
    "fsl_feat_from_payload",
]
