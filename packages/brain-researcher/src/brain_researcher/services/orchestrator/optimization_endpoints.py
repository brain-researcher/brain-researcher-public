"""Compatibility alias for orchestrator optimization endpoints."""

import sys

from .endpoints import optimization as _impl

sys.modules[__name__] = _impl
