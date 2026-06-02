"""
Agent runtime dependency bootstrapper.

This module ensures the agent service has all Python packages it depends on by
running a pip installation step at process start. It supports environments
where the Docker image intentionally omits the full dependency graph (Option B
from the deployment discussion) and instead installs requirements on demand.

The bootstrap process is intentionally lightweight:
* It avoids importing any third-party modules.
* It skips installation when a sentinel file is present (unless forced).
* It allows customization via environment variables, so operators may choose
  their own requirement spec or installation target.

Environment variables:
    BR_AGENT_BOOTSTRAP_DISABLED   -> "1" to disable the bootstrap entirely.
    BR_AGENT_FORCE_BOOTSTRAP      -> "1" to force install even if sentinel exists.
    BR_AGENT_BOOTSTRAP_SPEC       -> Pip spec to install (default: editable ."[agent]").
    BR_AGENT_BOOTSTRAP_SENTINEL   -> Path to sentinel file (default: /tmp/agent_deps_installed).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def _default_project_root() -> Path:
    """Resolve repository root from current file location."""
    return Path(__file__).resolve().parents[4]


def _resolve_install_command(spec: str) -> List[str]:
    """
    Build the pip install command based on the provided spec.

    The default spec (`".[agent]"`) installs the project's editable
    distribution with the agent extras, which mirrors the
    dependencies required by the runtime tools. Callers can override this via
    BR_AGENT_BOOTSTRAP_SPEC for custom bundles (e.g., a requirements file).
    """
    if spec.startswith("requirements:"):
        req_path = spec.split(":", 1)[1]
        return [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "-r",
            req_path,
        ]

    # Default path-aware editable install.
    if spec.startswith("."):
        return [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "-e",
            spec,
        ]

    return [sys.executable, "-m", "pip", "install", "--no-cache-dir", spec]


def install_runtime_dependencies() -> None:
    """
    Ensure agent runtime dependencies are installed.

    This function is safe to call multiple times; by default subsequent calls
    will no-op thanks to the sentinel file. Set BR_AGENT_FORCE_BOOTSTRAP=1 to
    force reinstallation (useful for updates).
    """
    if os.getenv("BR_AGENT_BOOTSTRAP_DISABLED") == "1":
        logger.info("Agent runtime bootstrap disabled via environment variable.")
        return

    sentinel_path = Path(
        os.getenv("BR_AGENT_BOOTSTRAP_SENTINEL", "/tmp/agent_deps_installed")
    )
    force = os.getenv("BR_AGENT_FORCE_BOOTSTRAP") == "1"

    if sentinel_path.exists() and not force:
        logger.debug("Agent runtime dependencies already installed (sentinel found).")
        return

    spec = os.getenv("BR_AGENT_BOOTSTRAP_SPEC", ".[agent]")
    install_cmd = _resolve_install_command(spec)

    logger.info("Installing agent runtime dependencies using spec '%s'.", spec)
    logger.debug("Running install command: %s", install_cmd)

    try:
        subprocess.run(
            install_cmd,
            check=True,
            cwd=_default_project_root(),
        )
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to install agent runtime dependencies: %s", exc)
        raise

    try:
        sentinel_path.parent.mkdir(parents=True, exist_ok=True)
        sentinel_path.write_text("installed\n")
    except OSError as exc:
        logger.warning(
            "Unable to write bootstrap sentinel file %s: %s", sentinel_path, exc
        )


# Execute bootstrap at import time so the rest of the agent stack can assume
# dependencies are present.
install_runtime_dependencies()
