"""Backend job specification data classes (relocated to ``services.shared``).

These pure data classes were previously defined in
``brain_researcher.services.agent.backends.base_backend``. They are used both by
the agent-layer execution backends and by ``services.tools.neurodesk_compiler``;
relocating them here (round 2 services-layer DAG work) lets the tools layer
reference them without a ``tools -> agent`` import back-edge.

``base_backend`` re-exports these names, so existing callers continue to work
unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ResourceRequirements:
    """Resource requirements for job execution."""

    cpu: float = 1.0
    memory_gb: float = 4.0
    gpu: int = 0
    storage_gb: float = 10.0
    walltime_minutes: int = 60
    node_count: int = 1


@dataclass
class JobSpecification:
    """Job specification for backend execution."""

    name: str
    command: str
    image: str
    environment: dict[str, str]
    resources: ResourceRequirements
    working_dir: str = "/workspace"
    output_path: str = "/outputs"
    input_files: list[str] = None
    output_files: list[str] = None

    def __post_init__(self):
        if self.input_files is None:
            self.input_files = []
        if self.output_files is None:
            self.output_files = []


__all__ = ["ResourceRequirements", "JobSpecification"]
