from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ._utils import _run, tool

logger = logging.getLogger(__name__)


def _retry_request(func, max_retries: int = 3, initial_delay: float = 1.0):
    """Retry network requests with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = initial_delay * (2**attempt)
            logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}): {e}")
            logger.info(f"Retrying in {delay:.1f} seconds...")
            time.sleep(delay)


@tool
def download_openneuro(
    dataset_id: str,
    out_dir: str,
    use_s3: bool = True,
    exclude_derivatives: bool = False,
) -> str:
    """Download from OpenNeuro using AWS S3 sync (recommended) or fallback methods.

    Args:
        dataset_id: OpenNeuro dataset ID (e.g., 'ds000114')
        out_dir: Output directory path
        use_s3: Use AWS S3 sync method (recommended, no authentication required)
        exclude_derivatives: Exclude derivative folders to save space

    Returns:
        Path to downloaded dataset
    """
    dataset_path = Path(out_dir) / dataset_id
    dataset_path.mkdir(parents=True, exist_ok=True)

    if use_s3:
        # Use AWS S3 sync - the recommended method for OpenNeuro downloads
        cmd = [
            "aws",
            "s3",
            "sync",
            "--no-sign-request",  # No authentication required
            f"s3://openneuro.org/{dataset_id}/",
            dataset_path.resolve().as_posix(),
        ]

        # Add exclusions if requested
        if exclude_derivatives:
            cmd.extend(["--exclude", "derivatives/*"])

        # Exclude version control files
        cmd.extend(
            [
                "--exclude",
                ".git/*",
                "--exclude",
                ".datalad/*",
                "--exclude",
                ".gitattributes",
            ]
        )

        logger.info(f"Downloading {dataset_id} from S3 (this may take a while)...")
        _run(cmd)
    else:
        # Fallback to openneuro CLI if available
        cmd = ["openneuro", "download", dataset_id, Path(out_dir).resolve().as_posix()]
        _run(cmd)

    return dataset_path.resolve().as_posix()


@tool
def list_openneuro_files(dataset_id: str, use_s3: bool = True) -> list[str]:
    """List files in OpenNeuro dataset using S3 or CLI.

    Args:
        dataset_id: OpenNeuro dataset ID (e.g., 'ds000114')
        use_s3: Use AWS S3 ls command (recommended)

    Returns:
        List of file paths in the dataset
    """
    if use_s3:
        cmd = [
            "aws",
            "s3",
            "ls",
            "--no-sign-request",
            f"s3://openneuro.org/{dataset_id}/",
            "--recursive",
        ]
        proc = _run(cmd)
        # Parse S3 ls output to extract file paths
        files = []
        for line in proc.stdout.splitlines():
            if line.strip():
                # S3 ls format: "2023-01-01 12:00:00  size  path"
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    files.append(parts[3])
        return files
    else:
        # Fallback to openneuro CLI
        cmd = ["openneuro", "list-files", dataset_id]
        proc = _run(cmd)
        return [line for line in proc.stdout.splitlines() if line]


@tool
def download_openneuro_subset(
    dataset_id: str,
    out_dir: str,
    include: Iterable[str],
    *,
    exclude: Iterable[str] | None = None,
    verify_hash: bool = False,
    verify_size: bool = True,
    max_retries: int = 3,
    max_concurrent_downloads: int = 5,
) -> str:
    """Download a targeted public OpenNeuro subset into ``out_dir``.

    The destination is treated as the dataset root. Callers should provide
    include patterns relative to the OpenNeuro dataset root, for example
    ``sub-01/**/*bold*`` or ``derivatives/fmriprep/**/*confounds*``.
    """

    try:
        import openneuro
    except Exception as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "openneuro-py is required for targeted OpenNeuro subset downloads."
        ) from exc

    dataset_root = Path(out_dir).expanduser().resolve()
    dataset_root.mkdir(parents=True, exist_ok=True)
    include_patterns = [
        str(pattern).strip() for pattern in (include or []) if str(pattern).strip()
    ]
    if not include_patterns:
        raise ValueError("At least one include pattern is required.")
    exclude_patterns = [
        str(pattern).strip() for pattern in (exclude or []) if str(pattern).strip()
    ]

    openneuro.download(
        dataset=dataset_id,
        target_dir=dataset_root,
        include=include_patterns,
        exclude=exclude_patterns or None,
        verify_hash=verify_hash,
        verify_size=verify_size,
        max_retries=max_retries,
        max_concurrent_downloads=max_concurrent_downloads,
    )
    return dataset_root.as_posix()


@tool
def download_dandiset(
    dandiset_id: str, out_dir: str, include_assets: str = "all"
) -> str:
    """Download from DANDI."""
    cmd = [
        "dandi",
        "download",
        dandiset_id,
        "--output-dir",
        Path(out_dir).resolve().as_posix(),
    ]
    if include_assets != "all":
        cmd += ["--include", include_assets]
    _run(cmd)
    return Path(out_dir).resolve().as_posix()


@tool
def search_dandi(search_term: str, max_results: int = 20) -> list[dict[str, Any]]:
    """Search the DANDI archive for matching dandisets."""
    import requests

    def _make_request():
        resp = requests.get(
            "https://api.dandiarchive.org/api/dandisets/",
            params={"search": search_term, "page[size]": max_results},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", []) or []
        if max_results and max_results > 0:
            return results[:max_results]
        return results

    return _retry_request(_make_request)


@tool
def download_neurovault_collection(collection_id: int, out_dir: str) -> list[str]:
    """Download NeuroVault collection."""
    import requests

    def _get_collection_metadata():
        resp = requests.get(
            f"https://neurovault.org/api/collections/{collection_id}/images/",
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])

    images = _retry_request(_get_collection_metadata)
    paths = []
    for img in images:
        url = img.get("file")
        if not url:
            continue
        fname = Path(out_dir) / Path(url).name

        def _download_file(download_url: str = url):
            r = requests.get(download_url, timeout=30)
            r.raise_for_status()
            return r.content

        content = _retry_request(_download_file)
        fname.parent.mkdir(parents=True, exist_ok=True)
        with open(fname, "wb") as f:
            f.write(content)
        paths.append(fname.resolve().as_posix())
    return paths


@tool
def search_neurovault_images(
    text_query: str, threshold: float = 0.8
) -> list[dict[str, Any]]:
    """Search NeuroVault images."""
    import requests

    def _make_request():
        resp = requests.get(
            "https://neurovault.org/api/images/",
            params={"search": text_query, "threshold": threshold},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])

    return _retry_request(_make_request)
