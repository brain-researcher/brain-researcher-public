"""Back-compat shim for novelty-calibration helpers.

The pure implementation now lives in ``brain_researcher.services.shared``.
"""

from __future__ import annotations

import sys as _sys

from brain_researcher.services.shared import novelty_calibration_questions as _moved

_sys.modules[__name__] = _moved
