"""
Unit tests for FileAttachment model with new storage metadata fields.

Tests backward compatibility and new field validation.
"""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError


class TestFileAttachment:
    """Tests for FileAttachment model backward compatibility and new fields."""

    @pytest.fixture
    def old_format_attachment(self) -> dict:
        """Attachment in old format without new fields."""
        return {
            "id": "file_123abc",
            "name": "test.nii.gz",
            "type": "application/gzip",
            "size": 1000,
            "url": "/uploads/file_123abc/test.nii.gz",
        }

    @pytest.fixture
    def full_format_attachment(self) -> dict:
        """Attachment with all fields including new ones."""
        return {
            "id": "file_456def",
            "name": "brain_scan.nii.gz",
            "type": "application/gzip",
            "size": 50000000,
            "url": "/uploads/file_456def/brain_scan.nii.gz",
            "upload_progress": 100.0,
            "storage": "local",
            "path": "/data/uploads/chat/file_456def",
            "checksum": "sha256:abc123def456789",
            "uploaded_by": "user_001",
            "expires_at": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
        }

    def test_backward_compatibility_old_format(self, old_format_attachment):
        """Old attachments without new fields should still validate."""
        from brain_researcher.services.orchestrator.models import FileAttachment

        att = FileAttachment(**old_format_attachment)

        assert att.id == "file_123abc"
        assert att.name == "test.nii.gz"
        assert att.type == "application/gzip"
        assert att.size == 1000
        assert att.url == "/uploads/file_123abc/test.nii.gz"
        # New fields should be None
        assert att.storage is None
        assert att.path is None
        assert att.checksum is None
        assert att.uploaded_by is None
        assert att.expires_at is None

    def test_new_fields_populated(self, full_format_attachment):
        """New attachments with all fields should validate."""
        from brain_researcher.services.orchestrator.models import FileAttachment

        att = FileAttachment(**full_format_attachment)

        assert att.storage == "local"
        assert att.path == "/data/uploads/chat/file_456def"
        assert att.checksum == "sha256:abc123def456789"
        assert att.uploaded_by == "user_001"
        assert att.expires_at is not None

    def test_partial_new_fields(self, old_format_attachment):
        """Partial new fields should work."""
        from brain_researcher.services.orchestrator.models import FileAttachment

        data = {**old_format_attachment, "storage": "s3", "checksum": "sha256:xxx"}
        att = FileAttachment(**data)

        assert att.storage == "s3"
        assert att.checksum == "sha256:xxx"
        assert att.path is None  # Not provided
        assert att.uploaded_by is None

    def test_storage_literal_validation(self, old_format_attachment):
        """Storage field should only accept valid literals."""
        from brain_researcher.services.orchestrator.models import FileAttachment

        # Valid values
        for storage_type in ["local", "s3", "remote"]:
            data = {**old_format_attachment, "storage": storage_type}
            att = FileAttachment(**data)
            assert att.storage == storage_type

        # Invalid value
        data = {**old_format_attachment, "storage": "invalid_storage"}
        with pytest.raises(ValidationError):
            FileAttachment(**data)

    def test_filename_validation_path_traversal_sanitized(self):
        """Filename validation should sanitize path traversal attempts.

        The validator extracts just the basename, effectively removing
        path traversal components rather than rejecting them outright.
        """
        from brain_researcher.services.orchestrator.models import FileAttachment

        # Path traversal attempt - should be sanitized to just 'passwd'
        att = FileAttachment(
            id="file_test",
            name="../../../etc/passwd",
            type="text/plain",
            size=100,
            url="/uploads/file_test/passwd",
        )
        # Path components should be stripped
        assert att.name == "passwd"
        assert "/" not in att.name
        assert ".." not in att.name

    def test_filename_validation_hidden_files(self):
        """Filename validation should block hidden files."""
        from brain_researcher.services.orchestrator.models import FileAttachment

        with pytest.raises(ValidationError):
            FileAttachment(
                id="file_test",
                name=".hidden_file",
                type="text/plain",
                size=100,
                url="/uploads/file_test/.hidden_file",
            )

    def test_size_validation(self):
        """Size must be non-negative."""
        from brain_researcher.services.orchestrator.models import FileAttachment

        # Negative size should fail
        with pytest.raises(ValidationError):
            FileAttachment(
                id="file_test",
                name="test.txt",
                type="text/plain",
                size=-1,
                url="/uploads/file_test/test.txt",
            )

        # Zero size should work
        att = FileAttachment(
            id="file_test",
            name="empty.txt",
            type="text/plain",
            size=0,
            url="/uploads/file_test/empty.txt",
        )
        assert att.size == 0

    def test_upload_progress_bounds(self, old_format_attachment):
        """Upload progress should be between 0 and 100."""
        from brain_researcher.services.orchestrator.models import FileAttachment

        # Valid progress
        data = {**old_format_attachment, "upload_progress": 50.0}
        att = FileAttachment(**data)
        assert att.upload_progress == 50.0

        # Out of bounds
        data = {**old_format_attachment, "upload_progress": 150.0}
        with pytest.raises(ValidationError):
            FileAttachment(**data)

        data = {**old_format_attachment, "upload_progress": -10.0}
        with pytest.raises(ValidationError):
            FileAttachment(**data)

    def test_serialization_roundtrip(self, full_format_attachment):
        """Model should serialize and deserialize correctly."""
        from brain_researcher.services.orchestrator.models import FileAttachment

        att = FileAttachment(**full_format_attachment)
        json_data = att.model_dump_json()
        restored = FileAttachment.model_validate_json(json_data)

        assert restored.id == att.id
        assert restored.storage == att.storage
        assert restored.checksum == att.checksum
        assert restored.path == att.path

    def test_model_dump_excludes_none_by_default(self, old_format_attachment):
        """Serialization should handle None fields correctly."""
        from brain_researcher.services.orchestrator.models import FileAttachment

        att = FileAttachment(**old_format_attachment)
        dump = att.model_dump(exclude_none=True)

        # New fields should not appear when None and exclude_none=True
        assert "storage" not in dump
        assert "path" not in dump
        assert "checksum" not in dump
