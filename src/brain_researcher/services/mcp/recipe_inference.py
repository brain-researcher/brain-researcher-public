"""Compatibility alias for execution recipe inference helpers."""

import sys

from brain_researcher.services.tools import recipe_inference as _impl

sys.modules[__name__] = _impl
