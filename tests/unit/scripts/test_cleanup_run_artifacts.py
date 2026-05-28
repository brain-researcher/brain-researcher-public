"""Unit tests for cleanup_run_artifacts script."""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.cleanup_run_artifacts import (
    RunInfo,
    cleanup_by_age,
    cleanup_by_size,
    cleanup_empty_date_dirs,
    get_dir_size,
    parse_run_info,
    scan_runs,
)


@pytest.fixture
def mock_runs_dir(tmp_path):
    """Create a mock runs directory structure."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    return runs_root


@pytest.fixture
def create_run():
    """Factory fixture to create run directories with metadata."""

    def _create_run(
        runs_root: Path,
        run_id: str,
        state: str = "succeeded",
        age_days: float = 0,
        size_mb: float = 10,
    ):
        """Create a run directory with status.json and some files."""
        # Calculate date directory based on age
        run_date = datetime.now() - timedelta(days=age_days)
        date_str = run_date.strftime("%Y%m%d")
        date_dir = runs_root / date_str
        date_dir.mkdir(exist_ok=True)

        run_dir = date_dir / run_id
        run_dir.mkdir()

        # Create status.json
        started_at = time.time() - (age_days * 86400)
        status = {
            "state": state,
            "started_at": started_at,
            "updated_at": started_at + 10,
            "transitions": [
                {"from": "scheduled", "to": "running", "timestamp": started_at},
                {"from": "running", "to": state, "timestamp": started_at + 10},
            ],
        }
        with open(run_dir / "status.json", "w") as f:
            json.dump(status, f)

        # Create some files to reach target size
        target_bytes = int(size_mb * 1_048_576)
        chunk_size = min(target_bytes, 1_048_576)  # 1MB chunks
        bytes_written = 0

        file_idx = 0
        while bytes_written < target_bytes:
            chunk = min(chunk_size, target_bytes - bytes_written)
            (run_dir / f"data_{file_idx}.bin").write_bytes(b"x" * chunk)
            bytes_written += chunk
            file_idx += 1

        # Create other standard files
        (run_dir / "command.txt").write_text("mock command")
        (run_dir / "stdout.txt").write_text("mock stdout")
        (run_dir / "stderr.txt").write_text("")
        (run_dir / "provenance.json").write_text("{}")

        # Set mtime of all files and directory to match age
        # This is critical for is_active checks
        mtime = started_at + 10  # Match the updated_at time
        for file_path in run_dir.rglob("*"):
            if file_path.is_file():
                os.utime(file_path, (mtime, mtime))
        os.utime(run_dir, (mtime, mtime))

        return run_dir

    return _create_run


class TestRunInfo:
    """Tests for RunInfo dataclass."""

    def test_age_days_calculation(self):
        """Test age calculation in days."""
        one_day_ago = time.time() - 86400
        run = RunInfo(
            run_dir=Path("/tmp/run"),
            run_id="run123",
            state="succeeded",
            started_at=one_day_ago,
            size_bytes=1000,
            mtime=one_day_ago,
        )

        assert 0.9 < run.age_days < 1.1  # Allow some timing variance

    def test_size_mb_conversion(self):
        """Test size conversion to MB."""
        run = RunInfo(
            run_dir=Path("/tmp/run"),
            run_id="run123",
            state="succeeded",
            started_at=time.time(),
            size_bytes=10_485_760,  # 10 MB
            mtime=time.time(),
        )

        assert run.size_mb == 10.0

    def test_is_active_running_state(self):
        """Test that running state is considered active."""
        run = RunInfo(
            run_dir=Path("/tmp/run"),
            run_id="run123",
            state="running",
            started_at=time.time() - 3600,  # 1 hour ago
            size_bytes=1000,
            mtime=time.time() - 3600,
        )

        assert run.is_active is True

    def test_is_active_recent_mtime(self):
        """Test that recent mtime is considered active."""
        run = RunInfo(
            run_dir=Path("/tmp/run"),
            run_id="run123",
            state="succeeded",
            started_at=time.time() - 3600,
            size_bytes=1000,
            mtime=time.time() - 60,  # Modified 1 minute ago
        )

        assert run.is_active is True

    def test_is_active_old_completed(self):
        """Test that old completed runs are not active."""
        old_time = time.time() - 86400  # 1 day ago
        run = RunInfo(
            run_dir=Path("/tmp/run"),
            run_id="run123",
            state="succeeded",
            started_at=old_time,
            size_bytes=1000,
            mtime=old_time,
        )

        assert run.is_active is False


class TestGetDirSize:
    """Tests for get_dir_size function."""

    def test_empty_directory(self, tmp_path):
        """Test size of empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        assert get_dir_size(empty_dir) == 0

    def test_directory_with_files(self, tmp_path):
        """Test size calculation with files."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        (test_dir / "file1.txt").write_bytes(b"x" * 1000)
        (test_dir / "file2.txt").write_bytes(b"x" * 2000)

        assert get_dir_size(test_dir) == 3000

    def test_nested_directories(self, tmp_path):
        """Test size calculation with nested directories."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        sub_dir = test_dir / "sub"
        sub_dir.mkdir()

        (test_dir / "file1.txt").write_bytes(b"x" * 1000)
        (sub_dir / "file2.txt").write_bytes(b"x" * 2000)

        assert get_dir_size(test_dir) == 3000


