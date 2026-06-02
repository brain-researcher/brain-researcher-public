"""Startup validation for bounded predictive and discovery autoresearch."""

from __future__ import annotations

import json
import os
import pwd
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from brain_researcher.autoresearch.artifact_schema import ArtifactPaths


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class StartupIssue:
    code: str
    message: str
    severity: str = "error"
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "path": self.path,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class SecretRequirement:
    name: str
    description: str | None = None
    optional: bool = False
    validator_command: tuple[str, ...] | None = None


@dataclass(frozen=True)
class StartupValidationResult:
    line_id: str
    issues: tuple[StartupIssue, ...]
    checked_paths: dict[str, str]
    checked_secrets: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
            "checked_paths": self.checked_paths,
            "checked_secrets": list(self.checked_secrets),
        }


def _default_owner_name() -> str:
    return pwd.getpwuid(os.getuid()).pw_name


def _issue(
    issues: list[StartupIssue],
    code: str,
    message: str,
    *,
    severity: str = "error",
    path: Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    issues.append(
        StartupIssue(
            code=code,
            message=message,
            severity=severity,
            path=None if path is None else str(path),
            metadata=metadata or {},
        )
    )


def _check_write_access(
    issues: list[StartupIssue],
    path: Path,
    *,
    owner_name: str,
) -> None:
    if not path.exists():
        return
    if not os.access(path, os.W_OK):
        _issue(
            issues,
            "ownership_mismatch",
            f"Runtime path is not writable by the current process owner `{owner_name}`.",
            path=path,
        )


def _validate_alias_roots(issues: list[StartupIssue], paths: ArtifactPaths) -> None:
    tracked_names = [paths.ledger_path.name]
    if paths.checkpoint_root is not None:
        tracked_names.extend(path.name for path in paths.scored_ledgers)
        tracked_names.append("closed_loop_checkpoint.json")

    for alias_root in paths.alias_project_roots:
        if not alias_root.exists():
            continue
        if alias_root.is_symlink():
            continue
        for name in tracked_names:
            candidate = alias_root / name
            if candidate.exists():
                _issue(
                    issues,
                    "alias_writable_artifact",
                    "Legacy or alias project root still contains writable tracked artifacts.",
                    path=candidate,
                )


def validate_secret_requirements(
    requirements: Sequence[SecretRequirement],
    *,
    env: Mapping[str, str] | None = None,
) -> list[StartupIssue]:
    issues: list[StartupIssue] = []
    effective_env = dict(os.environ)
    if env is not None:
        effective_env.update(env)
    for requirement in requirements:
        value = effective_env.get(requirement.name, "").strip()
        if not value:
            if not requirement.optional:
                _issue(
                    issues,
                    "missing_secret",
                    requirement.description
                    or f"Required secret `{requirement.name}` is missing.",
                )
            continue
        if requirement.validator_command:
            completed = subprocess.run(
                list(requirement.validator_command),
                capture_output=True,
                text=True,
                check=False,
                env=effective_env,
            )
            if completed.returncode != 0:
                _issue(
                    issues,
                    "invalid_secret",
                    f"Secret `{requirement.name}` failed validation: "
                    f"{completed.stderr.strip() or completed.stdout.strip() or 'validator exited non-zero'}.",
                )
    return issues


def _base_validation(
    paths: ArtifactPaths,
    *,
    owner_name: str | None = None,
) -> list[StartupIssue]:
    issues: list[StartupIssue] = []
    owner = owner_name or _default_owner_name()
    required_paths = (
        paths.line_root,
        paths.project_root,
        paths.artifact_root,
        paths.status_root,
        paths.inputs_root,
    )
    for path in required_paths:
        if not path.exists():
            _issue(
                issues,
                "missing_path",
                "Required runtime path does not exist.",
                path=path,
            )
            continue
        _check_write_access(issues, path, owner_name=owner)
    _validate_alias_roots(issues, paths)
    return issues


def validate_predictive_startup(
    paths: ArtifactPaths,
    *,
    manifest_path: Path | str | None = None,
    owner_name: str | None = None,
    secret_requirements: Sequence[SecretRequirement] = (),
    env: Mapping[str, str] | None = None,
) -> StartupValidationResult:
    issues = _base_validation(paths, owner_name=owner_name)
    data_manifest = (
        Path(manifest_path).expanduser().resolve()
        if manifest_path
        else (paths.project_root / "manifests" / "lane_b_data_manifest.json")
    )
    if not data_manifest.exists():
        _issue(
            issues,
            "missing_predictive_manifest",
            "Predictive data manifest is missing.",
            path=data_manifest,
        )
    else:
        payload = _read_json(data_manifest)
        cache_dir = Path(str(payload.get("term_cache_dir", ""))).expanduser()
        if not cache_dir.exists():
            _issue(
                issues,
                "missing_term_cache_dir",
                "Predictive term_iu cache directory is missing.",
                path=cache_dir,
            )
        elif not any(cache_dir.glob("term_*_iu.h5")):
            _issue(
                issues,
                "empty_term_cache_dir",
                "Predictive term_iu cache directory exists but has no materialized term cache files.",
                path=cache_dir,
            )
    issues.extend(validate_secret_requirements(secret_requirements, env=env))
    return StartupValidationResult(
        line_id=paths.line_id,
        issues=tuple(issues),
        checked_paths=paths.to_dict(),
        checked_secrets=tuple(requirement.name for requirement in secret_requirements),
    )


def validate_discovery_startup(
    paths: ArtifactPaths,
    *,
    manifest_index_path: Path | str | None = None,
    owner_name: str | None = None,
    secret_requirements: Sequence[SecretRequirement] = (),
    env: Mapping[str, str] | None = None,
    strict_biological_motion: bool = True,
) -> StartupValidationResult:
    issues = _base_validation(paths, owner_name=owner_name)
    manifest_index = (
        Path(manifest_index_path).expanduser().resolve()
        if manifest_index_path
        else paths.project_root / "manifests" / "wave1_manifest_index.json"
    )
    if not manifest_index.exists():
        _issue(
            issues,
            "missing_manifest_index",
            "Discovery manifest index is missing.",
            path=manifest_index,
        )
    else:
        index = _read_json(manifest_index)
        for task in index.get("tasks", []):
            manifest_path = Path(str(task.get("manifest_path", ""))).expanduser()
            if not manifest_path.exists():
                _issue(
                    issues,
                    "missing_task_manifest",
                    "Discovery task manifest referenced from manifest index is missing.",
                    path=manifest_path,
                    metadata={"task_id": task.get("task_id")},
                )
                continue
            if (
                strict_biological_motion
                and str(task.get("task_id")) == "ibc_biological_motion"
            ):
                manifest = _read_json(manifest_path)
                counts = manifest.get("condition_counts") or {}
                if not (
                    "intact_biological_motion" in counts
                    and "spatial_or_phase_scrambled_motion" in counts
                ):
                    _issue(
                        issues,
                        "biological_motion_harness_unresolved",
                        "Biological motion still uses the legacy biomo_type harness. "
                        "Materialize walkerdata.mat intact-vs-scrambled stimuli before live rollout.",
                        path=manifest_path,
                    )
    issues.extend(validate_secret_requirements(secret_requirements, env=env))
    return StartupValidationResult(
        line_id=paths.line_id,
        issues=tuple(issues),
        checked_paths=paths.to_dict(),
        checked_secrets=tuple(requirement.name for requirement in secret_requirements),
    )


def run_startup_validation(
    paths: ArtifactPaths,
    *,
    secret_requirements: Sequence[SecretRequirement] = (),
    env: Mapping[str, str] | None = None,
    strict_biological_motion: bool = True,
) -> StartupValidationResult:
    if paths.line_id == "predictive":
        return validate_predictive_startup(
            paths,
            secret_requirements=secret_requirements,
            env=env,
        )
    return validate_discovery_startup(
        paths,
        secret_requirements=secret_requirements,
        env=env,
        strict_biological_motion=strict_biological_motion,
    )


__all__ = [
    "SecretRequirement",
    "StartupIssue",
    "StartupValidationResult",
    "run_startup_validation",
    "validate_discovery_startup",
    "validate_predictive_startup",
    "validate_secret_requirements",
]
