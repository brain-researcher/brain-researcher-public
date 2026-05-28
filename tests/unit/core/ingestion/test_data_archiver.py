"""Unit tests for the Data Archiver component."""

import pytest
import tempfile
import shutil
import sqlite3
import tarfile
import gzip
import json
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from brain_researcher.core.ingestion.archival.archiver import (
    DataArchiver,
    ArchiveStatus,
    CompressionLevel
)


class TestArchiveStatus:
    """Test ArchiveStatus enum."""
    
    def test_archive_status_values(self):
        """Test that all archive status values are correct."""
        assert ArchiveStatus.PENDING.value == "pending"
        assert ArchiveStatus.ARCHIVING.value == "archiving"
        assert ArchiveStatus.ARCHIVED.value == "archived"
        assert ArchiveStatus.RETRIEVING.value == "retrieving"
        assert ArchiveStatus.RESTORED.value == "restored"
        assert ArchiveStatus.EXPIRED.value == "expired"
        assert ArchiveStatus.ERROR.value == "error"


class TestCompressionLevel:
    """Test CompressionLevel enum."""
    
    def test_compression_level_values(self):
        """Test that all compression level values are correct."""
        assert CompressionLevel.NONE.value == 0
        assert CompressionLevel.FAST.value == 1
        assert CompressionLevel.BALANCED.value == 6
        assert CompressionLevel.MAXIMUM.value == 9


