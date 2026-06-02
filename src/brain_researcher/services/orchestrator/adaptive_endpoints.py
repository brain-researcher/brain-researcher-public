"""Compatibility alias for orchestrator adaptive endpoints."""

import sys

from .endpoints import adaptive as _impl

sys.modules[__name__] = _impl
