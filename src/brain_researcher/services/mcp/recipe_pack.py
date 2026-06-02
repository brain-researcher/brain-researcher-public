"""Compatibility alias for execution recipe pack helpers."""

import sys

from brain_researcher.services.tools import recipe_pack as _impl

sys.modules[__name__] = _impl
