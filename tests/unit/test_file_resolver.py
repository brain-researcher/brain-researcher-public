"""
Unit tests for FileResolver security validations and resolution logic.

Tests file_id validation, filename sanitization, checksum verification,
and security constraints.
"""

import hashlib
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain_researcher.services.agent.file_resolver import (
    ChecksumMismatchError,
    FileNotFoundError,
    FileResolver,
    FileResolverConfig,
    FileResolverError,
    ResolvedFile,
    SecurityValidationError,
)


class TestFileResolverValidation:
    """Tests for FileResolver input validation."""

    @pytest.fixture
    def resolver(self, tmp_path):
        """Create resolver with temp cache directory."""
        config = FileResolverConfig(
            cache_dir=tmp_path / "cache",
            orchestrator_url="http://localhost:8000",
        )
        return FileResolver(config)

    def test_validate_file_id_valid(self, resolver):
        """Valid file_id patterns should pass."""
        valid_ids = [
            "file_abc123",
            "file_123",
            "file_abc-def_123",
            "file_ABC123",
            "file_a",
        ]
        for file_id in valid_ids:
            result = resolver._validate_file_id(file_id)
            assert result == file_id

    def test_validate_file_id_invalid(self, resolver):
        """Invalid file_id patterns should raise SecurityValidationError."""
        invalid_ids = [
            "",  # Empty
            "abc123",  # Missing file_ prefix
            "file_",  # Only prefix
            "file_abc/def",  # Contains slash
            "file_abc..def",  # Contains dots
            "file_abc def",  # Contains space
            "../file_abc",  # Path traversal
            "file_abc\x00def",  # Null byte
        ]
        for file_id in invalid_ids:
            with pytest.raises(SecurityValidationError):
                resolver._validate_file_id(file_id)

    def test_sanitize_filename_valid(self, resolver):
        """Valid filenames should pass and remain unchanged."""
        valid_names = [
            "test.nii.gz",
            "brain_scan.nii.gz",
            "data-file.csv",
            "file123.json",
        ]
        for name in valid_names:
            result = resolver._sanitize_filename(name)
            assert result == name

    def test_sanitize_filename_removes_path(self, resolver):
        """Path components should be stripped."""
        assert resolver._sanitize_filename("/path/to/file.txt") == "file.txt"
        assert resolver._sanitize_filename("../../../etc/passwd") == "passwd"
        assert resolver._sanitize_filename("dir/subdir/data.csv") == "data.csv"

    def test_sanitize_filename_replaces_dangerous_chars(self, resolver):
        """Dangerous characters should be replaced with underscores."""
        # Spaces become underscores
        assert resolver._sanitize_filename("file name.txt") == "file_name.txt"
        # Special chars (;) become underscores, but hyphens are allowed
        assert resolver._sanitize_filename("file;rm -rf.txt") == "file_rm_-rf.txt"

    def test_sanitize_filename_rejects_hidden(self, resolver):
        """Hidden files (starting with .) should be rejected."""
        with pytest.raises(SecurityValidationError):
            resolver._sanitize_filename(".hidden")

        with pytest.raises(SecurityValidationError):
            resolver._sanitize_filename(".")

        with pytest.raises(SecurityValidationError):
            resolver._sanitize_filename("..")

    def test_sanitize_filename_limits_length(self, resolver):
        """Filenames longer than 255 chars should be truncated."""
        long_name = "a" * 300 + ".txt"
        result = resolver._sanitize_filename(long_name)
        assert len(result) <= 255
        assert result.endswith(".txt")  # Extension preserved

    def test_sanitize_filename_empty(self, resolver):
        """Empty filename should raise error."""
        with pytest.raises(SecurityValidationError):
            resolver._sanitize_filename("")


