"""Sandbox isolation for container execution (P3.8).

Provides security isolation via Apptainer flags, read-only mounts,
path validation, and network isolation.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_RELAXED_PATH_COUNTER = 0


def _record_relaxed_mode(*, source: str, run_dir: Optional[str], reason: str) -> None:
    """Record that sandbox strict validation has been relaxed.

    Keeps an in-process counter so operators can observe how often we drop to
    non-strict mode and emits a structured warning for log-based monitoring.
    """

    global _RELAXED_PATH_COUNTER
    _RELAXED_PATH_COUNTER += 1
    logger.warning(
        "Sandbox strict path validation disabled (count=%d, source=%s, reason=%s, run_dir=%s)",
        _RELAXED_PATH_COUNTER,
        source,
        reason,
        run_dir,
    )


def get_relaxed_mode_count() -> int:
    """Return how many times we've relaxed sandbox validation (primarily for tests)."""

    return _RELAXED_PATH_COUNTER


def reset_relaxed_mode_counter_for_tests() -> None:
    """Reset relaxed-mode counter (used by unit tests to ensure isolation)."""

    global _RELAXED_PATH_COUNTER
    _RELAXED_PATH_COUNTER = 0


@dataclass
class MountSpec:
    """Specification for a container mount point."""

    host_path: str  # Path on host system
    container_path: str  # Path inside container
    read_only: bool = True  # Read-only by default for security

    def to_bind_flag(self) -> str:
        """Convert to apptainer bind flag format."""
        mode = "ro" if self.read_only else "rw"
        return f"{self.host_path}:{self.container_path}:{mode}"


@dataclass
class SandboxConfig:
    """Complete sandbox configuration for a container execution."""

    enabled: bool = True  # Master switch for sandbox
    clean_env: bool = True  # Use --cleanenv to clear host environment
    writable_tmpfs: bool = True  # Use --writable-tmpfs for temp space
    no_home: bool = True  # Use --no-home to prevent home dir access
    containall: bool = True  # Use --containall for full isolation
    network_isolated: bool = True  # Disable network access
    mounts: List[MountSpec] = field(default_factory=list)  # Mount specifications
    allowed_paths: List[str] = field(default_factory=list)  # Allowed path prefixes

    def get_apptainer_flags(self) -> List[str]:
        """Get all apptainer flags for this sandbox config."""
        flags = []

        if not self.enabled:
            return flags

        if self.no_home:
            flags.append("--no-home")

        if self.containall:
            flags.append("--containall")

        if self.clean_env:
            flags.append("--cleanenv")

        if self.writable_tmpfs:
            flags.append("--writable-tmpfs")

        if self.network_isolated:
            flags.extend(["--net", "--network", "none"])

        return flags

    def get_mount_flags(self) -> List[str]:
        """Get all mount bind flags."""
        flags = []
        for mount in self.mounts:
            flags.extend(["-B", mount.to_bind_flag()])
        return flags


def validate_path(path: str, strict: bool = True) -> bool:
    """Validate path against traversal attacks and suspicious patterns.

    Args:
        path: Path to validate
        strict: If True, enforce strict validation rules

    Returns:
        True if path is valid

    Raises:
        ValueError: If path contains suspicious patterns
    """
    if not path:
        raise ValueError("Empty path not allowed")

    # Check for parent directory traversal
    if ".." in path:
        raise ValueError(f"Path contains '..' (directory traversal): {path}")

    # Check for null bytes
    if "\x00" in path:
        raise ValueError(f"Path contains null byte: {path}")

    # In strict mode, validate absolute paths.
    #
    # The orchestrator frequently runs from a repo checkout during development/CI, so
    # we allow paths under the current working directory in addition to common
    # "safe" system prefixes. This keeps strict mode useful (blocks traversal and
    # obvious exfil paths) without making local temp paths unusable.
    if strict and path.startswith("/"):
        resolved = Path(path).expanduser().resolve(strict=False)
        cwd = Path.cwd().resolve()

        # List of allowed absolute path prefixes
        allowed_prefixes = [
            "/cvmfs",  # CVMFS distributed filesystem
            "/ref",  # Reference data
            "/data",  # Data directories
            "/tmp",  # Temporary files
            "/var/tmp",  # Temporary files (alternate)
            "/outputs",  # Output directory (inside container)
            "/inputs",  # Input directory (inside container)
        ]

        if not any(str(resolved).startswith(prefix) for prefix in allowed_prefixes) and not resolved.is_relative_to(cwd):
            raise ValueError(
                f"Absolute path outside allowed directories: {path}. "
                f"Allowed prefixes: {', '.join(allowed_prefixes)} "
                f"(or under cwd={cwd})"
            )

    # Check for suspicious patterns
    suspicious_patterns = [
        "/etc/",
        "/root/",
        "/.ssh/",
        "/.aws/",
        "/proc/",
        "/sys/",
    ]

    for pattern in suspicious_patterns:
        if pattern in path:
            raise ValueError(f"Path contains suspicious pattern '{pattern}': {path}")

    logger.debug(f"Path validation passed: {path}")
    return True


def validate_paths(paths: List[str], strict: bool = True) -> bool:
    """Validate multiple paths.

    Args:
        paths: List of paths to validate
        strict: If True, enforce strict validation rules

    Returns:
        True if all paths are valid

    Raises:
        ValueError: If any path is invalid
    """
    for path in paths:
        validate_path(path, strict=strict)
    return True


