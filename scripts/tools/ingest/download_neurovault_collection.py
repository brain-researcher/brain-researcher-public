#!/usr/bin/env python3
"""Download and extract a NeuroVault collection (e.g., Neurosynth parcellations #2099)."""

from __future__ import annotations

import argparse
import logging
import zipfile
from pathlib import Path

import requests


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
LOGGER = logging.getLogger("download_neurovault_collection")


def build_download_url(collection_id: int) -> str:
    return f"https://neurovault.org/collections/{collection_id}/download/?format=zip"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--collection-id",
        type=int,
        default=2099,
        help="NeuroVault collection ID (default: 2099, Neurosynth coactivation parcellations)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/neurovault"),
        help="Directory where the collection will be extracted",
    )
    parser.add_argument(
        "--keep-zip",
        action="store_true",
        help="Keep the downloaded ZIP archive after extraction",
    )
    return parser.parse_args()


def download_zip(url: str, destination: Path) -> None:
    LOGGER.info("Downloading %s -> %s", url, destination)
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    LOGGER.info("Finished downloading %s", destination)


def extract_zip(zip_path: Path, target_dir: Path) -> None:
    LOGGER.info("Extracting %s -> %s", zip_path, target_dir)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(target_dir)
    LOGGER.info("Extraction complete")


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    url = build_download_url(args.collection_id)
    archive_path = output_dir / f"collection_{args.collection_id}.zip"

    try:
        download_zip(url, archive_path)
        extract_zip(archive_path, output_dir / f"collection_{args.collection_id}")
    finally:
        if archive_path.exists() and not args.keep_zip:
            archive_path.unlink()
            LOGGER.info("Removed temporary archive %s", archive_path)


if __name__ == "__main__":
    main()
