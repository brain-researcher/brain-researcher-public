"""Predictive self-critique gates for FC autoresearch."""

from .null_diagnosis import build_null_diagnosis
from .pivot_trigger import build_pivot_trigger, detect_unexpected_winners
from .so_what import evaluate_so_what

__all__ = [
    "build_null_diagnosis",
    "build_pivot_trigger",
    "detect_unexpected_winners",
    "evaluate_so_what",
]
