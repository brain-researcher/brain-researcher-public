"""
Unified file resolution helper for agent tools.

Resolves file_id references to local filesystem paths, downloading from
the orchestrator if necessary. Includes security validations for path
traversal, size limits, and content type verification.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Security constants
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
ALLOWED_CONTENT_TYPES: set[str] = {
    "application/gzip",
    "application/x-gzip",
    "application/x-nifti",
    "application/octet-stream",  # Often used for .nii.gz
    "application/json",
    "text/csv",
    "text/plain",
    "application/pdf",
    "image/png",
    "image/jpeg",
}

# File ID pattern: file_{timestamp}_{session_id} or similar
FILE_ID_PATTERN = re.compile(r"^file_[a-zA-Z0-9_-]+$")


def _resolve_orchestrator_url() -> str:
    raw = (
        os.getenv("BR_ORCHESTRATOR_URL")
        or os.getenv("ORCHESTRATOR_BASE_URL")
        or os.getenv("ORCHESTRATOR_API")
        or os.getenv("ORCHESTRATOR_URL")
        or os.getenv("ORCHESTRATOR_API_URL")
        or "http://localhost:3001"
    )
    return str(raw).rstrip("/")


@dataclass
class ResolvedFile:
    """Result of resolving a file_id to a local path."""

    path: Path
    size: int
    checksum: str
    content_type: str
    source_url: str
    storage: str  # "local" | "downloaded" | "cached"
    file_id: str = ""
    filename: str = ""


@dataclass
class FileResolverConfig:
    """Configuration for FileResolver."""

    orchestrator_url: str = field(default_factory=_resolve_orchestrator_url)
    cache_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("FILE_CACHE_DIR", "/tmp/brain_researcher_files")
        )
    )
    max_file_size: int = MAX_FILE_SIZE
    allowed_content_types: set[str] = field(
        default_factory=lambda: ALLOWED_CONTENT_TYPES.copy()
    )
    auth_token: str | None = field(
        default_factory=lambda: os.getenv("ORCHESTRATOR_AUTH_TOKEN")
    )
    verify_checksum: bool = True
    timeout_seconds: float = 60.0


class FileResolverError(Exception):
    """Base exception for file resolution errors."""

    pass


class FileNotFoundError(FileResolverError):
    """File not found in orchestrator."""

    pass


class SecurityValidationError(FileResolverError):
    """Security validation failed."""

    pass


class ChecksumMismatchError(FileResolverError):
    """File checksum does not match expected value."""

    pass


class FileResolver:
    """
    Resolves file_id references to local filesystem paths.

    Usage:
        resolver = FileResolver()
        resolved = await resolver.resolve("file_123abc", "data.nii.gz")
        # Use resolved.path for local file access
    """

    def __init__(self, config: FileResolverConfig | None = None):
        self.config = config or FileResolverConfig()
        self._ensure_cache_dir()

    def _ensure_cache_dir(self) -> None:
        """Ensure the cache directory exists."""
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)

    async def resolve(
        self,
        file_id: str,
        filename: str,
        expected_checksum: str | None = None,
    ) -> ResolvedFile:
        """
        Resolve a file_id to a local path, downloading if necessary.

        Args:
            file_id: The file identifier (e.g., "file_123abc")
            filename: The original filename (for extension and cache path)
            expected_checksum: Optional checksum to verify after download

        Returns:
            ResolvedFile with local path and metadata

        Raises:
            SecurityValidationError: If file_id or filename fails validation
            FileNotFoundError: If file not found in orchestrator
            ChecksumMismatchError: If downloaded file checksum doesn't match
        """
        # Validate inputs
        safe_file_id = self._validate_file_id(file_id)
        safe_filename = self._sanitize_filename(filename)

        # Try to get file info from orchestrator
        info = await self._get_file_info(safe_file_id)

        # Check if file is already local (same host as orchestrator)
        local_path = info.get("path")
        if local_path and Path(local_path).exists():
            logger.debug(f"File {safe_file_id} found locally at {local_path}")
            return self._create_resolved_file(
                path=Path(local_path),
                info=info,
                storage="local",
                file_id=safe_file_id,
                filename=safe_filename,
            )

        # Check cache
        cached_path = self._get_cache_path(safe_file_id, safe_filename)
        if cached_path.exists():
            # Verify checksum if available
            if expected_checksum or info.get("checksum"):
                actual = self._compute_checksum(cached_path)
                expected = expected_checksum or info.get("checksum")
                if actual == expected:
                    logger.debug(f"File {safe_file_id} found in cache at {cached_path}")
                    return self._create_resolved_file(
                        path=cached_path,
                        info=info,
                        storage="cached",
                        file_id=safe_file_id,
                        filename=safe_filename,
                    )
                else:
                    logger.warning(
                        f"Cache checksum mismatch for {safe_file_id}, re-downloading"
                    )
                    cached_path.unlink()
            else:
                # No checksum to verify, use cached file
                logger.debug(f"File {safe_file_id} found in cache (no checksum)")
                return self._create_resolved_file(
                    path=cached_path,
                    info=info,
                    storage="cached",
                    file_id=safe_file_id,
                    filename=safe_filename,
                )

        # Validate before download
        self._validate_file_info(info)

        # Download to cache
        download_url = info.get("url")
        if not download_url:
            raise FileResolverError(f"No download URL for file {safe_file_id}")

        await self._download_file(download_url, cached_path)

        # Verify checksum after download
        if self.config.verify_checksum and (expected_checksum or info.get("checksum")):
            actual = self._compute_checksum(cached_path)
            expected = expected_checksum or info.get("checksum")
            if actual != expected:
                cached_path.unlink()  # Remove invalid file
                raise ChecksumMismatchError(
                    f"Checksum mismatch for {safe_file_id}: expected {expected}, got {actual}"
                )

        return self._create_resolved_file(
            path=cached_path,
            info=info,
            storage="downloaded",
            file_id=safe_file_id,
            filename=safe_filename,
        )

    async def resolve_batch(
        self,
        attachments: list[dict],
    ) -> dict[str, str]:
        """
        Resolve multiple file attachments to local paths.

        Args:
            attachments: List of attachment dicts with 'id' and 'name' keys

        Returns:
            Dict mapping file_id to local path string
        """
        resolved = {}
        for att in attachments:
            file_id = att.get("id")
            filename = att.get("name", f"{file_id}.dat")
            checksum = att.get("checksum")

            if not file_id:
                logger.warning("Attachment missing file_id, skipping")
                continue

            try:
                result = await self.resolve(file_id, filename, checksum)
                resolved[file_id] = str(result.path)
            except FileResolverError as e:
                logger.warning(f"Failed to resolve {file_id}: {e}")
                # Continue with other files
            except Exception as e:
                logger.error(f"Unexpected error resolving {file_id}: {e}")

        return resolved

    def _validate_file_id(self, file_id: str) -> str:
        """Validate file_id format."""
        if not file_id:
            raise SecurityValidationError("Empty file_id")

        if not FILE_ID_PATTERN.match(file_id):
            raise SecurityValidationError(
                f"Invalid file_id format: {file_id}. "
                f"Expected pattern: file_[alphanumeric_-]+"
            )

        return file_id

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename to prevent path traversal attacks.

        Removes path components and dangerous characters.
        """
        if not filename:
            raise SecurityValidationError("Empty filename")

        # Get base filename only (remove path components)
        name = os.path.basename(filename)

        # Remove any remaining dangerous characters
        # Allow: alphanumeric, dots, underscores, hyphens
        name = re.sub(r"[^\w.\-]", "_", name)

        # Prevent hidden files and special names
        if not name or name.startswith(".") or name in (".", ".."):
            raise SecurityValidationError(f"Invalid filename: {filename}")

        # Limit length
        if len(name) > 255:
            # Preserve extension
            base, ext = os.path.splitext(name)
            max_base = 255 - len(ext)
            name = base[:max_base] + ext

        return name

    def _validate_file_info(self, info: dict) -> None:
        """Validate file info before download."""
        # Check size
        size = info.get("size", 0)
        if size > self.config.max_file_size:
            raise SecurityValidationError(
                f"File too large: {size} bytes > {self.config.max_file_size} bytes"
            )

        # Check content type
        content_type = info.get("content_type", "")
        if content_type and content_type not in self.config.allowed_content_types:
            raise SecurityValidationError(
                f"Disallowed content type: {content_type}. "
                f"Allowed: {', '.join(sorted(self.config.allowed_content_types))}"
            )

    def _get_cache_path(self, file_id: str, filename: str) -> Path:
        """Get deterministic cache path for a file."""
        return self.config.cache_dir / file_id / filename

    async def _get_file_info(self, file_id: str) -> dict:
        """Fetch file metadata from orchestrator."""
        url = f"{self.config.orchestrator_url}/uploads/info/{file_id}"
        headers = {}
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 404:
                    raise FileNotFoundError(f"File not found: {file_id}")
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise FileNotFoundError(f"File not found: {file_id}")
                raise FileResolverError(f"Failed to get file info: {e}")
            except httpx.RequestError as e:
                raise FileResolverError(f"Request failed: {e}")

    async def _download_file(self, url: str, destination: Path) -> None:
        """Download file from URL to destination path."""
        # Ensure parent directory exists
        destination.parent.mkdir(parents=True, exist_ok=True)

        headers = {}
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"

        # Use absolute URL if relative
        if url.startswith("/"):
            url = f"{self.config.orchestrator_url}{url}"

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            try:
                async with client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()

                    # Check size from headers
                    content_length = response.headers.get("content-length")
                    if (
                        content_length
                        and int(content_length) > self.config.max_file_size
                    ):
                        raise SecurityValidationError(
                            f"File too large: {content_length} bytes"
                        )

                    # Stream to file with size tracking
                    downloaded = 0
                    with open(destination, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            downloaded += len(chunk)
                            if downloaded > self.config.max_file_size:
                                f.close()
                                destination.unlink()
                                raise SecurityValidationError(
                                    f"Download exceeded size limit: {downloaded} bytes"
                                )
                            f.write(chunk)

                    logger.info(f"Downloaded {downloaded} bytes to {destination}")

            except httpx.HTTPStatusError as e:
                raise FileResolverError(f"Download failed: {e}")
            except httpx.RequestError as e:
                raise FileResolverError(f"Request failed: {e}")

    def _compute_checksum(self, path: Path) -> str:
        """Compute SHA256 checksum of a file."""
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return f"sha256:{sha256.hexdigest()}"

    def _create_resolved_file(
        self,
        path: Path,
        info: dict,
        storage: str,
        file_id: str,
        filename: str,
    ) -> ResolvedFile:
        """Create ResolvedFile from path and metadata."""
        # Compute checksum if not provided
        checksum = info.get("checksum", "")
        if not checksum and path.exists():
            checksum = self._compute_checksum(path)

        return ResolvedFile(
            path=path,
            size=info.get("size", path.stat().st_size if path.exists() else 0),
            checksum=checksum,
            content_type=info.get("content_type", "application/octet-stream"),
            source_url=info.get("url", ""),
            storage=storage,
            file_id=file_id,
            filename=filename,
        )

    def clear_cache(self, file_id: str | None = None) -> int:
        """
        Clear cached files.

        Args:
            file_id: If provided, only clear cache for this file_id.
                    Otherwise, clear all cached files.

        Returns:
            Number of files deleted
        """
        deleted = 0
        if file_id:
            cache_dir = self.config.cache_dir / file_id
            if cache_dir.exists():
                for f in cache_dir.iterdir():
                    f.unlink()
                    deleted += 1
                cache_dir.rmdir()
        else:
            for subdir in self.config.cache_dir.iterdir():
                if subdir.is_dir():
                    for f in subdir.iterdir():
                        f.unlink()
                        deleted += 1
                    subdir.rmdir()

        logger.info(f"Cleared {deleted} cached files")
        return deleted


# Convenience function for one-off resolution
async def resolve_file(
    file_id: str,
    filename: str,
    expected_checksum: str | None = None,
) -> ResolvedFile:
    """
    Convenience function to resolve a single file.

    Uses default configuration from environment variables.
    """
    resolver = FileResolver()
    return await resolver.resolve(file_id, filename, expected_checksum)
