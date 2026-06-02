"""Back-compat shim for SLURM parsing helpers."""

from __future__ import annotations

import sys as _sys

from brain_researcher.services.shared import r2toolsagent_slurm_helpers as _moved

_sys.modules[__name__] = _moved
