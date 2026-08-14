"""Exact-identity registry for future canonical autoresearch programs.

The registry is an in-process hook boundary only.  It does not resolve paths,
allocate runs, grant authority, or execute a program.  Existing frozen program
implementations are deliberately not imported or registered here.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Literal, Protocol

CANONICAL_PROGRAM_DESCRIPTOR_SCHEMA_VERSION = "br.canonical_program_descriptor.v1"
CANONICAL_PROGRAM_LAUNCH_PLAN_SCHEMA_VERSION = "br.canonical_program_launch_plan.v1"


class CanonicalProgramRegistryError(ValueError):
    """A canonical program hook could not be registered or resolved safely."""


class CanonicalProgramDuplicateError(CanonicalProgramRegistryError):
    """The same hook was registered more than once."""


class CanonicalProgramConflictError(CanonicalProgramRegistryError):
    """Different hooks claimed the same exact identity."""


class CanonicalProgramNotRegisteredError(CanonicalProgramRegistryError):
    """No hook owns the requested exact program and executor versions."""


def _identifier(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CanonicalProgramRegistryError(f"{name} must be non-empty stripped text")
    if value in {".", ".."} or any(token in value for token in ("/", "\\", "\x00")):
        raise CanonicalProgramRegistryError(f"{name} must be a safe identifier")
    return value


@dataclass(frozen=True, slots=True, order=True)
class CanonicalProgramKey:
    """Exact program plus executor identity used by a future launcher."""

    program_id: str
    program_version: str
    executor_id: str
    executor_version: str

    def __post_init__(self) -> None:
        for name in (
            "program_id",
            "program_version",
            "executor_id",
            "executor_version",
        ):
            object.__setattr__(self, name, _identifier(name, getattr(self, name)))


@dataclass(frozen=True, slots=True)
class CanonicalProgramDescriptor:
    """Non-executing descriptor published by one canonical program hook."""

    key: CanonicalProgramKey
    schema_version: str = field(
        default=CANONICAL_PROGRAM_DESCRIPTOR_SCHEMA_VERSION,
        init=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.key, CanonicalProgramKey):
            raise CanonicalProgramRegistryError("key must be CanonicalProgramKey")


@dataclass(frozen=True, slots=True)
class CanonicalProgramLaunchPlanV1:
    """Server-built execution plan for one exact registered program version."""

    scenario: str
    plan: Mapping[str, Any]
    scientific_acceptance: Literal[False] = field(default=False, init=False)
    schema_version: str = field(
        default=CANONICAL_PROGRAM_LAUNCH_PLAN_SCHEMA_VERSION,
        init=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario", _identifier("scenario", self.scenario))
        if not isinstance(self.plan, Mapping):
            raise CanonicalProgramRegistryError("launch plan must be a JSON object")
        try:
            normalized = json.loads(
                json.dumps(dict(self.plan), allow_nan=False, sort_keys=True)
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CanonicalProgramRegistryError(
                "launch plan must be strict JSON"
            ) from exc
        if not isinstance(normalized, dict):  # pragma: no cover - JSON invariant
            raise CanonicalProgramRegistryError("launch plan must be a JSON object")
        object.__setattr__(self, "plan", normalized)

    def plan_dict(self) -> dict[str, Any]:
        """Return an isolated JSON copy for the execution boundary."""

        return json.loads(json.dumps(dict(self.plan), allow_nan=False, sort_keys=True))


class CanonicalProgramHook(Protocol):
    """Registered identity plus server-owned authority and plan resolvers."""

    @property
    def descriptor(self) -> CanonicalProgramDescriptor: ...

    @property
    def authorization_resolver(self) -> Callable[..., Any]: ...

    @property
    def launch_plan_builder(self) -> Callable[..., CanonicalProgramLaunchPlanV1]: ...

    @property
    def episode_preparer(self) -> Callable[..., Mapping[str, Any]] | None: ...

    @property
    def goal_confirmation_adopter(self) -> Callable[..., Any] | None: ...

    @property
    def scientific_goal_confirmation_adopter(self) -> Callable[..., Any] | None: ...


@dataclass(frozen=True, slots=True)
class RegisteredCanonicalProgram:
    """Immutable server-owned registry result used by downstream policies."""

    descriptor: CanonicalProgramDescriptor
    hook: CanonicalProgramHook
    authorization_resolver: Callable[..., Any]
    launch_plan_builder: Callable[..., CanonicalProgramLaunchPlanV1]
    episode_preparer: Callable[..., Mapping[str, Any]] | None = None
    goal_confirmation_adopter: Callable[..., Any] | None = None
    scientific_goal_confirmation_adopter: Callable[..., Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, CanonicalProgramDescriptor):
            raise CanonicalProgramRegistryError(
                "registered descriptor must be CanonicalProgramDescriptor"
            )
        if not callable(self.authorization_resolver):
            raise CanonicalProgramRegistryError(
                "registered authorization_resolver must be callable"
            )
        if not callable(self.launch_plan_builder):
            raise CanonicalProgramRegistryError(
                "registered launch_plan_builder must be callable"
            )
        if self.episode_preparer is not None and not callable(self.episode_preparer):
            raise CanonicalProgramRegistryError(
                "registered episode_preparer must be callable when provided"
            )
        if self.goal_confirmation_adopter is not None and not callable(
            self.goal_confirmation_adopter
        ):
            raise CanonicalProgramRegistryError(
                "registered goal_confirmation_adopter must be callable when provided"
            )
        if self.scientific_goal_confirmation_adopter is not None and not callable(
            self.scientific_goal_confirmation_adopter
        ):
            raise CanonicalProgramRegistryError(
                "registered scientific_goal_confirmation_adopter must be callable "
                "when provided"
            )


class CanonicalProgramRegistry:
    """Fail-closed mapping from an exact key to one in-process hook."""

    def __init__(self) -> None:
        self._entries: dict[CanonicalProgramKey, RegisteredCanonicalProgram] = {}
        self._lock = RLock()

    @staticmethod
    def _revalidate(
        registered: RegisteredCanonicalProgram,
    ) -> RegisteredCanonicalProgram:
        if getattr(registered.hook, "descriptor", None) != registered.descriptor:
            raise CanonicalProgramConflictError(
                "registered hook descriptor changed after registration"
            )
        resolver = getattr(registered.hook, "authorization_resolver", None)
        if not callable(resolver) or resolver != registered.authorization_resolver:
            raise CanonicalProgramConflictError(
                "registered hook authorization_resolver changed after registration"
            )
        builder = getattr(registered.hook, "launch_plan_builder", None)
        if not callable(builder) or builder != registered.launch_plan_builder:
            raise CanonicalProgramConflictError(
                "registered hook launch_plan_builder changed after registration"
            )
        preparer = getattr(registered.hook, "episode_preparer", None)
        if preparer != registered.episode_preparer:
            raise CanonicalProgramConflictError(
                "registered hook episode_preparer changed after registration"
            )
        adopter = getattr(registered.hook, "goal_confirmation_adopter", None)
        if adopter != registered.goal_confirmation_adopter:
            raise CanonicalProgramConflictError(
                "registered hook goal_confirmation_adopter changed after registration"
            )
        scientific_adopter = getattr(
            registered.hook, "scientific_goal_confirmation_adopter", None
        )
        if scientific_adopter != registered.scientific_goal_confirmation_adopter:
            raise CanonicalProgramConflictError(
                "registered hook scientific_goal_confirmation_adopter changed "
                "after registration"
            )
        return registered

    def register(self, hook: CanonicalProgramHook) -> CanonicalProgramDescriptor:
        descriptor = getattr(hook, "descriptor", None)
        if not isinstance(descriptor, CanonicalProgramDescriptor):
            raise CanonicalProgramRegistryError(
                "hook must expose a CanonicalProgramDescriptor"
            )
        authorization_resolver = getattr(hook, "authorization_resolver", None)
        if not callable(authorization_resolver):
            raise CanonicalProgramRegistryError(
                "hook must expose a callable authorization_resolver"
            )
        launch_plan_builder = getattr(hook, "launch_plan_builder", None)
        if not callable(launch_plan_builder):
            raise CanonicalProgramRegistryError(
                "hook must expose a callable launch_plan_builder"
            )
        episode_preparer = getattr(hook, "episode_preparer", None)
        if episode_preparer is not None and not callable(episode_preparer):
            raise CanonicalProgramRegistryError(
                "hook episode_preparer must be callable when provided"
            )
        goal_confirmation_adopter = getattr(hook, "goal_confirmation_adopter", None)
        if goal_confirmation_adopter is not None and not callable(
            goal_confirmation_adopter
        ):
            raise CanonicalProgramRegistryError(
                "hook goal_confirmation_adopter must be callable when provided"
            )
        scientific_goal_confirmation_adopter = getattr(
            hook, "scientific_goal_confirmation_adopter", None
        )
        if scientific_goal_confirmation_adopter is not None and not callable(
            scientific_goal_confirmation_adopter
        ):
            raise CanonicalProgramRegistryError(
                "hook scientific_goal_confirmation_adopter must be callable when "
                "provided"
            )

        with self._lock:
            existing = self._entries.get(descriptor.key)
            if existing is not None:
                self._revalidate(existing)
                if existing.hook is hook:
                    raise CanonicalProgramDuplicateError(
                        "canonical program hook is already registered"
                    )
                raise CanonicalProgramConflictError(
                    "canonical program identity is already owned by another hook"
                )

            self._entries[descriptor.key] = RegisteredCanonicalProgram(
                descriptor=descriptor,
                hook=hook,
                authorization_resolver=authorization_resolver,
                launch_plan_builder=launch_plan_builder,
                episode_preparer=episode_preparer,
                goal_confirmation_adopter=goal_confirmation_adopter,
                scientific_goal_confirmation_adopter=(
                    scientific_goal_confirmation_adopter
                ),
            )
        return descriptor

    def resolve(
        self,
        *,
        program_id: str,
        program_version: str,
        executor_id: str,
        executor_version: str,
    ) -> RegisteredCanonicalProgram:
        key = CanonicalProgramKey(
            program_id=program_id,
            program_version=program_version,
            executor_id=executor_id,
            executor_version=executor_version,
        )
        with self._lock:
            registered = self._entries.get(key)
            if registered is None:
                raise CanonicalProgramNotRegisteredError(
                    "exact canonical program and executor version is not registered"
                )
            return self._revalidate(registered)

    def resolve_admission_program(
        self, *, program_id: str
    ) -> RegisteredCanonicalProgram:
        """Resolve one server-owned preparer without selecting a version implicitly."""

        normalized_program_id = _identifier("program_id", program_id)
        with self._lock:
            candidates = tuple(
                self._revalidate(registered)
                for key, registered in self._entries.items()
                if key.program_id == normalized_program_id
                and registered.episode_preparer is not None
            )
        if not candidates:
            raise CanonicalProgramNotRegisteredError(
                "canonical program has no registered admission preparer"
            )
        if len(candidates) != 1:
            raise CanonicalProgramConflictError(
                "canonical program_id has ambiguous registered admission preparers"
            )
        return candidates[0]

    def registered_descriptors(self) -> tuple[CanonicalProgramDescriptor, ...]:
        with self._lock:
            return tuple(
                self._revalidate(self._entries[key]).descriptor
                for key in sorted(self._entries)
            )

    def registered_goal_confirmation_programs(
        self,
    ) -> tuple[RegisteredCanonicalProgram, ...]:
        """Return exact registered programs that explicitly adopt Goal candidates."""

        with self._lock:
            return tuple(
                registered
                for key in sorted(self._entries)
                if (
                    registered := self._revalidate(self._entries[key])
                ).goal_confirmation_adopter
                is not None
            )

    def registered_scientific_goal_confirmation_programs(
        self,
    ) -> tuple[RegisteredCanonicalProgram, ...]:
        """Return exact programs that opt into the scientific Goal contract."""

        with self._lock:
            return tuple(
                registered
                for key in sorted(self._entries)
                if (
                    registered := self._revalidate(self._entries[key])
                ).scientific_goal_confirmation_adopter
                is not None
            )


# Empty by design.  Successor program modules may register only after they adopt
# the canonical storage and authority contracts.  Frozen V1 implementations do
# not become canonical-capable merely because this registry exists.
CANONICAL_PROGRAM_REGISTRY = CanonicalProgramRegistry()


__all__ = [
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
    "RegisteredCanonicalProgram",
]
