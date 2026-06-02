"""Compatibility module for native review contract helpers."""

from __future__ import annotations

import sys

from brain_researcher.core.contracts import (
    native_review_contract as _native_review_contract,
)

sys.modules[__name__] = _native_review_contract
