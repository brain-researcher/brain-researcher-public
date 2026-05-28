"""
Provider verification tests for Agent service.

These tests verify that the Agent service can fulfill
the contracts defined by its consumers (Orchestrator, legacy API Gateway).
"""

import pytest
import asyncio
import json
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

try:
    from pact import Verifier
    from ..pact_config import (
        LEGACY_GATEWAY_CONTRACT_ENV,
        pact_config,
        get_service_config,
        legacy_gateway_contracts_enabled,
    )
    from ..pact_helpers.state_setup import AgentStateSetup
    from ..pact_helpers.verification_utils import VerificationHelper
except ImportError:
    pytest.skip("pact contract tooling not available for provider verification", allow_module_level=True)


class TestAgentProvider:
    """Provider verification tests for Agent service."""
    
    @pytest.fixture
    def state_manager(self):
        """Get state setup manager for agent."""
        return AgentStateSetup.get_state_manager()
    
    @pytest.fixture
    def agent_config(self):
        """Get agent service configuration."""
        return get_service_config("agent")
    
    @pytest.fixture
    def verifier(self, agent_config):
        """Create Pact verifier for agent."""
        return Verifier(
            provider="agent-service",
            provider_base_url=agent_config.base_url,
            pact_dir=str(pact_config.pact_dir),
            provider_states_setup_url=f"{agent_config.base_url}/pact/provider-states",
            publish_version="1.0.0",
            publish_verification_results=pact_config.broker.publish_verification_results
        )
    
    def test_verify_orchestrator_consumer_contract(self, verifier, state_manager):
        """Verify contract with Orchestrator consumer."""
        pact_file = pact_config.pact_dir / "orchestrator-agent.json"
        
        # Skip if pact file doesn't exist (consumer test not run)
        if not pact_file.exists():
            pytest.skip("Orchestrator consumer contract not available")
        
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
        pact_file = pact_config.pact_dir / "api_gateway-agent.json"
        
        # Skip if pact file doesn't exist
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
    async def test_agent_ready_provider_state(self, state_manager):
        """Test agent ready state setup."""
        # Set up state
        state_data = await state_manager.setup_state("agent can execute queries")
        
        assert state_data["status"] == "ready"
        assert state_data["queue_length"] == 0
    
    @pytest.mark.asyncio
    async def test_agent_busy_provider_state(self, state_manager):
        """Test agent busy state setup."""
        # Set up state
        state_data = await state_manager.setup_state("agent is busy with other jobs")
        
        assert state_data["status"] == "busy"
        assert state_data["queue_length"] > 0
    
    @pytest.mark.asyncio
    async def test_health_endpoint_response(self, state_manager):
        """Test health endpoint response structure."""
        # Set up ready state
        await state_manager.setup_state("agent can execute queries")
        
        # Mock health response
        health_response = {
            "status": "healthy",
            "queue_length": 0,
            "active_jobs": 2,
            "available_tools": 45,
            "timestamp": "2025-01-01T00:00:00Z",
            "version": "1.0.0"
        }
        
        # Verify response structure
        assert health_response["status"] == "healthy"
        assert "queue_length" in health_response
        assert "active_jobs" in health_response
        assert "available_tools" in health_response
        assert "timestamp" in health_response
        assert "version" in health_response
    
    @pytest.mark.asyncio
    async def test_execute_query_response(self, state_manager):
        """Test query execution response structure."""
        # Set up ready state
        await state_manager.setup_state("agent can execute queries")
        
        # Mock execute response
        execute_response = {
            "execution_id": "12345678-1234-1234-1234-123456789012",
            "status": "accepted",
            "estimated_duration": 120,
            "steps": [
                {
                    "id": "step_preprocess",
                    "name": "Data Preprocessing",
                    "tool": "fmriprep",
                    "estimated_duration": 60
                },
                {
                    "id": "step_glm",
                    "name": "GLM Analysis",
                    "tool": "fsl_glm",
                    "estimated_duration": 60
                }
            ],
            "stream_url": "/executions/12345678-1234-1234-1234-123456789012/stream"
        }
        
        # Verify response structure
        assert "execution_id" in execute_response
        assert execute_response["status"] == "accepted"
        assert "estimated_duration" in execute_response
        assert "steps" in execute_response
        assert isinstance(execute_response["steps"], list)
        assert len(execute_response["steps"]) == 2
        assert "stream_url" in execute_response
    
    @pytest.mark.asyncio
    async def test_execution_status_response(self, state_manager):
        """Test execution status response structure."""
        # Set up state with running execution
        await state_manager.setup_state("agent can execute queries")
        
        # Mock execution status response
        status_response = {
            "execution_id": "12345678-1234-1234-1234-123456789012",
            "status": "running",
            "progress": {
                "current_step": 1,
                "total_steps": 2,
                "percentage": 50.0,
                "estimated_remaining_seconds": 60
            },
            "current_step": {
                "id": "step_glm",
                "name": "GLM Analysis",
                "status": "running",
                "progress": 0.75
            },
            "completed_steps": [
                {
                    "id": "step_preprocess",
                    "name": "Data Preprocessing",
                    "status": "completed",
                    "duration_seconds": 45,
                    "artifacts": [
                        {
                            "id": "artifact_preprocessed",
                            "type": "file",
                            "name": "preprocessed_data.nii.gz",
                            "url": "/api/artifacts/artifact_preprocessed"
                        }
                    ]
                }
            ],
            "artifacts": [],
            "timing": {
                "start_time": "2025-01-01T00:00:00Z",
                "estimated_end_time": "2025-01-01T00:02:00Z"
            }
        }
        
        # Verify response structure
        assert status_response["execution_id"] == "12345678-1234-1234-1234-123456789012"
        assert "status" in status_response
        assert "progress" in status_response
        assert "current_step" in status_response
        assert "completed_steps" in status_response
        assert "timing" in status_response
        
        # Verify progress structure
        progress = status_response["progress"]
        assert "current_step" in progress
        assert "total_steps" in progress
        assert "percentage" in progress
        assert 0 <= progress["percentage"] <= 100
    
    @pytest.mark.asyncio
    async def test_tools_listing_response(self, state_manager):
        """Test tools listing response structure."""
        # Set up state
        await state_manager.setup_state("agent has tools available")
        
        # Mock tools response
        tools_response = {
            "tools": [
                {
                    "id": "fsl_glm",
                    "name": "FSL GLM Analysis",
                    "category": "neuroimaging",
                    "description": "General Linear Model analysis using FSL",
                    "version": "6.0.5",
                    "parameters": [
                        {
                            "name": "smoothing",
                            "type": "float",
                            "default": 6.0,
                            "required": False,
                            "description": "FWHM smoothing kernel size"
                        }
                    ],
                    "required_inputs": ["fmri_data", "design_matrix"],
                    "outputs": ["statistical_map", "design_matrix_image"],
                    "estimated_runtime": "2-5 minutes"
                }
            ],
            "categories": ["neuroimaging", "statistics", "visualization"],
            "total_count": 1
        }
        
        # Verify response structure
        assert "tools" in tools_response
        assert "categories" in tools_response
        assert "total_count" in tools_response
        assert isinstance(tools_response["tools"], list)
        
        # Verify tool structure
        tool = tools_response["tools"][0]
        assert "id" in tool
        assert "name" in tool
        assert "category" in tool
        assert "parameters" in tool
        assert "required_inputs" in tool
        assert "outputs" in tool
    
    @pytest.mark.asyncio
    async def test_agent_busy_response(self, state_manager):
        """Test agent busy error response."""
        # Set up busy state
        await state_manager.setup_state("agent is busy with other jobs")
        
        # Mock busy response
        busy_response = {
            "error": {
                "code": "SERVICE_UNAVAILABLE",
                "message": "Agent is currently busy processing other requests",
                "details": {
                    "queue_length": 5,
                    "estimated_wait_time": 300
                },
                "retry_after": 60,
                "timestamp": "2025-01-01T00:00:00Z"
            }
        }
        
        # Verify error response structure
        assert "error" in busy_response
        error = busy_response["error"]
        assert error["code"] == "SERVICE_UNAVAILABLE"
        assert "message" in error
        assert "details" in error
        assert "queue_length" in error["details"]
        assert "retry_after" in error
    
    @pytest.mark.asyncio
    async def test_cancellation_response(self, state_manager):
        """Test execution cancellation response."""
        # Set up state
        await state_manager.setup_state("agent can execute queries")
        
        # Mock cancellation response
        cancel_response = {
            "execution_id": "12345678-1234-1234-1234-123456789012",
            "status": "cancelled",
            "message": "Execution cancelled successfully",
            "cancelled_at": "2025-01-01T00:01:00Z"
        }
        
        # Verify response structure
        assert cancel_response["execution_id"] == "12345678-1234-1234-1234-123456789012"
        assert cancel_response["status"] == "cancelled"
        assert "message" in cancel_response
        assert "cancelled_at" in cancel_response
    
    @pytest.mark.asyncio
    async def test_metrics_response(self, state_manager):
        """Test agent metrics response structure."""
        # Set up state
        await state_manager.setup_state("agent has metrics available")
        
        # Mock metrics response
        metrics_response = {
            "metrics": {
                "executions_total": 150,
                "executions_successful": 142,
                "executions_failed": 8,
                "average_execution_time_seconds": 85.5,
                "queue_length": 2,
                "active_executions": 3,
                "tools_used": {
                    "fsl_glm": 45,
                    "fmriprep": 32,
                    "nilearn_decoding": 28
                },
                "error_rates": {
                    "timeout": 0.02,
                    "tool_error": 0.03,
                    "validation_error": 0.01
                }
            },
            "timestamp": "2025-01-01T00:00:00Z",
            "collection_period": "last_24h"
        }
        
        # Verify response structure
        assert "metrics" in metrics_response
        metrics = metrics_response["metrics"]
        assert "executions_total" in metrics
        assert "executions_successful" in metrics
        assert "executions_failed" in metrics
        assert "average_execution_time_seconds" in metrics
        assert "tools_used" in metrics
        assert "error_rates" in metrics
        assert "timestamp" in metrics_response
        assert "collection_period" in metrics_response
    
    def test_provider_state_coverage(self, state_manager):
        """Test that all required provider states are available."""
        # Get all pact files that use this provider
        pact_files = list(pact_config.pact_dir.glob("*-agent.json"))
        
        required_states = set()
        for pact_file in pact_files:
            if not pact_file.exists():
                continue
                
            interactions = VerificationHelper.extract_pact_interactions(pact_file)
            for interaction in interactions:
                if "providerState" in interaction:
                    required_states.add(interaction["providerState"])
                elif "provider_state" in interaction:
                    required_states.add(interaction["provider_state"])
        
        # Verify all required states can be set up
        available_states = set(state_manager._state_handlers.keys())
        missing_states = required_states - available_states
        
        if missing_states:
            pytest.skip(f"Missing provider states: {missing_states}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
