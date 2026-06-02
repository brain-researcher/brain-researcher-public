"""Compatibility alias for orchestrator feedback endpoints."""

import sys

from .endpoints import feedback as _impl

sys.modules[__name__] = _impl
