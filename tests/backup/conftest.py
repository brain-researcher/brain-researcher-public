"""
Pytest fixtures for backup testing
"""

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def temp_backup_dir():
    """Create temporary backup directory for testing"""
    temp_dir = tempfile.mkdtemp(prefix="backup_test_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_encryption_key(temp_backup_dir):
    """Create mock encryption key file"""
    key_file = temp_backup_dir / "encryption.key"
    key_file.write_text("test-encryption-key-for-testing-only")
    return key_file


@pytest.fixture
def sample_postgres_backup(temp_backup_dir):
    """Create sample PostgreSQL backup file"""
    sql_content = """-- PostgreSQL database dump
-- Dumped from database version 13.4
-- Dumped by pg_dump version 13.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;

CREATE TABLE test_table (
    id SERIAL PRIMARY KEY,
    data TEXT NOT NULL
);

INSERT INTO test_table (data) VALUES ('test data');
"""
    backup_file = temp_backup_dir / "postgres_brain_researcher_20240101_120000.sql"
    backup_file.write_text(sql_content)

    # Create compressed version
    subprocess.run(["gzip", str(backup_file)], check=True)
    return backup_file.with_suffix(".sql.gz")


@pytest.fixture
def sample_br_kg_db(temp_backup_dir):
    """Create sample BR-KG database"""
    db_file = temp_backup_dir / "br_kg_test.db"

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE nodes (
            id INTEGER PRIMARY KEY,
            label TEXT,
            type TEXT,
            properties TEXT
        )
    """
    )

    cursor.execute(
        """
        CREATE TABLE edges (
            id INTEGER PRIMARY KEY,
            source_id INTEGER,
            target_id INTEGER,
            relationship TEXT,
            FOREIGN KEY (source_id) REFERENCES nodes(id),
            FOREIGN KEY (target_id) REFERENCES nodes(id)
        )
    """
    )

    cursor.execute("INSERT INTO nodes VALUES (1, 'Test Node', 'Concept', '{}')")
    cursor.execute("INSERT INTO edges VALUES (1, 1, 1, 'relates_to')")

    conn.commit()
    conn.close()

    return db_file


@pytest.fixture
def sample_redis_data(temp_backup_dir):
    """Create sample Redis backup data"""
    redis_dir = temp_backup_dir / "redis"
    redis_dir.mkdir()

    # Create mock dump.rdb
    rdb_file = redis_dir / "dump.rdb"
    rdb_file.write_bytes(b"REDIS0009\xfa\tredis-ver\x056.2.6\x00")

    # Create mock appendonly.aof
    aof_file = redis_dir / "appendonly.aof"
    aof_file.write_text(
        "*2\r\n$6\r\nSELECT\r\n$1\r\n0\r\n*3\r\n$3\r\nSET\r\n$8\r\ntest:key\r\n$10\r\ntest:value\r\n"
    )

    # Create JSON export
    json_file = redis_dir / "redis_keys_20240101_120000.json"
    json_data = {
        "test:key": "test:value",
        "test:hash": {"field1": "value1", "field2": "value2"},
        "test:list": ["item1", "item2", "item3"],
    }
    json_file.write_text(json.dumps(json_data, indent=2))

    # Create metadata
    metadata_file = redis_dir / "metadata.json"
    metadata = {
        "backup_type": "redis",
        "timestamp": "20240101_120000",
        "keys_count": 3,
        "memory_usage": 1024,
    }
    metadata_file.write_text(json.dumps(metadata, indent=2))

    return redis_dir


@pytest.fixture
def backup_config(temp_backup_dir, mock_encryption_key):
    """Standard backup configuration for testing"""
    return {
        "backup_dir": str(temp_backup_dir),
        "encryption_key_file": str(mock_encryption_key),
        "retention_days": 7,
        "webhook_url": "http://test-webhook.example.com",
        "s3_bucket": "test-backup-bucket",
        "postgres_host": "localhost",
        "postgres_port": 5432,
        "postgres_user": "test_user",
        "postgres_db": "test_db",
    }


@pytest.fixture
def mock_subprocess():
    """Mock subprocess calls for testing"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        yield mock_run


@pytest.fixture
def mock_postgres_connection():
    """Mock PostgreSQL connection for testing"""
    with patch("subprocess.run") as mock_pg:
        # Mock pg_isready
        mock_pg.return_value = Mock(returncode=0)
        yield mock_pg


@pytest.fixture
def mock_s3_client():
    """Mock S3 client for testing"""
    with patch("boto3.client") as mock_boto:
        mock_client = Mock()
        mock_client.list_objects_v2.return_value = {
            "Contents": [{"Key": "postgres-backups/2024/01/01/test_backup.sql.gz.enc"}]
        }
        mock_client.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": "test_backup.sql.gz.enc"}]}
        ]
        mock_boto.return_value = mock_client
        yield mock_client


@pytest.fixture
def failed_backup_scenario(temp_backup_dir):
    """Create scenario with failed/corrupted backups"""
    # Create empty backup file
    empty_backup = temp_backup_dir / "postgres_empty_20240101_120000.sql.gz.enc"
    empty_backup.write_text("")

    # Create corrupted backup file
    corrupted_backup = temp_backup_dir / "postgres_corrupted_20240101_120000.sql.gz.enc"
    corrupted_backup.write_bytes(b"corrupted data that's not valid")

    return {"empty_backup": empty_backup, "corrupted_backup": corrupted_backup}


@pytest.fixture
def backup_metadata():
    """Sample backup metadata for testing"""
    return {
        "backup_type": "postgres",
        "database": "brain_researcher",
        "host": "localhost",
        "port": 5432,
        "timestamp": "20240101_120000",
        "backup_file": "/backups/postgres_brain_researcher_20240101_120000.sql.gz.enc",
        "size_bytes": 1024000,
        "retention_days": 30,
        "created_at": "2025-01-01T12:00:00+00:00",
        "postgres_version": "PostgreSQL 13.4",
        "checksums": {"encrypted_file": "a1b2c3d4e5f6"},
    }


@pytest.fixture
def performance_benchmark_data():
    """Performance benchmark data for testing"""
    return {
        "backup_duration_seconds": 120.5,
        "backup_size_mb": 1024,
        "compression_ratio": 0.65,
        "network_throughput_mbps": 50.2,
        "disk_io_wait_percent": 12.3,
    }


@pytest.fixture
def network_failure_mock():
    """Mock network failures for testing"""

    def side_effect(*args, **kwargs):
        import requests

        raise requests.exceptions.ConnectionError("Network failure")

    with patch("requests.post", side_effect=side_effect) as mock_post:
        yield mock_post


@pytest.fixture
def disk_full_mock():
    """Mock disk full scenario for testing"""

    def side_effect(*args, **kwargs):
        raise OSError(28, "No space left on device")

    with patch("builtins.open", side_effect=side_effect) as mock_open:
        yield mock_open


@pytest.fixture
def backup_schedule_config():
    """Backup schedule configuration for testing"""
    return {
        "postgres": {"cron": "0 2 * * *", "retention_days": 30},
        "br_kg": {"cron": "0 3 * * *", "retention_days": 30},
        "redis": {"cron": "0 4 * * *", "retention_days": 7},
        "files": {"cron": "0 5 * * 0", "retention_days": 90},
        "agent": {"cron": "0 6 * * *", "retention_days": 7},
        "config": {"cron": "0 7 * * 0", "retention_days": 90},
    }
