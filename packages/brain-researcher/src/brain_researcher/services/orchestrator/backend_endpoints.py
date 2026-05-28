"""Compatibility alias for orchestrator backend endpoints."""

import sys

from .endpoints import backend as _impl

sys.modules[__name__] = _impl
