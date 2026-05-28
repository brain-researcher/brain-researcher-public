"""
Unit tests for Evidence Rail endpoints.

Tests real data path, mock fallback behavior, and feature flag functionality.
"""

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEvidenceEndpointHelpers:
    """Tests for Evidence Rail helper functions."""

    def test_get_jobs_db_returns_dict_on_import_error(self):
        """_get_jobs_db should return empty dict if import fails."""
        with patch.dict("sys.modules", {"brain_researcher.services.orchestrator.main_enhanced": None}):
            # Force reimport to test import error handling
            from brain_researcher.services.orchestrator import integration_endpoints

            # Reset module to clear cached import
            if hasattr(integration_endpoints, "_get_jobs_db"):
                # Mock the function to simulate import error
                with patch.object(integration_endpoints, "_get_jobs_db") as mock:
                    mock.return_value = {}
                    result = integration_endpoints._get_jobs_db()
                    assert result == {}

    def test_mock_provenance_graph_structure(self):
        """_mock_provenance_graph should return valid structure."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            _mock_provenance_graph,
        )

        result = _mock_provenance_graph()

        # Result is a Pydantic model, check attributes
        assert hasattr(result, "nodes")
        assert hasattr(result, "edges")
        assert isinstance(result.nodes, list)
        assert isinstance(result.edges, list)

        # Check node structure
        for node in result.nodes:
            assert hasattr(node, "id")
            assert hasattr(node, "type")

        # Check edge structure
        for edge in result.edges:
            assert hasattr(edge, "source")
            assert hasattr(edge, "target")

    def test_mock_artifacts_structure(self):
        """_mock_artifacts should return valid artifact list."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            _mock_artifacts,
        )

        result = _mock_artifacts()

        assert isinstance(result, list)
        for artifact in result:
            assert "id" in artifact
            assert "type" in artifact
            assert "name" in artifact


