"""Compatibility alias for the shared in-memory JobStore implementation."""

import sys
from importlib import import_module

_module = import_module("brain_researcher.services.shared.memory_job_store")
sys.modules[__name__] = _module
