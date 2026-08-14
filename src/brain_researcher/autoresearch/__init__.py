"""Shared autoresearch contracts for line-specific controllers."""

from .artifact_schema import (
    ArtifactPaths,
    LineSpec,
    canonicalize_line_path,
    legacy_line_root,
    resolve_line_paths,
)
from .canonical_program_registry import (
    CANONICAL_PROGRAM_DESCRIPTOR_SCHEMA_VERSION,
    CANONICAL_PROGRAM_LAUNCH_PLAN_SCHEMA_VERSION,
    CANONICAL_PROGRAM_REGISTRY,
    CanonicalProgramConflictError,
    CanonicalProgramDescriptor,
    CanonicalProgramDuplicateError,
    CanonicalProgramHook,
    CanonicalProgramKey,
    CanonicalProgramLaunchPlanV1,
    CanonicalProgramNotRegisteredError,
    CanonicalProgramRegistry,
    CanonicalProgramRegistryError,
    RegisteredCanonicalProgram,
)
from .critic import CriticVerdict, run_independent_critic
from .episode_paths import (
    AUTORESEARCH_DATA_ROOT_ENV,
    EPISODE_ADDRESS_SCHEMA_VERSION,
    EPISODE_LAYOUT_VERSION,
    EpisodeAddressV1,
    EpisodePaths,
    EpisodeRunPaths,
    resolve_autoresearch_data_root,
)
from .quality_protocol import GateVerdict, LineId, StopReason
from .scorer_contract import ScoreResult
from .startup_validation import SecretRequirement, StartupValidationResult
from .state_contract import (
    GateCheck,
    HandoffArtifact,
    RuntimeStateArtifact,
    StopArtifact,
    VerdictArtifact,
)

__all__ = [
    "ArtifactPaths",
    "AUTORESEARCH_DATA_ROOT_ENV",
    "CANONICAL_PROGRAM_DESCRIPTOR_SCHEMA_VERSION",
    "CANONICAL_PROGRAM_LAUNCH_PLAN_SCHEMA_VERSION",
    "CANONICAL_PROGRAM_REGISTRY",
    "CanonicalProgramConflictError",
    "CanonicalProgramDescriptor",
    "CanonicalProgramDuplicateError",
    "CanonicalProgramHook",
    "CanonicalProgramKey",
    "CanonicalProgramLaunchPlanV1",
    "CanonicalProgramNotRegisteredError",
    "CanonicalProgramRegistry",
    "CanonicalProgramRegistryError",
    "CriticVerdict",
    "EPISODE_ADDRESS_SCHEMA_VERSION",
    "EPISODE_LAYOUT_VERSION",
    "EpisodeAddressV1",
    "EpisodePaths",
    "EpisodeRunPaths",
    "GateVerdict",
    "GateCheck",
    "HandoffArtifact",
    "LineId",
    "LineSpec",
    "RuntimeStateArtifact",
    "RegisteredCanonicalProgram",
    "ScoreResult",
    "SecretRequirement",
    "StopReason",
    "StopArtifact",
    "StartupValidationResult",
    "VerdictArtifact",
    "canonicalize_line_path",
    "legacy_line_root",
    "resolve_line_paths",
    "resolve_autoresearch_data_root",
    "run_independent_critic",
]
