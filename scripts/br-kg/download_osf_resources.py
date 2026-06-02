#!/usr/bin/env python3
"""CLI wrapper for downloading Neuromaps OSF resources."""

from __future__ import annotations

import sys

from brain_researcher.services.br_kg.spatial.download_osf_resources import (
    OSF_FILE_API,
    OSF_STORAGE_API,
    DownloadTarget,
    _build_parser,
    _compute_md5,
    _configure_logging,
    _download_entry,
    _entry_matches_filters,
    _infer_filename,
    _iter_entries,
    _normalize_url,
    _parse_filters,
    _resolve_section,
    main,
)

__all__ = [
    "DownloadTarget",
    "OSF_FILE_API",
    "OSF_STORAGE_API",
    "_build_parser",
    "_compute_md5",
    "_configure_logging",
    "_download_entry",
    "_entry_matches_filters",
    "_infer_filename",
    "_iter_entries",
    "_normalize_url",
    "_parse_filters",
    "_resolve_section",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