class TestFileResolverFileInfo:
    """Tests for file info validation."""

    @pytest.fixture
    def resolver(self, tmp_path):
        """Create resolver with temp cache directory."""
        config = FileResolverConfig(
            cache_dir=tmp_path / "cache",
            max_file_size=10 * 1024 * 1024,  # 10MB
            allowed_content_types={"application/gzip", "text/plain"},
        )
        return FileResolver(config)

    def test_validate_file_info_valid(self, resolver):
        """Valid file info should pass."""
        info = {
            "size": 1000,
            "content_type": "application/gzip",
        }
        # Should not raise
        resolver._validate_file_info(info)

    def test_validate_file_info_too_large(self, resolver):
        """Files exceeding size limit should be rejected."""
        info = {
            "size": 100 * 1024 * 1024,  # 100MB
            "content_type": "application/gzip",
        }
        with pytest.raises(SecurityValidationError) as exc_info:
            resolver._validate_file_info(info)
        assert "too large" in str(exc_info.value).lower()

    def test_validate_file_info_disallowed_content_type(self, resolver):
        """Disallowed content types should be rejected."""
        info = {
            "size": 1000,
            "content_type": "application/x-executable",
        }
        with pytest.raises(SecurityValidationError) as exc_info:
            resolver._validate_file_info(info)
        assert "content type" in str(exc_info.value).lower()

    def test_validate_file_info_unknown_content_type_allowed(self, resolver):
        """Unknown/empty content type should pass (validated elsewhere)."""
        info = {
            "size": 1000,
            "content_type": "",
        }
        # Should not raise - empty content type is allowed
        resolver._validate_file_info(info)


class TestFileResolverChecksum:
    """Tests for checksum computation and verification."""

    @pytest.fixture
    def resolver(self, tmp_path):
        """Create resolver with temp cache directory."""
        config = FileResolverConfig(cache_dir=tmp_path / "cache")
        return FileResolver(config)

    def test_compute_checksum(self, resolver, tmp_path):
        """Checksum should be computed correctly."""
        test_file = tmp_path / "test.txt"
        test_content = b"Hello, World!"
        test_file.write_bytes(test_content)

        expected_hash = hashlib.sha256(test_content).hexdigest()
        expected_checksum = f"sha256:{expected_hash}"

        result = resolver._compute_checksum(test_file)
        assert result == expected_checksum

    def test_compute_checksum_empty_file(self, resolver, tmp_path):
        """Empty file should have valid checksum."""
        test_file = tmp_path / "empty.txt"
        test_file.write_bytes(b"")

        result = resolver._compute_checksum(test_file)
        assert result.startswith("sha256:")
        assert len(result) == len("sha256:") + 64  # SHA256 hex length


class TestFileResolverCachePath:
    """Tests for cache path generation."""

    @pytest.fixture
    def resolver(self, tmp_path):
        """Create resolver with temp cache directory."""
        config = FileResolverConfig(cache_dir=tmp_path / "cache")
        return FileResolver(config)

    def test_get_cache_path(self, resolver, tmp_path):
        """Cache path should be deterministic."""
        path = resolver._get_cache_path("file_abc123", "data.nii.gz")

        expected = tmp_path / "cache" / "file_abc123" / "data.nii.gz"
        assert path == expected

    def test_get_cache_path_isolates_files(self, resolver):
        """Different file_ids should get isolated directories."""
        path1 = resolver._get_cache_path("file_abc", "data.txt")
        path2 = resolver._get_cache_path("file_def", "data.txt")

        assert path1.parent != path2.parent
        assert path1.parent.name == "file_abc"
        assert path2.parent.name == "file_def"


class TestFileResolverConfig:
    """Tests for FileResolver configuration defaults."""

    def test_default_orchestrator_url_uses_orchestrator_port(self, monkeypatch):
        """Default orchestrator fallback should target the orchestrator service."""
        for key in [
            "BR_ORCHESTRATOR_URL",
            "ORCHESTRATOR_BASE_URL",
            "ORCHESTRATOR_API",
            "ORCHESTRATOR_URL",
            "ORCHESTRATOR_API_URL",
        ]:
            monkeypatch.delenv(key, raising=False)

        config = FileResolverConfig()

        assert config.orchestrator_url == "http://localhost:3001"

    def test_prefers_explicit_internal_orchestrator_url(self, monkeypatch):
        """BR_ORCHESTRATOR_URL should take precedence over legacy env names."""
        monkeypatch.setenv("ORCHESTRATOR_URL", "http://legacy-orchestrator:3001")
        monkeypatch.setenv("BR_ORCHESTRATOR_URL", "http://internal-orchestrator:3001/")

        config = FileResolverConfig()

        assert config.orchestrator_url == "http://internal-orchestrator:3001"