def build_sandbox_flags() -> List[str]:
    """Build apptainer sandbox flags from environment configuration.

    Returns:
        List of sandbox flags to pass to apptainer exec

    Environment Variables:
        BR_SANDBOX_ENABLED: Master switch (default: true)
        BR_SANDBOX_CLEAN_ENV: Clear environment (default: true)
        BR_SANDBOX_WRITABLE_TMPFS: Writable tmpfs (default: true)
        BR_SANDBOX_NET: Network mode (default: isolated)
    """
    flags = []

    enabled = os.getenv("BR_SANDBOX_ENABLED", "true").lower() == "true"
    if not enabled:
        logger.info("Sandbox disabled via BR_SANDBOX_ENABLED=false")
        return flags

    # No-home: Prevent access to user home directory
    flags.append("--no-home")

    # Containall: Maximum isolation
    flags.append("--containall")

    # Clean environment
    if os.getenv("BR_SANDBOX_CLEAN_ENV", "true").lower() == "true":
        flags.append("--cleanenv")

    # Writable tmpfs for scratch space
    if os.getenv("BR_SANDBOX_WRITABLE_TMPFS", "true").lower() == "true":
        flags.append("--writable-tmpfs")

    # Network isolation
    net_mode = os.getenv("BR_SANDBOX_NET", "isolated").lower()
    if net_mode == "isolated":
        flags.extend(["--net", "--network", "none"])

    logger.debug(f"Built sandbox flags: {flags}")
    return flags


def build_sandbox_config(
    run_dir: str,
    input_paths: Optional[List[str]] = None,
    allow_cvmfs: bool = True,
    allow_ref: bool = True,
    strict_paths: Optional[bool] = None,
    source: str = "sandbox",
) -> SandboxConfig:
    """Build a complete sandbox configuration.

    Args:
        run_dir: Run directory for outputs (will be mounted as /outputs)
        input_paths: List of input file paths to mount read-only
        allow_cvmfs: If True, mount /cvmfs as read-only
        allow_ref: If True, mount /ref as read-only
        strict_paths: If True, enforce strict path validation (default: from env)
        source: Identifier recorded in logs/metrics when strict validation is relaxed

    Returns:
        SandboxConfig with all mounts and settings

    Environment Variables:
        BR_SANDBOX_ENABLED: Master switch
        BR_SANDBOX_STRICT_PATHS: Strict validation (default: true)
    """
    enabled = os.getenv("BR_SANDBOX_ENABLED", "true").lower() == "true"
    strict_reason = "caller"
    if strict_paths is None:
        strict_paths = os.getenv("BR_SANDBOX_STRICT_PATHS", "true").lower() == "true"
        strict_reason = "env"

    if not strict_paths:
        reason = "env_override" if strict_reason == "env" else "explicit"
        _record_relaxed_mode(source=source, run_dir=run_dir, reason=reason)

    config = SandboxConfig(
        enabled=enabled,
        clean_env=os.getenv("BR_SANDBOX_CLEAN_ENV", "true").lower() == "true",
        writable_tmpfs=os.getenv("BR_SANDBOX_WRITABLE_TMPFS", "true").lower() == "true",
        no_home=True,
        containall=True,
        network_isolated=os.getenv("BR_SANDBOX_NET", "isolated").lower() == "isolated",
    )

    # Build mount specifications
    mounts = []

    # Mount /cvmfs as read-only (if exists and enabled)
    if allow_cvmfs and os.path.exists("/cvmfs"):
        mounts.append(MountSpec(host_path="/cvmfs", container_path="/cvmfs", read_only=True))
        config.allowed_paths.append("/cvmfs")
        logger.debug("Added /cvmfs as read-only mount")

    # Mount /ref as read-only (if exists and enabled)
    if allow_ref and os.path.exists("/ref"):
        mounts.append(MountSpec(host_path="/ref", container_path="/ref", read_only=True))
        config.allowed_paths.append("/ref")
        logger.debug("Added /ref as read-only mount")

    # Mount input files/directories as read-only
    if input_paths:
        input_dirs = set()
        for input_path in input_paths:
            if strict_paths:
                try:
                    validate_path(input_path, strict=True)
                except ValueError as e:
                    logger.error(f"Input path validation failed: {e}")
                    raise

            # If it's a file, mount its parent directory
            # If it's a directory, mount it directly
            if os.path.isfile(input_path):
                parent_dir = str(Path(input_path).parent)
                input_dirs.add(parent_dir)
            elif os.path.isdir(input_path):
                input_dirs.add(input_path)
            else:
                logger.warning(f"Input path does not exist: {input_path}")

        for input_dir in sorted(input_dirs):
            mounts.append(MountSpec(host_path=input_dir, container_path=input_dir, read_only=True))
            config.allowed_paths.append(input_dir)
            logger.debug(f"Added {input_dir} as read-only mount")

    # Mount run_dir/outputs as read-write (only writable location)
    outputs_dir = os.path.join(run_dir, "outputs")
    Path(outputs_dir).mkdir(parents=True, exist_ok=True)
    mounts.append(MountSpec(host_path=outputs_dir, container_path="/outputs", read_only=False))
    config.allowed_paths.append("/outputs")
    logger.debug(f"Added {outputs_dir} → /outputs as read-write mount")

    config.mounts = mounts

    logger.info(
        f"Built sandbox config: {len(mounts)} mounts, "
        f"network_isolated={config.network_isolated}, "
        f"clean_env={config.clean_env}"
    )

    return config
