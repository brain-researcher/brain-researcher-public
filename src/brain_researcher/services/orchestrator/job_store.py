"""Compatibility alias for the shared JobStore contracts."""

import sys
from importlib import import_module

_module = import_module("brain_researcher.services.shared.job_store")
sys.modules[__name__] = _module