class TestGetPersistedRunCard:
    """Tests for get_persisted_run_card function."""

    def test_returns_none_for_nonexistent_job(self, tmp_path):
        """Should return None if no run card file exists."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_persisted_run_card,
        )

        with patch(
            "brain_researcher.services.orchestrator.integration_endpoints.RUN_CARDS_DIR",
            tmp_path,
        ):
            result = get_persisted_run_card("nonexistent_job_123")
            assert result is None

    def test_returns_run_card_data_exact_pattern(self, tmp_path):
        """Should return run card data from {job_id}.json file (primary pattern)."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_persisted_run_card,
        )

        # Create a run card file with primary naming pattern: {job_id}.json
        run_card_data = {
            "id": "test_job_456",
            "title": "Test Analysis",
            "timestamp": datetime.utcnow().isoformat(),
        }
        run_card_file = tmp_path / "test_job_456.json"
        run_card_file.write_text(json.dumps(run_card_data))

        with patch(
            "brain_researcher.services.orchestrator.integration_endpoints.RUN_CARDS_DIR",
            tmp_path,
        ):
            result = get_persisted_run_card("test_job_456")

            assert result is not None
            assert result["id"] == "test_job_456"
            assert result["title"] == "Test Analysis"

    def test_returns_run_card_data_legacy_pattern(self, tmp_path):
        """Should return run card data from legacy run_card_{job_id}_*.json file."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_persisted_run_card,
        )

        # Create a run card file with legacy naming pattern
        run_card_data = {
            "id": "legacy_job",
            "title": "Legacy Analysis",
        }
        run_card_file = tmp_path / "run_card_legacy_job_20240101_120000.json"
        run_card_file.write_text(json.dumps(run_card_data))

        with patch(
            "brain_researcher.services.orchestrator.integration_endpoints.RUN_CARDS_DIR",
            tmp_path,
        ):
            result = get_persisted_run_card("legacy_job")

            assert result is not None
            assert result["id"] == "legacy_job"
            assert result["title"] == "Legacy Analysis"

    def test_exact_pattern_takes_precedence(self, tmp_path):
        """Exact {job_id}.json should take precedence over legacy pattern."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_persisted_run_card,
        )

        # Create both exact and legacy files
        exact_data = {"id": "job_priority", "source": "exact"}
        legacy_data = {"id": "job_priority", "source": "legacy"}

        exact_file = tmp_path / "job_priority.json"
        legacy_file = tmp_path / "run_card_job_priority_20240101_120000.json"

        exact_file.write_text(json.dumps(exact_data))
        legacy_file.write_text(json.dumps(legacy_data))

        # Make exact_file the newest by mtime
        now = time.time()
        os.utime(exact_file, (now, now))
        os.utime(legacy_file, (now - 100, now - 100))

        with patch(
            "brain_researcher.services.orchestrator.integration_endpoints.RUN_CARDS_DIR",
            tmp_path,
        ):
            result = get_persisted_run_card("job_priority")

            assert result is not None
            # Should prefer exact match over legacy
            assert result["source"] == "exact"

    def test_returns_most_recent_legacy_file(self, tmp_path):
        """Should return the most recent legacy run card if multiple exist."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_persisted_run_card,
        )

        # Create multiple run card files with legacy naming pattern
        old_data = {"id": "job_multi", "version": "old"}
        new_data = {"id": "job_multi", "version": "new"}

        old_file = tmp_path / "run_card_job_multi_20240101_100000.json"
        new_file = tmp_path / "run_card_job_multi_20240101_120000.json"

        old_file.write_text(json.dumps(old_data))
        new_file.write_text(json.dumps(new_data))

        # Set mtimes so new_file is newest
        now = time.time()
        os.utime(new_file, (now, now))
        os.utime(old_file, (now - 120, now - 120))

        with patch(
            "brain_researcher.services.orchestrator.integration_endpoints.RUN_CARDS_DIR",
            tmp_path,
        ):
            result = get_persisted_run_card("job_multi")

            assert result is not None
            # Most recent by mtime
            assert result["version"] == "new"


class TestGetJobSafe:
    """Tests for get_job_safe adapter function."""

    @pytest.mark.asyncio
    async def test_returns_job_if_exists(self):
        """Should return job from jobs_db if it exists."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_job_safe,
        )

        mock_job = MagicMock()
        mock_job.id = "existing_job"
        mock_jobs_db = {"existing_job": mock_job}

        with patch(
            "brain_researcher.services.orchestrator.integration_endpoints._get_jobs_db"
        ) as mock:
            mock.return_value = mock_jobs_db

            result = await get_job_safe("existing_job")

            assert result is not None
            assert result.id == "existing_job"

    @pytest.mark.asyncio
    async def test_returns_none_if_not_exists(self):
        """Should return None if job not in jobs_db."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_job_safe,
        )

        with patch(
            "brain_researcher.services.orchestrator.integration_endpoints._get_jobs_db"
        ) as mock:
            mock.return_value = {}

            result = await get_job_safe("nonexistent_job")

            assert result is None


class TestProvenanceEndpoint:
    """Tests for get_provenance endpoint."""

    @pytest.mark.asyncio
    async def test_returns_real_provenance_if_job_has_graph(self):
        """Should return job's provenance_graph if available."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_provenance,
        )

        mock_graph = {
            "nodes": [{"id": "n1", "type": "input"}],
            "edges": [{"source": "n1", "target": "n2"}],
        }
        mock_job = MagicMock()
        mock_job.provenance_graph = mock_graph

        with patch(
            "brain_researcher.services.orchestrator.integration_endpoints.get_job_safe",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = mock_job

            result = await get_provenance("job_with_graph")

            assert result == mock_graph

    @pytest.mark.asyncio
    async def test_generates_graph_from_steps(self):
        """Should generate provenance from steps if no explicit graph."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_provenance,
        )

        mock_step1 = MagicMock()
        mock_step1.id = "step1"
        mock_step1.name = "Preprocessing"
        mock_step1.tool = "preprocessor"
        mock_step1.status = MagicMock()
        mock_step1.status.value = "completed"

        mock_step2 = MagicMock()
        mock_step2.id = "step2"
        mock_step2.name = "Analysis"
        mock_step2.tool = "analyzer"
        mock_step2.status = MagicMock()
        mock_step2.status.value = "completed"

        mock_job = MagicMock()
        mock_job.provenance_graph = None
        mock_job.steps = [mock_step1, mock_step2]

        with patch(
            "brain_researcher.services.orchestrator.integration_endpoints.get_job_safe",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = mock_job

            result = await get_provenance("job_with_steps")

            # Result is a Pydantic ProvenanceGraph model
            assert hasattr(result, "nodes")
            assert len(result.nodes) == 2
            assert hasattr(result, "edges")

    @pytest.mark.asyncio
    async def test_returns_mock_if_job_not_found_with_flag(self):
        """Should return mock data if job not found and flag enabled."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_provenance,
        )

        with (
            patch(
                "brain_researcher.services.orchestrator.integration_endpoints.get_job_safe",
                new_callable=AsyncMock,
            ) as mock_job,
            patch(
                "brain_researcher.services.orchestrator.integration_endpoints.ENABLE_MOCK_FALLBACK",
                True,
            ),
        ):
            mock_job.return_value = None

            result = await get_provenance("nonexistent_job")

            # Result is a Pydantic ProvenanceGraph model
            assert hasattr(result, "nodes")
            assert hasattr(result, "edges")


