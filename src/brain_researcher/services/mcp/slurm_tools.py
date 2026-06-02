"""Compatibility alias for Slurm helper tools."""

import sys

from brain_researcher.services.tools import slurm_tools as _impl

sys.modules[__name__] = _impl
