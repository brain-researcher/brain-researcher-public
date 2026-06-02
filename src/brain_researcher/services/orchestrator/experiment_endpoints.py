"""Compatibility alias for orchestrator experiment endpoints."""

import sys

from .endpoints import experiment as _impl

sys.modules[__name__] = _impl
