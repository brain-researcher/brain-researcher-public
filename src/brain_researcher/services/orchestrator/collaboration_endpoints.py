"""Compatibility alias for orchestrator collaboration endpoints."""

import sys

from .endpoints import collaboration as _impl

sys.modules[__name__] = _impl