class TestFileResolverClearCache:
    """Tests for cache clearing functionality."""

    @pytest.fixture
    def resolver_with_cache(self, tmp_path):
        """Create resolver and populate cache."""
        config = FileResolverConfig(cache_dir=tmp_path / "cache")
        resolver = FileResolver(config)

        # Create some cached files
        (tmp_path / "cache" / "file_abc" / "data.txt").parent.mkdir(
            parents=True, exist_ok=True
        )
        (tmp_path / "cache" / "file_abc" / "data.txt").write_text("test1")
        (tmp_path / "cache" / "file_def" / "data.txt").parent.mkdir(
            parents=True, exist_ok=True
        )
        (tmp_path / "cache" / "file_def" / "data.txt").write_text("test2")

        return resolver

    def test_clear_cache_all(self, resolver_with_cache, tmp_path):
        """Clearing all cache should remove all files."""
        deleted = resolver_with_cache.clear_cache()

        assert deleted == 2
        assert not (tmp_path / "cache" / "file_abc").exists()
        assert not (tmp_path / "cache" / "file_def").exists()

    def test_clear_cache_specific(self, resolver_with_cache, tmp_path):
        """Clearing specific file_id should only remove that file."""
        deleted = resolver_with_cache.clear_cache("file_abc")

        assert deleted == 1
        assert not (tmp_path / "cache" / "file_abc").exists()
        assert (tmp_path / "cache" / "file_def" / "data.txt").exists()


class TestFileResolverResolve:
    """Integration tests for the resolve method."""

    @pytest.fixture
    def resolver(self, tmp_path):
        """Create resolver with temp cache directory."""
        config = FileResolverConfig(
            cache_dir=tmp_path / "cache",
            orchestrator_url="http://localhost:8000",
        )
        return FileResolver(config)

    @pytest.mark.asyncio
    async def test_resolve_local_file(self, resolver, tmp_path):
        """Should return local path if file exists locally."""
        # Create a local file
        local_file = tmp_path / "local" / "data.nii.gz"
        local_file.parent.mkdir(parents=True, exist_ok=True)
        local_file.write_bytes(b"test data")

        file_info = {
            "path": str(local_file),
            "size": local_file.stat().st_size,
            "content_type": "application/gzip",
            "url": "/uploads/file_test/data.nii.gz",
        }

        with patch.object(resolver, "_get_file_info", new_callable=AsyncMock) as mock:
            mock.return_value = file_info

            result = await resolver.resolve("file_test", "data.nii.gz")

            assert result.storage == "local"
            assert result.path == local_file
            assert result.file_id == "file_test"

    @pytest.mark.asyncio
    async def test_resolve_cached_file(self, resolver, tmp_path):
        """Should return cached file if available and checksum matches."""
        # Create a cached file
        cache_path = resolver._get_cache_path("file_cache", "data.txt")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(b"cached data")

        checksum = resolver._compute_checksum(cache_path)

        file_info = {
            "size": cache_path.stat().st_size,
            "content_type": "text/plain",
            "url": "/uploads/file_cache/data.txt",
            "checksum": checksum,
        }

        with patch.object(resolver, "_get_file_info", new_callable=AsyncMock) as mock:
            mock.return_value = file_info

            result = await resolver.resolve("file_cache", "data.txt")

            assert result.storage == "cached"
            assert result.path == cache_path

    @pytest.mark.asyncio
    async def test_resolve_download_and_cache(self, resolver, tmp_path):
        """Should download file if not in cache."""
        file_info = {
            "size": 100,
            "content_type": "text/plain",
            "url": "/uploads/file_download/data.txt",
        }

        with (
            patch.object(resolver, "_get_file_info", new_callable=AsyncMock) as mock_info,
            patch.object(
                resolver, "_download_file", new_callable=AsyncMock
            ) as mock_download,
        ):
            mock_info.return_value = file_info

            async def write_file(url, dest):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"downloaded content")

            mock_download.side_effect = write_file

            result = await resolver.resolve("file_download", "data.txt")

            assert result.storage == "downloaded"
            mock_download.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_checksum_mismatch(self, resolver, tmp_path):
        """Should raise error if checksum doesn't match after download."""
        file_info = {
            "size": 100,
            "content_type": "text/plain",
            "url": "/uploads/file_mismatch/data.txt",
            "checksum": "sha256:expected_but_wrong",
        }

        with (
            patch.object(resolver, "_get_file_info", new_callable=AsyncMock) as mock_info,
            patch.object(
                resolver, "_download_file", new_callable=AsyncMock
            ) as mock_download,
        ):
            mock_info.return_value = file_info

            async def write_file(url, dest):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"downloaded content")

            mock_download.side_effect = write_file

            with pytest.raises(ChecksumMismatchError):
                await resolver.resolve("file_mismatch", "data.txt")


