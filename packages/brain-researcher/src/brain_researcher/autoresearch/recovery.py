"""Shared recovery and failure-normalization helpers for bounded autoresearch."""

from __future__ import annotations

from pathlib import Path

from .artifact_schema import ArtifactPaths
from .quality_protocol import RecoveryEvent

OOM_TOKENS = ("oom", "out of memory", "killed process", "oom-kill")
GPU_MISSING_TOKENS = ("cuda unavailable", "no cuda", "nvidia-smi", "no devices found")
PATH_DRIFT_TOKENS = ("no such file or directory", "path drift", "missing checkpoint")
MCP_CONFIG_TOKENS = ("mcp", "auth", "token", "forbidden", "unauthorized")


def classify_failure_text(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in OOM_TOKENS):
        return "oom"
    if any(token in lowered for token in GPU_MISSING_TOKENS):
        return "missing_gpu"
    if any(token in lowered for token in PATH_DRIFT_TOKENS):
        return "path_drift"
    if any(token in lowered for token in MCP_CONFIG_TOKENS):
        return "mcp_config"
    return "unknown"


def detect_missing_artifacts(paths: ArtifactPaths) -> list[str]:
    missing: list[str] = []
    if not paths.project_root.exists():
        missing.append("project_root")
    if paths.checkpoint_root is not None and not paths.checkpoint_root.exists():
        missing.append("checkpoint_root")
    if paths.diagnostics_root is not None and not paths.diagnostics_root.exists():
        missing.append("diagnostics_root")
    return missing


def detect_path_drift(paths: ArtifactPaths) -> bool:
    for alias_project_root in paths.alias_project_roots:
        if alias_project_root.exists() and alias_project_root.resolve() != paths.project_root:
            return True
    return False


def build_recovery_event(
    *,
    line_id: str,
    code: str,
    detail: str,
    status: str = "blocked",
    stop_reason: str = "needs_human_review",
    metadata: dict[str, object] | None = None,
) -> RecoveryEvent:
    return RecoveryEvent(
        line_id=line_id,
        status=status,
        stop_reason=stop_reason,
        code=code,
        detail=detail,
        metadata=None if metadata is None else dict(metadata),
    )


def latest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


__all__ = [
    "OOM_TOKENS",
    "GPU_MISSING_TOKENS",
    "PATH_DRIFT_TOKENS",
    "MCP_CONFIG_TOKENS",
    "build_recovery_event",
    "classify_failure_text",
    "detect_missing_artifacts",
    "detect_path_drift",
    "latest_existing_parent",
]
