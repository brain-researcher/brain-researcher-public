"""Utilities for normalising BIDS metadata into scorer-friendly payloads."""

from .bids_participants import load_participant_profile
from .bids_events import extract_hed_tags
from .bids_scans import extract_modalities

__all__ = [
    "load_participant_profile",
    "extract_hed_tags",
    "extract_modalities",
]
