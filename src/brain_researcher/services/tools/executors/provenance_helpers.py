"""Backward-compatible import shim for shared provenance helpers."""

import sys
from importlib import import_module

_module = import_module("brain_researcher.services.shared.provenance_helpers")
sys.modules[__name__] = _module
