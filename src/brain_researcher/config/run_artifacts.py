"""Configuration for run artifacts and provenance tracking.

This module provides centralized configuration for the run recording system,
including environment variable parsing, canonical run path helpers, and
cleanup-scan guardrails.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_DATE_DIR_RE = re.compile(r"^\d{8}$")
ACTIVE_RUN_STATES = frozenset({"running", "queued", "in_progress", "pending"})
ACTIVE_RUN_MTIME_SECS = 120
METADATA_ROOT_DEFAULT = (REPO_ROOT / "artifacts" / "metadata").resolve()
METADATA_ROOT_LEGACY_FALLBACK = (REPO_ROOT / "metadata").resolve()
RECORDER_ROOT_LEGACY_FALLBACK = (REPO_ROOT / "data" / "runs").resolve()
MCP_RUN_ROOT_DEFAULT = (REPO_ROOT / "data" / "runs" / "mcp_runs").resolve()
MCP_RUN_ROOT_LEGACY_FALLBACK = (REPO_ROOT / "artifacts" / "mcp_runs").resolve()
RUN_PATH_ALIASES: tuple[tuple[Path, Path], ...] = (
    (MCP_RUN_ROOT_LEGACY_FALLBACK, MCP_RUN_ROOT_DEFAULT),
)


def _env_bool(key: str, default: bool) -> bool:
    """Parse boolean from environment variable."""
    value = os.environ.get(key, "").lower()
    if value in ("true", "1", "yes", "on"):
        return True
    elif value in ("false", "0", "no", "off"):
        return False
    return default


def _env_int(key: str, default: int) -> int:
    """Parse integer from environment variable."""
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def _env_path(key: str, default: str) -> Path:
    """Parse path from environment variable."""
    return Path(os.environ.get(key, default))


def _expand_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    return candidate.resolve()


def _parse_root_list(raw: str | None) -> tuple[Path, ...]:
    if not raw:
        return ()
    roots: list[Path] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        roots.append(_expand_path(value))
    return _unique_paths(roots)


def _unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = _expand_path(path)
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return tuple(unique)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        _expand_path(path).relative_to(_expand_path(root))
    except ValueError:
        return False
    return True


@dataclass
class RecorderConfig:
    """Configuration for RunRecorder.

    All settings can be overridden via environment variables:
    - BR_RUN_STORE_ENABLED: Enable/disable run recording (default: true)
    - BR_RUN_STORE_ROOT: Root directory for runs (default: data/runs)
    - BR_RUN_STORE_MAX_STD_BYTES: Max bytes for stdout/stderr before truncation (default: 1MB)
    - BR_OUTPUT_COPY_ENABLED: Enable output file collection (default: false)
    - BR_OUTPUT_COPY_MAX_BYTES: Max bytes per output file (default: 100MB)
    - BR_OUTPUT_COPY_RUN_MAX_BYTES: Max total bytes per run (default: 1GB)
    """

    # Core settings
    enabled: bool = field(
        default_factory=lambda: _env_bool("BR_RUN_STORE_ENABLED", True)
    )
    root: Path = field(
        default_factory=lambda: _env_path("BR_RUN_STORE_ROOT", "data/runs")
    )

    # Log capture settings
    max_std_bytes: int = field(
        default_factory=lambda: _env_int("BR_RUN_STORE_MAX_STD_BYTES", 1_048_576)
    )  # 1MB

    # Output collection settings
    output_enabled: bool = field(
        default_factory=lambda: _env_bool("BR_OUTPUT_COPY_ENABLED", False)
    )
    output_max_per_file: int = field(
        default_factory=lambda: _env_int("BR_OUTPUT_COPY_MAX_BYTES", 104_857_600)
    )  # 100MB
    output_max_per_run: int = field(
        default_factory=lambda: _env_int("BR_OUTPUT_COPY_RUN_MAX_BYTES", 1_073_741_824)
    )  # 1GB

    # File type filter for output collection
    output_extensions: set[str] = field(
        default_factory=lambda: {
            ".nii",
            ".nii.gz",
            ".json",
            ".tsv",
            ".txt",
            ".brik",
            ".BRIK",
            ".head",
            ".HEAD",
            ".mif",
        }
    )

    # Environment variable allowlist (only these keys will be persisted)
    env_allowlist: set[str] = field(
        default_factory=lambda: {
            "PATH",
            "FSLDIR",
            "FREESURFER_HOME",
            "AFNI_PLUGINPATH",
            "MRTRIX_ROOT",
            "ANTSPATH",
            "ARTHOME",
        }
    )

    # Patterns to redact (even if in allowlist)
    env_redact_patterns: list[str] = field(
        default_factory=lambda: [
            "LICENSE",
            "SECRET",
            "KEY",
            "TOKEN",
            "PASSWORD",
            "CREDENTIALS",
        ]
    )

    # Input fingerprinting (provenance)
    inputs_fingerprints_enabled: bool = field(
        default_factory=lambda: _env_bool("BR_INPUT_FINGERPRINTS_ENABLED", True)
    )
    inputs_fingerprints_max_hash_mb: int = field(
        default_factory=lambda: _env_int("BR_INPUT_FINGERPRINTS_MAX_MB", 128)
    )


# Singleton instance
_config: RecorderConfig | None = None


def get_repo_root() -> Path:
    """Return the repository root used for canonical artifact paths."""
    return REPO_ROOT


def get_recorder_config() -> RecorderConfig:
    """Get the global RecorderConfig instance."""
    global _config
    if _config is None:
        _config = RecorderConfig()
    return _config


def get_recorder_root(
    cfg: RecorderConfig | None = None,
    *,
    resolve: bool = False,
) -> Path:
    """Return the recorder root path.

    Relative paths are preserved by default so persisted run paths keep their
    historical shape. Set ``resolve=True`` when the caller needs a canonical
    absolute path for comparisons or security checks.
    """

    root = Path((cfg or get_recorder_config()).root)
    if resolve:
        return _expand_path(root)
    return root


def get_recorder_root_aliases(primary_root: Path | None = None) -> tuple[Path, ...]:
    """Return recorder-root aliases used for backward-compatible reads."""

    primary = _expand_path(primary_root or get_recorder_root(resolve=True))
    aliases = _parse_root_list(os.getenv("BR_RUN_STORE_ROOT_ALIASES"))
    if not aliases and primary != RECORDER_ROOT_LEGACY_FALLBACK:
        aliases = (RECORDER_ROOT_LEGACY_FALLBACK,)
    return tuple(alias for alias in aliases if alias != primary)


def get_recorder_roots_for_read(primary_root: Path | None = None) -> tuple[Path, ...]:
    """Return primary recorder root plus readable legacy aliases."""

    primary = _expand_path(primary_root or get_recorder_root(resolve=True))
    return _unique_paths((primary, *get_recorder_root_aliases(primary)))


def iter_recorded_path_candidates(
    path: Path | str,
    *,
    primary_root: Path | None = None,
) -> Iterator[Path]:
    """Yield canonical and legacy candidates for a recorded run-store path."""

    primary = _expand_path(primary_root or get_recorder_root(resolve=True))
    raw = Path(path).expanduser()
    roots = get_recorder_roots_for_read(primary)

    def _yield_existing_mapping(resolved: Path) -> Iterator[Path]:
        seen: set[str] = set()
        for root in roots:
            try:
                relative = resolved.relative_to(root)
            except ValueError:
                continue
            mapped = (primary / relative).resolve()
            for candidate in (mapped, resolved):
                key = str(candidate)
                if key in seen:
                    continue
                seen.add(key)
                yield candidate
            return
        yield resolved

    if raw.is_absolute():
        yield from _yield_existing_mapping(raw.resolve())
        return

    expanded = _expand_path(raw)
    yielded = False
    for candidate in _yield_existing_mapping(expanded):
        yielded = True
        yield candidate
    if yielded:
        return

    yield (primary / raw).resolve()


def resolve_recorded_path_for_read(
    path: Path | str,
    *,
    primary_root: Path | None = None,
) -> Path:
    """Resolve a recorded run-store path to the best readable candidate."""

    candidates = tuple(
        iter_recorded_path_candidates(path, primary_root=primary_root)
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def run_date_str(when: datetime | None = None) -> str:
    """Return the YYYYMMDD date bucket used for recorded runs."""
    return (when or datetime.now()).strftime("%Y%m%d")


def build_run_base_dir(
    root: Path | str,
    run_id: str,
    *,
    when: datetime | None = None,
    parent_run_id: str | None = None,
    step_id: str | None = None,
) -> Path:
    """Build the base directory for a run before attempt suffixing."""

    root_path = Path(root)
    day_root = root_path / run_date_str(when)
    if parent_run_id and step_id:
        return day_root / parent_run_id / "steps" / step_id
    return day_root / run_id


def build_run_dir(
    root: Path | str,
    run_id: str,
    *,
    when: datetime | None = None,
    parent_run_id: str | None = None,
    step_id: str | None = None,
    attempt: int = 1,
) -> Path:
    """Build the final run directory path for a recorder or run bundle."""

    base_dir = build_run_base_dir(
        root,
        run_id,
        when=when,
        parent_run_id=parent_run_id,
        step_id=step_id,
    )
    if attempt > 1:
        return base_dir / f"attempt-{attempt}"
    return base_dir


def is_run_date_dir(path: Path) -> bool:
    """Return True when the directory matches the recorder date-bucket layout."""
    return path.is_dir() and bool(RUN_DATE_DIR_RE.fullmatch(path.name))


def get_metadata_root() -> Path:
    """Return the canonical metadata root for new runtime writes.

    Phase 1 only centralizes path resolution. Existing call sites may still
    write to the legacy ``metadata`` root until they are migrated to this
    helper in a later phase.
    """

    return _expand_path(os.getenv("BR_METADATA_DIR", str(METADATA_ROOT_DEFAULT)))


def get_metadata_root_aliases(primary_root: Path | None = None) -> tuple[Path, ...]:
    """Return metadata-root aliases used for backward-compatible reads."""

    primary = _expand_path(primary_root or get_metadata_root())
    aliases = _parse_root_list(os.getenv("BR_METADATA_DIR_ALIASES"))
    if not aliases and primary != METADATA_ROOT_LEGACY_FALLBACK:
        aliases = (METADATA_ROOT_LEGACY_FALLBACK,)
    return tuple(alias for alias in aliases if alias != primary)


def get_metadata_roots_for_read(primary_root: Path | None = None) -> tuple[Path, ...]:
    """Return the primary metadata root plus readable legacy aliases."""

    primary = _expand_path(primary_root or get_metadata_root())
    return _unique_paths((primary, *get_metadata_root_aliases(primary)))


def get_mcp_run_root() -> Path:
    """Return the canonical MCP run root."""
    return _expand_path(os.getenv("BR_MCP_RUN_ROOT", str(MCP_RUN_ROOT_DEFAULT)))


def get_mcp_run_root_aliases(primary_root: Path | None = None) -> tuple[Path, ...]:
    """Return MCP run-root aliases used for backward-compatible reads."""

    primary = _expand_path(primary_root or get_mcp_run_root())
    aliases = _parse_root_list(os.getenv("BR_MCP_RUN_ROOT_ALIASES"))
    if not aliases and primary != MCP_RUN_ROOT_LEGACY_FALLBACK:
        aliases = (MCP_RUN_ROOT_LEGACY_FALLBACK,)
    return tuple(alias for alias in aliases if alias != primary)


def get_mcp_run_roots_for_read(primary_root: Path | None = None) -> tuple[Path, ...]:
    """Return primary MCP run root plus readable aliases."""

    primary = _expand_path(primary_root or get_mcp_run_root())
    return _unique_paths((primary, *get_mcp_run_root_aliases(primary)))


def build_mcp_run_dir(run_id: str, root: Path | str | None = None) -> Path:
    """Build the metadata directory for an MCP run."""

    base_root = Path(root) if root is not None else get_mcp_run_root()
    return base_root / "runs" / run_id


def iter_mcp_run_dir_candidates(
    run_id: str,
    primary_root: Path | str | None = None,
) -> Iterator[Path]:
    """Yield MCP run directory candidates across the primary root and aliases."""

    primary = Path(primary_root) if primary_root is not None else get_mcp_run_root()
    for root in get_mcp_run_roots_for_read(primary):
        yield build_mcp_run_dir(run_id, root)


def iter_mcp_run_dirs(root: Path | str | None = None) -> Iterator[Path]:
    """Yield direct MCP run directories under the metadata ``runs/`` tree."""

    base_root = Path(root) if root is not None else get_mcp_run_root()
    runs_root = base_root / "runs"
    if not runs_root.exists():
        return
    for run_dir in sorted(runs_root.iterdir()):
        if run_dir.is_dir():
            yield run_dir


def get_cleanup_excluded_run_roots(runs_root: Path | str) -> tuple[Path, ...]:
    """Return run subtrees that must not be treated as date-bucketed runs."""

    root = _expand_path(runs_root)
    return tuple(
        candidate
        for candidate in get_mcp_run_roots_for_read()
        if candidate != root and _is_relative_to(candidate, root)
    )


def iter_run_date_dirs(
    runs_root: Path | str,
    *,
    excluded_roots: Sequence[Path] | None = None,
) -> Iterator[Path]:
    """Yield date-bucket directories under a run store, excluding special roots."""

    root = Path(runs_root)
    if not root.exists():
        return

    excluded = _unique_paths(
        get_cleanup_excluded_run_roots(root)
        if excluded_roots is None
        else excluded_roots
    )
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        child_resolved = _expand_path(child)
        if any(child_resolved == excluded_root for excluded_root in excluded):
            continue
        if not is_run_date_dir(child):
            continue
        yield child


def iter_recorded_run_dirs(
    runs_root: Path | str,
    *,
    excluded_roots: Sequence[Path] | None = None,
) -> Iterator[Path]:
    """Yield recorded run directories from YYYYMMDD/date-bucketed stores only."""

    for date_dir in iter_run_date_dirs(runs_root, excluded_roots=excluded_roots):
        for run_dir in sorted(date_dir.iterdir()):
            if run_dir.is_dir():
                yield run_dir


def is_active_run(
    state: str,
    mtime: float,
    *,
    now_ts: float | None = None,
) -> bool:
    """Return True when a run should be considered active for cleanup."""

    normalized = str(state or "unknown").strip().lower()
    if normalized in ACTIVE_RUN_STATES:
        return True
    current_ts = time.time() if now_ts is None else now_ts
    return (current_ts - mtime) <= ACTIVE_RUN_MTIME_SECS


def reset_recorder_config() -> None:
    """Reset the global config (useful for testing)."""
    global _config
    _config = None


__all__ = [
    "ACTIVE_RUN_MTIME_SECS",
    "ACTIVE_RUN_STATES",
    "METADATA_ROOT_DEFAULT",
    "METADATA_ROOT_LEGACY_FALLBACK",
    "RECORDER_ROOT_LEGACY_FALLBACK",
    "MCP_RUN_ROOT_DEFAULT",
    "MCP_RUN_ROOT_LEGACY_FALLBACK",
    "RUN_PATH_ALIASES",
    "RecorderConfig",
    "build_run_base_dir",
    "build_run_dir",
    "build_mcp_run_dir",
    "get_cleanup_excluded_run_roots",
    "get_metadata_root",
    "get_metadata_root_aliases",
    "get_metadata_roots_for_read",
    "get_recorder_root_aliases",
    "get_recorder_roots_for_read",
    "get_mcp_run_root",
    "get_mcp_run_root_aliases",
    "get_mcp_run_roots_for_read",
    "get_recorder_config",
    "get_recorder_root",
    "get_repo_root",
    "is_active_run",
    "is_run_date_dir",
    "iter_recorded_path_candidates",
    "iter_recorded_run_dirs",
    "iter_mcp_run_dir_candidates",
    "iter_mcp_run_dirs",
    "iter_run_date_dirs",
    "reset_recorder_config",
    "resolve_recorded_path_for_read",
    "run_date_str",
]
