"""Back-compat shim for backend base contracts.

The implementation now lives in ``brain_researcher.services.shared`` so lower
service layers can depend on these pure contracts.
"""

from __future__ import annotations

import sys as _sys

from brain_researcher.services.shared import r2toolsagent_base_backend as _moved

_sys.modules[__name__] = _moved