class TestParseRunInfo:
    """Tests for parse_run_info function."""

    def test_parse_valid_run(self, mock_runs_dir, create_run):
        """Test parsing a valid run directory."""
        run_dir = create_run(mock_runs_dir, "run123", state="succeeded", age_days=1, size_mb=5)

        run_info = parse_run_info(run_dir)

        assert run_info is not None
        assert run_info.run_id == "run123"
        assert run_info.state == "succeeded"
        assert run_info.age_days > 0.9
        assert run_info.size_mb > 4.5  # Allow some overhead from status.json, etc.

    def test_parse_incomplete_run(self, tmp_path):
        """Test parsing run without status.json."""
        run_dir = tmp_path / "20250101" / "incomplete_run"
        run_dir.mkdir(parents=True)
        (run_dir / "command.txt").write_text("test")

        run_info = parse_run_info(run_dir)

        assert run_info is not None
        assert run_info.state == "unknown"

    def test_parse_corrupted_status(self, tmp_path):
        """Test parsing run with corrupted status.json."""
        run_dir = tmp_path / "20250101" / "corrupted_run"
        run_dir.mkdir(parents=True)
        (run_dir / "status.json").write_text("invalid json{{{")

        run_info = parse_run_info(run_dir)

        assert run_info is not None
        assert run_info.state == "unknown"


class TestScanRuns:
    """Tests for scan_runs function."""

    def test_scan_empty_directory(self, mock_runs_dir):
        """Test scanning empty runs directory."""
        runs = scan_runs(mock_runs_dir)

        assert runs == []

    def test_scan_multiple_runs(self, mock_runs_dir, create_run):
        """Test scanning multiple run directories."""
        create_run(mock_runs_dir, "run1", age_days=1)
        create_run(mock_runs_dir, "run2", age_days=2)
        create_run(mock_runs_dir, "run3", age_days=3)

        runs = scan_runs(mock_runs_dir)

        assert len(runs) == 3
        run_ids = {r.run_id for r in runs}
        assert run_ids == {"run1", "run2", "run3"}

    def test_scan_multiple_date_directories(self, mock_runs_dir, create_run):
        """Test scanning runs across multiple date directories."""
        create_run(mock_runs_dir, "run1", age_days=1)
        create_run(mock_runs_dir, "run2", age_days=10)
        create_run(mock_runs_dir, "run3", age_days=20)

        runs = scan_runs(mock_runs_dir)

        assert len(runs) == 3

    def test_scan_nonexistent_directory(self, tmp_path):
        """Test scanning nonexistent directory."""
        runs = scan_runs(tmp_path / "nonexistent")

        assert runs == []


