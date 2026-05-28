#!/usr/bin/env python3
"""Download the Yeo/Buckner GSP population-average functional connectivity seed maps."""
# THIS FILE IS NOT AVAILABLE OR NOT USED IN THE PROJECT

from __future__ import annotations

import argparse
import logging
import tarfile
import zipfile
from pathlib import Path
from typing import Iterable

import shutil
import urllib.request

import requests


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
LOGGER = logging.getLogger("download_yeo_gsp_fc")

# Canonical public location for the tarball (mirrors welcome via --url)
DEFAULT_URL = "https://surfer.nmr.mgh.harvard.edu/ftp/data/yeo_fsaverage/Yeo_Buckner_GSP_FC_maps.tgz"


def stream_download(url: str, destination: Path, chunk_size: int = 1024 * 1024) -> None:
    LOGGER.info("Downloading %s -> %s", url, destination)
    if url.startswith("ftp://"):
        with urllib.request.urlopen(url) as response, destination.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    else:
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            downloaded = 0
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        LOGGER.info("  %.1f%% (%s / %s bytes)", pct, downloaded, total)
    LOGGER.info("Finished downloading %s", destination)


def extract_archive(path: Path, target_dir: Path) -> None:
    LOGGER.info("Extracting %s -> %s", path, target_dir)
    suffix = path.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            archive.extractall(target_dir)
    else:
        mode = "r:gz" if suffix.endswith("gz") else "r"
        with tarfile.open(path, mode) as archive:
            archive.extractall(path=target_dir)
    LOGGER.info("Extraction complete")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="Source URL for Yeo/Buckner tarball (default: official FreeSurfer mirror)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/neurokg/raw/nilearn_atlases"),
        help="Destination directory for extracted fc_seed_*.nii.gz files",
    )
    parser.add_argument(
        "--keep-archive",
        action="store_true",
        help="Keep the downloaded .tgz file instead of deleting after extraction",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / Path(args.url).name

    try:
        stream_download(args.url, archive_path)
        extract_archive(archive_path, output_dir)
    finally:
        if archive_path.exists() and not args.keep_archive:
            archive_path.unlink()
            LOGGER.info("Removed temporary archive %s", archive_path)


if __name__ == "__main__":
    main()
