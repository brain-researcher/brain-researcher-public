"""Compatibility alias for orchestrator share endpoints."""

import sys

from .endpoints import share as _impl

sys.modules[__name__] = _impl
