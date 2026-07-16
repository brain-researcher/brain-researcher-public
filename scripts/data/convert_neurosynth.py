#!/usr/bin/env python3.11
"""Convert a verified Neurosynth version-7 snapshot to a NiMARE Dataset pickle."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Any

from brain_researcher.core.datasets.neurosynth_source import (
    COORDINATES_FILENAME,
    DEFAULT_DATASET_PICKLE,
    DEFAULT_SOURCE_DIR,
    FEATURES_FILENAME,
    METADATA_FILENAME,
    SOURCE_FILES,
    VOCABULARY_FILENAME,
    converted_provenance_path,
    publish_converted_dataset_provenance,
    verify_source_bundle,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = DEFAULT_SOURCE_DIR
DEFAULT_OUTPUT = DEFAULT_DATASET_PICKLE
COORDINATES = COORDINATES_FILENAME
METADATA = METADATA_FILENAME
FEATURES = FEATURES_FILENAME
VOCABULARY = VOCABULARY_FILENAME


def convert_dataset(
    data_dir: Path,
    output_file: Path,
    *,
    io_module: Any | None = None,
) -> None:
    """Convert inputs and publish the new pickle only after a complete save.

    The canonical output is removed before validation/conversion starts. This
    deliberately prevents a failed rerun from leaving an older pickle at the
    documented output path where it could be mistaken for the new result.
    """
    data_dir = data_dir.expanduser().resolve()
    output_file = output_file.expanduser().resolve()
    partial_file = output_file.with_name(
        f".{output_file.stem}.incomplete{output_file.suffix}"
    )
    provenance_file = converted_provenance_path(output_file)
    partial_provenance_file = provenance_file.with_name(provenance_file.name + ".part")
    output_file.unlink(missing_ok=True)
    partial_file.unlink(missing_ok=True)
    provenance_file.unlink(missing_ok=True)
    partial_provenance_file.unlink(missing_ok=True)

    verify_source_bundle(data_dir, source_files=SOURCE_FILES)

    inputs = {
        "coordinates": data_dir / COORDINATES,
        "metadata": data_dir / METADATA,
        "features": data_dir / FEATURES,
        "vocabulary": data_dir / VOCABULARY,
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if io_module is None:
        from nimare import io as io_module

    try:
        dataset = io_module.convert_neurosynth_to_dataset(
            coordinates_file=str(inputs["coordinates"]),
            metadata_file=str(inputs["metadata"]),
            annotations_files={
                "features": str(inputs["features"]),
                "vocabulary": str(inputs["vocabulary"]),
            },
        )
        dataset.save(str(partial_file))
        if not partial_file.is_file() or partial_file.stat().st_size == 0:
            raise RuntimeError("NiMARE did not write a non-empty dataset pickle")
        os.replace(partial_file, output_file)
        publish_converted_dataset_provenance(
            output_file, data_dir, source_files=SOURCE_FILES
        )
    except Exception:
        partial_file.unlink(missing_ok=True)
        output_file.unlink(missing_ok=True)
        provenance_file.unlink(missing_ok=True)
        partial_provenance_file.unlink(missing_ok=True)
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Directory containing the four verified Neurosynth version-7 files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Canonical NiMARE Dataset pickle to replace on success.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        convert_dataset(args.data_dir, args.output)
    except Exception:
        logger.exception("Neurosynth conversion failed; no canonical output was kept")
        return 1
    logger.info("Neurosynth dataset and provenance sidecar written: %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
