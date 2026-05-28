"""Shared autoresearch contracts for line-specific controllers."""

from .artifact_schema import (
    ArtifactPaths,
    LineSpec,
    canonicalize_line_path,
    legacy_line_root,
    resolve_line_paths,
)
from .critic import CriticVerdict, run_independent_critic
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
    "CriticVerdict",
    "GateVerdict",
    "GateCheck",
    "HandoffArtifact",
    "LineId",
    "LineSpec",
    "RuntimeStateArtifact",
    "ScoreResult",
    "SecretRequirement",
    "StopReason",
    "StopArtifact",
    "StartupValidationResult",
    "VerdictArtifact",
    "canonicalize_line_path",
    "legacy_line_root",
    "resolve_line_paths",
    "run_independent_critic",
]
