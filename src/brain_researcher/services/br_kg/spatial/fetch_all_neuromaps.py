"""Reusable Neuromaps download helpers.

This module wraps the :mod:`neuromaps.datasets` fetchers so we can stage
surface/volume parcellations and statistical maps under the shared atlas home
(``/app/data/atlases/neuromaps`` by default) or a user-specified directory.
The resulting cache can then be consumed by ``scripts/br-kg/load_neuromaps_parcellations.py``
or any other ingestion step that expects Neuromaps resources to be present on
disk.

Usage examples
--------------
Fetch everything (atlases + annotations) into the project cache::

    python scripts/br-kg/fetch_all_neuromaps.py

Only download atlases while storing the cache elsewhere::

    python scripts/br-kg/fetch_all_neuromaps.py \
        --output-dir ~/datasets/neuromaps --skip-annotations

You must run this on a machine with network access. Restricted annotations
require an OSF token (``--include-restricted`` or ``NEUROMAPS_OSF_TOKEN``).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Dict, Iterable, List

from neuromaps.datasets import annotations, atlases
from neuromaps.datasets.utils import _get_session
from nilearn.datasets._utils import fetch_single_file

from brain_researcher.services.shared.brkg_atlas_paths import default_atlas_output_root

logger = logging.getLogger(__name__)


def _configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity <= 0:
        level = logging.ERROR
    elif verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Neuromaps resources")
    parser.add_argument(
        "--output-dir",
        default=default_atlas_output_root() / "neuromaps",
        type=Path,
        help=(
            "Directory to store the Neuromaps cache "
            "(default: BR_ATLAS_OUTPUT_ROOT/neuromaps)."
        ),
    )
    parser.add_argument(
        "--skip-atlases",
        action="store_true",
        help="Do not download atlas surfaces/volumes",
    )
    parser.add_argument(
        "--skip-annotations",
        action="store_true",
        help="Do not download statistical/functional annotation maps",
    )
    parser.add_argument(
        "--include-restricted",
        action="store_true",
        help="Attempt to fetch restricted annotations (requires OSF token)",
    )
    parser.add_argument(
        "--osf-token",
        default=None,
        help="Explicit OSF token to access restricted datasets (overrides NEUROMAPS_OSF_TOKEN)",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        type=Path,
        help="Optional path to write a JSON manifest of downloaded files",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=1,
        help="Increase log verbosity (repeat for more detail)",
    )
    return parser.parse_args()


def _flatten(values: Iterable) -> List[str]:
    """Recursively collect file paths from nested containers."""

    files: List[str] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            files.extend(_flatten(value))
        elif hasattr(value, "L") and hasattr(value, "R"):
            files.extend(_flatten([value.L, value.R]))
        else:
            files.append(str(value))
    return files


def _fetch_atlases(output_dir: Path, verbose: int) -> Dict[str, Dict[str, List[str]]]:
    logger.info("Fetching Neuromaps atlases (all densities)")
    atlas_payload = atlases.fetch_all_atlases(data_dir=str(output_dir), verbose=verbose)

    manifest: Dict[str, Dict[str, List[str]]] = {}
    atlas_root = output_dir / "atlases"

    for atlas_name, densities in atlas_payload.items():
        manifest[atlas_name] = {}
        for density, bundle in densities.items():
            if isinstance(bundle, dict) or hasattr(bundle, "items"):
                values = list(bundle.values())
            else:
                values = [bundle]
            manifest[atlas_name][density] = _flatten(values)

    if atlas_root.exists():
        logger.info("Atlas cache lives at %s", atlas_root)
    else:
        logger.warning(
            "Atlas cache directory %s was not created; check for download errors",
            atlas_root,
        )

    return manifest


def _fetch_annotations(
    output_dir: Path, verbose: int, token: str | None
) -> Dict[str, List[str]]:
    logger.info("Fetching Neuromaps annotations (this may take a while)")

    manifest: Dict[str, List[str]] = {}
    dataset_info = annotations.get_dataset_info("annotations", bool(token))
    session = _get_session(token=token)

    for idx, entry in enumerate(dataset_info, start=1):
        url = entry.get("url")
        if not url:
            logger.debug(
                "Skipping annotation %s:%s:%s:%s (no public URL)",
                entry.get("source"),
                entry.get("desc"),
                entry.get("space"),
                entry.get("den") or entry.get("res"),
            )
            continue

        rel_dir = Path("annotations") / entry["rel_path"]
        dest_dir = (output_dir / rel_dir).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)

        try:
            downloaded = fetch_single_file(
                url,
                dest_dir,
                md5sum=entry.get("checksum"),
                verbose=max(0, verbose - 1),
                session=session,
            )
        except Exception as exc:  # pragma: no cover - network/OSF issues
            logger.warning(
                "Failed to download annotation %s:%s:%s:%s: %s",
                entry.get("source"),
                entry.get("desc"),
                entry.get("space"),
                entry.get("den") or entry.get("res"),
                exc,
            )
            continue

        target_name = entry.get("fname")
        final_path = downloaded
        if target_name:
            final_path = dest_dir / target_name
            if final_path.exists():
                if downloaded != final_path:
                    downloaded.unlink(missing_ok=True)  # type: ignore[attr-defined]
            else:
                try:
                    downloaded.rename(final_path)
                except OSError:
                    logger.debug("Falling back to copy for %s", final_path)
                    final_path.write_bytes(downloaded.read_bytes())
                    downloaded.unlink(missing_ok=True)  # type: ignore[attr-defined]
        final_path = final_path.resolve()

        key = ":".join(
            [
                part
                for part in (
                    entry.get("source"),
                    entry.get("desc"),
                    entry.get("space"),
                    entry.get("den") or entry.get("res"),
                )
                if part
            ]
        )
        manifest.setdefault(key, []).append(str(final_path))

        if verbose >= 1 and idx % 25 == 0:
            logger.info("Fetched %d/%d annotations", idx, len(dataset_info))

    annot_root = output_dir / "annotations"
    if annot_root.exists():
        logger.info("Annotation cache lives at %s", annot_root)
    else:
        logger.warning(
            "Annotation cache directory %s was not created; some datasets may not have downloaded",
            annot_root,
        )

    session.close()
    return manifest


def main() -> None:
    args = _parse_args()
    _configure_logging(args.verbose)

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Ensure neuromaps writes to our target directory
    os.environ["NEUROMAPS_DATA"] = str(output_dir)

    token = args.osf_token or os.environ.get("NEUROMAPS_OSF_TOKEN")
    if args.include_restricted and not token:
        raise SystemExit(
            "--include-restricted requested but no OSF token supplied. "
            "Provide --osf-token or set NEUROMAPS_OSF_TOKEN."
        )

    atlas_manifest: Dict[str, Dict[str, List[str]]] = {}
    annot_manifest: Dict[str, List[str]] = {}

    try:
        if not args.skip_atlases:
            atlas_manifest = _fetch_atlases(output_dir, verbose=args.verbose)
        else:
            logger.info("Skipping atlas download")

        if not args.skip_annotations:
            annot_manifest = _fetch_annotations(
                output_dir,
                verbose=args.verbose,
                token=token if args.include_restricted else None,
            )
        else:
            logger.info("Skipping annotation download")
    except Exception as exc:  # pragma: no cover - network errors, etc.
        logger.error("Neuromaps download failed: %s", exc)
        raise

    total_files = sum(
        len(vs) for atlas in atlas_manifest.values() for vs in atlas.values()
    )
    total_files += sum(len(vs) for vs in annot_manifest.values())
    logger.info(
        "Neuromaps download complete (%d file references recorded)", total_files
    )

    if args.manifest:
        manifest_path = args.manifest.expanduser().resolve()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "output_dir": str(output_dir),
            "atlases": atlas_manifest,
            "annotations": annot_manifest,
        }
        manifest_path.write_text(json.dumps(payload, indent=2))
        logger.info("Wrote manifest to %s", manifest_path)


if __name__ == "__main__":
    main()
