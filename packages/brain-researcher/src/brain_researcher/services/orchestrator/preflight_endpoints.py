"""Compatibility alias for orchestrator preflight endpoints."""

import sys

from .endpoints import preflight as _impl

sys.modules[__name__] = _impl
