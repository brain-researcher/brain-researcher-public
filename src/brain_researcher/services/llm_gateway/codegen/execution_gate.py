"""Verification gates for constitution-aware codegen execution."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

PYTHON_CHECKABLE_SUFFIXES = {".py", ".pyi"}


@dataclass(frozen=True)
class VerificationPlan:
    """Plan describing how codegen output will be verified."""

    mode: str
    candidate_paths: tuple[Path, ...] = ()
    reason: str | None = None


def build_verification_plan(
    *,
    workdir: Path,
    materialized: Sequence[Path] | Sequence[str] = (),
    touched: Iterable[str] = (),
    test_command: str | None = None,
) -> VerificationPlan:
    """Pick the strongest available verification route.

    `test_command` wins when present. Otherwise we only allow syntax checks when
    there is concrete Python code to validate. When the model touched files, we
    require verification to target those touched files rather than unrelated
    materialized context.
    """

    if test_command:
        return VerificationPlan(mode="test_command")

    touched_items = [item for item in touched if item]
    touched_paths = _existing_python_paths(workdir, touched_items)
    if touched_items:
        if touched_paths:
            return VerificationPlan(
                mode="py_compile", candidate_paths=tuple(touched_paths)
            )
        return VerificationPlan(mode="none", reason=_missing_verification_reason())

    materialized_paths = _existing_python_paths(workdir, materialized)
    if materialized_paths:
        return VerificationPlan(
            mode="py_compile",
            candidate_paths=tuple(materialized_paths),
        )

    return VerificationPlan(mode="none", reason=_missing_verification_reason())


def _existing_python_paths(
    workdir: Path,
    candidates: Sequence[Path] | Sequence[str],
) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for item in candidates:
        rel = _normalize_candidate(item)
        if rel is None:
            continue
        full = rel if rel.is_absolute() else workdir / rel
        if not full.is_file():
            continue
        if full.suffix not in PYTHON_CHECKABLE_SUFFIXES:
            continue
        key = full.resolve()
        if key in seen:
            continue
        seen.add(key)
        resolved.append(full)
    return resolved


def _normalize_candidate(candidate: Path | str) -> Path | None:
    path = Path(candidate)
    if str(path) == "/dev/null":
        return None
    path_str = str(path)
    if path_str.startswith("a/") or path_str.startswith("b/"):
        path = Path(path_str[2:])
    return path


def _missing_verification_reason() -> str:
    return (
        "No verification evidence available: provide an allowed test command or "
        "touch/materialize Python files that can be checked. Silent success is "
        "forbidden by the codegen constitution."
    )


__all__ = ["VerificationPlan", "build_verification_plan"]
