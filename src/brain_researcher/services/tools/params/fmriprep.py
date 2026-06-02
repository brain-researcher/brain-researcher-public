"""DEPRECATED: fMRIPrep parameters have moved to services.tools.pipelines.

Import from the new location:
    from brain_researcher.services.tools.pipelines import (
        FMRIPrepParameters,
        build_fmriprep_command,
        build_fmriprep_env,
        fmriprep_from_payload,
    )

This module re-exports from the new location with deprecation warnings.
"""

from __future__ import annotations

import warnings
from typing import Any, Dict, Mapping

# Import from canonical location
from brain_researcher.services.tools.pipelines.params import (
    FMRIPrepParameters as _FMRIPrepParameters,
)
from brain_researcher.services.tools.pipelines.params import (
    build_fmriprep_command as _build_fmriprep_command,
)
from brain_researcher.services.tools.pipelines.params import (
    build_fmriprep_env as _build_fmriprep_env,
)
from brain_researcher.services.tools.pipelines.params import (
    fmriprep_from_payload as _fmriprep_from_payload,
)

_DEPRECATION_MSG = (
    "Importing {name} from brain_researcher.services.tools.params.fmriprep is deprecated. "
    "Use brain_researcher.services.tools.pipelines instead."
)

# Re-export the class directly (can't warn on class import easily)
FMRIPrepParameters = _FMRIPrepParameters


def build_fmriprep_command(
    params: _FMRIPrepParameters,
    *,
    include_executable: bool = True,
) -> list[str]:
    """Build fMRIPrep CLI command.

    DEPRECATED: Use brain_researcher.services.tools.pipelines.build_fmriprep_command instead.
    """
    warnings.warn(
        _DEPRECATION_MSG.format(name="build_fmriprep_command"),
        DeprecationWarning,
        stacklevel=2,
    )
    return _build_fmriprep_command(params, include_executable=include_executable)


def build_fmriprep_env(params: _FMRIPrepParameters) -> Dict[str, str]:
    """Build fMRIPrep environment variables.

    DEPRECATED: Use brain_researcher.services.tools.pipelines.build_fmriprep_env instead.
    """
    warnings.warn(
        _DEPRECATION_MSG.format(name="build_fmriprep_env"),
        DeprecationWarning,
        stacklevel=2,
    )
    return _build_fmriprep_env(params)


def fmriprep_from_payload(payload: Mapping[str, Any]) -> _FMRIPrepParameters:
    """Create FMRIPrepParameters from a dict payload.

    DEPRECATED: Use brain_researcher.services.tools.pipelines.fmriprep_from_payload instead.
    """
    warnings.warn(
        _DEPRECATION_MSG.format(name="fmriprep_from_payload"),
        DeprecationWarning,
        stacklevel=2,
    )
    return _fmriprep_from_payload(payload)


__all__ = [
    "FMRIPrepParameters",
    "build_fmriprep_command",
    "build_fmriprep_env",
    "fmriprep_from_payload",
]
