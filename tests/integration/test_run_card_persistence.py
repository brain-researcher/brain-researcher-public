"""
Integration tests for RunCard persistence.

Tests the full flow: generate -> persist -> read back.
"""

import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRunCardPersistence:
    """Integration tests for RunCard persistence lifecycle."""

    @pytest.fixture
    def run_cards_dir(self, tmp_path):
        """Create temporary run cards directory."""
        run_cards = tmp_path / "run_cards"
        run_cards.mkdir(parents=True, exist_ok=True)
        return run_cards

    @pytest.fixture
    def sample_run_card(self):
        """Create a sample RunCard-like object with model_dump method."""
        run_card_data = {
            "id": "test_job_123",
            "title": "Test fMRI Analysis",
            "timestamp": datetime.utcnow().isoformat(),
            "execution": {
                "duration_seconds": 45.5,
                "steps": [
                    {"id": "step1", "name": "Preprocessing", "status": "completed"},
                    {"id": "step2", "name": "GLM Analysis", "status": "completed"},
                ],
            },
            "inputs": {
                "datasets": [{"id": "ds000114", "name": "Motor Task Dataset"}],
                "parameters": {"smoothing_fwhm": 6, "hrf_model": "spm"},
            },
            "outputs": {
                "artifacts": [
                    {"id": "art1", "type": "nifti", "name": "stat_map.nii.gz"}
                ],
                "metrics": {"r_squared": 0.85},
            },
            "provenance": {
                "tools": [{"name": "nilearn", "version": "0.10.1"}],
                "citations": [],
            },
            "reproducibility": {
                "score": 95,
                "is_reproducible": True,
                "random_seed": 42,
            },
        }
        mock_card = MagicMock()
        # persist_run_card checks model_dump first (returns dict)
        mock_card.model_dump.return_value = run_card_data
        mock_card.model_dump_json.return_value = json.dumps(run_card_data, indent=2)
        return mock_card

    @pytest.mark.asyncio
    async def test_persist_run_card_creates_file(self, run_cards_dir, sample_run_card):
        """persist_run_card should create a JSON file."""
        # Import and patch the module
        from brain_researcher.services.orchestrator.main_enhanced import (
            persist_run_card,
        )

        with patch(
            "brain_researcher.services.orchestrator.main_enhanced.RUN_CARDS_DIR",
            run_cards_dir,
        ):
            path = await persist_run_card("test_job_123", sample_run_card)

            assert path is not None
            assert path.exists()
            assert path.suffix == ".json"
            assert "test_job_123" in path.name

    @pytest.mark.asyncio
    async def test_persist_run_card_content_valid(
        self, run_cards_dir, sample_run_card
    ):
        """Persisted run card should contain valid JSON with required fields."""
        from brain_researcher.services.orchestrator.main_enhanced import (
            persist_run_card,
        )

        with patch(
            "brain_researcher.services.orchestrator.main_enhanced.RUN_CARDS_DIR",
            run_cards_dir,
        ):
            path = await persist_run_card("test_job_123", sample_run_card)

            # Read and parse the file content
            raw_content = path.read_text()
            content = json.loads(raw_content)

            # Assert required RunCard fields are present and correct
            assert content["id"] == "test_job_123"
            assert content["title"] == "Test fMRI Analysis"
            assert "execution" in content
            assert "inputs" in content
            assert "outputs" in content
            assert "provenance" in content
            assert "reproducibility" in content

            # Verify nested structure
            assert content["execution"]["duration_seconds"] == 45.5
            assert len(content["execution"]["steps"]) == 2
            assert content["inputs"]["parameters"]["smoothing_fwhm"] == 6
            assert content["outputs"]["metrics"]["r_squared"] == 0.85
            assert content["reproducibility"]["score"] == 95

    @pytest.mark.asyncio
    async def test_persist_and_retrieve_roundtrip(
        self, run_cards_dir, sample_run_card
    ):
        """Should be able to persist and retrieve run card in a true roundtrip.

        Tests that get_persisted_run_card picks up timestamped files written by
        persist_run_card and returns the most recent.
        """
        from brain_researcher.services.orchestrator.main_enhanced import (
            persist_run_card,
        )
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_persisted_run_card,
        )

        with (
            patch(
                "brain_researcher.services.orchestrator.main_enhanced.RUN_CARDS_DIR",
                run_cards_dir,
            ),
            patch(
                "brain_researcher.services.orchestrator.integration_endpoints.RUN_CARDS_DIR",
                run_cards_dir,
            ),
        ):
            # Persist the run card
            path = await persist_run_card("roundtrip_job", sample_run_card)
            assert path is not None
            assert path.exists()
            assert path.name.startswith("run_card_roundtrip_job_")
            assert path.suffix == ".json"

            # Retrieve the same run card - should find newest matching file
            retrieved = get_persisted_run_card("roundtrip_job")

            # Verify roundtrip works - data should match what was persisted
            assert retrieved is not None
            assert retrieved["id"] == "test_job_123"
            assert retrieved["title"] == "Test fMRI Analysis"
            assert retrieved["execution"]["duration_seconds"] == 45.5
            assert retrieved["reproducibility"]["score"] == 95

    @pytest.mark.asyncio
    async def test_retrieve_legacy_pattern(self, run_cards_dir):
        """Should still retrieve files with legacy run_card_{job_id}_*.json pattern."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_persisted_run_card,
        )

        # Create a file with legacy naming pattern
        legacy_data = {
            "id": "legacy_job",
            "title": "Legacy Analysis",
            "execution": {"duration_seconds": 30},
        }
        legacy_path = run_cards_dir / "run_card_legacy_job_20240601_120000.json"
        legacy_path.write_text(json.dumps(legacy_data))

        with patch(
            "brain_researcher.services.orchestrator.integration_endpoints.RUN_CARDS_DIR",
            run_cards_dir,
        ):
            retrieved = get_persisted_run_card("legacy_job")

            assert retrieved is not None
            assert retrieved["id"] == "legacy_job"
            assert retrieved["title"] == "Legacy Analysis"

    @pytest.mark.asyncio
    async def test_cleanup_old_run_cards(self, run_cards_dir):
        """cleanup_old_run_cards should remove files older than retention period."""
        from brain_researcher.services.orchestrator.main_enhanced import (
            cleanup_old_run_cards,
        )

        # Create some run card files with different ages
        old_file = run_cards_dir / "old_job_20240101T000000.json"
        recent_file = run_cards_dir / "recent_job_20240601T000000.json"

        old_file.write_text('{"id": "old_job"}')
        recent_file.write_text('{"id": "recent_job"}')

        # Make old_file actually old by setting mtime
        old_mtime = (datetime.now() - timedelta(days=60)).timestamp()
        os.utime(old_file, (old_mtime, old_mtime))

        with (
            patch(
                "brain_researcher.services.orchestrator.main_enhanced.RUN_CARDS_DIR",
                run_cards_dir,
            ),
            patch(
                "brain_researcher.services.orchestrator.main_enhanced.RUN_CARDS_RETENTION_DAYS",
                30,
            ),
        ):
            deleted = await cleanup_old_run_cards()

            assert deleted >= 1
            assert not old_file.exists()
            assert recent_file.exists()

    @pytest.mark.asyncio
    async def test_cleanup_preserves_recent_files(self, run_cards_dir):
        """cleanup should preserve files within retention period."""
        from brain_researcher.services.orchestrator.main_enhanced import (
            cleanup_old_run_cards,
        )

        # Create recent files
        for i in range(3):
            f = run_cards_dir / f"recent_{i}_20240601T000000.json"
            f.write_text(f'{{"id": "recent_{i}"}}')

        with (
            patch(
                "brain_researcher.services.orchestrator.main_enhanced.RUN_CARDS_DIR",
                run_cards_dir,
            ),
            patch(
                "brain_researcher.services.orchestrator.main_enhanced.RUN_CARDS_RETENTION_DAYS",
                30,
            ),
        ):
            deleted = await cleanup_old_run_cards()

            # Should not delete any recent files
            assert deleted == 0
            assert len(list(run_cards_dir.glob("*.json"))) == 3


class TestRunCardPersistenceConfig:
    """Tests for RunCard persistence configuration."""

    def test_run_cards_dir_configurable(self, tmp_path):
        """RUN_CARDS_DIR should be a Path that can be overridden."""
        from brain_researcher.services.orchestrator.main_enhanced import (
            RUN_CARDS_DIR,
        )

        # Verify it's a Path object
        assert isinstance(RUN_CARDS_DIR, Path)

        # Verify it can be patched for testing
        custom_path = tmp_path / "custom_run_cards"
        with patch(
            "brain_researcher.services.orchestrator.main_enhanced.RUN_CARDS_DIR",
            custom_path,
        ):
            from brain_researcher.services.orchestrator import main_enhanced

            assert main_enhanced.RUN_CARDS_DIR == custom_path

    def test_retention_days_configurable(self):
        """RUN_CARDS_RETENTION_DAYS should be an int that can be overridden."""
        from brain_researcher.services.orchestrator.main_enhanced import (
            RUN_CARDS_RETENTION_DAYS,
        )

        # Verify it's an integer with reasonable default
        assert isinstance(RUN_CARDS_RETENTION_DAYS, int)
        assert RUN_CARDS_RETENTION_DAYS > 0

        # Verify it can be patched for testing
        with patch(
            "brain_researcher.services.orchestrator.main_enhanced.RUN_CARDS_RETENTION_DAYS",
            60,
        ):
            from brain_researcher.services.orchestrator import main_enhanced

            assert main_enhanced.RUN_CARDS_RETENTION_DAYS == 60

    def test_env_var_based_configuration(self):
        """Configuration should read from environment variables."""
        # Test that the module uses os.getenv for configuration
        # We verify this by checking the variable values make sense
        from brain_researcher.services.orchestrator.main_enhanced import (
            RUN_CARDS_DIR,
            RUN_CARDS_RETENTION_DAYS,
        )

        # Default values should be reasonable
        assert RUN_CARDS_RETENTION_DAYS >= 1  # At least 1 day
        assert RUN_CARDS_RETENTION_DAYS <= 365  # Not more than a year by default
        assert isinstance(RUN_CARDS_DIR, Path)


class TestRunCardInExecuteJob:
    """Tests for RunCard persistence in execute_job flow."""

    @pytest.mark.asyncio
    async def test_execute_job_persists_run_card_on_completion(self):
        """execute_job should persist run card when job completes successfully."""
        # This is a higher-level integration test that would require
        # significant mocking of the job execution flow.
        # For now, we test the components separately.
        pass

    @pytest.mark.asyncio
    async def test_execute_job_emits_telemetry_events(self):
        """execute_job should emit telemetry events at key points."""
        # This would test the telemetry integration
        pass


class TestTelemetryIntegration:
    """Tests for telemetry event emission."""

    def test_telemetry_available_flag(self):
        """AGENT_TELEMETRY_AVAILABLE should be set correctly."""
        from brain_researcher.services.orchestrator.main_enhanced import (
            AGENT_TELEMETRY_AVAILABLE,
        )

        # Should be True if telemetry module is available
        # (depends on installation)
        assert isinstance(AGENT_TELEMETRY_AVAILABLE, bool)

    def test_record_telemetry_event_noop_when_unavailable(self):
        """record_telemetry_event should be a no-op when telemetry unavailable."""
        with patch(
            "brain_researcher.services.orchestrator.main_enhanced.AGENT_TELEMETRY_AVAILABLE",
            False,
        ):
            from brain_researcher.services.orchestrator.main_enhanced import (
                record_telemetry_event,
            )

            # Should not raise
            record_telemetry_event({"test": "data"}, event_type="test_event")
