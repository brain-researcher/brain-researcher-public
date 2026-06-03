"""Unified executors package for container and subprocess execution.

This package provides standardized execution helpers for neuroimaging tools,
supporting both containerized (Docker/Apptainer) and direct subprocess execution.

Also includes provenance tracking via RunRecorder and RecorderFactory.
"""
from brain_researcher.services.tools.executors.container import (
    BindMount,
    ContainerRequest,
    ContainerExecutionError,
    SlurmConfig,
    run_container,
    describe_request,
)

from brain_researcher.services.tools.executors.provenance_helpers import (
    get_git_metadata,
    get_host_metadata,
    get_container_fingerprint,
    get_file_fingerprint,
    get_inputs_fingerprints,
    PROVENANCE_SCHEMA_VERSION,
)

from brain_researcher.services.tools.executors.run_recorder import (
    RunRecorder,
    StateTransition,
    compute_container_fingerprint,
    prepare_child_summary_extra,
)

from brain_researcher.services.tools.executors.recorder_factory import (
    RecorderFactory,
    DefaultRecorderFactory,
    create_recorder_factory,
)

__all__ = [
    # Container execution
    "BindMount",
    "ContainerRequest",
    "ContainerExecutionError",
    "SlurmConfig",
    "run_container",
    "describe_request",
    # Provenance helpers
    "get_git_metadata",
    "get_host_metadata",
    "get_container_fingerprint",
    "get_file_fingerprint",
    "get_inputs_fingerprints",
    "PROVENANCE_SCHEMA_VERSION",
    # Run recorder
    "RunRecorder",
    "StateTransition",
    "compute_container_fingerprint",
    "prepare_child_summary_extra",
    # Recorder factory
    "RecorderFactory",
    "DefaultRecorderFactory",
    "create_recorder_factory",
]
