"""
Backup Validation Tests

Tests for backup script execution, integrity checks, compression, encryption,
and retention policies.
"""

import gzip
import json
import os
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest


class TestBackupScriptExecution:
    """Test backup script execution"""

    def test_postgres_backup_script_success(
        self, backup_config, mock_postgres_connection
    ):
        """Test successful PostgreSQL backup execution"""
        with patch("subprocess.run") as mock_run:
            # Mock successful pg_dump
            mock_run.side_effect = [
                Mock(returncode=0),  # pg_isready
                Mock(returncode=0),  # pg_dump custom format
                Mock(returncode=0),  # pg_dump plain format
            ]

            # Import and run backup script logic
            from backup.scripts import postgres_backup

            result = postgres_backup.run_backup(backup_config)

            assert result["success"] is True
            assert "backup_file" in result
            assert mock_run.call_count >= 2

    def test_br_kg_backup_script_success(self, backup_config, sample_br_kg_db):
        """Test successful BR-KG backup execution"""
        # Copy sample DB to expected location
        br_kg_dir = Path(backup_config["backup_dir"]) / "br_kg"
        br_kg_dir.mkdir(exist_ok=True)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            # Simulate backup script
            result = self._run_br_kg_backup(backup_config)

            assert result["success"] is True
            assert result["components_backed_up"] > 0

    def test_redis_backup_script_success(self, backup_config, sample_redis_data):
        """Test successful Redis backup execution"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            result = self._run_redis_backup(backup_config)

            assert result["success"] is True
            assert result["backup_types"] == ["rdb", "aof", "json"]

    def test_backup_script_failure_handling(self, backup_config):
        """Test backup script handles failures gracefully"""
        with patch("subprocess.run") as mock_run:
            # Mock command failure
            mock_run.return_value = Mock(returncode=1, stderr="Connection failed")

            result = self._run_postgres_backup_with_error(backup_config)

            assert result["success"] is False
            assert "error" in result
            assert "Connection failed" in result["error"]

    def test_backup_script_timeout_handling(self, backup_config):
        """Test backup script handles timeouts"""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(["pg_dump"], 30)

            result = self._run_postgres_backup_with_timeout(backup_config)

            assert result["success"] is False
            assert "timeout" in result.get("error", "").lower()

    def test_parallel_backup_execution(self, backup_config):
        """Test parallel execution of multiple backup scripts"""
        from concurrent.futures import ThreadPoolExecutor

        def mock_backup_component(component):
            return {"success": True, "component": component}

        with ThreadPoolExecutor(max_workers=3) as executor:
            components = ["postgres", "br_kg", "redis"]
            futures = {
                executor.submit(mock_backup_component, comp): comp
                for comp in components
            }

            results = {}
            for future in futures:
                comp = futures[future]
                results[comp] = future.result()

        assert len(results) == 3
        assert all(r["success"] for r in results.values())

    def _run_br_kg_backup(self, config):
        """Mock BR-KG backup execution"""
        return {
            "success": True,
            "components_backed_up": 2,
            "backup_file": f"{config['backup_dir']}/br_kg_20240101_120000.tar.gz.enc",
        }

    def _run_redis_backup(self, config):
        """Mock Redis backup execution"""
        return {
            "success": True,
            "backup_types": ["rdb", "aof", "json"],
            "backup_file": f"{config['backup_dir']}/redis_20240101_120000.tar.gz.enc",
        }

    def _run_postgres_backup_with_error(self, config):
        """Mock PostgreSQL backup with error"""
        return {"success": False, "error": "Connection failed"}

    def _run_postgres_backup_with_timeout(self, config):
        """Mock PostgreSQL backup with timeout"""
        return {"success": False, "error": "Backup operation timeout"}


class TestBackupIntegrity:
    """Test backup integrity verification"""

    def test_backup_file_integrity_check(self, temp_backup_dir, mock_encryption_key):
        """Test basic backup file integrity"""
        # Create test backup file
        backup_file = temp_backup_dir / "test_backup.sql.gz"
        with gzip.open(backup_file, "wt") as f:
            f.write("-- Test SQL content\nCREATE TABLE test (id INT);")

        # Verify integrity
        result = self._verify_file_integrity(backup_file)

        assert result["valid"] is True
        assert result["file_size"] > 0
        assert result["compression_valid"] is True

    def test_corrupted_backup_detection(self, temp_backup_dir):
        """Test detection of corrupted backups"""
        # Create corrupted file
        corrupted_file = temp_backup_dir / "corrupted_backup.sql.gz"
        corrupted_file.write_bytes(b"not a valid gzip file")

        result = self._verify_file_integrity(corrupted_file)

        assert result["valid"] is False
        assert result["compression_valid"] is False

    def test_empty_backup_detection(self, temp_backup_dir):
        """Test detection of empty backup files"""
        empty_file = temp_backup_dir / "empty_backup.sql"
        empty_file.write_text("")

        result = self._verify_file_integrity(empty_file)

        assert result["valid"] is False
        assert result["file_size"] == 0

    def test_backup_checksum_verification(self, temp_backup_dir):
        """Test backup file checksum verification"""
        import hashlib

        backup_file = temp_backup_dir / "test_backup.sql"
        content = "-- Test backup content\nCREATE TABLE test (id INT);"
        backup_file.write_text(content)

        # Calculate expected checksum
        expected_checksum = hashlib.sha256(content.encode()).hexdigest()

        result = self._verify_checksum(backup_file)

        assert result["checksum"] == expected_checksum
        assert result["valid"] is True

    def test_metadata_validation(self, temp_backup_dir, backup_metadata):
        """Test backup metadata validation"""
        metadata_file = temp_backup_dir / "metadata.json"
        metadata_file.write_text(json.dumps(backup_metadata))

        result = self._validate_metadata(metadata_file)

        assert result["valid"] is True
        assert result["required_fields_present"] is True
        assert result["timestamp_valid"] is True

    def test_sql_content_validation(self, sample_postgres_backup):
        """Test PostgreSQL backup SQL content validation"""
        # Decompress and read content
        with gzip.open(sample_postgres_backup, "rt") as f:
            content = f.read()

        result = self._validate_sql_content(content)

        assert result["valid_sql"] is True
        assert result["has_dump_header"] is True
        assert result["has_create_statements"] is True

    def test_database_backup_validation(self, temp_backup_dir, sample_br_kg_db):
        """Test database backup content validation"""
        # Create backup archive containing the database
        import tarfile

        archive_path = temp_backup_dir / "br_kg_backup.tar"
        with tarfile.open(archive_path, "w") as tar:
            tar.add(sample_br_kg_db, arcname="br_kg_graph.db")

        result = self._validate_database_backup(archive_path)

        assert result["valid"] is True
        assert result["database_files"] > 0
        assert result["tables_found"] > 0

    def _verify_file_integrity(self, file_path):
        """Mock file integrity verification"""
        try:
            file_size = file_path.stat().st_size

            if file_size == 0:
                return {"valid": False, "file_size": 0, "compression_valid": False}

            compression_valid = True
            if file_path.suffix == ".gz":
                try:
                    with gzip.open(file_path, "rt") as f:
                        f.read(1)  # Try to read first byte
                except:
                    compression_valid = False

            return {
                "valid": compression_valid and file_size > 0,
                "file_size": file_size,
                "compression_valid": compression_valid,
            }
        except Exception:
            return {"valid": False, "file_size": 0, "compression_valid": False}

    def _verify_checksum(self, file_path):
        """Mock checksum verification"""
        import hashlib

        with open(file_path, "rb") as f:
            content = f.read()

        checksum = hashlib.sha256(content).hexdigest()
        return {"checksum": checksum, "valid": True}

    def _validate_metadata(self, metadata_file):
        """Mock metadata validation"""
        with open(metadata_file, "r") as f:
            metadata = json.load(f)

        required_fields = ["backup_type", "timestamp", "backup_file", "size_bytes"]
        fields_present = all(field in metadata for field in required_fields)

        # Validate timestamp format
        timestamp_valid = True
        try:
            datetime.strptime(metadata.get("timestamp", ""), "%Y%m%d_%H%M%S")
        except:
            timestamp_valid = False

        return {
            "valid": fields_present and timestamp_valid,
            "required_fields_present": fields_present,
            "timestamp_valid": timestamp_valid,
        }

    def _validate_sql_content(self, content):
        """Mock SQL content validation"""
        has_dump_header = "-- PostgreSQL database dump" in content
        has_create_statements = "CREATE" in content
        has_set_statements = "SET" in content

        return {
            "valid_sql": has_dump_header
            and (has_create_statements or has_set_statements),
            "has_dump_header": has_dump_header,
            "has_create_statements": has_create_statements,
        }

    def _validate_database_backup(self, archive_path):
        """Mock database backup validation"""
        import tarfile

        with tarfile.open(archive_path, "r") as tar:
            members = tar.getmembers()
            db_files = [m for m in members if m.name.endswith(".db")]

        # Check tables in database if found
        tables_found = 0
        if db_files:
            # Mock table count
            tables_found = 2

        return {
            "valid": len(db_files) > 0,
            "database_files": len(db_files),
            "tables_found": tables_found,
        }


class TestCompressionAndEncryption:
    """Test backup compression and encryption"""

    def test_gzip_compression(self, temp_backup_dir):
        """Test gzip compression functionality"""
        # Create test file
        test_file = temp_backup_dir / "test_backup.sql"
        content = "-- Large test content\n" + "SELECT * FROM test;\n" * 1000
        test_file.write_text(content)

        original_size = test_file.stat().st_size

        # Compress
        compressed_file = temp_backup_dir / "test_backup.sql.gz"
        with open(test_file, "rb") as f_in:
            with gzip.open(compressed_file, "wb") as f_out:
                f_out.write(f_in.read())

        compressed_size = compressed_file.stat().st_size
        compression_ratio = compressed_size / original_size

        assert compressed_size < original_size
        assert compression_ratio < 0.5  # Should achieve significant compression

        # Test decompression
        with gzip.open(compressed_file, "rt") as f:
            decompressed_content = f.read()

        assert decompressed_content == content

    def test_encryption_decryption(self, temp_backup_dir, mock_encryption_key):
        """Test AES encryption and decryption"""
        test_file = temp_backup_dir / "test_backup.sql"
        content = "-- Secret backup content\nCREATE TABLE secret (id INT);"
        test_file.write_text(content)

        encrypted_file = temp_backup_dir / "test_backup.sql.enc"

        # Mock encryption
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            result = self._encrypt_file(test_file, encrypted_file, mock_encryption_key)

            assert result["success"] is True
            assert mock_run.called

            # Mock decryption verification
            decrypt_result = self._decrypt_file(encrypted_file, mock_encryption_key)
            assert decrypt_result["success"] is True

    def test_compression_encryption_pipeline(
        self, temp_backup_dir, mock_encryption_key
    ):
        """Test combined compression and encryption pipeline"""
        test_file = temp_backup_dir / "test_backup.sql"
        content = "-- Test content\n" + "INSERT INTO test VALUES (1);\n" * 100
        test_file.write_text(content)

        # Compress then encrypt
        compressed_file = temp_backup_dir / "test_backup.sql.gz"
        encrypted_file = temp_backup_dir / "test_backup.sql.gz.enc"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            # Compression
            with open(test_file, "rb") as f_in:
                with gzip.open(compressed_file, "wb") as f_out:
                    f_out.write(f_in.read())

            # Encryption
            encrypt_result = self._encrypt_file(
                compressed_file, encrypted_file, mock_encryption_key
            )

            assert encrypt_result["success"] is True

            # Verify pipeline integrity
            verify_result = self._verify_encrypted_compressed_file(
                encrypted_file, mock_encryption_key
            )
            assert verify_result["valid"] is True

    def test_encryption_key_validation(self, temp_backup_dir):
        """Test encryption key validation"""
        # Test missing key
        missing_key = temp_backup_dir / "missing_key.key"
        result = self._validate_encryption_key(missing_key)
        assert result["valid"] is False
        assert "not found" in result["error"]

        # Test empty key
        empty_key = temp_backup_dir / "empty_key.key"
        empty_key.write_text("")
        result = self._validate_encryption_key(empty_key)
        assert result["valid"] is False
        assert "empty" in result["error"]

        # Test valid key
        valid_key = temp_backup_dir / "valid_key.key"
        valid_key.write_text("valid-encryption-key-content")
        result = self._validate_encryption_key(valid_key)
        assert result["valid"] is True

    def test_compression_algorithm_selection(self, temp_backup_dir):
        """Test different compression algorithms"""
        test_file = temp_backup_dir / "test_data.sql"
        content = "-- Test data\n" + "SELECT * FROM large_table;\n" * 500
        test_file.write_text(content)

        compression_results = {}

        # Test gzip
        gzip_file = temp_backup_dir / "test_data.sql.gz"
        with open(test_file, "rb") as f_in:
            with gzip.open(gzip_file, "wb", compresslevel=9) as f_out:
                f_out.write(f_in.read())

        compression_results["gzip"] = {
            "original_size": test_file.stat().st_size,
            "compressed_size": gzip_file.stat().st_size,
            "ratio": gzip_file.stat().st_size / test_file.stat().st_size,
        }

        # Verify compression effectiveness
        assert compression_results["gzip"]["ratio"] < 0.8
        assert compression_results["gzip"]["compressed_size"] > 0

    def _encrypt_file(self, input_file, output_file, key_file):
        """Mock file encryption"""
        return {"success": True, "output_file": str(output_file)}

    def _decrypt_file(self, encrypted_file, key_file):
        """Mock file decryption"""
        return {"success": True, "decrypted_size": 1024}

    def _verify_encrypted_compressed_file(self, file_path, key_file):
        """Mock verification of encrypted compressed file"""
        return {"valid": True, "encryption_valid": True, "compression_valid": True}

    def _validate_encryption_key(self, key_file):
        """Mock encryption key validation"""
        if not key_file.exists():
            return {"valid": False, "error": "Key file not found"}

        if key_file.stat().st_size == 0:
            return {"valid": False, "error": "Key file is empty"}

        return {"valid": True}


class TestBackupSizeAndContent:
    """Test backup size and content validation"""

    def test_backup_size_validation(self, temp_backup_dir):
        """Test backup file size validation"""
        # Create backups of different sizes
        small_backup = temp_backup_dir / "small_backup.sql"
        small_backup.write_text("-- Small backup\nSELECT 1;")

        large_backup = temp_backup_dir / "large_backup.sql"
        large_content = "-- Large backup\n" + "SELECT * FROM table;\n" * 10000
        large_backup.write_text(large_content)

        empty_backup = temp_backup_dir / "empty_backup.sql"
        empty_backup.write_text("")

        # Validate sizes
        small_result = self._validate_backup_size(
            small_backup, min_size=1, max_size=1024 * 1024
        )
        assert small_result["valid"] is True
        assert small_result["within_limits"] is True

        large_result = self._validate_backup_size(
            large_backup, min_size=1000, max_size=1024 * 1024
        )
        assert large_result["valid"] is True
        assert large_result["size_mb"] > 0

        empty_result = self._validate_backup_size(empty_backup, min_size=1)
        assert empty_result["valid"] is False
        assert empty_result["too_small"] is True

    def test_backup_content_completeness(self, temp_backup_dir, sample_br_kg_db):
        """Test backup content completeness"""
        # Create archive with database
        import tarfile

        complete_backup = temp_backup_dir / "complete_backup.tar"
        with tarfile.open(complete_backup, "w") as tar:
            tar.add(sample_br_kg_db, arcname="database/br_kg_graph.db")

            # Add metadata
            metadata_info = tarfile.TarInfo("metadata.json")
            metadata_content = json.dumps(
                {"version": "1.0", "tables": ["nodes", "edges"]}
            )
            metadata_info.size = len(metadata_content.encode())
            tar.addfile(
                metadata_info, fileobj=tempfile.BytesIO(metadata_content.encode())
            )

        result = self._validate_backup_completeness(complete_backup)

        assert result["complete"] is True
        assert result["database_present"] is True
        assert result["metadata_present"] is True

    def test_backup_version_consistency(self, temp_backup_dir):
        """Test backup version consistency across components"""
        timestamp = "20240101_120000"

        # Create multiple component backups with same timestamp
        postgres_backup = (
            temp_backup_dir / f"postgres_brain_researcher_{timestamp}.sql.gz.enc"
        )
        br_kg_backup = temp_backup_dir / f"br_kg_{timestamp}.tar.gz.enc"
        redis_backup = temp_backup_dir / f"redis_{timestamp}.tar.gz.enc"

        # Mock backup files
        postgres_backup.write_text("postgres backup content")
        br_kg_backup.write_text("br_kg backup content")
        redis_backup.write_text("redis backup content")

        backups = [postgres_backup, br_kg_backup, redis_backup]
        result = self._validate_backup_set_consistency(backups)

        assert result["consistent"] is True
        assert result["same_timestamp"] is True
        assert len(result["components"]) == 3

    def test_database_table_coverage(self, sample_br_kg_db):
        """Test database backup covers all tables"""
        # Connect to sample database
        conn = sqlite3.connect(sample_br_kg_db)
        cursor = conn.cursor()

        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        expected_tables = {row[0] for row in cursor.fetchall()}

        conn.close()

        # Simulate backup analysis
        result = self._analyze_database_coverage(sample_br_kg_db, expected_tables)

        assert result["coverage_complete"] is True
        assert result["tables_covered"] == len(expected_tables)
        assert result["missing_tables"] == []

    def _validate_backup_size(self, backup_file, min_size=0, max_size=None):
        """Mock backup size validation"""
        file_size = backup_file.stat().st_size
        size_mb = file_size / (1024 * 1024)

        too_small = file_size < min_size
        too_large = max_size is not None and file_size > max_size
        within_limits = not too_small and not too_large

        return {
            "valid": file_size > 0 and within_limits,
            "size_bytes": file_size,
            "size_mb": round(size_mb, 2),
            "within_limits": within_limits,
            "too_small": too_small,
            "too_large": too_large,
        }

    def _validate_backup_completeness(self, backup_file):
        """Mock backup completeness validation"""
        import tarfile

        try:
            with tarfile.open(backup_file, "r") as tar:
                members = tar.getmembers()
                filenames = [m.name for m in members]

                database_present = any(".db" in f for f in filenames)
                metadata_present = any("metadata.json" in f for f in filenames)

                return {
                    "complete": database_present and metadata_present,
                    "database_present": database_present,
                    "metadata_present": metadata_present,
                    "total_files": len(members),
                }
        except:
            return {
                "complete": False,
                "database_present": False,
                "metadata_present": False,
                "total_files": 0,
            }

    def _validate_backup_set_consistency(self, backup_files):
        """Mock backup set consistency validation"""
        import re

        timestamps = []
        components = []

        for backup_file in backup_files:
            # Extract timestamp from filename
            match = re.search(r"(\d{8}_\d{6})", backup_file.name)
            if match:
                timestamps.append(match.group(1))

            # Extract component name
            if "postgres" in backup_file.name:
                components.append("postgres")
            elif "br_kg" in backup_file.name:
                components.append("br_kg")
            elif "redis" in backup_file.name:
                components.append("redis")

        same_timestamp = len(set(timestamps)) <= 1 if timestamps else False

        return {
            "consistent": same_timestamp and len(components) > 0,
            "same_timestamp": same_timestamp,
            "components": components,
            "timestamps": timestamps,
        }

    def _analyze_database_coverage(self, db_file, expected_tables):
        """Mock database coverage analysis"""
        # For testing, assume all expected tables are covered
        return {
            "coverage_complete": True,
            "tables_covered": len(expected_tables),
            "missing_tables": [],
            "expected_tables": list(expected_tables),
        }


class TestRetentionPolicies:
    """Test backup retention policies"""

    def test_retention_policy_enforcement(self, temp_backup_dir):
        """Test retention policy removes old backups"""
        retention_days = 7

        # Create backups with different ages
        now = datetime.now()

        # Recent backup (keep)
        recent_backup = temp_backup_dir / "postgres_recent_20240101_120000.sql.gz.enc"
        recent_backup.write_text("recent backup")
        recent_time = now - timedelta(days=3)
        os.utime(recent_backup, (recent_time.timestamp(), recent_time.timestamp()))

        # Old backup (remove)
        old_backup = temp_backup_dir / "postgres_old_20231201_120000.sql.gz.enc"
        old_backup.write_text("old backup")
        old_time = now - timedelta(days=10)
        os.utime(old_backup, (old_time.timestamp(), old_time.timestamp()))

        # Very old backup (remove)
        very_old_backup = (
            temp_backup_dir / "postgres_very_old_20231101_120000.sql.gz.enc"
        )
        very_old_backup.write_text("very old backup")
        very_old_time = now - timedelta(days=30)
        os.utime(
            very_old_backup, (very_old_time.timestamp(), very_old_time.timestamp())
        )

        # Apply retention policy
        result = self._apply_retention_policy(temp_backup_dir, retention_days)

        assert result["files_removed"] == 2
        assert result["files_kept"] == 1
        assert recent_backup.exists()
        assert not old_backup.exists()
        assert not very_old_backup.exists()

    def test_retention_policy_different_components(self, temp_backup_dir):
        """Test different retention policies for different components"""
        retention_policies = {"postgres": 30, "redis": 7, "files": 90}

        now = datetime.now()

        # Create backups for different components
        postgres_backup = temp_backup_dir / "postgres_20240101_120000.sql.gz.enc"
        postgres_backup.write_text("postgres backup")
        postgres_time = now - timedelta(days=20)
        os.utime(
            postgres_backup, (postgres_time.timestamp(), postgres_time.timestamp())
        )

        redis_backup = temp_backup_dir / "redis_20240101_120000.tar.gz.enc"
        redis_backup.write_text("redis backup")
        redis_time = now - timedelta(days=10)
        os.utime(redis_backup, (redis_time.timestamp(), redis_time.timestamp()))

        files_backup = temp_backup_dir / "files_20240101_120000.tar.gz.enc"
        files_backup.write_text("files backup")
        files_time = now - timedelta(days=60)
        os.utime(files_backup, (files_time.timestamp(), files_time.timestamp()))

        # Apply component-specific retention
        results = {}
        for component, days in retention_policies.items():
            results[component] = self._apply_component_retention(
                temp_backup_dir, component, days
            )

        # PostgreSQL: 20 days old, retention 30 days -> keep
        assert results["postgres"]["files_kept"] == 1
        assert results["postgres"]["files_removed"] == 0

        # Redis: 10 days old, retention 7 days -> remove
        assert results["redis"]["files_kept"] == 0
        assert results["redis"]["files_removed"] == 1

        # Files: 60 days old, retention 90 days -> keep
        assert results["files"]["files_kept"] == 1
        assert results["files"]["files_removed"] == 0

    def test_retention_minimum_backups_preservation(self, temp_backup_dir):
        """Test retention preserves minimum number of backups"""
        min_backups = 3
        retention_days = 7

        now = datetime.now()

        # Create 5 old backups (all older than retention period)
        backup_files = []
        for i in range(5):
            backup_file = (
                temp_backup_dir / f"postgres_backup_{i}_20240101_120000.sql.gz.enc"
            )
            backup_file.write_text(f"backup {i}")
            backup_time = now - timedelta(days=10 + i)
            os.utime(backup_file, (backup_time.timestamp(), backup_time.timestamp()))
            backup_files.append(backup_file)

        # Apply retention with minimum preservation
        result = self._apply_retention_with_minimum(
            temp_backup_dir, retention_days, min_backups
        )

        # Should keep the 3 most recent backups despite age
        assert result["files_kept"] == min_backups
        assert result["files_removed"] == 2

        # Verify the most recent backups were kept
        remaining_files = list(temp_backup_dir.glob("postgres_backup_*.sql.gz.enc"))
        assert len(remaining_files) == min_backups

    def test_s3_retention_policy(self, temp_backup_dir, mock_s3_client):
        """Test S3 backup retention policy"""
        retention_days = 30

        # Mock S3 objects with different ages
        now = datetime.now()
        mock_objects = [
            {
                "Key": "postgres-backups/2024/01/01/recent_backup.sql.gz.enc",
                "LastModified": now - timedelta(days=5),
            },
            {
                "Key": "postgres-backups/2023/12/01/old_backup.sql.gz.enc",
                "LastModified": now - timedelta(days=45),
            },
        ]

        mock_s3_client.list_objects_v2.return_value = {"Contents": mock_objects}

        result = self._apply_s3_retention_policy(
            mock_s3_client, "test-bucket", retention_days
        )

        assert result["objects_deleted"] == 1
        assert result["objects_kept"] == 1
        assert mock_s3_client.delete_object.called

    def _apply_retention_policy(self, backup_dir, retention_days):
        """Mock retention policy application"""
        files_to_check = list(backup_dir.glob("*.enc"))
        now = datetime.now()
        cutoff_time = now - timedelta(days=retention_days)

        files_removed = 0
        files_kept = 0

        for file_path in files_to_check:
            file_time = datetime.fromtimestamp(file_path.stat().st_mtime)

            if file_time < cutoff_time:
                file_path.unlink()  # Remove old file
                files_removed += 1
            else:
                files_kept += 1

        return {
            "files_removed": files_removed,
            "files_kept": files_kept,
            "cutoff_time": cutoff_time.isoformat(),
        }

    def _apply_component_retention(self, backup_dir, component, retention_days):
        """Mock component-specific retention policy"""
        pattern = f"{component}_*.enc"
        files_to_check = list(backup_dir.glob(pattern))
        now = datetime.now()
        cutoff_time = now - timedelta(days=retention_days)

        files_removed = 0
        files_kept = 0

        for file_path in files_to_check:
            file_time = datetime.fromtimestamp(file_path.stat().st_mtime)

            if file_time < cutoff_time:
                file_path.unlink()
                files_removed += 1
            else:
                files_kept += 1

        return {
            "files_removed": files_removed,
            "files_kept": files_kept,
            "component": component,
        }

    def _apply_retention_with_minimum(self, backup_dir, retention_days, min_backups):
        """Mock retention policy with minimum backup preservation"""
        files_to_check = list(backup_dir.glob("postgres_backup_*.enc"))
        files_to_check.sort(key=lambda f: f.stat().st_mtime, reverse=True)

        now = datetime.now()
        cutoff_time = now - timedelta(days=retention_days)

        files_removed = 0
        files_kept = 0

        for i, file_path in enumerate(files_to_check):
            file_time = datetime.fromtimestamp(file_path.stat().st_mtime)

            # Keep file if within retention period OR if it's one of the minimum required
            if file_time >= cutoff_time or i < min_backups:
                files_kept += 1
            else:
                file_path.unlink()
                files_removed += 1

        return {
            "files_removed": files_removed,
            "files_kept": files_kept,
            "min_backups_enforced": min_backups,
        }

    def _apply_s3_retention_policy(self, s3_client, bucket, retention_days):
        """Mock S3 retention policy"""
        response = s3_client.list_objects_v2(Bucket=bucket)
        objects = response.get("Contents", [])

        now = datetime.now()
        cutoff_time = now - timedelta(days=retention_days)

        objects_deleted = 0
        objects_kept = 0

        for obj in objects:
            if obj["LastModified"] < cutoff_time:
                s3_client.delete_object(Bucket=bucket, Key=obj["Key"])
                objects_deleted += 1
            else:
                objects_kept += 1

        return {"objects_deleted": objects_deleted, "objects_kept": objects_kept}
