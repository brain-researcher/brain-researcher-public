"""Compatibility alias for orchestrator Studio execution gateway endpoints."""

import sys

from .endpoints import studio_executions as _impl

sys.modules[__name__] = _impl
