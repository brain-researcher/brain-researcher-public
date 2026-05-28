"""Artifact contract (v1).

Artifacts are typed references to outputs produced during a job/run:
- files (including stdout/stderr/logs)
- structured JSON documents (observation, provenance, bundles)
- trace/event logs

This contract is intentionally transport-agnostic: the same ArtifactV1 can be used
in API responses, on-disk manifests, or stream events.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator

from .ids import IdsV1
from .policy_ref import PolicyRefV1, build_policy_ref_v1
from .version_ref import VersionRefV1, get_cached_version_ref_v1


class ArtifactKindV1(str, Enum):
    file = "file"
    json = "json"
    blob = "blob"
    bundle = "bundle"
    log = "log"
    trace = "trace"


class ArtifactV1(BaseModel):
    schema_version: Literal["artifact-v1"] = "artifact-v1"

    # M0 primitives (first-class; stable envelope)
    ids: IdsV1 = Field(default_factory=IdsV1)
    policy: PolicyRefV1 = Field(default_factory=build_policy_ref_v1)
    versions: VersionRefV1 = Field(default_factory=get_cached_version_ref_v1)

    artifact_id: str | None = Field(
        default=None, description="Optional stable artifact identifier"
    )

    # Canonical owner reference (accepts legacy aliases during validation).
    job_id: str | None = Field(
        default=None,
        description="Owning job/analysis identifier",
        validation_alias=AliasChoices("job_id", "analysis_id"),
    )

    kind: ArtifactKindV1 = Field(description="High-level artifact kind")
    media_type: str | None = Field(
        default=None,
        description="IANA media type (e.g. application/json, text/plain)",
        validation_alias=AliasChoices("media_type", "mime_type", "mime"),
    )

    # Prefer a run_dir-relative path or abstract URI; avoid leaking host absolute paths.
    uri: str = Field(
        description="Relative path within the run directory, or an abstract URI",
        validation_alias=AliasChoices("uri", "path", "ref"),
    )

    # Canonical hash fields (accepts legacy artifact-manifest keys).
    sha256: str | None = Field(
        default=None,
        description="Checksum in the form sha256:<hex> when available",
        validation_alias=AliasChoices("sha256", "checksum"),
    )
    bytes: int | None = Field(
        default=None,
        description="Size in bytes when known",
        validation_alias=AliasChoices("bytes", "size"),
    )

    created_at: int | None = Field(
        default=None, description="Unix timestamp (seconds) when recorded"
    )

    tags: list[str] = Field(default_factory=list, description="Semantic tags/roles")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _backfill_ids(self) -> "ArtifactV1":
        if self.job_id and self.ids.job_id is None:
            self.ids.job_id = self.job_id
        if self.job_id and self.ids.analysis_id is None:
            # P0 convention: analysis_id == job_id
            self.ids.analysis_id = self.job_id
        return self


__all__ = ["ArtifactKindV1", "ArtifactV1"]
