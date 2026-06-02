"""Compatibility alias for orchestrator Studio session gateway endpoints."""

import sys

from .endpoints import studio_sessions as _impl

sys.modules[__name__] = _impl
