"""Build a JSON manifest of OpenNeuro GLM FitLins statistical maps."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Sequence

from brain_researcher.core.ingestion.loaders.openneuro_glm_loader import (
    OpenNeuroGLMFitlinsLoader,
    load_path_config,
)


logger = logging.getLogger(__name__)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="data/openneuro_glmfitlins/path_config.local.json",
        type=Path,
        help="Path to the FitLins path_config.json file.",
    )
    parser.add_argument(
        "--output",
        default="data/openneuro_glmfitlins/manifest/openneuro_glm_statsmaps.json",
        type=Path,
        help="Output path for the manifest JSON file.",
    )
    parser.add_argument(
        "--checksum",
        action="store_true",
        help="Compute SHA-256 checksums for each map (expensive).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on the number of maps to include (for testing).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    config = load_path_config(args.config)
    loader = OpenNeuroGLMFitlinsLoader.from_config(
        config=config, compute_checksum=args.checksum
    )

    records = loader.discover()
    if args.limit is not None:
        records = records[: args.limit]

    manifest_data = [row.to_record() for row in records]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest_data, indent=2))

    logger.info("Wrote %s map records to %s", len(manifest_data), args.output)


if __name__ == "__main__":
    main()
