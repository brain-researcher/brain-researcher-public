"""Version reference contract (v1)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class VersionRefV1(BaseModel):
    """Best-effort versions for reproducibility/auditing."""

    schema_version: Literal["version-ref-v1"] = "version-ref-v1"

    contracts_version: str = Field(
        default="contracts-v1", description="Version identifier for this contract set"
    )
    brain_researcher_version: str | None = Field(
        default=None, description="Installed brain_researcher package version"
    )
    git_commit: str | None = Field(default=None, description="Git commit SHA if known")

    tool_versions: dict[str, str] = Field(
        default_factory=dict, description="Tool/library versions"
    )
    image_digests: dict[str, str] = Field(
        default_factory=dict, description="Container/image digests"
    )


_CACHED_VERSION_REF: VersionRefV1 | None = None


def _pkg_version(dist_name: str) -> str | None:
    try:
        import importlib.metadata

        return importlib.metadata.version(dist_name)
    except Exception:
        return None


def _git_commit(repo_root: Path) -> str | None:
    env_commit = (
        os.getenv("BR_GIT_COMMIT")
        or os.getenv("GIT_COMMIT")
        or os.getenv("COMMIT_SHA")
        or os.getenv("SOURCE_VERSION")
    )
    if env_commit:
        return env_commit.strip()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        sha = result.stdout.strip()
        return sha or None
    except Exception:
        return None


def build_version_ref_v1() -> VersionRefV1:
    repo_root = Path(__file__).resolve().parents[4]
    return VersionRefV1(
        brain_researcher_version=_pkg_version("brain_researcher"),
        git_commit=_git_commit(repo_root),
    )


def get_cached_version_ref_v1() -> VersionRefV1:
    global _CACHED_VERSION_REF
    if _CACHED_VERSION_REF is None:
        _CACHED_VERSION_REF = build_version_ref_v1()
    # Return a copy so callers can safely mutate nested dicts.
    return _CACHED_VERSION_REF.model_copy(deep=True)


__all__ = ["VersionRefV1", "build_version_ref_v1", "get_cached_version_ref_v1"]