class TestCleanupByAge:
    """Tests for cleanup_by_age function."""

    def test_cleanup_old_runs(self, mock_runs_dir, create_run):
        """Test cleanup deletes runs older than threshold."""
        old_run = create_run(mock_runs_dir, "old_run", age_days=10)
        recent_run = create_run(mock_runs_dir, "recent_run", age_days=1)

        runs = scan_runs(mock_runs_dir)
        deleted = cleanup_by_age(runs, max_age_days=5, dry_run=False)

        assert deleted == 1
        assert not old_run.exists()
        assert recent_run.exists()

    def test_cleanup_preserves_active_runs(self, mock_runs_dir, create_run):
        """Test cleanup skips active runs even if old."""
        old_running = create_run(mock_runs_dir, "old_running", state="running", age_days=10)
        old_completed = create_run(mock_runs_dir, "old_completed", state="succeeded", age_days=10)

        runs = scan_runs(mock_runs_dir)
        deleted = cleanup_by_age(runs, max_age_days=5, dry_run=False)

        assert deleted == 1
        assert old_running.exists()  # Active, should be preserved
        assert not old_completed.exists()

    def test_cleanup_dry_run(self, mock_runs_dir, create_run):
        """Test dry-run mode doesn't delete."""
        old_run = create_run(mock_runs_dir, "old_run", age_days=10)

        runs = scan_runs(mock_runs_dir)
        deleted = cleanup_by_age(runs, max_age_days=5, dry_run=True)

        assert deleted == 1
        assert old_run.exists()  # Should still exist in dry-run

    def test_cleanup_no_matching_runs(self, mock_runs_dir, create_run):
        """Test cleanup when no runs exceed age threshold."""
        create_run(mock_runs_dir, "run1", age_days=1)
        create_run(mock_runs_dir, "run2", age_days=2)

        runs = scan_runs(mock_runs_dir)
        deleted = cleanup_by_age(runs, max_age_days=10, dry_run=False)

        assert deleted == 0


class TestCleanupBySize:
    """Tests for cleanup_by_size function."""

    def test_cleanup_when_under_limit(self, mock_runs_dir, create_run):
        """Test no cleanup when under size limit."""
        create_run(mock_runs_dir, "run1", size_mb=10)
        create_run(mock_runs_dir, "run2", size_mb=10)

        runs = scan_runs(mock_runs_dir)
        deleted = cleanup_by_size(runs, max_size_gb=1.0, dry_run=False)

        assert deleted == 0

    def test_cleanup_when_over_limit(self, mock_runs_dir, create_run):
        """Test cleanup when over size limit."""
        old_run = create_run(mock_runs_dir, "old_run", age_days=10, size_mb=100)
        mid_run = create_run(mock_runs_dir, "mid_run", age_days=5, size_mb=100)
        new_run = create_run(mock_runs_dir, "new_run", age_days=1, size_mb=100)

        runs = scan_runs(mock_runs_dir)
        # Total ~300MB, limit 0.15GB (150MB), should delete oldest until under
        deleted = cleanup_by_size(runs, max_size_gb=0.15, dry_run=False)

        assert deleted >= 1
        assert not old_run.exists()  # Oldest should be deleted first

    def test_cleanup_preserves_active_runs(self, mock_runs_dir, create_run):
        """Test size cleanup skips active runs."""
        old_running = create_run(
            mock_runs_dir, "old_running", state="running", age_days=10, size_mb=150
        )
        old_completed = create_run(mock_runs_dir, "old_completed", age_days=9, size_mb=150)

        runs = scan_runs(mock_runs_dir)
        # Total ~300MB, limit 100MB - should delete completed run but not active
        deleted = cleanup_by_size(runs, max_size_gb=0.1, dry_run=False)

        assert deleted >= 1
        assert old_running.exists()  # Active, should be preserved
        assert not old_completed.exists()  # Should be deleted

    def test_cleanup_deletes_oldest_first(self, mock_runs_dir, create_run):
        """Test that oldest runs are deleted first."""
        oldest = create_run(mock_runs_dir, "oldest", age_days=10, size_mb=50)
        middle = create_run(mock_runs_dir, "middle", age_days=5, size_mb=50)
        newest = create_run(mock_runs_dir, "newest", age_days=1, size_mb=50)

        runs = scan_runs(mock_runs_dir)
        # Total ~150MB, limit 0.08GB (~80MB), should delete oldest until under
        cleanup_by_size(runs, max_size_gb=0.08, dry_run=False)

        # Oldest should definitely be gone
        assert not oldest.exists()
        # Newest should definitely still exist
        assert newest.exists()

    def test_cleanup_size_dry_run(self, mock_runs_dir, create_run):
        """Test size cleanup dry-run doesn't delete."""
        # Use age_days=1 to ensure runs are not considered active (mtime > 2 minutes old)
        create_run(mock_runs_dir, "run1", age_days=1, size_mb=150)
        create_run(mock_runs_dir, "run2", age_days=1, size_mb=150)

        runs = scan_runs(mock_runs_dir)
        # Total ~300MB, limit 100MB - should identify runs to delete
        deleted = cleanup_by_size(runs, max_size_gb=0.1, dry_run=True)

        # Should identify runs to delete but not actually delete
        assert deleted >= 1
        # All runs should still exist
        for run in scan_runs(mock_runs_dir):
            assert run.run_dir.exists()


