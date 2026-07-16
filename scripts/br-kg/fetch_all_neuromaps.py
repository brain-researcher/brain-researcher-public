#!/usr/bin/env python3
"""[experimental] Download Neuromaps atlases and annotations."""

from brain_researcher.services.br_kg.spatial.fetch_all_neuromaps import (
    _configure_logging,
    _fetch_annotations,
    _fetch_atlases,
    _flatten,
    _parse_args,
    main,
)

DOWNLOAD_STATUS = "experimental"

__all__ = [
    "_configure_logging",
    "_fetch_annotations",
    "_fetch_atlases",
    "_flatten",
    "_parse_args",
    "main",
]


if __name__ == "__main__":
    main()
