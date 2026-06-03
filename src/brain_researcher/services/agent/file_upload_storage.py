"""File upload storage helpers for the Agent UI API.

Provides constants, helpers, and in-memory storage classes for handling
file uploads (both simple and resumable Tus-like) served by the Agent.

No Flask objects, no route decorators — safe to import anywhere.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Allowed file extensions for upload
ALLOWED_EXTENSIONS = {
    "nii",
    "nii.gz",  # NIfTI
    "csv",
    "tsv",  # Tabular
    "json",  # JSON
    "pdf",  # Documents
    "txt",
    "md",  # Text
    "png",
    "jpg",
    "jpeg",
    "gif",  # Images
    "zip",  # Zipped datasets (BIDS)
}

# Max file size (100MB)
MAX_FILE_SIZE = 100 * 1024 * 1024

# Max resumable upload size (default 50GB; override for production)
MAX_RESUMABLE_FILE_SIZE = int(os.getenv("AGENT_RESUMABLE_MAX_BYTES", str(50 * 1024**3)))


# ---------------------------------------------------------------------------
# Upload directory helper
# ---------------------------------------------------------------------------


def _compute_upload_dir() -> Path:
    """Return upload base directory, creating it if necessary."""
    env_dir = os.getenv("AGENT_UPLOAD_DIR")
    candidates = []
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    candidates.append(Path("/tmp/brain_researcher_uploads"))
    candidates.append(Path.cwd() / ".uploads")
    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            return cand
        except Exception:
            continue
    # last resort: mkdtemp
    import tempfile

    return Path(tempfile.mkdtemp(prefix="br_uploads_"))


UPLOAD_DIR = _compute_upload_dir()


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------


def _get_file_extension(filename: str) -> str:
    """Get normalized file extension, handling .nii.gz specially."""
    if filename.lower().endswith(".nii.gz"):
        return "nii.gz"
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _is_allowed_file(filename: str) -> bool:
    """Check if file extension is allowed."""
    ext = _get_file_extension(filename)
    return ext in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Content-Range parser
# ---------------------------------------------------------------------------


def _parse_content_range(value: str) -> tuple[int, int, int]:
    """Parse ``Content-Range: bytes start-end/total``."""
    import re

    m = re.match(r"^bytes\s+(\d+)-(\d+)/(\d+)$", (value or "").strip(), re.IGNORECASE)
    if not m:
        raise ValueError("invalid_content_range")
    start = int(m.group(1))
    end = int(m.group(2))
    total = int(m.group(3))
    if start < 0 or end < start or total <= 0:
        raise ValueError("invalid_content_range_values")
    return start, end, total


# ---------------------------------------------------------------------------
# Storage classes
# ---------------------------------------------------------------------------


class FileStorage:
    """Simple file storage for uploaded files."""

    def __init__(self, base_dir: Path = UPLOAD_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._files: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def save(
        self, file_data: bytes, filename: str, content_type: str, user_id: str
    ) -> dict[str, Any]:
        """Save uploaded file and return metadata."""
        file_id = str(uuid.uuid4())
        ext = _get_file_extension(filename)
        safe_filename = f"{file_id}.{ext}" if ext else file_id

        # Create user subdirectory
        user_dir = self.base_dir / user_id
        user_dir.mkdir(parents=True, exist_ok=True)

        file_path = user_dir / safe_filename
        with open(file_path, "wb") as f:
            f.write(file_data)

        metadata = {
            "file_id": file_id,
            "filename": filename,
            "safe_filename": safe_filename,
            "content_type": content_type,
            "size": len(file_data),
            "path": str(file_path),
            "user_id": user_id,
            "url": f"/api/files/{file_id}",
            "created_at": int(time.time()),
        }

        with self._lock:
            self._files[file_id] = metadata

        return metadata

    def register_existing_file(
        self,
        *,
        file_id: str,
        filename: str,
        content_type: str,
        user_id: str,
        file_path: Path,
    ) -> dict[str, Any]:
        """Register an already-written file in storage (used by resumable uploads)."""
        ext = _get_file_extension(filename)
        safe_filename = f"{file_id}.{ext}" if ext else file_id

        user_dir = self.base_dir / user_id
        user_dir.mkdir(parents=True, exist_ok=True)

        final_path = user_dir / safe_filename
        if file_path.resolve() != final_path.resolve():
            final_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.replace(final_path)

        try:
            size = final_path.stat().st_size
        except Exception:
            size = None

        metadata = {
            "file_id": file_id,
            "filename": filename,
            "safe_filename": safe_filename,
            "content_type": content_type or "application/octet-stream",
            "size": size,
            "path": str(final_path),
            "user_id": user_id,
            "url": f"/api/files/{file_id}",
            "created_at": int(time.time()),
        }

        with self._lock:
            self._files[file_id] = metadata

        return metadata

    def get(self, file_id: str) -> dict[str, Any] | None:
        """Get file metadata by ID."""
        with self._lock:
            return self._files.get(file_id)

    def delete(self, file_id: str, user_id: str) -> bool:
        """Delete a file. Only owner can delete."""
        with self._lock:
            metadata = self._files.get(file_id)
            if not metadata:
                return False
            if metadata["user_id"] != user_id:
                return False

            # Delete physical file
            try:
                Path(metadata["path"]).unlink(missing_ok=True)
            except Exception:
                pass

            del self._files[file_id]
            return True

    def list_user_files(self, user_id: str) -> list[dict[str, Any]]:
        """List all files for a user."""
        with self._lock:
            return [m for m in self._files.values() if m["user_id"] == user_id]


class ResumableUploadStorage:
    """In-memory resumable upload tracker (Tus-like, minimal)."""

    def __init__(self, base_dir: Path = UPLOAD_DIR):
        self.base_dir = base_dir
        self._uploads: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def init(
        self,
        *,
        filename: str,
        content_type: str,
        total_size: int,
        user_id: str,
    ) -> dict[str, Any]:
        if total_size < 0:
            raise ValueError("total_size must be >= 0")
        if total_size > MAX_RESUMABLE_FILE_SIZE:
            raise ValueError("total_size exceeds server limit")

        upload_id = str(uuid.uuid4())
        ext = _get_file_extension(filename)
        safe_filename = f"{upload_id}.{ext}" if ext else upload_id

        user_dir = self.base_dir / user_id
        user_dir.mkdir(parents=True, exist_ok=True)

        tmp_path = user_dir / f".{safe_filename}.partial"
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_bytes(b"")

        meta = {
            "upload_id": upload_id,
            "filename": filename,
            "content_type": content_type or "application/octet-stream",
            "total_size": int(total_size),
            "received": 0,
            "path": str(tmp_path),
            "user_id": user_id,
            "created_at": int(time.time()),
            "status": "uploading",
        }
        with self._lock:
            self._uploads[upload_id] = meta
        return meta

    def get(self, upload_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._uploads.get(upload_id)

    def append_chunk(
        self,
        *,
        upload_id: str,
        user_id: str,
        start: int,
        data: bytes,
        total: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            meta = self._uploads.get(upload_id)
            if not meta:
                raise KeyError("upload not found")
            if meta["user_id"] != user_id:
                raise PermissionError("not owner")
            if meta.get("status") != "uploading":
                raise ValueError("upload not in uploading state")
            received = int(meta.get("received", 0))
            total_size = int(meta.get("total_size", 0))

        if start != received:
            raise ValueError(f"offset_mismatch expected={received} got={start}")
        if total is not None and int(total) != total_size:
            raise ValueError("total_size_mismatch")
        if received + len(data) > total_size:
            raise ValueError("chunk_exceeds_total")

        path = Path(meta["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as f:
            f.write(data)

        with self._lock:
            meta = self._uploads.get(upload_id)
            if not meta:
                raise KeyError("upload not found")
            meta["received"] = received + len(data)
            if meta["received"] == total_size:
                meta["status"] = "uploaded"
            return dict(meta)

    def abort(self, *, upload_id: str, user_id: str) -> bool:
        with self._lock:
            meta = self._uploads.get(upload_id)
            if not meta:
                return False
            if meta["user_id"] != user_id:
                return False
            del self._uploads[upload_id]

        try:
            Path(meta["path"]).unlink(missing_ok=True)
        except Exception:
            pass
        return True

    def complete(
        self, *, upload_id: str, user_id: str, storage: FileStorage
    ) -> dict[str, Any]:
        with self._lock:
            meta = self._uploads.get(upload_id)
            if not meta:
                raise KeyError("upload not found")
            if meta["user_id"] != user_id:
                raise PermissionError("not owner")
            if int(meta.get("received", 0)) != int(meta.get("total_size", 0)):
                raise ValueError("upload_incomplete")
            if meta.get("status") not in {"uploaded", "uploading"}:
                raise ValueError("invalid_state")
            meta["status"] = "completed"

        tmp_path = Path(meta["path"]).resolve()
        file_id = upload_id
        return storage.register_existing_file(
            file_id=file_id,
            filename=meta["filename"],
            content_type=meta["content_type"],
            user_id=user_id,
            file_path=tmp_path,
        )
