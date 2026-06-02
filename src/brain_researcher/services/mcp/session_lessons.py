"""Compatibility alias for session lesson helpers now hosted in shared."""

from __future__ import annotations

import sys
from importlib import import_module

_compat_name = __name__
_module = import_module("brain_researcher.services.shared.session_lessons")
globals().update(_module.__dict__)
sys.modules[_compat_name] = _module
