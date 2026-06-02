"""Compatibility alias for execution recipe script helpers."""

import sys

from brain_researcher.services.tools import recipe_scripts as _impl

sys.modules[__name__] = _impl
