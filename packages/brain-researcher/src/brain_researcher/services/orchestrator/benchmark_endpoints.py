"""Compatibility alias for orchestrator benchmark endpoints."""

import sys

from .endpoints import benchmark as _impl

sys.modules[__name__] = _impl
