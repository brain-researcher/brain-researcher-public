#!/usr/bin/env python3
"""Download Neurosynth LDA topic datasets for a given release version."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import requests


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
LOGGER = logging.getLogger("download_neurosynth_lda")

BASE_URL = "https://raw.githubusercontent.com/neurosynth/neurosynth-data/master"
DEFAULT_VARIANTS = ("LDA50", "LDA100", "LDA200", "LDA400")
FILE_SUFFIXES = (
    ("keys", ".tsv"),
    ("metadata", ".json"),
    ("source-abstract_type-weight_features", ".npz"),
    ("vocabulary", ".txt"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        default="7",
        help="Neurosynth release version (default: 7)",
    )
    parser.add_argument(
        "--variants",
        default=",".join(DEFAULT_VARIANTS),
        help="Comma-separated list of LDA variants to download (default: LDA50,LDA100,LDA200,LDA400)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/neurosynth_nimare/lda"),
        help="Destination directory root",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download files even if they already exist",
    )
    return parser.parse_args()


def download_file(url: str, destination: Path, overwrite: bool = False) -> None:
    if destination.exists() and not overwrite:
        LOGGER.info("Skipping existing %s", destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Downloading %s -> %s", url, destination)
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)


def main() -> None:
    args = parse_args()
    variants = [variant.strip() for variant in args.variants.split(",") if variant.strip()]
    if not variants:
        raise SystemExit("No LDA variants provided")

    for variant in variants:
        for suffix, ext in FILE_SUFFIXES:
            filename = f"data-neurosynth_version-{args.version}_vocab-{variant}_{suffix}{ext}"
            url = f"{BASE_URL}/{filename}"
            dest = args.output_dir / f"version_{args.version}" / variant / filename
            download_file(url, dest, overwrite=args.overwrite)

    LOGGER.info("Done downloading LDA assets for version %s (%s)", args.version, ",".join(variants))


if __name__ == "__main__":
    main()
