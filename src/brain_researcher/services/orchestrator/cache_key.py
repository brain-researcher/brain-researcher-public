"""Backward-compatible import shim for shared cache-key helpers."""

import sys
from importlib import import_module

_module = import_module("brain_researcher.services.shared.cache_key")
sys.modules[__name__] = _module
