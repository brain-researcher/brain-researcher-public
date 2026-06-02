"""
Checkpoint Management for Intelligent Failure Recovery (AGENT-014)

This module implements automatic checkpoint creation and restoration
for resilient execution with partial rerun capabilities.
"""

import json
import logging
import os
import pickle
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import redis
from fakeredis import FakeRedis

logger = logging.getLogger(__name__)


@dataclass
class ExecutionState:
    """Execution state for checkpointing."""

    execution_id: str
    current_step: int
    completed_steps: List[int]
    step_results: Dict[int, Any]
    variables: Dict[str, Any]
    timestamp: float
    metadata: Dict[str, Any]


class CheckpointManager:
    """
    Manages execution checkpoints with versioning and lifecycle management.

    Features:
    - Automatic checkpoint creation at critical points
    - State serialization and versioning
    - Checkpoint lifecycle management
    - Partial rerun from last successful checkpoint
    - Storage backend abstraction (Redis/disk)
    """

    def __init__(self, storage_backend: Optional[str] = None):
        """Initialize checkpoint manager.

        storage_backend: "redis" (default) or "memory".
        """
        self.storage_backend = (storage_backend or "redis").lower()
        self.memory_store: dict[str, str] = {}

        if self.storage_backend == "redis":
            try:
                self.redis_client = redis.from_url(
                    os.environ.get("REDIS_URL", "redis://localhost:6379")
                )
            except Exception:
                self.redis_client = FakeRedis()
        elif self.storage_backend == "memory":
            # no external dependency; keep everything in-process
            self.redis_client = None
        else:
            raise ValueError(f"Unsupported checkpoint backend: {self.storage_backend}")

        self.checkpoint_strategy = AdaptiveCheckpointing()
        logger.info(
            "Checkpoint manager initialized with %s backend", self.storage_backend
        )

    def create_checkpoint(self, state: ExecutionState) -> str:
        """Create checkpoint from execution state."""
        checkpoint_id = f"checkpoint_{state.execution_id}_{int(time.time())}"

        try:
            serialized_state = self._serialize_state(state)
            key = f"checkpoint:{checkpoint_id}"

            if self.storage_backend == "redis":
                self.redis_client.setex(key, 86400, serialized_state)  # 24-hour TTL
            else:  # memory
                self.memory_store[key] = serialized_state

            logger.info(f"Checkpoint {checkpoint_id} created successfully")
            return checkpoint_id

        except Exception as e:
            logger.error(f"Failed to create checkpoint: {e}")
            raise

    def restore_from_checkpoint(self, checkpoint_id: str) -> ExecutionState:
        """Restore execution state from checkpoint."""
        try:
            key = f"checkpoint:{checkpoint_id}"
            if self.storage_backend == "redis":
                serialized_data = self.redis_client.get(key)
            else:
                serialized_data = self.memory_store.get(key)

            if not serialized_data:
                raise ValueError(f"Checkpoint {checkpoint_id} not found")

            state = self._deserialize_state(serialized_data)
            logger.info(f"Restored from checkpoint {checkpoint_id}")
            return state

        except Exception as e:
            logger.error(f"Failed to restore checkpoint: {e}")
            raise

    def _serialize_state(self, state: ExecutionState) -> str:
        """Serialize execution state."""
        return json.dumps(asdict(state), default=str)

    def _deserialize_state(self, data: str) -> ExecutionState:
        """Deserialize execution state."""
        state_dict = json.loads(data)
        return ExecutionState(**state_dict)


class AdaptiveCheckpointing:
    """Adaptive checkpointing strategy."""

    def should_checkpoint(self, step_number: int, step_duration: float) -> bool:
        """Determine if checkpoint should be created."""
        # Checkpoint after long-running steps or at regular intervals
        return step_duration > 300 or step_number % 3 == 0
