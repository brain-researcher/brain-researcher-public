"""Compatibility alias for orchestrator A/B testing endpoints."""

import sys

from .endpoints import ab_testing as _impl

sys.modules[__name__] = _impl
