"""Compatibility module alias for TaskBeacon handoff helpers."""

from __future__ import annotations

import sys

from brain_researcher.services.tools import taskbeacon_handoff as _impl

sys.modules[__name__] = _impl
