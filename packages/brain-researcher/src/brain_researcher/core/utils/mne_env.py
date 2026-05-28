"""
Helpers to make MNE/Numba play nicely in constrained environments.

These utilities make sure the environment variables expected by MNE are set
before any heavy modules are imported.  The defaults disable numba disk
caching (which frequently fails inside ephemeral CI sandboxes) and ensure we
cache to a writable directory when caching is enabled.
"""

from __future__ import annotations

import logging
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)


def _ensure_dir(path: Path) -> Path:
    """Create *path* if it does not already exist."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - defensive logging
        logger.warning("Unable to create %s (%s); disabling numba caching", path, exc)
        os.environ["NUMBA_DISABLE_CACHING"] = "1"
    return path


@lru_cache(maxsize=1)
def configure_mne_environment() -> Dict[str, str]:
    """
    Configure environment variables needed for a reliable MNE/numba setup.

    Returns a dictionary with the variables we touched so callers can log or
    inspect the effective configuration if needed.
    """

    updated: Dict[str, str] = {}

    # Always prefer a writable temp directory for cache artefacts.
    if "NUMBA_CACHE_DIR" not in os.environ:
        cache_dir = Path(tempfile.gettempdir()) / "brain_researcher_numba_cache"
        _ensure_dir(cache_dir)
        os.environ["NUMBA_CACHE_DIR"] = str(cache_dir)
        updated["NUMBA_CACHE_DIR"] = str(cache_dir)
    else:
        cache_dir = Path(os.environ["NUMBA_CACHE_DIR"])
        _ensure_dir(cache_dir)

    if os.environ.setdefault("NUMBA_DISABLE_CACHING", "1") != "1":
        # If the user explicitly wants caching we still make sure the path exists.
        _ensure_dir(cache_dir)
    else:
        updated["NUMBA_DISABLE_CACHING"] = "1"

    if "NUMBA_DISABLE_JIT" not in os.environ:
        os.environ["NUMBA_DISABLE_JIT"] = "0"
        updated["NUMBA_DISABLE_JIT"] = "0"

    # Turn off native code usage unless the user opted in.
    if "MNE_USE_NATIVE_CODE" not in os.environ:
        os.environ["MNE_USE_NATIVE_CODE"] = "0"
        updated["MNE_USE_NATIVE_CODE"] = "0"

    if "MNE_DONTWRITE_HOME" not in os.environ:
        os.environ["MNE_DONTWRITE_HOME"] = "true"
        updated["MNE_DONTWRITE_HOME"] = "true"

    if "_MNE_FAKE_HOME_DIR" not in os.environ:
        fake_home = Path(tempfile.gettempdir()) / "brain_researcher_mne_home"
        _ensure_dir(fake_home)
        _ensure_dir(fake_home / ".mne")
        os.environ["_MNE_FAKE_HOME_DIR"] = str(fake_home)
        updated["_MNE_FAKE_HOME_DIR"] = str(fake_home)

    if "MNE_HOME" not in os.environ:
        mne_home = Path(tempfile.gettempdir()) / "mne"
        _ensure_dir(mne_home)
        os.environ["MNE_HOME"] = str(mne_home)
        updated["MNE_HOME"] = str(mne_home)

    if "MNE_CONFIG" not in os.environ:
        mne_config_dir = Path(tempfile.gettempdir()) / "mne"
        _ensure_dir(mne_config_dir)
        mne_config = mne_config_dir / "mne-python.json"
        os.environ["MNE_CONFIG"] = str(mne_config)
        updated["MNE_CONFIG"] = str(mne_config)

    if "JOBLIB_TEMP_FOLDER" not in os.environ:
        joblib_dir = Path(tempfile.gettempdir()) / "brain_researcher_joblib"
        _ensure_dir(joblib_dir)
        os.environ["JOBLIB_TEMP_FOLDER"] = str(joblib_dir)
        updated["JOBLIB_TEMP_FOLDER"] = str(joblib_dir)

    if "JOBLIB_MULTIPROCESSING" not in os.environ:
        os.environ["JOBLIB_MULTIPROCESSING"] = "0"
        updated["JOBLIB_MULTIPROCESSING"] = "0"

    if updated:
        logger.debug("Configured MNE/numba environment: %s", updated)

    return updated
