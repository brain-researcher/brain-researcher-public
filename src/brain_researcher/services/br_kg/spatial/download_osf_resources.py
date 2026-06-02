#!/usr/bin/env python3
"""
Download Neuromaps resources directly from OSF using local metadata.

This module backs ``scripts/br-kg/download_osf_resources.py``. It consumes
the JSON metadata files shipped with the Neuromaps dataset repository
(``osf.json`` / ``meta.json``) to retrieve assets via the OSF REST API.
Entries are filtered via simple key/value matches (e.g.,
``--filter format=dlabel``) so you can target specific parcellations without
downloading the entire catalogue.

Example usage
-------------
Download all parcellations into the project cache (requires OSF token)::

    python scripts/br-kg/download_osf_resources.py \\
        --metadata data/br-kg/raw/neuromaps/datasets/data/osf.json \\
        --section annotations \\
        --filter format=dlabel \\
        --token ${NEUROMAPS_OSF_TOKEN}

Dry-run to preview which files would be fetched::

    python scripts/br-kg/download_osf_resources.py \\
        --filter source=schaefer2018 --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

import requests

OSF_FILE_API = "https://api.osf.io/v2/files/{file_id}/"
OSF_STORAGE_API = (
    "https://files.osf.io/v1/resources/{resource}/providers/osfstorage/{file_id}"
)

logger = logging.getLogger(__name__)

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


# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DownloadTarget:
    """Resolved download target."""

    section: str
    entry: Mapping[str, object]
    url: str
    file_id: str
    project_id: str


# --------------------------------------------------------------------------- #
# Logging / argument parsing
# --------------------------------------------------------------------------- #


def _configure_logging(verbosity: int) -> None:
    log_level = logging.WARNING
    if verbosity >= 2:
        log_level = logging.DEBUG
    elif verbosity == 1:
        log_level = logging.INFO

    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(levelname)s - %(message)s"
    )


def _parse_filters(raw_filters: Sequence[str]) -> Dict[str, str]:
    filters: Dict[str, str] = {}
    for item in raw_filters:
        if "=" not in item:
            raise argparse.ArgumentTypeError(
                f"Invalid filter '{item}'. Expected format key=value."
            )
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise argparse.ArgumentTypeError(
                f"Invalid filter '{item}'. Key cannot be empty."
            )
        filters[key] = value
    return filters


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download Neuromaps resources from OSF using local metadata."
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        required=True,
        help="Path to osf.json (or equivalent) metadata file with OSF resource identifiers.",
    )
    parser.add_argument(
        "--section",
        action="append",
        default=None,
        help=(
            "Metadata section to traverse (default: 'annotations' if present, otherwise all top-level sections). "
            "Use dotted paths for nested keys (e.g., 'atlases.fsaverage')."
        ),
    )
    parser.add_argument(
        "--filter",
        action="append",
        default=None,
        help="Key=value filter applied to each entry (match on string equality). Repeat for multiple filters.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/br-kg/raw/neuromaps"),
        help="Directory where downloaded files will be stored (default: data/br-kg/raw/neuromaps).",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="OSF personal access token. If omitted, NEUROMAPS_OSF_TOKEN env var is used.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matching resources without downloading.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download files even if they already exist and pass checksum verification.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="HTTP connection timeout in seconds (default: 60).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1024 * 1024,
        help="Download chunk size in bytes (default: 1 MiB).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (repeat for more detail).",
    )
    return parser


# --------------------------------------------------------------------------- #
# Metadata traversal helpers
# --------------------------------------------------------------------------- #


def _resolve_section(metadata: Mapping[str, object], section_path: str) -> object:
    node: object = metadata
    for part in section_path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise KeyError(f"Section '{section_path}' not found in metadata.")
        node = node[part]
    return node


def _iter_entries(
    section_path: str, node: object
) -> Iterator[Tuple[str, Mapping[str, object]]]:
    """
    Yield metadata entries that include an OSF url hint.

    The walker stops at dicts that expose a 'url' field; nested metadata inside
    those dicts is not traversed further.
    """
    if isinstance(node, list):
        for item in node:
            if isinstance(item, Mapping) and "url" in item:
                yield section_path, item
    elif isinstance(node, Mapping):
        if "url" in node:
            yield section_path, node
        else:
            for key, value in node.items():
                new_path = f"{section_path}.{key}" if section_path else key
                yield from _iter_entries(new_path, value)


def _normalize_url(url_field: object) -> Tuple[str, str, str]:
    """
    Convert the 'url' metadata field into a concrete OSF download URL.

    Returns a tuple of (download_url, project_id, file_id).
    """
    if isinstance(url_field, str):
        # Basic sanity check: expect .../{project}/providers/osfstorage/{file_id}
        parts = url_field.strip("/").split("/")
        if "resources" in parts and "osfstorage" in parts:
            project_idx = parts.index("resources") + 1
            file_idx = parts.index("osfstorage") + 1
            project_id = parts[project_idx]
            file_id = parts[file_idx]
            return url_field, project_id, file_id
        raise ValueError(f"Cannot parse OSF URL '{url_field}'.")

    if isinstance(url_field, Sequence) and len(url_field) >= 2:
        project_id = str(url_field[0])
        file_id = str(url_field[1])
        return (
            OSF_STORAGE_API.format(resource=project_id, file_id=file_id),
            project_id,
            file_id,
        )

    raise ValueError(f"Unsupported OSF URL representation: {url_field!r}")


# --------------------------------------------------------------------------- #
# Download helpers
# --------------------------------------------------------------------------- #


def _infer_filename(
    entry: Mapping[str, object],
    response: requests.Response,
    file_id: str,
    token: Optional[str],
) -> str:
    if "fname" in entry and isinstance(entry["fname"], str) and entry["fname"]:
        return entry["fname"]

    content_disposition = response.headers.get("Content-Disposition", "")
    if "filename=" in content_disposition:
        # RFC 6266 compliant header: attachment; filename="..."
        filename = (
            content_disposition.split("filename=", 1)[1].strip().strip('"').strip("'")
        )
        if filename:
            return filename

    # Fallback to OSF metadata query for deterministic naming
    try:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        meta_resp = requests.get(
            OSF_FILE_API.format(file_id=file_id), headers=headers, timeout=30
        )
        if meta_resp.ok:
            meta = meta_resp.json()
            name = meta.get("data", {}).get("attributes", {}).get("name")
            if isinstance(name, str) and name:
                return name
    except Exception:  # pragma: no cover - network issues handled gracefully
        logger.debug(
            "Failed to resolve filename for %s via OSF API.", file_id, exc_info=True
        )

    source = entry.get("source") or entry.get("atlas") or "resource"
    return f"{source}_{file_id}"


def _compute_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entry_matches_filters(
    entry: Mapping[str, object], filters: Mapping[str, str]
) -> bool:
    for key, expected in filters.items():
        value = entry.get(key)
        if value is None:
            return False
        if isinstance(value, (list, tuple, set)):
            if expected not in {str(item) for item in value}:
                return False
        else:
            if str(value) != expected:
                return False
    return True


def _download_entry(
    target: DownloadTarget,
    dest_dir: Path,
    *,
    token: Optional[str],
    timeout: int,
    chunk_size: int,
    force: bool,
) -> Optional[Path]:
    expected_checksum = (
        target.entry.get("checksum")
        or target.entry.get("md5")
        or target.entry.get("hash")
        or target.entry.get("sha1")
    )

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Derive final filename lazily once we have response headers
    try:
        response = requests.get(
            target.url, stream=True, headers=headers, timeout=timeout
        )
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - network issues delegated to user
        logger.error("Request failed for %s: %s", target.url, exc)
        return None

    filename = _infer_filename(target.entry, response, target.file_id, token)
    final_path = dest_dir / filename
    temp_path = final_path.with_suffix(final_path.suffix + ".part")

    if final_path.exists() and not force:
        if expected_checksum:
            current_md5 = _compute_md5(final_path)
            if current_md5.lower() == str(expected_checksum).lower():
                logger.info("Skipping %s (already downloaded, checksum OK)", final_path)
                response.close()
                return final_path
        else:
            logger.info(
                "Skipping %s (already exists, no checksum to verify)", final_path
            )
            response.close()
            return final_path

    try:
        with temp_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size):
                if chunk:
                    handle.write(chunk)
    except Exception as exc:  # pragma: no cover - disk issues
        logger.error("Failed to write %s: %s", temp_path, exc)
        response.close()
        temp_path.unlink(missing_ok=True)  # type: ignore[attr-defined]
        return None
    finally:
        response.close()

    temp_path.replace(final_path)

    if expected_checksum:
        actual_md5 = _compute_md5(final_path)
        if actual_md5.lower() != str(expected_checksum).lower():
            logger.error(
                "Checksum mismatch for %s (expected %s, got %s)",
                final_path,
                expected_checksum,
                actual_md5,
            )
            return None

    logger.info("Downloaded %s", final_path)
    return final_path


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    metadata_path: Path = args.metadata
    if not metadata_path.exists():
        parser.error(f"Metadata file {metadata_path} does not exist.")

    try:
        metadata = json.loads(metadata_path.read_text())
    except Exception as exc:
        parser.error(f"Failed to read metadata file {metadata_path}: {exc}")

    if args.section:
        sections = args.section
    else:
        default_section = "annotations" if "annotations" in metadata else None
        sections = [default_section] if default_section else list(metadata.keys())

    filters = _parse_filters(args.filter or [])
    token = args.token or os.getenv("NEUROMAPS_OSF_TOKEN")
    if filters:
        logger.info(
            "Applying filters: %s", ", ".join(f"{k}={v}" for k, v in filters.items())
        )
    if args.dry_run:
        logger.info("Running in dry-run mode; no files will be downloaded.")

    matched: List[DownloadTarget] = []
    for section_path in sections:
        if not section_path:
            continue
        try:
            node = _resolve_section(metadata, section_path)
        except KeyError as exc:
            logger.warning("%s", exc)
            continue

        for entry_section, entry in _iter_entries(section_path, node):
            if not isinstance(entry, Mapping):
                continue
            if filters and not _entry_matches_filters(entry, filters):
                continue
            try:
                download_url, project_id, file_id = _normalize_url(entry.get("url"))
            except Exception as exc:
                logger.debug("Skipping entry in %s: %s", entry_section, exc)
                continue
            matched.append(
                DownloadTarget(
                    section=entry_section,
                    entry=entry,
                    url=download_url,
                    file_id=file_id,
                    project_id=project_id,
                )
            )

    if not matched:
        logger.warning("No entries matched the given filters.")
        return 1

    logger.info("Matched %d resources.", len(matched))

    if args.dry_run:
        for target in matched:
            name_hint = (
                target.entry.get("fname")
                or target.entry.get("source")
                or target.file_id
            )
            logger.info("[%s] %s -> %s", target.section, name_hint, target.url)
        return 0

    exit_code = 0
    for target in matched:
        dest_root = args.output_dir / target.section.replace(".", "/")
        rel_path = target.entry.get("rel_path")
        if isinstance(rel_path, str) and rel_path.strip("/"):
            dest_root = (
                args.output_dir / target.section.split(".", 1)[0] / rel_path.strip("/")
            )

        result = _download_entry(
            target,
            dest_root,
            token=token,
            timeout=args.timeout,
            chunk_size=args.chunk_size,
            force=args.force,
        )
        if result is None:
            exit_code = 2

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