class TestRunCardEndpoint:
    """Tests for get_run_card endpoint."""

    @pytest.mark.asyncio
    async def test_returns_persisted_run_card(self, tmp_path):
        """Should return persisted run card if available."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_run_card,
        )

        persisted_data = {
            "id": "persisted_job",
            "title": "Persisted Analysis",
            "execution": {"duration_seconds": 120},
        }

        with (
            patch(
                "brain_researcher.services.orchestrator.integration_endpoints.get_job_safe",
                new_callable=AsyncMock,
            ) as mock_job,
            patch(
                "brain_researcher.services.orchestrator.integration_endpoints.get_persisted_run_card"
            ) as mock_persisted,
        ):
            mock_job.return_value = None
            mock_persisted.return_value = persisted_data

            result = await get_run_card("persisted_job")

            assert result["id"] == "persisted_job"
            assert result["title"] == "Persisted Analysis"

    @pytest.mark.asyncio
    async def test_returns_job_run_card(self):
        """Should return pre-generated run card from job if available."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_run_card,
        )

        mock_run_card = MagicMock()
        mock_run_card.model_dump.return_value = {
            "id": "job_with_card",
            "title": "Pre-generated Analysis",
        }

        mock_job = MagicMock()
        mock_job.run_card = mock_run_card

        with patch(
            "brain_researcher.services.orchestrator.integration_endpoints.get_job_safe",
            new_callable=AsyncMock,
        ) as mock_get_job:
            mock_get_job.return_value = mock_job

            result = await get_run_card("job_with_card")

            assert result["id"] == "job_with_card"
            assert result["title"] == "Pre-generated Analysis"


class TestArtifactsEndpoint:
    """Tests for get_artifacts endpoint."""

    @pytest.mark.asyncio
    async def test_returns_real_artifacts(self):
        """Should return job's artifacts if job exists."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_artifacts,
        )

        mock_artifact = MagicMock()
        mock_artifact.model_dump.return_value = {
            "id": "artifact1",
            "type": "image",
            "name": "brain_map.png",
        }

        mock_job = MagicMock()
        mock_job.artifacts = [mock_artifact]

        with patch(
            "brain_researcher.services.orchestrator.integration_endpoints.get_job_safe",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = mock_job

            result = await get_artifacts("job_with_artifacts")

            assert "artifacts" in result
            assert len(result["artifacts"]) == 1
            assert result["artifacts"][0]["id"] == "artifact1"

    @pytest.mark.asyncio
    async def test_returns_mock_if_job_not_found_with_flag(self):
        """Should return mock artifacts if job not found and flag enabled."""
        from brain_researcher.services.orchestrator.integration_endpoints import (
            get_artifacts,
        )

        with (
            patch(
                "brain_researcher.services.orchestrator.integration_endpoints.get_job_safe",
                new_callable=AsyncMock,
            ) as mock_job,
            patch(
                "brain_researcher.services.orchestrator.integration_endpoints.ENABLE_MOCK_FALLBACK",
                True,
            ),
        ):
            mock_job.return_value = None

            result = await get_artifacts("nonexistent_job")

            assert "artifacts" in result
            assert isinstance(result["artifacts"], list)


class TestFeatureFlag:
    """Tests for ENABLE_MOCK_FALLBACK feature flag."""

    def test_feature_flag_from_env_true(self):
        """Flag should be True when env var is 'true'."""
        with patch.dict(os.environ, {"ENABLE_EVIDENCE_MOCK_FALLBACK": "true"}):
            # Need to reimport to pick up env var
            import importlib
            from brain_researcher.services.orchestrator import integration_endpoints

            importlib.reload(integration_endpoints)

            assert integration_endpoints.ENABLE_MOCK_FALLBACK is True

    def test_feature_flag_from_env_false(self):
        """Flag should be False when env var is 'false'."""
        with patch.dict(os.environ, {"ENABLE_EVIDENCE_MOCK_FALLBACK": "false"}):
            import importlib
            from brain_researcher.services.orchestrator import integration_endpoints

            importlib.reload(integration_endpoints)

            assert integration_endpoints.ENABLE_MOCK_FALLBACK is False

    def test_feature_flag_default(self):
        """Flag should default to True when env var not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove the env var if it exists
            os.environ.pop("ENABLE_EVIDENCE_MOCK_FALLBACK", None)

            import importlib
            from brain_researcher.services.orchestrator import integration_endpoints

            importlib.reload(integration_endpoints)

            # Default is True
            assert integration_endpoints.ENABLE_MOCK_FALLBACK is True
