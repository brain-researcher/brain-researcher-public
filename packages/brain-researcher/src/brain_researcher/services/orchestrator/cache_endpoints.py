"""Compatibility alias for orchestrator cache management endpoints."""

import sys

from .endpoints import cache as _impl

sys.modules[__name__] = _impl
