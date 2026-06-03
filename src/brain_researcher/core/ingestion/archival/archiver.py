"""Data archival system for long-term storage and retrieval."""

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tarfile
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ArchiveStatus(Enum):
    """Archive status states."""

    PENDING = "pending"
    ARCHIVING = "archiving"
    ARCHIVED = "archived"
    RETRIEVING = "retrieving"
    RESTORED = "restored"
    EXPIRED = "expired"
    ERROR = "error"


class CompressionLevel(Enum):
    """Compression levels for archival."""

    NONE = 0
    FAST = 1
    BALANCED = 6
    MAXIMUM = 9


class DataArchiver:
    """Manages long-term data archival and retrieval."""

    def __init__(
        self,
        archive_dir: str = "/data/archives",
        staging_dir: str = "/tmp/staging",
        db_path: str = "/data/archive_catalog.db",
    ):
        """Initialize data archiver.

        Args:
            archive_dir: Long-term storage directory
            staging_dir: Temporary staging area
            db_path: Archive catalog database path
        """
        self.archive_dir = Path(archive_dir)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        self.staging_dir = Path(staging_dir)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = Path(db_path)
        self._initialize_database()

        # Default policies
        self.default_retention_days = 365 * 5  # 5 years
        self.default_compression = CompressionLevel.BALANCED

    def _initialize_database(self):
        """Initialize archive catalog database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS archives (
                archive_id TEXT PRIMARY KEY,
                dataset_name TEXT NOT NULL,
                source_path TEXT NOT NULL,
                archive_path TEXT NOT NULL,
                size_bytes INTEGER,
                checksum TEXT,
                compression_type TEXT,
                compression_ratio REAL,
                archived_at TIMESTAMP,
                expires_at TIMESTAMP,
                status TEXT,
                metadata TEXT
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS retrieval_history (
                retrieval_id TEXT PRIMARY KEY,
                archive_id TEXT,
                retrieved_at TIMESTAMP,
                restored_path TEXT,
                user TEXT,
                FOREIGN KEY (archive_id) REFERENCES archives (archive_id)
            )
        """
        )

        conn.commit()
        conn.close()

    def archive_dataset(
        self,
        dataset_path: str,
        dataset_name: str | None = None,
        retention_days: int | None = None,
        compression: CompressionLevel | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Archive a dataset for long-term storage.

        Args:
            dataset_path: Path to dataset to archive
            dataset_name: Optional name for archive
            retention_days: Days to retain archive
            compression: Compression level
            metadata: Additional metadata

        Returns:
            Archive information
        """
        dataset_path = Path(dataset_path)

        if not dataset_path.exists():
            raise FileNotFoundError(f"Dataset not found: {dataset_path}")

        # Generate archive ID and name
        archive_id = self._generate_archive_id()
        dataset_name = dataset_name or dataset_path.name

        # Set retention and compression
        retention_days = retention_days or self.default_retention_days
        compression = compression or self.default_compression

        logger.info(f"Archiving dataset: {dataset_name} (ID: {archive_id})")

        # Update status
        self._update_archive_status(archive_id, ArchiveStatus.ARCHIVING)

        try:
            # Stage the data
            staged_path = self._stage_data(dataset_path, archive_id)

            # Calculate checksum before compression
            checksum = self._calculate_checksum(staged_path)

            # Compress if requested
            if compression != CompressionLevel.NONE:
                original_size = self._get_path_size(staged_path)
                archive_path = self._compress_data(staged_path, compression)
                compression_ratio = self._calculate_compression_ratio(
                    original_size, archive_path
                )
            else:
                archive_path = staged_path
                compression_ratio = 1.0

            # Move to archive location
            final_path = self.archive_dir / f"{archive_id}.tar.gz"
            shutil.move(str(archive_path), str(final_path))

            archived_at = datetime.now()
            expires_at = archived_at + timedelta(days=retention_days)

            # Store in catalog
            archive_info = {
                "archive_id": archive_id,
                "dataset_name": dataset_name,
                "source_path": str(dataset_path),
                "archive_path": str(final_path),
                "size_bytes": final_path.stat().st_size,
                "checksum": checksum,
                "compression_type": compression.name,
                "compression_ratio": compression_ratio,
                "archived_at": archived_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "status": ArchiveStatus.ARCHIVED.value,
                "metadata": json.dumps(metadata or {}),
            }

            self._store_archive_info(archive_info)

            # Clean up staging
            self._cleanup_staging(archive_id)

            logger.info(f"Archive completed: {archive_id}")
            return archive_info

        except Exception as e:
            logger.error(f"Archive failed: {e}")
            self._update_archive_status(archive_id, ArchiveStatus.ERROR)
            self._cleanup_staging(archive_id)
            raise

    def retrieve_archive(
        self,
        archive_id: str,
        restore_path: str | None = None,
        user: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve an archived dataset.

        Args:
            archive_id: Archive identifier
            restore_path: Where to restore the data
            user: User requesting retrieval

        Returns:
            Retrieval information
        """
        logger.info(f"Retrieving archive: {archive_id}")

        # Get archive info
        archive_info = self._get_archive_info(archive_id)

        if not archive_info:
            raise ValueError(f"Archive not found: {archive_id}")

        if archive_info["status"] == ArchiveStatus.EXPIRED.value:
            raise ValueError(f"Archive has expired: {archive_id}")

        # Update status
        self._update_archive_status(archive_id, ArchiveStatus.RETRIEVING)

        try:
            # Determine restore path
            if not restore_path:
                restore_path = self.staging_dir / f"restore_{archive_id}"
            else:
                restore_path = Path(restore_path)

            restore_path.mkdir(parents=True, exist_ok=True)

            # Copy from archive
            archive_file = Path(archive_info["archive_path"])

            if not archive_file.exists():
                raise FileNotFoundError(f"Archive file not found: {archive_file}")

            # Decompress if needed
            if archive_info["compression_type"] != "NONE":
                self._decompress_archive(archive_file, restore_path)
            else:
                if archive_file.is_dir():
                    shutil.copytree(archive_file, restore_path, dirs_exist_ok=True)
                else:
                    shutil.copy2(archive_file, restore_path)

            # Verify checksum
            restored_checksum = self._calculate_checksum(restore_path)
            if restored_checksum != archive_info["checksum"]:
                logger.warning("Checksum mismatch during retrieval")

            # Log retrieval
            retrieval_info = {
                "retrieval_id": self._generate_archive_id(),
                "archive_id": archive_id,
                "retrieved_at": datetime.now().isoformat(),
                "restored_path": str(restore_path),
                "user": user or "unknown",
            }

            self._log_retrieval(retrieval_info)

            # Update status
            self._update_archive_status(archive_id, ArchiveStatus.RESTORED)

            logger.info(f"Retrieval completed: {restore_path}")
            return retrieval_info

        except Exception as e:
            logger.error(f"Retrieval failed: {e}")
            self._update_archive_status(archive_id, ArchiveStatus.ERROR)
            raise

    def list_archives(
        self, status: ArchiveStatus | None = None, dataset_name: str | None = None
    ) -> list[dict[str, Any]]:
        """List archived datasets.

        Args:
            status: Filter by status
            dataset_name: Filter by dataset name

        Returns:
            List of archive records
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = "SELECT * FROM archives WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status.value)

        if dataset_name:
            query += " AND dataset_name LIKE ?"
            params.append(f"%{dataset_name}%")

        cursor.execute(query, params)

        columns = [desc[0] for desc in cursor.description]
        archives = []

        for row in cursor.fetchall():
            archive = dict(zip(columns, row, strict=False))
            # Parse metadata
            if archive.get("metadata"):
                archive["metadata"] = json.loads(archive["metadata"])
            archives.append(archive)

        conn.close()
        return archives

    def check_expiration(self) -> list[str]:
        """Check for expired archives.

        Returns:
            List of expired archive IDs
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT archive_id FROM archives
            WHERE expires_at < ? AND status != ?
        """,
            (datetime.now().isoformat(), ArchiveStatus.EXPIRED.value),
        )

        expired = [row[0] for row in cursor.fetchall()]

        # Update status for expired archives
        for archive_id in expired:
            self._update_archive_status(archive_id, ArchiveStatus.EXPIRED)

        conn.close()

        if expired:
            logger.info(f"Found {len(expired)} expired archives")

        return expired

    def purge_expired(self, confirm: bool = False) -> dict[str, Any]:
        """Purge expired archives to free space.

        Args:
            confirm: Confirmation flag for safety

        Returns:
            Purge results
        """
        if not confirm:
            raise ValueError("Purge requires confirmation flag")

        expired = set(self.check_expiration())
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT archive_id FROM archives WHERE status = ?",
            (ArchiveStatus.EXPIRED.value,),
        )
        expired.update(row[0] for row in cursor.fetchall())
        conn.close()
        expired = list(expired)
        purged = []
        failed = []
        space_freed = 0

        for archive_id in expired:
            try:
                archive_info = self._get_archive_info(archive_id)
                archive_path = Path(archive_info["archive_path"])

                if archive_path.exists():
                    size = archive_path.stat().st_size
                    archive_path.unlink()
                    space_freed += size

                # Remove from catalog
                self._remove_from_catalog(archive_id)
                purged.append(archive_id)

                logger.info(f"Purged archive: {archive_id}")

            except Exception as e:
                logger.error(f"Failed to purge {archive_id}: {e}")
                failed.append(archive_id)

        return {
            "purged": purged,
            "failed": failed,
            "space_freed_bytes": space_freed,
            "space_freed_gb": space_freed / (1024**3),
        }

    def get_storage_stats(self) -> dict[str, Any]:
        """Get archive storage statistics.

        Returns:
            Storage statistics
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Total archives
        cursor.execute("SELECT COUNT(*) FROM archives")
        total_archives = cursor.fetchone()[0]

        # Storage by status
        cursor.execute(
            """
            SELECT status, COUNT(*), SUM(size_bytes)
            FROM archives
            GROUP BY status
        """
        )

        status_stats = {}
        total_size = 0

        for status, count, size in cursor.fetchall():
            status_stats[status] = {
                "count": count,
                "size_bytes": size or 0,
                "size_gb": (size or 0) / (1024**3),
            }
            total_size += size or 0

        # Average compression ratio
        cursor.execute(
            """
            SELECT AVG(compression_ratio)
            FROM archives
            WHERE compression_type != 'NONE'
        """
        )
        avg_compression = cursor.fetchone()[0] or 1.0

        conn.close()

        # Check disk space
        archive_stats = os.statvfs(self.archive_dir)
        free_space = archive_stats.f_bavail * archive_stats.f_frsize
        total_space = archive_stats.f_blocks * archive_stats.f_frsize

        return {
            "total_archives": total_archives,
            "status_breakdown": status_stats,
            "total_size_bytes": total_size,
            "total_size_gb": total_size / (1024**3),
            "average_compression_ratio": avg_compression,
            "disk_free_bytes": free_space,
            "disk_free_gb": free_space / (1024**3),
            "disk_total_gb": total_space / (1024**3),
            "disk_usage_percent": (1 - free_space / total_space) * 100,
        }

    # Private helper methods

    def _generate_archive_id(self) -> str:
        """Generate unique archive ID."""
        timestamp = datetime.now().isoformat()
        return f"arch_{hashlib.md5(timestamp.encode()).hexdigest()[:12]}"

    def _stage_data(self, source_path: Path, archive_id: str) -> Path:
        """Stage data for archival."""
        staged_dir = self.staging_dir / archive_id

        if source_path.is_dir():
            shutil.copytree(source_path, staged_dir)
        else:
            staged_dir.mkdir()
            shutil.copy2(source_path, staged_dir)

        return staged_dir

    def _compress_data(self, data_path: Path, compression: CompressionLevel) -> Path:
        """Compress data for archival."""
        archive_path = data_path.with_suffix(".tar.gz")

        with tarfile.open(archive_path, "w:gz", compresslevel=compression.value) as tar:
            tar.add(data_path, arcname=data_path.name)

        # Remove uncompressed data
        if data_path.is_dir():
            shutil.rmtree(data_path)
        else:
            data_path.unlink()

        return archive_path

    def _decompress_archive(self, archive_path: Path, restore_path: Path):
        """Decompress archived data."""
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(restore_path)

    def _calculate_checksum(self, path: Path) -> str:
        """Calculate MD5 checksum."""
        md5 = hashlib.md5()

        if path.is_file():
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    md5.update(chunk)
        else:
            # Checksum of directory contents
            for file in sorted(path.rglob("*")):
                if file.is_file():
                    with open(file, "rb") as f:
                        for chunk in iter(lambda: f.read(8192), b""):
                            md5.update(chunk)

        return md5.hexdigest()

    def _calculate_compression_ratio(
        self, original: Path | int, compressed: Path
    ) -> float:
        """Calculate compression ratio."""
        if isinstance(original, int | float):
            original_size = int(original)
        else:
            if not original.exists():
                return 1.0
            original_size = self._get_path_size(original)

        if not compressed.exists():
            return 1.0

        compressed_size = compressed.stat().st_size
        if compressed_size <= 0 or original_size <= 0:
            return 1.0

        ratio = original_size / compressed_size
        return ratio if ratio >= 1.0 else 1.0

    def _get_path_size(self, path: Path) -> int:
        """Get total size of path."""
        if path.is_file():
            return path.stat().st_size

        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    def _store_archive_info(self, info: dict[str, Any]):
        """Store archive information in catalog."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO archives VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                info["archive_id"],
                info["dataset_name"],
                info["source_path"],
                info["archive_path"],
                info["size_bytes"],
                info["checksum"],
                info["compression_type"],
                info["compression_ratio"],
                info["archived_at"],
                info["expires_at"],
                info["status"],
                info["metadata"],
            ),
        )

        conn.commit()
        conn.close()

    def _get_archive_info(self, archive_id: str) -> dict[str, Any] | None:
        """Get archive information from catalog."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM archives WHERE archive_id = ?", (archive_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return None

        columns = [desc[0] for desc in cursor.description]
        info = dict(zip(columns, row, strict=False))

        # Parse metadata
        if info.get("metadata"):
            info["metadata"] = json.loads(info["metadata"])

        conn.close()
        return info

    def _update_archive_status(self, archive_id: str, status: ArchiveStatus):
        """Update archive status."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE archives SET status = ?
            WHERE archive_id = ?
        """,
            (status.value, archive_id),
        )

        conn.commit()
        conn.close()

    def _log_retrieval(self, retrieval_info: dict[str, Any]):
        """Log archive retrieval."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO retrieval_history VALUES (?, ?, ?, ?, ?)
        """,
            (
                retrieval_info["retrieval_id"],
                retrieval_info["archive_id"],
                retrieval_info["retrieved_at"],
                retrieval_info["restored_path"],
                retrieval_info["user"],
            ),
        )

        conn.commit()
        conn.close()

    def _cleanup_staging(self, archive_id: str):
        """Clean up staging directory."""
        staging_path = self.staging_dir / archive_id
        if staging_path.exists():
            shutil.rmtree(staging_path)

    def _remove_from_catalog(self, archive_id: str):
        """Remove archive from catalog."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM archives WHERE archive_id = ?", (archive_id,))

        conn.commit()
        conn.close()
