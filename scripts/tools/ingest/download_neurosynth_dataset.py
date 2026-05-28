#!/usr/bin/env python3
"""Download the official Neurosynth NiMARE bundle (coordinates/metadata/features)."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

try:
    from nimare.extract import fetch_neurosynth
except ImportError as exc:  # pragma: no cover - informative error path
    raise SystemExit(
        "nimare is required for this downloader. Install with `pip install nimare`."
    ) from exc


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
LOGGER = logging.getLogger("download_neurosynth_dataset")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/neurosynth_nimare"),
        help="Directory where the Neurosynth bundle will be stored (default: data/neurosynth_nimare)",
    )
    parser.add_argument(
        "--version",
        default="7",
        help="Neurosynth release version (default: 7)",
    )
    parser.add_argument(
        "--source",
        default="abstract",
        choices=["abstract", "fulltext"],
        help="Text source to use for TF-IDF features (default: abstract)",
    )
    parser.add_argument(
        "--vocab",
        default="terms",
        help="Vocabulary variant to download (default: terms)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be downloaded without running fetch_neurosynth",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info(
        "Requested Neurosynth download: version=%s source=%s vocab=%s -> %s",
        args.version,
        args.source,
        args.vocab,
        output_dir,
    )

    if args.dry_run:
        LOGGER.info("Dry run complete (no files downloaded).")
        return

    files = fetch_neurosynth(
        data_dir=str(output_dir),
        version=args.version,
        source=args.source,
        vocab=args.vocab,
    )
    def _flatten(entry: object, prefix: str = "") -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        if isinstance(entry, dict):
            for key, value in entry.items():
                new_prefix = f"{prefix}.{key}" if prefix else key
                rows.extend(_flatten(value, new_prefix))
        elif isinstance(entry, list):
            for idx, value in enumerate(entry):
                new_prefix = f"{prefix}[{idx}]"
                rows.extend(_flatten(value, new_prefix))
        else:
            path = Path(entry)
            rows.append((prefix or path.name, str(path)))
        return rows

    if isinstance(files, dict):
        items = sorted(_flatten(files))
    else:
        items = sorted(_flatten(files))

    LOGGER.info("Downloaded/verified %s files:", len(items))
    for key, path in items:
        LOGGER.info("  %s -> %s", key, path)


if __name__ == "__main__":
    main()
