"""Compatibility alias for execution recipe payload helpers."""

import sys

from brain_researcher.services.tools import recipe_payloads as _impl

sys.modules[__name__] = _impl
