"""Paradigm defaults registry.

Provides ``resolve_defaults`` and ``psyflow_config_for`` as the stable
public entry points. Keys are lower-cased with hyphens normalized to
underscores; each paradigm is registered under its canonical key plus
common aliases.
"""

from __future__ import annotations

from typing import Any, Callable

from brain_researcher.behavior.task_spec import BehaviorTaskSpecV1
from brain_researcher.behavior.catalog import flanker, go_no_go, nback

RESOLVERS: dict[str, Callable[[dict[str, Any] | None], BehaviorTaskSpecV1]] = {
    "n_back": nback.build,
    "nback": nback.build,
    "go_no_go": go_no_go.build,
    "gonogo": go_no_go.build,
    "go_nogo": go_no_go.build,
    "flanker": flanker.build,
}

CONFIG_MAPPERS: dict[str, Callable[[BehaviorTaskSpecV1], dict[str, Any]]] = {
    "n_back": nback.to_psyflow_config,
    "nback": nback.to_psyflow_config,
    "go_no_go": go_no_go.to_psyflow_config,
    "gonogo": go_no_go.to_psyflow_config,
    "go_nogo": go_no_go.to_psyflow_config,
    "flanker": flanker.to_psyflow_config,
}


def _key(paradigm: str | None) -> str:
    return (paradigm or "").strip().lower().replace("-", "_")


def resolve_defaults(
    paradigm: str, overrides: dict[str, Any] | None = None
) -> BehaviorTaskSpecV1:
    k = _key(paradigm)
    if k not in RESOLVERS:
        raise KeyError(f"unknown paradigm: {paradigm!r}")
    return RESOLVERS[k](overrides or {})


def psyflow_config_for(spec: BehaviorTaskSpecV1) -> dict[str, Any]:
    k = _key(spec.paradigm)
    if k not in CONFIG_MAPPERS:
        raise KeyError(f"unknown paradigm: {spec.paradigm!r}")
    return CONFIG_MAPPERS[k](spec)


def config_mapper_for(paradigm: str) -> Callable[[BehaviorTaskSpecV1], dict[str, Any]]:
    k = _key(paradigm)
    if k not in CONFIG_MAPPERS:
        raise KeyError(f"unknown paradigm: {paradigm!r}")
    return CONFIG_MAPPERS[k]


__all__ = [
    "RESOLVERS",
    "CONFIG_MAPPERS",
    "resolve_defaults",
    "psyflow_config_for",
    "config_mapper_for",
]
