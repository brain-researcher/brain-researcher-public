"""Compatibility alias for execution recipe builders."""

import sys

from brain_researcher.services.tools import recipe_builders as _impl

sys.modules[__name__] = _impl
