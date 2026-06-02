"""
Environment loading utilities for Brain Researcher services.

This module centralizes ``python-dotenv`` usage so that every service can
load environment variables from the nearest repo dotenv files exactly once.

Precedence is:
1. Existing process environment
2. ``.env.local``
3. ``.env``
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

_load_lock = threading.Lock()
_loaded: bool = False
_loaded_path: Optional[Path] = None


def _discover_env_files(find_dotenv) -> list[Path]:
    files: list[Path] = []

    env_path_str = find_dotenv(".env", usecwd=True)
    env_file = Path(env_path_str) if env_path_str else None
    if env_file and env_file.exists():
        files.append(env_file.resolve())
        local_sibling = env_file.with_name(".env.local")
        if local_sibling.exists():
            files.append(local_sibling.resolve())
            return files

    env_local_path_str = find_dotenv(".env.local", usecwd=True)
    env_local_file = Path(env_local_path_str) if env_local_path_str else None
    if env_local_file and env_local_file.exists():
        resolved = env_local_file.resolve()
        if resolved not in files:
            files.append(resolved)

    return files


def _merge_env_file(
    env_file: Path,
    *,
    protected_keys: set[str],
    dotenv_values,
    override: bool,
) -> None:
    values = dotenv_values(env_file)
    for key, value in values.items():
        if value is None:
            continue
        if override or key not in protected_keys:
            os.environ[key] = value


def ensure_env_loaded(*, override: bool = False) -> Optional[Path]:
    """
    Load environment variables from the closest repo ``.env`` / ``.env.local``
    files if available.

    Args:
        override: When ``True`` the discovered ``.env`` file will be reloaded
            even if it has already been processed.

    Returns:
        The resolved ``Path`` to the most specific loaded dotenv file, or
        ``None`` when no dotenv file was discovered or ``python-dotenv`` is
        not installed.
    """

    global _loaded, _loaded_path

    if _loaded and not override:
        return _loaded_path

    with _load_lock:
        if _loaded and not override:
            return _loaded_path

        if os.getenv("BRAIN_RESEARCHER_SKIP_DOTENV"):
            _loaded = True
            _loaded_path = None
            return _loaded_path

        try:  # pragma: no cover - optional dependency
            from dotenv import dotenv_values, find_dotenv  # type: ignore
        except Exception:  # pragma: no cover - py-dotenv not available
            _loaded = True
            _loaded_path = None
            return _loaded_path

        env_files = _discover_env_files(find_dotenv)
        if env_files:
            protected_keys = set(os.environ)
            for env_file in env_files:
                _merge_env_file(
                    env_file,
                    protected_keys=protected_keys,
                    dotenv_values=dotenv_values,
                    override=override,
                )
            _loaded = True
            _loaded_path = env_files[-1]
            return _loaded_path

        _loaded = True
        _loaded_path = None
        return _loaded_path


__all__ = ["ensure_env_loaded"]