class TestCleanupEmptyDateDirs:
    """Tests for cleanup_empty_date_dirs function."""

    def test_remove_empty_directories(self, mock_runs_dir):
        """Test removal of empty date directories."""
        (mock_runs_dir / "20250101").mkdir()
        (mock_runs_dir / "20250102").mkdir()

        removed = cleanup_empty_date_dirs(mock_runs_dir, dry_run=False)

        assert removed == 2
        assert not (mock_runs_dir / "20250101").exists()
        assert not (mock_runs_dir / "20250102").exists()

    def test_preserve_nonempty_directories(self, mock_runs_dir, create_run):
        """Test non-empty directories are preserved."""
        run_dir = create_run(mock_runs_dir, "run1", age_days=1)
        (mock_runs_dir / "20250103").mkdir()  # Empty

        removed = cleanup_empty_date_dirs(mock_runs_dir, dry_run=False)

        assert removed == 1
        # Date directory with run should still exist
        assert run_dir.parent.exists(), "Run's date directory should still exist"
        assert not (mock_runs_dir / "20250103").exists(), "Empty directory should be removed"

    def test_cleanup_empty_dry_run(self, mock_runs_dir):
        """Test dry-run doesn't remove directories."""
        (mock_runs_dir / "20250101").mkdir()

        removed = cleanup_empty_date_dirs(mock_runs_dir, dry_run=True)

        assert removed == 1
        assert (mock_runs_dir / "20250101").exists()


class TestIntegration:
    """Integration tests for full cleanup workflow."""

    def test_full_cleanup_workflow(self, mock_runs_dir, create_run):
        """Test complete cleanup workflow."""
        # Create varied runs
        create_run(mock_runs_dir, "very_old", age_days=100, size_mb=50)
        create_run(mock_runs_dir, "old", age_days=40, size_mb=50)
        create_run(mock_runs_dir, "recent", age_days=5, size_mb=50)
        create_run(mock_runs_dir, "new", age_days=1, size_mb=50)
        create_run(mock_runs_dir, "active", state="running", age_days=50, size_mb=50)

        # Age-based cleanup (30 days)
        runs = scan_runs(mock_runs_dir)
        cleanup_by_age(runs, max_age_days=30, dry_run=False)

        # Re-scan and check
        runs = scan_runs(mock_runs_dir)
        assert len(runs) == 3  # recent, new, active (active preserved even though old)

        # Size-based cleanup (100MB limit)
        cleanup_by_size(runs, max_size_gb=0.1, dry_run=False)

        # Re-scan
        runs = scan_runs(mock_runs_dir)
        # Should keep newest runs + active, total under 100MB
        assert all(r.state == "running" or r.age_days < 10 for r in runs)

        # Cleanup empty directories
        cleanup_empty_date_dirs(mock_runs_dir, dry_run=False)

        # Check no empty date directories remain
        for date_dir in mock_runs_dir.iterdir():
            if date_dir.is_dir():
                assert any(date_dir.iterdir())
