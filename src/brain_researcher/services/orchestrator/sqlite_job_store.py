"""Compatibility alias for the shared SQLite JobStore implementations."""

import sys
from importlib import import_module

_module = import_module("brain_researcher.services.shared.sqlite_job_store")
sys.modules[__name__] = _module
