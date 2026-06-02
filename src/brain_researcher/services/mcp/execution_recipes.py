"""Compatibility alias for execution recipe helpers.

The implementation lives under ``services.tools`` so tool execution paths do
not depend on the MCP package.
"""

import sys

from brain_researcher.services.tools import execution_recipes as _impl

sys.modules[__name__] = _impl
