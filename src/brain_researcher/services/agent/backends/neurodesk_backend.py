"""Back-compat shim for ``NeurodeskBackend``.

The implementation now lives in ``brain_researcher.services.tools`` so
``tools.neurodesk_compiler`` does not import up into ``services.agent``.
"""

from __future__ import annotations

import sys as _sys

from brain_researcher.services.tools import neurodesk_backend as _moved

_sys.modules[__name__] = _moved
