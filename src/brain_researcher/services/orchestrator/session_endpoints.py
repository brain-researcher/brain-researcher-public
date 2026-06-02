"""Compatibility alias for orchestrator session endpoints."""

import sys

from .endpoints import session as _impl

sys.modules[__name__] = _impl
