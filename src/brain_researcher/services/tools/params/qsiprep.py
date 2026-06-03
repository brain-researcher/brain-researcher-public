"""DEPRECATED: QSIPrep parameters have moved to services.tools.pipelines.

Import from the new location:
    from brain_researcher.services.tools.pipelines import (
        QSIPrepParameters,
        build_qsiprep_command,
        build_qsiprep_env,
        qsiprep_from_payload,
    )

This module re-exports from the new location with deprecation warnings.
"""

from __future__ import annotations

import warnings
from typing import Any, Dict, Mapping

# Import from canonical location
from brain_researcher.services.tools.pipelines.params import (
    QSIPrepParameters as _QSIPrepParameters,
    build_qsiprep_command as _build_qsiprep_command,
    build_qsiprep_env as _build_qsiprep_env,
    qsiprep_from_payload as _qsiprep_from_payload,
)

_DEPRECATION_MSG = (
    "Importing {name} from brain_researcher.services.tools.params.qsiprep is deprecated. "
    "Use brain_researcher.services.tools.pipelines instead."
)

# Re-export the class directly (can't warn on class import easily)
QSIPrepParameters = _QSIPrepParameters


def build_qsiprep_command(
    params: _QSIPrepParameters,
    *,
    include_executable: bool = True,
) -> list[str]:
    """Build QSIPrep CLI command.

    DEPRECATED: Use brain_researcher.services.tools.pipelines.build_qsiprep_command instead.
    """
    warnings.warn(
        _DEPRECATION_MSG.format(name="build_qsiprep_command"),
        DeprecationWarning,
        stacklevel=2,
    )
    return _build_qsiprep_command(params, include_executable=include_executable)


def build_qsiprep_env(params: _QSIPrepParameters) -> Dict[str, str]:
    """Build QSIPrep environment variables.

    DEPRECATED: Use brain_researcher.services.tools.pipelines.build_qsiprep_env instead.
    """
    warnings.warn(
        _DEPRECATION_MSG.format(name="build_qsiprep_env"),
        DeprecationWarning,
        stacklevel=2,
    )
    return _build_qsiprep_env(params)


def qsiprep_from_payload(payload: Mapping[str, Any]) -> _QSIPrepParameters:
    """Create QSIPrepParameters from a dict payload.

    DEPRECATED: Use brain_researcher.services.tools.pipelines.qsiprep_from_payload instead.
    """
    warnings.warn(
        _DEPRECATION_MSG.format(name="qsiprep_from_payload"),
        DeprecationWarning,
        stacklevel=2,
    )
    return _qsiprep_from_payload(payload)


__all__ = [
    "QSIPrepParameters",
    "build_qsiprep_command",
    "build_qsiprep_env",
    "qsiprep_from_payload",
]
