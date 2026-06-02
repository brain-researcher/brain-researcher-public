"""Compatibility alias for benchmark import helpers."""

from __future__ import annotations

import sys as _sys

from brain_researcher.services.shared import benchmark_importer as _impl

_sys.modules[__name__] = _impl
