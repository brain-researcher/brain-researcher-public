"""Compatibility alias for orchestrator monitor endpoints."""

import sys

from .endpoints import monitor as _impl

sys.modules[__name__] = _impl
