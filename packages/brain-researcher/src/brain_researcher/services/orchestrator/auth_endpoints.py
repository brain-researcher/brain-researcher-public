"""Compatibility alias for orchestrator auth endpoints."""

import sys

from .endpoints import auth as _impl

sys.modules[__name__] = _impl
