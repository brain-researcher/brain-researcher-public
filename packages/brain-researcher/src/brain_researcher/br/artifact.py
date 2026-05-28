"""Stable namespace: artifact manifest, checksums, contract validation."""

from brain_researcher.core.artifact_checksums import (
    compute_file_sha256,
    fill_artifact_checksums,
)
from brain_researcher.core.artifact_manifest import save_artifact_manifest
from brain_researcher.core.artifact_validator import (
    ArtifactContractSpec,
    artifact_contract_for_profile,
    infer_artifact_profile,
    optional_artifacts_for_profile,
    required_artifacts_for_profile,
)

__all__ = [
    "ArtifactContractSpec",
    "artifact_contract_for_profile",
    "compute_file_sha256",
    "fill_artifact_checksums",
    "infer_artifact_profile",
    "optional_artifacts_for_profile",
    "required_artifacts_for_profile",
    "save_artifact_manifest",
]
