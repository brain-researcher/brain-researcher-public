"""Compatibility alias for orchestrator feedback widget endpoints."""

import sys

from .endpoints import feedback_widget as _impl

sys.modules[__name__] = _impl
