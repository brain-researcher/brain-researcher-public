"""Back-compat shim for hypothesis candidate card helpers.

The implementation now lives in ``brain_researcher.services.tools`` so tools
can reuse it without importing up into ``services.agent``.
"""

from __future__ import annotations

import sys as _sys

from brain_researcher.services.tools import hypothesis_candidate_cards as _moved

_sys.modules[__name__] = _moved
