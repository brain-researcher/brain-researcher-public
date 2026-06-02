"""
Provider state setup for contract verification.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)


class StateSetupManager:
    """Manages provider states for contract verification."""

    def __init__(self):
        self._state_handlers: Dict[str, Callable] = {}
        self._cleanup_handlers: Dict[str, Callable] = {}

    def register_state(
        self, state_name: str, setup_func: Callable, cleanup_func: Callable = None
    ):
        """Register a state setup handler."""
        self._state_handlers[state_name] = setup_func
        if cleanup_func:
            self._cleanup_handlers[state_name] = cleanup_func

    async def setup_state(self, state_name: str, params: Dict[str, Any] = None) -> Any:
        """Set up a provider state."""
        if state_name not in self._state_handlers:
            raise ValueError(f"Unknown state: {state_name}")

        handler = self._state_handlers[state_name]
        params = params or {}

        try:
            if hasattr(handler, "__await__"):
                return await handler(**params)
            else:
                return handler(**params)
        except Exception as e:
            logger.error(f"Failed to setup state '{state_name}': {e}")
            raise

    async def cleanup_state(self, state_name: str, params: Dict[str, Any] = None):
        """Clean up a provider state."""
        if state_name in self._cleanup_handlers:
            cleanup_func = self._cleanup_handlers[state_name]
            params = params or {}

            try:
                if hasattr(cleanup_func, "__await__"):
                    await cleanup_func(**params)
                else:
                    cleanup_func(**params)
            except Exception as e:
                logger.warning(f"Failed to cleanup state '{state_name}': {e}")


class OrchestratorStateSetup:
    """State setup for Orchestrator service."""

    @staticmethod
    def get_state_manager() -> StateSetupManager:
        """Get configured state manager for Orchestrator."""
        manager = StateSetupManager()

        # Job-related states
        manager.register_state(
            "a job exists",
            OrchestratorStateSetup._setup_job_exists,
            OrchestratorStateSetup._cleanup_job_exists,
        )

        manager.register_state(
            "a completed job exists",
            OrchestratorStateSetup._setup_completed_job_exists,
            OrchestratorStateSetup._cleanup_job_exists,
        )

        manager.register_state(
            "no jobs exist", OrchestratorStateSetup._setup_no_jobs_exist
        )

        # Thread-related states
        manager.register_state(
            "a thread exists",
            OrchestratorStateSetup._setup_thread_exists,
            OrchestratorStateSetup._cleanup_thread_exists,
        )

        manager.register_state(
            "no threads exist", OrchestratorStateSetup._setup_no_threads_exist
        )

        # Dataset-related states
        manager.register_state(
            "datasets are available", OrchestratorStateSetup._setup_datasets_available
        )

        # User-related states
        manager.register_state(
            "user is authenticated", OrchestratorStateSetup._setup_user_authenticated
        )

        # Service health states
        manager.register_state(
            "all services are healthy", OrchestratorStateSetup._setup_services_healthy
        )

        manager.register_state(
            "agent service is unavailable",
            OrchestratorStateSetup._setup_agent_unavailable,
        )

        return manager

    @staticmethod
    async def _setup_job_exists(job_id: str = "job_test123") -> Dict[str, Any]:
        """Set up state where a job exists."""
        # In real implementation, would create job in database/cache
        job_data = {
            "id": job_id,
            "status": "running",
            "prompt": "Test job",
            "steps": [],
            "artifacts": [],
            "timing": {"start_time": "2025-01-01T00:00:00Z"},
            "metadata": {},
        }

        # Mock database insertion
        logger.info(f"Created test job: {job_id}")
        return job_data

    @staticmethod
    async def _setup_completed_job_exists(
        job_id: str = "job_completed123",
    ) -> Dict[str, Any]:
        """Set up state where a completed job exists."""
        job_data = {
            "id": job_id,
            "status": "completed",
            "prompt": "Completed test job",
            "steps": [
                {
                    "id": "step_analysis",
                    "name": "Analysis",
                    "tool": "test_tool",
                    "status": "completed",
                }
            ],
            "artifacts": [
                {
                    "id": "artifact_result",
                    "type": "image",
                    "name": "Test Result",
                    "url": f"/api/artifacts/artifact_result",
                }
            ],
            "timing": {
                "start_time": "2025-01-01T00:00:00Z",
                "end_time": "2025-01-01T00:01:00Z",
                "duration_ms": 60000,
            },
            "metadata": {},
        }

        logger.info(f"Created completed test job: {job_id}")
        return job_data

    @staticmethod
    async def _cleanup_job_exists(job_id: str = "job_test123"):
        """Clean up job state."""
        # In real implementation, would remove job from database/cache
        logger.info(f"Cleaned up test job: {job_id}")

    @staticmethod
    async def _setup_no_jobs_exist():
        """Set up state where no jobs exist."""
        # In real implementation, would clear job database/cache
        logger.info("Ensured no jobs exist")
        return {}

    @staticmethod
    async def _setup_thread_exists(thread_id: str = "thread_test123") -> Dict[str, Any]:
        """Set up state where a thread exists."""
        thread_data = {
            "thread_id": thread_id,
            "title": "Test Thread",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "message_count": 0,
            "context": {},
            "metadata": {},
        }

        logger.info(f"Created test thread: {thread_id}")
        return thread_data

    @staticmethod
    async def _cleanup_thread_exists(thread_id: str = "thread_test123"):
        """Clean up thread state."""
        logger.info(f"Cleaned up test thread: {thread_id}")

    @staticmethod
    async def _setup_no_threads_exist():
        """Set up state where no threads exist."""
        logger.info("Ensured no threads exist")
        return {}

    @staticmethod
    async def _setup_datasets_available() -> Dict[str, Any]:
        """Set up state where datasets are available."""
        datasets_data = {
            "datasets": [
                {
                    "id": "motor-task-001",
                    "name": "Motor Task Dataset",
                    "description": "Test dataset for motor task",
                    "source": "BuiltIn",
                    "modality": ["fMRI"],
                    "n_subjects": 20,
                    "n_sessions": 1,
                    "tasks": ["motor"],
                    "size_gb": 5.0,
                    "has_derivatives": True,
                    "last_updated": "2025-01-01T00:00:00Z",
                }
            ],
            "pagination": {"page": 1, "limit": 20, "total_items": 1, "total_pages": 1},
            "facets": {},
        }

        logger.info("Set up available datasets")
        return datasets_data

    @staticmethod
    async def _setup_user_authenticated(
        user_id: str = "user_test123",
    ) -> Dict[str, Any]:
        """Set up authenticated user state."""
        user_data = {
            "id": user_id,
            "username": "testuser",
            "email": "test@example.com",
            "role": "researcher",
            "is_active": True,
        }

        # Mock authentication token
        auth_data = {"user": user_data, "token": "mock_jwt_token_12345"}

        logger.info(f"Set up authenticated user: {user_id}")
        return auth_data

    @staticmethod
    async def _setup_services_healthy():
        """Set up state where all services are healthy."""
        health_data = {
            "status": "healthy",
            "services": {
                "agent": {"name": "agent-service", "status": "healthy"},
                "br_kg": {"name": "br_kg-service", "status": "healthy"},
            },
        }

        logger.info("Set up healthy services state")
        return health_data

    @staticmethod
    async def _setup_agent_unavailable():
        """Set up state where agent service is unavailable."""
        health_data = {
            "status": "degraded",
            "services": {
                "agent": {"name": "agent-service", "status": "unavailable"},
                "br_kg": {"name": "br_kg-service", "status": "healthy"},
            },
        }

        logger.info("Set up agent unavailable state")
        return health_data


class AgentStateSetup:
    """State setup for Agent service."""

    @staticmethod
    def get_state_manager() -> StateSetupManager:
        """Get configured state manager for Agent service."""
        manager = StateSetupManager()

        manager.register_state(
            "agent can execute queries", AgentStateSetup._setup_agent_ready
        )

        manager.register_state(
            "agent is busy with other jobs", AgentStateSetup._setup_agent_busy
        )

        manager.register_state(
            "br_kg service is available", AgentStateSetup._setup_br_kg_available
        )

        return manager

    @staticmethod
    async def _setup_agent_ready():
        """Set up agent ready state."""
        logger.info("Agent is ready to execute queries")
        return {"status": "ready", "queue_length": 0}

    @staticmethod
    async def _setup_agent_busy():
        """Set up agent busy state."""
        logger.info("Agent is busy with other jobs")
        return {"status": "busy", "queue_length": 5}

    @staticmethod
    async def _setup_br_kg_available():
        """Set up BR-KG available state."""
        logger.info("BR-KG service is available")
        return {"br_kg_status": "available"}


class BRKGStateSetup:
    """State setup for BR-KG service."""

    @staticmethod
    def get_state_manager() -> StateSetupManager:
        """Get configured state manager for BR-KG service."""
        manager = StateSetupManager()

        manager.register_state(
            "knowledge graph has data", BRKGStateSetup._setup_kg_with_data
        )

        manager.register_state(
            "knowledge graph is empty", BRKGStateSetup._setup_empty_kg
        )

        return manager

    @staticmethod
    async def _setup_kg_with_data():
        """Set up KG with data state."""
        logger.info("Knowledge graph populated with test data")
        return {"nodes": 1000, "relationships": 5000}

    @staticmethod
    async def _setup_empty_kg():
        """Set up empty KG state."""
        logger.info("Knowledge graph is empty")
        return {"nodes": 0, "relationships": 0}
