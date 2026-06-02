"""Compatibility alias for orchestrator distributed endpoints."""

import sys

from .endpoints import distributed as _impl

sys.modules[__name__] = _impl