class TestFileResolverBatch:
    """Tests for batch resolution."""

    @pytest.fixture
    def resolver(self, tmp_path):
        """Create resolver with temp cache directory."""
        config = FileResolverConfig(cache_dir=tmp_path / "cache")
        return FileResolver(config)

    @pytest.mark.asyncio
    async def test_resolve_batch_success(self, resolver, tmp_path):
        """Batch resolution should return all resolved files."""
        attachments = [
            {"id": "file_one", "name": "one.txt"},
            {"id": "file_two", "name": "two.txt"},
        ]

        async def mock_resolve(file_id, filename, checksum=None):
            path = tmp_path / file_id / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"data")
            return ResolvedFile(
                path=path,
                size=4,
                checksum="sha256:xxx",
                content_type="text/plain",
                source_url=f"/uploads/{file_id}/{filename}",
                storage="local",
                file_id=file_id,
                filename=filename,
            )

        with patch.object(resolver, "resolve", new_callable=AsyncMock) as mock:
            mock.side_effect = mock_resolve

            result = await resolver.resolve_batch(attachments)

            assert len(result) == 2
            assert "file_one" in result
            assert "file_two" in result

    @pytest.mark.asyncio
    async def test_resolve_batch_partial_failure(self, resolver, tmp_path):
        """Batch resolution should continue on individual failures."""
        attachments = [
            {"id": "file_ok", "name": "ok.txt"},
            {"id": "file_fail", "name": "fail.txt"},
        ]

        async def mock_resolve(file_id, filename, checksum=None):
            if file_id == "file_fail":
                raise FileNotFoundError(f"Not found: {file_id}")

            path = tmp_path / file_id / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"data")
            return ResolvedFile(
                path=path,
                size=4,
                checksum="sha256:xxx",
                content_type="text/plain",
                source_url=f"/uploads/{file_id}/{filename}",
                storage="local",
                file_id=file_id,
                filename=filename,
            )

        with patch.object(resolver, "resolve", new_callable=AsyncMock) as mock:
            mock.side_effect = mock_resolve

            result = await resolver.resolve_batch(attachments)

            assert len(result) == 1
            assert "file_ok" in result
            assert "file_fail" not in result

    @pytest.mark.asyncio
    async def test_resolve_batch_skip_missing_id(self, resolver):
        """Batch should skip attachments without file_id."""
        attachments = [
            {"name": "no_id.txt"},  # Missing id
            {"id": "file_ok", "name": "ok.txt"},
        ]

        async def mock_resolve(file_id, filename, checksum=None):
            return ResolvedFile(
                path=Path("/tmp/fake"),
                size=0,
                checksum="",
                content_type="text/plain",
                source_url="",
                storage="local",
                file_id=file_id,
                filename=filename,
            )

        with patch.object(resolver, "resolve", new_callable=AsyncMock) as mock:
            mock.side_effect = mock_resolve

            result = await resolver.resolve_batch(attachments)

            # Should only resolve the one with id
            assert mock.call_count == 1
            assert "file_ok" in result
