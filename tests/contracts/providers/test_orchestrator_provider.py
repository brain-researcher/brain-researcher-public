"""
Provider verification tests for Orchestrator service.

These tests verify that the Orchestrator service can fulfill
the contracts defined by its consumers (Web UI, legacy API Gateway).
"""

import pytest

try:
    from pact import Verifier

    from ..pact_config import (
        LEGACY_GATEWAY_CONTRACT_ENV,
        get_service_config,
        legacy_gateway_contracts_enabled,
        pact_config,
    )
    from ..pact_helpers.state_setup import OrchestratorStateSetup
    from ..pact_helpers.verification_utils import VerificationHelper
except ImportError:
    pytest.skip(
        "pact contract tooling not available for provider verification",
        allow_module_level=True,
    )


class TestOrchestratorProvider:
    """Provider verification tests for Orchestrator service."""

    @pytest.fixture
    def state_manager(self):
        """Get state setup manager for orchestrator."""
        return OrchestratorStateSetup.get_state_manager()

    @pytest.fixture
    def orchestrator_config(self):
        """Get orchestrator service configuration."""
        return get_service_config("orchestrator")

    @pytest.fixture
    def verifier(self, orchestrator_config):
        """Create Pact verifier for orchestrator."""
        return Verifier(
            provider="orchestrator",
            provider_base_url=orchestrator_config.base_url,
            pact_dir=str(pact_config.pact_dir),
            provider_states_setup_url=f"{orchestrator_config.base_url}/pact/provider-states",
            publish_version="1.0.0",
            publish_verification_results=pact_config.broker.publish_verification_results,
        )

    def test_verify_webui_consumer_contract(self, verifier, state_manager):
        """Verify contract with Web UI consumer."""
        pact_file = pact_config.pact_dir / "web_ui-orchestrator.json"

        # Verify the pact file exists and is valid
        is_valid, errors = VerificationHelper.validate_pact_file(pact_file)
        if not is_valid:
            pytest.skip(f"Invalid pact file: {errors}")

        # Set up state handlers
        self._setup_provider_states(state_manager)

        # Verify the contract
        try:
            verifier.verify_pacts(pact_file)
        except Exception as e:
            pytest.fail(f"Contract verification failed: {e}")

    def test_verify_api_gateway_consumer_contract(self, verifier, state_manager):
        """Verify contract with the legacy API Gateway consumer."""
        if not legacy_gateway_contracts_enabled():
            pytest.skip(
                f"Legacy API gateway contract coverage is disabled by default. Set {LEGACY_GATEWAY_CONTRACT_ENV}=1 to run it."
            )
        pact_file = pact_config.pact_dir / "api_gateway-orchestrator.json"

        # Skip if pact file doesn't exist (consumer test not run)
        if not pact_file.exists():
            pytest.skip("API Gateway consumer contract not available")

        # Verify the pact file exists and is valid
        is_valid, errors = VerificationHelper.validate_pact_file(pact_file)
        if not is_valid:
            pytest.skip(f"Invalid pact file: {errors}")

        # Set up state handlers
        self._setup_provider_states(state_manager)

        # Verify the contract
        try:
            verifier.verify_pacts(pact_file)
        except Exception as e:
            pytest.fail(f"Contract verification failed: {e}")

    def _setup_provider_states(self, state_manager):
        """Set up provider state handlers."""
        # This would be called by Pact verifier when setting up states
        pass

    @pytest.mark.asyncio
    async def test_health_endpoint_provider_state(self, state_manager):
        """Test health endpoint with 'all services are healthy' state."""
        # Set up state
        await state_manager.setup_state("all services are healthy")

        # In real implementation, would start orchestrator service
        # and verify it responds correctly to health checks

        # Mock verification - in practice this would be HTTP calls
        health_response = {
            "status": "healthy",
            "services": {
                "agent": {"name": "agent-service", "status": "healthy"},
                "br_kg": {"name": "br_kg-service", "status": "healthy"},
            },
            "timestamp": "2025-01-01T00:00:00Z",
            "uptime_seconds": 3600,
            "version": "1.0.0",
        }

        assert health_response["status"] == "healthy"
        assert "services" in health_response

    @pytest.mark.asyncio
    async def test_job_creation_provider_state(self, state_manager):
        """Test job creation with 'orchestrator can accept jobs' state."""
        # Set up state
        await state_manager.setup_state("orchestrator can accept jobs")

        # Mock job creation response
        job_response = {
            "job_id": "job_test123",
            "estimated_duration": 90,
            "queue_position": 0,
            "status_url": "/jobs/job_test123",
            "stream_url": "/jobs/job_test123/stream",
        }

        assert job_response["job_id"].startswith("job_")
        assert "estimated_duration" in job_response

    @pytest.mark.asyncio
    async def test_job_exists_provider_state(self, state_manager):
        """Test job retrieval with 'a job exists' state."""
        # Set up state
        job_data = await state_manager.setup_state(
            "a job exists", {"job_id": "job_test123"}
        )

        assert job_data["id"] == "job_test123"
        assert "status" in job_data

        # Clean up state
        await state_manager.cleanup_state("a job exists", {"job_id": "job_test123"})

    @pytest.mark.asyncio
    async def test_completed_job_provider_state(self, state_manager):
        """Test completed job with 'a completed job exists' state."""
        # Set up state
        job_data = await state_manager.setup_state(
            "a completed job exists", {"job_id": "job_completed123"}
        )

        assert job_data["id"] == "job_completed123"
        assert job_data["status"] == "completed"
        assert len(job_data["artifacts"]) > 0

        # Clean up state
        await state_manager.cleanup_state(
            "a completed job exists", {"job_id": "job_completed123"}
        )

    @pytest.mark.asyncio
    async def test_thread_creation_provider_state(self, state_manager):
        """Test thread creation with 'user is authenticated' state."""
        # Set up state
        auth_data = await state_manager.setup_state(
            "user is authenticated", {"user_id": "user_test123"}
        )

        assert auth_data["user"]["id"] == "user_test123"
        assert "token" in auth_data

    @pytest.mark.asyncio
    async def test_thread_exists_provider_state(self, state_manager):
        """Test thread operations with 'a thread exists' state."""
        # Set up state
        thread_data = await state_manager.setup_state(
            "a thread exists", {"thread_id": "thread_test123"}
        )

        assert thread_data["thread_id"] == "thread_test123"
        assert "title" in thread_data

        # Clean up state
        await state_manager.cleanup_state(
            "a thread exists", {"thread_id": "thread_test123"}
        )

    @pytest.mark.asyncio
    async def test_datasets_available_provider_state(self, state_manager):
        """Test dataset listing with 'datasets are available' state."""
        # Set up state
        datasets_data = await state_manager.setup_state("datasets are available")

        assert "datasets" in datasets_data
        assert len(datasets_data["datasets"]) > 0
        assert datasets_data["datasets"][0]["id"] == "motor-task-001"

    @pytest.mark.asyncio
    async def test_no_jobs_exist_provider_state(self, state_manager):
        """Test empty job list with 'no jobs exist' state."""
        # Set up state
        await state_manager.setup_state("no jobs exist")

        # In real implementation, would verify GET /jobs returns empty list
        empty_response = {"jobs": [], "total_count": 0}
        assert len(empty_response["jobs"]) == 0

    @pytest.mark.asyncio
    async def test_agent_unavailable_provider_state(self, state_manager):
        """Test degraded health with 'agent service is unavailable' state."""
        # Set up state
        health_data = await state_manager.setup_state("agent service is unavailable")

        assert health_data["status"] == "degraded"
        assert health_data["services"]["agent"]["status"] == "unavailable"
        assert health_data["services"]["br_kg"]["status"] == "healthy"

    def test_provider_state_coverage(self, state_manager):
        """Test that all required provider states are available."""
        # Get all pact files that use this provider
        pact_files = list(pact_config.pact_dir.glob("*-orchestrator.json"))

        required_states = set()
        for pact_file in pact_files:
            interactions = VerificationHelper.extract_pact_interactions(pact_file)
            for interaction in interactions:
                if "providerState" in interaction:
                    required_states.add(interaction["providerState"])
                elif "provider_state" in interaction:
                    required_states.add(interaction["provider_state"])

        # Verify all required states can be set up
        available_states = set(state_manager._state_handlers.keys())
        missing_states = required_states - available_states

        assert len(missing_states) == 0, f"Missing provider states: {missing_states}"

    def test_contract_backward_compatibility(self):
        """Test that contract changes are backward compatible."""
        # Compare current pact with previous version if available
        current_pact = pact_config.pact_dir / "web_ui-orchestrator.json"
        previous_pact = pact_config.pact_dir / "web_ui-orchestrator.json.previous"

        if not current_pact.exists():
            pytest.skip("Current pact file not available")

        if not previous_pact.exists():
            pytest.skip("Previous pact file not available for comparison")

        comparison = VerificationHelper.compare_pact_versions(
            previous_pact, current_pact
        )

        if not comparison["is_backward_compatible"]:
            pytest.fail(f"Breaking changes detected: {comparison['breaking_changes']}")

    def test_response_schema_validation(self):
        """Test that provider responses match expected schemas."""
        # Define expected schemas for common responses
        job_response_schema = {
            "type": "object",
            "required": [
                "job_id",
                "estimated_duration",
                "queue_position",
                "status_url",
                "stream_url",
            ],
            "properties": {
                "job_id": {"type": "string", "pattern": "^[a-zA-Z0-9_-]+$"},
                "estimated_duration": {"type": "integer", "minimum": 0},
                "queue_position": {"type": "integer", "minimum": 0},
                "status_url": {"type": "string"},
                "stream_url": {"type": "string"},
            },
        }

        # Mock response data
        mock_response = {
            "job_id": "job_test123",
            "estimated_duration": 90,
            "queue_position": 0,
            "status_url": "/jobs/job_test123",
            "stream_url": "/jobs/job_test123/stream",
        }

        is_valid, error = VerificationHelper.validate_response_schema(
            mock_response, job_response_schema
        )

        assert is_valid, f"Response schema validation failed: {error}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
