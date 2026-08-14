"""Future-only path contract for canonical autoresearch episodes.

This module only derives paths.  It does not create directories, locate legacy
episodes, register a program, grant execution authority, or start a run.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.autoresearch.artifact_schema import RESEARCH_ROOT_NAME

AUTORESEARCH_DATA_ROOT_ENV = "BR_AUTORESEARCH_DATA_ROOT"
EPISODE_ADDRESS_SCHEMA_VERSION = "br.autoresearch_episode_address.v1"
EPISODE_LAYOUT_VERSION = "br.autoresearch_episode_layout.v1"
_DEFAULT_AUTORESEARCH_DATA_ROOT = Path.home() / ".local" / "share" / "brain-researcher"


def _path_component(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty stripped text")
    if value in {".", ".."} or any(token in value for token in ("/", "\\", "\x00")):
        raise ValueError(f"{name} must be a safe path component")
    return value


def resolve_autoresearch_data_root(
    data_root: Path | str | None = None,
) -> Path:
    """Resolve the canonical autoresearch data root without creating it.

    An explicit ``data_root`` wins.  Otherwise
    ``BR_AUTORESEARCH_DATA_ROOT`` is used when configured, with the current
    user's ``~/.local/share/brain-researcher`` data directory as the fallback.
    """

    if data_root is None:
        configured = os.getenv(AUTORESEARCH_DATA_ROOT_ENV, "").strip()
        selected: Path | str = configured or _DEFAULT_AUTORESEARCH_DATA_ROOT
    else:
        if isinstance(data_root, str) and not data_root.strip():
            raise ValueError("data_root must be non-empty when provided")
        selected = data_root
    return Path(selected).expanduser().resolve()


@dataclass(frozen=True, slots=True)
class EpisodeAddressV1:
    """Filesystem address for one canonical episode, not its full registration.

    ``program_id``, ``parent_episode_id``, frozen contract identity, executor,
    budget, and input materialization belong in a later typed registration under
    ``registration/``.  They do not affect the directory address.
    """

    line_id: str
    owner_key: str
    campaign_id: str
    round_id: str
    episode_id: str
    schema_version: str = EPISODE_ADDRESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EPISODE_ADDRESS_SCHEMA_VERSION:
            raise ValueError("invalid episode address schema_version")
        for name in (
            "line_id",
            "owner_key",
            "campaign_id",
            "round_id",
            "episode_id",
        ):
            object.__setattr__(self, name, _path_component(name, getattr(self, name)))

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "line_id": self.line_id,
            "owner_key": self.owner_key,
            "campaign_id": self.campaign_id,
            "round_id": self.round_id,
            "episode_id": self.episode_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EpisodeAddressV1:
        expected = {
            "schema_version",
            "line_id",
            "owner_key",
            "campaign_id",
            "round_id",
            "episode_id",
        }
        if set(payload) != expected:
            raise ValueError("episode address fields must match the v1 schema exactly")
        return cls(
            schema_version=payload["schema_version"],
            line_id=payload["line_id"],
            owner_key=payload["owner_key"],
            campaign_id=payload["campaign_id"],
            round_id=payload["round_id"],
            episode_id=payload["episode_id"],
        )


@dataclass(frozen=True, slots=True)
class EpisodeRunPaths:
    """Derived paths for one run attempt within an episode."""

    run_id: str
    runs_root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _path_component("run_id", self.run_id))
        object.__setattr__(
            self,
            "runs_root",
            Path(self.runs_root).expanduser().resolve(),
        )

    @property
    def run_root(self) -> Path:
        return self.runs_root / self.run_id

    @property
    def execution_root(self) -> Path:
        return self.run_root / "execution"

    @property
    def outputs_root(self) -> Path:
        return self.run_root / "outputs"

    @property
    def society_root(self) -> Path:
        return self.run_root / "society"

    @property
    def public_root(self) -> Path:
        return self.run_root / "public"

    @property
    def private_root(self) -> Path:
        return self.run_root / "private"

    def to_dict(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "run_root": str(self.run_root),
            "execution_root": str(self.execution_root),
            "outputs_root": str(self.outputs_root),
            "society_root": str(self.society_root),
            "public_root": str(self.public_root),
            "private_root": str(self.private_root),
        }


@dataclass(frozen=True, slots=True)
class EpisodePaths:
    """Pure canonical path derivation for one future autoresearch episode."""

    address: EpisodeAddressV1
    data_root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.address, EpisodeAddressV1):
            raise ValueError("address must be an EpisodeAddressV1")
        object.__setattr__(
            self,
            "data_root",
            resolve_autoresearch_data_root(self.data_root),
        )

    @classmethod
    def from_ids(
        cls,
        *,
        line_id: str,
        owner_key: str,
        campaign_id: str,
        round_id: str,
        episode_id: str,
        data_root: Path | str | None = None,
    ) -> EpisodePaths:
        return cls(
            address=EpisodeAddressV1(
                line_id=line_id,
                owner_key=owner_key,
                campaign_id=campaign_id,
                round_id=round_id,
                episode_id=episode_id,
            ),
            data_root=resolve_autoresearch_data_root(data_root),
        )

    @property
    def research_root(self) -> Path:
        return self.data_root / RESEARCH_ROOT_NAME

    @property
    def line_root(self) -> Path:
        return self.research_root / self.address.line_id

    @property
    def inputs_root(self) -> Path:
        return self.line_root / "inputs"

    @property
    def sources_root(self) -> Path:
        return self.line_root / "sources"

    @property
    def owners_root(self) -> Path:
        return self.line_root / "owners"

    @property
    def owner_root(self) -> Path:
        return self.owners_root / self.address.owner_key

    @property
    def campaigns_root(self) -> Path:
        return self.owner_root / "campaigns"

    @property
    def campaign_root(self) -> Path:
        return self.campaigns_root / self.address.campaign_id

    @property
    def rounds_root(self) -> Path:
        return self.campaign_root / "rounds"

    @property
    def round_root(self) -> Path:
        return self.rounds_root / self.address.round_id

    @property
    def episodes_root(self) -> Path:
        return self.round_root / "episodes"

    @property
    def episode_root(self) -> Path:
        return self.episodes_root / self.address.episode_id

    @property
    def registration_root(self) -> Path:
        return self.episode_root / "registration"

    @property
    def authority_root(self) -> Path:
        return self.episode_root / "authority"

    @property
    def control_root(self) -> Path:
        return self.episode_root / "control"

    @property
    def runs_root(self) -> Path:
        return self.episode_root / "runs"

    def run(self, run_id: str) -> EpisodeRunPaths:
        normalized_run_id = _path_component("run_id", run_id)
        return EpisodeRunPaths(
            run_id=normalized_run_id,
            runs_root=self.runs_root,
        )

    def to_dict(self) -> dict[str, str | dict[str, str]]:
        return {
            "layout_version": EPISODE_LAYOUT_VERSION,
            "address": self.address.to_dict(),
            "data_root": str(self.data_root),
            "research_root": str(self.research_root),
            "line_root": str(self.line_root),
            "inputs_root": str(self.inputs_root),
            "sources_root": str(self.sources_root),
            "owners_root": str(self.owners_root),
            "owner_root": str(self.owner_root),
            "campaigns_root": str(self.campaigns_root),
            "campaign_root": str(self.campaign_root),
            "rounds_root": str(self.rounds_root),
            "round_root": str(self.round_root),
            "episodes_root": str(self.episodes_root),
            "episode_root": str(self.episode_root),
            "registration_root": str(self.registration_root),
            "authority_root": str(self.authority_root),
            "control_root": str(self.control_root),
            "runs_root": str(self.runs_root),
        }


__all__ = [
    "AUTORESEARCH_DATA_ROOT_ENV",
    "EPISODE_ADDRESS_SCHEMA_VERSION",
    "EPISODE_LAYOUT_VERSION",
    "EpisodeAddressV1",
    "EpisodePaths",
    "EpisodeRunPaths",
    "resolve_autoresearch_data_root",
]
