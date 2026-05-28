"""Execution manifest contract (v1).

Minimal reproducibility metadata for rerunning an analysis bundle.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ExecutionModeV1(str, Enum):
    python_script = "python_script"
    shell_script = "shell_script"
    docker_compose = "docker_compose"
    neurodesk = "neurodesk"
    mixed = "mixed"
    unknown = "unknown"


class ExecutionEntrypointsV1(BaseModel):
    python_script: str | None = None
    shell_script: str | None = None
    environment_file: str | None = None
    docker_compose: str | None = None


class ExecutionRuntimeV1(BaseModel):
    python_version: str | None = None
    docker_supported: bool = False
    neurodesk_supported: bool = False


class ExecutionIORefV1(BaseModel):
    name: str
    kind: Literal["file", "directory", "uri", "value"] = "file"
    required: bool = False
    description: str | None = None
    path: str | None = None


class ExecutionReproV1(BaseModel):
    working_directory: str | None = "."
    command: str | None = None
    notes: str | None = None


class NeurodeskExecutionV1(BaseModel):
    modules: list[str] = Field(default_factory=list)
    container_paths: list[str] = Field(default_factory=list)
    command_template: str | None = None


class ExecutionManifestV1(BaseModel):
    schema_version: Literal["execution-manifest-v1"] = "execution-manifest-v1"
    execution_mode: ExecutionModeV1 = ExecutionModeV1.unknown
    summary: str | None = None
    entrypoints: ExecutionEntrypointsV1 = Field(default_factory=ExecutionEntrypointsV1)
    runtime: ExecutionRuntimeV1 = Field(default_factory=ExecutionRuntimeV1)
    inputs: list[ExecutionIORefV1] = Field(default_factory=list)
    outputs: list[ExecutionIORefV1] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    repro: ExecutionReproV1 = Field(default_factory=ExecutionReproV1)
    neurodesk: NeurodeskExecutionV1 | None = None


__all__ = [
    "ExecutionEntrypointsV1",
    "ExecutionIORefV1",
    "ExecutionManifestV1",
    "ExecutionModeV1",
    "ExecutionReproV1",
    "ExecutionRuntimeV1",
    "NeurodeskExecutionV1",
]