class TestDataArchiver:
    """Test suite for DataArchiver class."""
    
    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing."""
        archive_dir = tempfile.mkdtemp()
        staging_dir = tempfile.mkdtemp()
        db_file = tempfile.NamedTemporaryFile(delete=False)
        db_path = db_file.name
        db_file.close()
        
        yield {
            'archive_dir': archive_dir,
            'staging_dir': staging_dir,
            'db_path': db_path
        }
        
        # Cleanup
        shutil.rmtree(archive_dir, ignore_errors=True)
        shutil.rmtree(staging_dir, ignore_errors=True)
        Path(db_path).unlink(missing_ok=True)
    
    @pytest.fixture
    def archiver(self, temp_dirs):
        """Create DataArchiver instance for testing."""
        return DataArchiver(
            archive_dir=temp_dirs['archive_dir'],
            staging_dir=temp_dirs['staging_dir'],
            db_path=temp_dirs['db_path']
        )
    
    @pytest.fixture
    def sample_dataset(self, temp_dirs):
        """Create sample dataset for testing."""
        dataset_path = Path(temp_dirs['staging_dir']) / "sample_dataset"
        dataset_path.mkdir(parents=True, exist_ok=True)
        
        # Create sample files
        (dataset_path / "data.csv").write_text("id,value\n1,100\n2,200\n")
        (dataset_path / "metadata.json").write_text('{"version": "1.0", "description": "Sample dataset"}')
        (dataset_path / "README.txt").write_text("This is a sample dataset for testing.")
        
        # Create subdirectory
        sub_dir = dataset_path / "subfolder"
        sub_dir.mkdir()
        (sub_dir / "subfile.txt").write_text("Subfolder content")
        
        return str(dataset_path)
    
    def test_initialization(self, temp_dirs):
        """Test DataArchiver initialization."""
        archiver = DataArchiver(
            archive_dir=temp_dirs['archive_dir'],
            staging_dir=temp_dirs['staging_dir'],
            db_path=temp_dirs['db_path']
        )
        
        # Check directories were created
        assert archiver.archive_dir.exists()
        assert archiver.staging_dir.exists()
        
        # Check database was initialized
        assert Path(archiver.db_path).exists()
        
        # Check default settings
        assert archiver.default_retention_days == 365 * 5
        assert archiver.default_compression == CompressionLevel.BALANCED
        
        # Verify database schema
        conn = sqlite3.connect(archiver.db_path)
        cursor = conn.cursor()
        
        # Check archives table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='archives'")
        assert cursor.fetchone() is not None
        
        # Check retrieval_history table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='retrieval_history'")
        assert cursor.fetchone() is not None
        
        conn.close()
    
    def test_archive_dataset_basic(self, archiver, sample_dataset):
        """Test basic dataset archiving."""
        result = archiver.archive_dataset(
            sample_dataset,
            dataset_name="test_dataset",
            retention_days=30
        )
        
        # Check result structure
        assert 'archive_id' in result
        assert result['dataset_name'] == "test_dataset"
        assert result['source_path'] == sample_dataset
        assert result['status'] == ArchiveStatus.ARCHIVED.value
        assert 'archive_path' in result
        assert 'size_bytes' in result
        assert 'checksum' in result
        assert 'compression_type' in result
        assert 'compression_ratio' in result
        assert 'archived_at' in result
        assert 'expires_at' in result
        
        # Check archive file was created
        archive_path = Path(result['archive_path'])
        assert archive_path.exists()
        assert archive_path.suffix == '.gz'  # Should be compressed
        
        # Check expiration date
        archived_at = datetime.fromisoformat(result['archived_at'])
        expires_at = datetime.fromisoformat(result['expires_at'])
        expected_expires = archived_at + timedelta(days=30)
        assert abs((expires_at - expected_expires).total_seconds()) < 60  # Within 1 minute
        
        # Verify database entry
        archive_info = archiver._get_archive_info(result['archive_id'])
        assert archive_info is not None
        assert archive_info['dataset_name'] == "test_dataset"
        assert archive_info['status'] == ArchiveStatus.ARCHIVED.value
    
    def test_archive_dataset_single_file(self, archiver, temp_dirs):
        """Test archiving a single file."""
        # Create single file
        single_file = Path(temp_dirs['staging_dir']) / "single_file.txt"
        single_file.write_text("This is a single file for archiving.")
        
        result = archiver.archive_dataset(
            str(single_file),
            dataset_name="single_file_dataset"
        )
        
        assert result['status'] == ArchiveStatus.ARCHIVED.value
        assert result['dataset_name'] == "single_file_dataset"
        
        # Archive should exist
        archive_path = Path(result['archive_path'])
        assert archive_path.exists()
    
    def test_archive_dataset_different_compression(self, archiver, sample_dataset):
        """Test archiving with different compression levels."""
        compression_levels = [
            CompressionLevel.NONE,
            CompressionLevel.FAST,
            CompressionLevel.BALANCED,
            CompressionLevel.MAXIMUM
        ]
        
        results = []
        
        for compression in compression_levels:
            result = archiver.archive_dataset(
                sample_dataset,
                dataset_name=f"compressed_{compression.name}",
                compression=compression
            )
            results.append(result)
            
            assert result['status'] == ArchiveStatus.ARCHIVED.value
            assert result['compression_type'] == compression.name
            
            # Check compression ratio
            if compression == CompressionLevel.NONE:
                assert result['compression_ratio'] == 1.0
            else:
                assert result['compression_ratio'] >= 1.0  # Should achieve some compression
        
        # Higher compression levels should generally achieve better ratios
        # (though this depends on data content)
        ratios = [r['compression_ratio'] for r in results if r['compression_type'] != 'NONE']
        assert all(ratio >= 1.0 for ratio in ratios)
    
    def test_archive_dataset_nonexistent_path(self, archiver):
        """Test archiving nonexistent dataset."""
        with pytest.raises(FileNotFoundError):
            archiver.archive_dataset("/nonexistent/path")
    
    def test_archive_dataset_with_metadata(self, archiver, sample_dataset):
        """Test archiving with custom metadata."""
        custom_metadata = {
            "study": "Test Study",
            "investigator": "Test Investigator",
            "notes": "This is a test archive"
        }
        
        result = archiver.archive_dataset(
            sample_dataset,
            dataset_name="metadata_test",
            metadata=custom_metadata
        )
        
        # Retrieve and verify metadata
        archive_info = archiver._get_archive_info(result['archive_id'])
        stored_metadata = archive_info['metadata']
        if isinstance(stored_metadata, str):
            stored_metadata = json.loads(stored_metadata)
        
        assert stored_metadata == custom_metadata
    
    def test_retrieve_archive_basic(self, archiver, sample_dataset, temp_dirs):
        """Test basic archive retrieval."""
        # First archive the dataset
        archive_result = archiver.archive_dataset(sample_dataset, dataset_name="retrieve_test")
        archive_id = archive_result['archive_id']
        
        # Retrieve the archive
        restore_path = Path(temp_dirs['staging_dir']) / "restored"
        retrieval_result = archiver.retrieve_archive(
            archive_id,
            restore_path=str(restore_path),
            user="test_user"
        )
        
        # Check retrieval result
        assert 'retrieval_id' in retrieval_result
        assert retrieval_result['archive_id'] == archive_id
        assert retrieval_result['user'] == "test_user"
        assert 'retrieved_at' in retrieval_result
        assert retrieval_result['restored_path'] == str(restore_path)
        
        # Check that files were restored
        assert restore_path.exists()
        
        # Verify content was restored correctly
        # The exact structure depends on how the archiver handles extraction
        restored_files = list(restore_path.rglob('*'))
        assert len(restored_files) > 0  # Should have restored some files
        
        # Check database status update
        archive_info = archiver._get_archive_info(archive_id)
        assert archive_info['status'] == ArchiveStatus.RESTORED.value
    
    def test_retrieve_archive_default_path(self, archiver, sample_dataset):
        """Test archive retrieval with default restore path."""
        # Archive dataset
        archive_result = archiver.archive_dataset(sample_dataset, dataset_name="default_path_test")
        archive_id = archive_result['archive_id']
        
        # Retrieve without specifying path
        retrieval_result = archiver.retrieve_archive(archive_id)
        
        # Should use staging directory with default naming
        restored_path = Path(retrieval_result['restored_path'])
        assert restored_path.exists()
        assert 'restore_' in str(restored_path)
        assert archive_id in str(restored_path)
    
    def test_retrieve_archive_nonexistent(self, archiver):
        """Test retrieving nonexistent archive."""
        with pytest.raises(ValueError, match="Archive not found"):
            archiver.retrieve_archive("nonexistent_archive_id")
    
    def test_retrieve_archive_expired(self, archiver, sample_dataset):
        """Test retrieving expired archive."""
        # Archive with very short retention
        archive_result = archiver.archive_dataset(
            sample_dataset,
            dataset_name="expired_test",
            retention_days=1
        )
        archive_id = archive_result['archive_id']
        
        # Manually mark as expired
        archiver._update_archive_status(archive_id, ArchiveStatus.EXPIRED)
        
        # Should raise error when trying to retrieve
        with pytest.raises(ValueError, match="Archive has expired"):
            archiver.retrieve_archive(archive_id)
    
    def test_list_archives_all(self, archiver, sample_dataset):
        """Test listing all archives."""
        # Create multiple archives
        archive_ids = []
        for i in range(3):
            result = archiver.archive_dataset(
                sample_dataset,
                dataset_name=f"list_test_{i}"
            )
            archive_ids.append(result['archive_id'])
        
        # List all archives
        archives = archiver.list_archives()
        
        assert len(archives) >= 3  # Should include our test archives
        
        # Check that our archives are in the list
        listed_ids = {archive['archive_id'] for archive in archives}
        for archive_id in archive_ids:
            assert archive_id in listed_ids
        
        # Check archive structure
        for archive in archives:
            assert 'archive_id' in archive
            assert 'dataset_name' in archive
            assert 'status' in archive
            assert 'archived_at' in archive
    
    def test_list_archives_filtered_by_status(self, archiver, sample_dataset):
        """Test listing archives filtered by status."""
        # Create archives with different statuses
        archive1 = archiver.archive_dataset(sample_dataset, dataset_name="status_test_1")
        archive2 = archiver.archive_dataset(sample_dataset, dataset_name="status_test_2")
        
        # Change one to different status
        archiver._update_archive_status(archive1['archive_id'], ArchiveStatus.EXPIRED)
        
        # List by status
        archived_only = archiver.list_archives(status=ArchiveStatus.ARCHIVED)
        expired_only = archiver.list_archives(status=ArchiveStatus.EXPIRED)
        
        # Check filtering
        archived_ids = {a['archive_id'] for a in archived_only}
        expired_ids = {a['archive_id'] for a in expired_only}
        
        assert archive2['archive_id'] in archived_ids
        assert archive1['archive_id'] not in archived_ids
        
        assert archive1['archive_id'] in expired_ids
        assert archive2['archive_id'] not in expired_ids
    
    def test_list_archives_filtered_by_name(self, archiver, sample_dataset):
        """Test listing archives filtered by dataset name."""
        # Create archives with different names
        archiver.archive_dataset(sample_dataset, dataset_name="search_test_dataset")
        archiver.archive_dataset(sample_dataset, dataset_name="other_dataset")
        archiver.archive_dataset(sample_dataset, dataset_name="search_test_analysis")
        
        # Search by name pattern
        search_results = archiver.list_archives(dataset_name="search_test")
        
        assert len(search_results) >= 2  # Should match both "search_test" datasets
        
        for archive in search_results:
            assert "search_test" in archive['dataset_name']
    
    def test_check_expiration(self, archiver, sample_dataset):
        """Test expiration checking."""
        # Create archive with short retention
        archive_result = archiver.archive_dataset(
            sample_dataset,
            dataset_name="expiration_test",
            retention_days=1
        )
        archive_id = archive_result['archive_id']
        
        # Manually set expiration to past date
        conn = sqlite3.connect(archiver.db_path)
        cursor = conn.cursor()
        past_date = (datetime.now() - timedelta(days=1)).isoformat()
        cursor.execute(
            "UPDATE archives SET expires_at = ? WHERE archive_id = ?",
            (past_date, archive_id)
        )
        conn.commit()
        conn.close()
        
        # Check expiration
        expired_ids = archiver.check_expiration()
        
        assert archive_id in expired_ids
        
        # Archive should now be marked as expired
        archive_info = archiver._get_archive_info(archive_id)
        assert archive_info['status'] == ArchiveStatus.EXPIRED.value
    
    def test_purge_expired(self, archiver, sample_dataset):
        """Test purging expired archives."""
        # Create and expire an archive
        archive_result = archiver.archive_dataset(
            sample_dataset,
            dataset_name="purge_test"
        )
        archive_id = archive_result['archive_id']
        
        # Mark as expired
        archiver._update_archive_status(archive_id, ArchiveStatus.EXPIRED)
        
        # Purge expired archives
        purge_result = archiver.purge_expired(confirm=True)
        
        # Check purge result
        assert 'purged' in purge_result
        assert 'failed' in purge_result
        assert 'space_freed_bytes' in purge_result
        assert 'space_freed_gb' in purge_result
        
        assert archive_id in purge_result['purged']
        
        # Archive file should be deleted
        archive_path = Path(archive_result['archive_path'])
        assert not archive_path.exists()
        
        # Archive should be removed from database
        archive_info = archiver._get_archive_info(archive_id)
        assert archive_info is None
    
    def test_purge_expired_no_confirmation(self, archiver):
        """Test purging expired archives without confirmation."""
        with pytest.raises(ValueError, match="Purge requires confirmation flag"):
            archiver.purge_expired(confirm=False)
    
    def test_get_storage_stats(self, archiver, sample_dataset):
        """Test getting storage statistics."""
        # Create some archives
        for i in range(3):
            archiver.archive_dataset(
                sample_dataset,
                dataset_name=f"stats_test_{i}",
                compression=CompressionLevel.BALANCED
            )
        
        stats = archiver.get_storage_stats()
        
        # Check stats structure
        assert 'total_archives' in stats
        assert 'status_breakdown' in stats
        assert 'total_size_bytes' in stats
        assert 'total_size_gb' in stats
        assert 'average_compression_ratio' in stats
        assert 'disk_free_bytes' in stats
        assert 'disk_free_gb' in stats
        assert 'disk_total_gb' in stats
        assert 'disk_usage_percent' in stats
        
        # Check values are reasonable
        assert stats['total_archives'] >= 3
        assert stats['total_size_bytes'] >= 0
        assert stats['average_compression_ratio'] >= 1.0
        assert 0 <= stats['disk_usage_percent'] <= 100
        
        # Check status breakdown
        status_breakdown = stats['status_breakdown']
        assert ArchiveStatus.ARCHIVED.value in status_breakdown
        
        archived_stats = status_breakdown[ArchiveStatus.ARCHIVED.value]
        assert 'count' in archived_stats
        assert 'size_bytes' in archived_stats
        assert 'size_gb' in archived_stats
    
    def test_generate_archive_id(self, archiver):
        """Test archive ID generation."""
        id1 = archiver._generate_archive_id()
        id2 = archiver._generate_archive_id()
        
        # IDs should be unique
        assert id1 != id2
        
        # Should start with "arch_" and be reasonable length
        assert id1.startswith("arch_")
        assert id2.startswith("arch_")
        assert len(id1) > 10  # Should be reasonably long
        assert len(id2) > 10
    
    def test_stage_data_directory(self, archiver, sample_dataset):
        """Test staging directory data."""
        archive_id = "test_archive_001"
        
        staged_path = archiver._stage_data(Path(sample_dataset), archive_id)
        
        assert staged_path.exists()
        assert staged_path.is_dir()
        assert staged_path.name == archive_id
        
        # Should contain copied files
        staged_files = list(staged_path.rglob('*'))
        assert len(staged_files) > 0
        
        # Should have same structure as original
        assert (staged_path / "data.csv").exists()
        assert (staged_path / "metadata.json").exists()
    
    def test_stage_data_single_file(self, archiver, temp_dirs):
        """Test staging single file data."""
        # Create single file
        single_file = Path(temp_dirs['staging_dir']) / "single.txt"
        single_file.write_text("Single file content")
        
        archive_id = "test_archive_002"
        staged_path = archiver._stage_data(single_file, archive_id)
        
        assert staged_path.exists()
        assert staged_path.is_dir()
        
        # File should be copied into staging directory
        staged_file = staged_path / "single.txt"
        assert staged_file.exists()
        assert staged_file.read_text() == "Single file content"
    
    def test_compress_data(self, archiver, sample_dataset):
        """Test data compression."""
        # Stage data first
        archive_id = "test_compress"
        staged_path = archiver._stage_data(Path(sample_dataset), archive_id)
        
        # Compress with different levels
        for compression_level in [CompressionLevel.FAST, CompressionLevel.BALANCED, CompressionLevel.MAXIMUM]:
            # Re-stage for each test (since compression removes original)
            test_staged_path = archiver._stage_data(Path(sample_dataset), f"{archive_id}_{compression_level.name}")
            
            compressed_path = archiver._compress_data(test_staged_path, compression_level)
            
            assert compressed_path.exists()
            assert compressed_path.suffix == '.gz'
            assert not test_staged_path.exists()  # Original should be removed
            
            # Should be a valid tar.gz file
            with tarfile.open(compressed_path, 'r:gz') as tf:
                assert len(tf.getnames()) > 0
    
    def test_decompress_archive(self, archiver, sample_dataset, temp_dirs):
        """Test archive decompression."""
        # Create and compress data
        archive_id = "test_decompress"
        staged_path = archiver._stage_data(Path(sample_dataset), archive_id)
        compressed_path = archiver._compress_data(staged_path, CompressionLevel.BALANCED)
        
        # Decompress to new location
        restore_path = Path(temp_dirs['staging_dir']) / "decompressed"
        restore_path.mkdir()
        
        archiver._decompress_archive(compressed_path, restore_path)
        
        # Should have restored files
        restored_files = list(restore_path.rglob('*'))
        assert len(restored_files) > 0
        
        # Should have restored original structure
        # Note: exact structure depends on how tar archives are created
        restored_file_names = {f.name for f in restored_files if f.is_file()}
        assert len(restored_file_names) > 0
    
    def test_calculate_checksum_file(self, archiver, temp_dirs):
        """Test checksum calculation for files."""
        test_file = Path(temp_dirs['staging_dir']) / "checksum_test.txt"
        test_content = "Test content for checksum calculation"
        test_file.write_text(test_content)
        
        checksum = archiver._calculate_checksum(test_file)
        
        assert len(checksum) == 32  # MD5 hash length
        assert isinstance(checksum, str)
        
        # Same content should produce same checksum
        test_file2 = Path(temp_dirs['staging_dir']) / "checksum_test2.txt"
        test_file2.write_text(test_content)
        checksum2 = archiver._calculate_checksum(test_file2)
        
        assert checksum == checksum2
        
        # Different content should produce different checksum
        test_file3 = Path(temp_dirs['staging_dir']) / "checksum_test3.txt"
        test_file3.write_text("Different content")
        checksum3 = archiver._calculate_checksum(test_file3)
        
        assert checksum != checksum3
    
    def test_calculate_checksum_directory(self, archiver, sample_dataset):
        """Test checksum calculation for directories."""
        checksum = archiver._calculate_checksum(Path(sample_dataset))
        
        assert len(checksum) == 32
        assert isinstance(checksum, str)
        
        # Modifying a file should change checksum
        (Path(sample_dataset) / "new_file.txt").write_text("New file")
        new_checksum = archiver._calculate_checksum(Path(sample_dataset))
        
        assert checksum != new_checksum
    
    def test_calculate_compression_ratio(self, archiver, sample_dataset, temp_dirs):
        """Test compression ratio calculation."""
        # Create original data
        original_path = Path(sample_dataset)
        
        # Create compressed version
        archive_id = "compression_ratio_test"
        staged_path = archiver._stage_data(original_path, archive_id)
        compressed_path = archiver._compress_data(staged_path, CompressionLevel.BALANCED)
        
        # Calculate ratio
        ratio = archiver._calculate_compression_ratio(original_path, compressed_path)
        
        assert ratio >= 1.0  # Should achieve some compression
        assert isinstance(ratio, float)
    
    def test_get_path_size_file(self, archiver, temp_dirs):
        """Test path size calculation for files."""
        test_file = Path(temp_dirs['staging_dir']) / "size_test.txt"
        test_content = "x" * 1000  # 1000 characters
        test_file.write_text(test_content)
        
        size = archiver._get_path_size(test_file)
        
        assert size == len(test_content.encode('utf-8'))
    
    def test_get_path_size_directory(self, archiver, sample_dataset):
        """Test path size calculation for directories."""
        size = archiver._get_path_size(Path(sample_dataset))
        
        assert size > 0
        assert isinstance(size, int)
        
        # Should be sum of all file sizes in directory
        total_size = 0
        for file_path in Path(sample_dataset).rglob('*'):
            if file_path.is_file():
                total_size += file_path.stat().st_size
        
        assert size == total_size
    
    def test_store_archive_info(self, archiver):
        """Test storing archive information in database."""
        archive_info = {
            'archive_id': 'test_store_001',
            'dataset_name': 'Test Dataset',
            'source_path': '/test/source',
            'archive_path': '/test/archive.tar.gz',
            'size_bytes': 1024,
            'checksum': 'abc123',
            'compression_type': 'BALANCED',
            'compression_ratio': 2.5,
            'archived_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(days=30)).isoformat(),
            'status': ArchiveStatus.ARCHIVED.value,
            'metadata': '{}'
        }
        
        archiver._store_archive_info(archive_info)
        
        # Retrieve and verify
        stored_info = archiver._get_archive_info('test_store_001')
        assert stored_info is not None
        assert stored_info['archive_id'] == 'test_store_001'
        assert stored_info['dataset_name'] == 'Test Dataset'
        assert stored_info['size_bytes'] == 1024
    
    def test_get_archive_info(self, archiver):
        """Test retrieving archive information."""
        # Store test info first
        archive_info = {
            'archive_id': 'test_get_001',
            'dataset_name': 'Get Test',
            'source_path': '/test/source',
            'archive_path': '/test/archive.tar.gz',
            'size_bytes': 2048,
            'checksum': 'def456',
            'compression_type': 'FAST',
            'compression_ratio': 1.8,
            'archived_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(days=60)).isoformat(),
            'status': ArchiveStatus.ARCHIVED.value,
            'metadata': '{"key": "value"}'
        }
        
        archiver._store_archive_info(archive_info)
        
        # Retrieve info
        retrieved_info = archiver._get_archive_info('test_get_001')
        
        assert retrieved_info is not None
        assert retrieved_info['archive_id'] == 'test_get_001'
        assert retrieved_info['size_bytes'] == 2048
        assert retrieved_info['metadata'] == {"key": "value"}  # Should be parsed JSON
        
        # Test nonexistent archive
        nonexistent = archiver._get_archive_info('nonexistent_id')
        assert nonexistent is None
    
    def test_update_archive_status(self, archiver):
        """Test updating archive status."""
        # Store test archive first
        archive_info = {
            'archive_id': 'test_status_001',
            'dataset_name': 'Status Test',
            'source_path': '/test/source',
            'archive_path': '/test/archive.tar.gz',
            'size_bytes': 1024,
            'checksum': 'abc123',
            'compression_type': 'BALANCED',
            'compression_ratio': 2.0,
            'archived_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(days=30)).isoformat(),
            'status': ArchiveStatus.ARCHIVED.value,
            'metadata': '{}'
        }
        
        archiver._store_archive_info(archive_info)
        
        # Update status
        archiver._update_archive_status('test_status_001', ArchiveStatus.RETRIEVING)
        
        # Verify update
        updated_info = archiver._get_archive_info('test_status_001')
        assert updated_info['status'] == ArchiveStatus.RETRIEVING.value
    
    def test_log_retrieval(self, archiver):
        """Test logging archive retrieval."""
        retrieval_info = {
            'retrieval_id': 'test_retrieval_001',
            'archive_id': 'test_archive_001',
            'retrieved_at': datetime.now().isoformat(),
            'restored_path': '/test/restored',
            'user': 'test_user'
        }
        
        archiver._log_retrieval(retrieval_info)
        
        # Verify log entry
        conn = sqlite3.connect(archiver.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM retrieval_history WHERE retrieval_id = ?",
            (retrieval_info['retrieval_id'],)
        )
        
        row = cursor.fetchone()
        assert row is not None
        
        # Get column names
        columns = [desc[0] for desc in cursor.description]
        logged_info = dict(zip(columns, row))
        
        assert logged_info['archive_id'] == 'test_archive_001'
        assert logged_info['user'] == 'test_user'
        
        conn.close()
    
    def test_cleanup_staging(self, archiver, temp_dirs):
        """Test staging directory cleanup."""
        # Create staging directory
        archive_id = "test_cleanup_001"
        staging_path = archiver.staging_dir / archive_id
        staging_path.mkdir()
        (staging_path / "test_file.txt").write_text("Test content")
        
        assert staging_path.exists()
        
        # Cleanup
        archiver._cleanup_staging(archive_id)
        
        assert not staging_path.exists()
    
    def test_remove_from_catalog(self, archiver):
        """Test removing archive from catalog."""
        # Store test archive first
        archive_info = {
            'archive_id': 'test_remove_001',
            'dataset_name': 'Remove Test',
            'source_path': '/test/source',
            'archive_path': '/test/archive.tar.gz',
            'size_bytes': 1024,
            'checksum': 'abc123',
            'compression_type': 'BALANCED',
            'compression_ratio': 2.0,
            'archived_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(days=30)).isoformat(),
            'status': ArchiveStatus.ARCHIVED.value,
            'metadata': '{}'
        }
        
        archiver._store_archive_info(archive_info)
        
        # Verify it exists
        assert archiver._get_archive_info('test_remove_001') is not None
        
        # Remove from catalog
        archiver._remove_from_catalog('test_remove_001')
        
        # Should no longer exist
        assert archiver._get_archive_info('test_remove_001') is None
    
    def test_error_handling_archive_failure(self, archiver, sample_dataset):
        """Test error handling during archive failures."""
        # Mock a failure in the staging process
        with patch.object(archiver, '_stage_data', side_effect=Exception("Staging failed")):
            with pytest.raises(Exception, match="Staging failed"):
                archiver.archive_dataset(sample_dataset, dataset_name="failure_test")
            
            # Archive should be marked as error status in database if it was created
            # This behavior depends on when the failure occurs
    
    def test_error_handling_retrieval_failure(self, archiver, sample_dataset):
        """Test error handling during retrieval failures."""
        # Archive dataset first
        archive_result = archiver.archive_dataset(sample_dataset, dataset_name="retrieval_failure_test")
        archive_id = archive_result['archive_id']
        
        # Mock failure during retrieval
        with patch.object(archiver, '_decompress_archive', side_effect=Exception("Decompression failed")):
            with pytest.raises(Exception, match="Decompression failed"):
                archiver.retrieve_archive(archive_id)
            
            # Status should be updated to error
            archive_info = archiver._get_archive_info(archive_id)
            assert archive_info['status'] == ArchiveStatus.ERROR.value


@pytest.mark.integration  
class TestDataArchiverIntegration:
    """Integration tests for DataArchiver."""
    
    def test_complete_archive_lifecycle(self, temp_dirs):
        """Test complete archive lifecycle from creation to retrieval."""
        archiver = DataArchiver(
            archive_dir=temp_dirs['archive_dir'],
            staging_dir=temp_dirs['staging_dir'], 
            db_path=temp_dirs['db_path']
        )
        
        # Create comprehensive test dataset
        dataset_path = Path(temp_dirs['staging_dir']) / "lifecycle_dataset"
        dataset_path.mkdir()
        
        # Add various file types
        (dataset_path / "data.csv").write_text("id,name,value\n1,Alice,100\n2,Bob,200\n")
        (dataset_path / "metadata.json").write_text('{"version": "2.0", "format": "CSV"}')
        (dataset_path / "README.md").write_text("# Test Dataset\n\nThis is a test dataset.")
        
        # Add subdirectory with files
        subdir = dataset_path / "analysis"
        subdir.mkdir()
        (subdir / "results.txt").write_text("Analysis results here")
        (subdir / "plot.png").write_bytes(b"fake PNG data")
        
        # Archive the dataset
        archive_result = archiver.archive_dataset(
            str(dataset_path),
            dataset_name="Lifecycle Test Dataset",
            retention_days=365,
            compression=CompressionLevel.BALANCED,
            metadata={
                "study": "Integration Test",
                "investigator": "Test Runner",
                "created": datetime.now().isoformat()
            }
        )
        
        archive_id = archive_result['archive_id']
        
        # Verify archive was created
        assert archive_result['status'] == ArchiveStatus.ARCHIVED.value
        assert Path(archive_result['archive_path']).exists()
        assert archive_result['compression_ratio'] >= 1.0
        
        # List archives and find ours
        all_archives = archiver.list_archives()
        our_archive = next((a for a in all_archives if a['archive_id'] == archive_id), None)
        assert our_archive is not None
        assert our_archive['dataset_name'] == "Lifecycle Test Dataset"
        
        # Retrieve the archive
        restore_path = Path(temp_dirs['staging_dir']) / "restored_dataset"
        retrieval_result = archiver.retrieve_archive(
            archive_id,
            restore_path=str(restore_path),
            user="integration_test"
        )
        
        # Verify retrieval
        assert 'retrieval_id' in retrieval_result
        assert restore_path.exists()
        
        # Verify restored content
        restored_files = list(restore_path.rglob('*'))
        assert len(restored_files) > 0
        
        # Should have same file structure (exact structure depends on archiver implementation)
        file_names = {f.name for f in restored_files if f.is_file()}
        expected_files = {"data.csv", "metadata.json", "README.md", "results.txt", "plot.png"}
        
        # Check if most files were restored (allowing for some implementation differences)
        restored_expected = len(expected_files & file_names)
        assert restored_expected >= len(expected_files) * 0.8  # At least 80% of files
        
        # Get storage statistics
        stats = archiver.get_storage_stats()
        assert stats['total_archives'] >= 1
        assert stats['total_size_bytes'] > 0
        
        # Test expiration and cleanup
        # First manually expire the archive
        archiver._update_archive_status(archive_id, ArchiveStatus.EXPIRED)
        
        # Check that it's now expired
        expired_archives = archiver.check_expiration()
        # (archive was manually expired, so might not be in this list)
        
        # Test purge
        purge_result = archiver.purge_expired(confirm=True)
        
        # Archive should be purged
        assert archive_id in purge_result['purged'] or archive_id in purge_result['failed']
    
    def test_multiple_datasets_with_different_settings(self, temp_dirs):
        """Test archiving multiple datasets with different configurations."""
        archiver = DataArchiver(
            archive_dir=temp_dirs['archive_dir'],
            staging_dir=temp_dirs['staging_dir'],
            db_path=temp_dirs['db_path']
        )
        
        # Create different types of datasets
        datasets = []
        
        # Small dataset with no compression
        small_dataset = Path(temp_dirs['staging_dir']) / "small_dataset"
        small_dataset.mkdir()
        (small_dataset / "small.txt").write_text("Small file content")
        datasets.append({
            'path': str(small_dataset),
            'name': 'Small Dataset',
            'compression': CompressionLevel.NONE,
            'retention': 30
        })
        
        # Medium dataset with balanced compression
        medium_dataset = Path(temp_dirs['staging_dir']) / "medium_dataset"
        medium_dataset.mkdir()
        for i in range(10):
            (medium_dataset / f"file_{i:02d}.txt").write_text(f"Content for file {i}" * 100)
        datasets.append({
            'path': str(medium_dataset),
            'name': 'Medium Dataset',
            'compression': CompressionLevel.BALANCED,
            'retention': 90
        })
        
        # Large dataset with maximum compression
        large_dataset = Path(temp_dirs['staging_dir']) / "large_dataset"
        large_dataset.mkdir()
        for i in range(50):
            (large_dataset / f"large_file_{i:03d}.txt").write_text(f"Large content {i}" * 1000)
        datasets.append({
            'path': str(large_dataset),
            'name': 'Large Dataset',
            'compression': CompressionLevel.MAXIMUM,
            'retention': 365
        })
        
        # Archive all datasets
        archive_results = []
        for dataset_config in datasets:
            result = archiver.archive_dataset(
                dataset_config['path'],
                dataset_name=dataset_config['name'],
                compression=dataset_config['compression'],
                retention_days=dataset_config['retention']
            )
            archive_results.append(result)
        
        # Verify all archives
        assert len(archive_results) == 3
        for result in archive_results:
            assert result['status'] == ArchiveStatus.ARCHIVED.value
            assert Path(result['archive_path']).exists()
        
        # Check compression ratios
        no_compression_ratio = archive_results[0]['compression_ratio']
        balanced_ratio = archive_results[1]['compression_ratio']
        max_ratio = archive_results[2]['compression_ratio']
        
        # No compression should have ratio of 1.0
        assert no_compression_ratio == 1.0
        
        # Compressed versions should have ratios > 1.0
        assert balanced_ratio >= 1.0
        assert max_ratio >= 1.0
        
        # Maximum compression might achieve better ratio than balanced
        # (depends on data content and compression efficiency)
        
        # List all archives
        all_archives = archiver.list_archives()
        assert len(all_archives) >= 3
        
        # Verify different retention periods
        archive_ids = [r['archive_id'] for r in archive_results]
        for archive_id in archive_ids:
            info = archiver._get_archive_info(archive_id)
            archived_at = datetime.fromisoformat(info['archived_at'])
            expires_at = datetime.fromisoformat(info['expires_at'])
            retention_days = (expires_at - archived_at).days
            assert retention_days in [30, 90, 365]  # One of our test retention periods
        
        # Test retrieving each archive
        for i, result in enumerate(archive_results):
            restore_path = Path(temp_dirs['staging_dir']) / f"restored_{i}"
            retrieval_result = archiver.retrieve_archive(
                result['archive_id'],
                restore_path=str(restore_path)
            )
            
            assert restore_path.exists()
            restored_files = list(restore_path.rglob('*'))
            assert len(restored_files) > 0
    
    def test_concurrent_operations(self, temp_dirs):
        """Test handling concurrent archive operations."""
        archiver = DataArchiver(
            archive_dir=temp_dirs['archive_dir'],
            staging_dir=temp_dirs['staging_dir'],
            db_path=temp_dirs['db_path']
        )
        
        # Create test datasets
        datasets = []
        for i in range(5):
            dataset_path = Path(temp_dirs['staging_dir']) / f"concurrent_dataset_{i}"
            dataset_path.mkdir()
            (dataset_path / "data.txt").write_text(f"Dataset {i} content" * 100)
            datasets.append(str(dataset_path))
        
        # Archive datasets concurrently (simulated)
        archive_results = []
        for i, dataset_path in enumerate(datasets):
            result = archiver.archive_dataset(
                dataset_path,
                dataset_name=f"Concurrent Dataset {i}"
            )
            archive_results.append(result)
        
        # All should succeed
        assert len(archive_results) == 5
        for result in archive_results:
            assert result['status'] == ArchiveStatus.ARCHIVED.value
        
        # Verify database integrity
        all_archives = archiver.list_archives()
        concurrent_archives = [a for a in all_archives if 'Concurrent Dataset' in a['dataset_name']]
        assert len(concurrent_archives) == 5
        
        # All archive IDs should be unique
        archive_ids = [a['archive_id'] for a in concurrent_archives]
        assert len(set(archive_ids)) == len(archive_ids)  # All unique
        
        # Test concurrent retrievals
        for result in archive_results[:3]:  # Test first 3
            restore_path = Path(temp_dirs['staging_dir']) / f"concurrent_restore_{result['archive_id']}"
            retrieval_result = archiver.retrieve_archive(
                result['archive_id'],
                restore_path=str(restore_path)
            )
            assert restore_path.exists()
    
    def test_error_recovery_and_consistency(self, temp_dirs):
        """Test error recovery and database consistency."""
        archiver = DataArchiver(
            archive_dir=temp_dirs['archive_dir'],
            staging_dir=temp_dirs['staging_dir'],
            db_path=temp_dirs['db_path']
        )
        
        # Create test dataset
        dataset_path = Path(temp_dirs['staging_dir']) / "error_test_dataset"
        dataset_path.mkdir()
        (dataset_path / "data.txt").write_text("Error test data")
        
        # Test normal archiving first
        normal_result = archiver.archive_dataset(
            str(dataset_path),
            dataset_name="Normal Archive"
        )
        assert normal_result['status'] == ArchiveStatus.ARCHIVED.value
        
        # Simulate archiving failure midway through process
        with patch.object(archiver, '_compress_data', side_effect=Exception("Compression failed")):
            try:
                archiver.archive_dataset(
                    str(dataset_path),
                    dataset_name="Failed Archive"
                )
                assert False, "Should have raised exception"
            except Exception as e:
                assert "Compression failed" in str(e)
        
        # Database should remain consistent
        all_archives = archiver.list_archives()
        
        # Should have the normal archive
        normal_archives = [a for a in all_archives if a['dataset_name'] == "Normal Archive"]
        assert len(normal_archives) == 1
        assert normal_archives[0]['status'] == ArchiveStatus.ARCHIVED.value
        
        # Failed archive might or might not be in database depending on when failure occurred
        failed_archives = [a for a in all_archives if a['dataset_name'] == "Failed Archive"]
        if failed_archives:
            # If it exists, should be marked as error
            assert failed_archives[0]['status'] == ArchiveStatus.ERROR.value
        
        # Test retrieval of normal archive still works
        restore_path = Path(temp_dirs['staging_dir']) / "error_recovery_restore"
        retrieval_result = archiver.retrieve_archive(
            normal_result['archive_id'],
            restore_path=str(restore_path)
        )
        assert restore_path.exists()
        
        # Test database integrity with storage stats
        stats = archiver.get_storage_stats()
        assert stats['total_archives'] >= 1  # At least our normal archive
        assert stats['total_size_bytes'] >= 0
        
        # Status breakdown should be consistent
        status_breakdown = stats['status_breakdown']
        total_from_breakdown = sum(s['count'] for s in status_breakdown.values())
        assert total_from_breakdown == stats['total_archives']
