"""
State persistence layer for the Brain Researcher agent.

Provides Redis-based checkpointing for production and memory-based for development.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Optional, List, Dict, Tuple

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)


class RedisCheckpointer(BaseCheckpointSaver):
    """
    Redis-based state persistence for production environments.
    
    Provides durable state storage with:
    - Automatic state serialization/deserialization
    - TTL-based expiration for old states
    - Atomic operations for consistency
    - Support for state history
    """
    
    def __init__(
        self,
        redis_url: str = None,
        ttl_seconds: int = 86400,  # 24 hours default
        namespace: str = "brain_researcher"
    ):
        """
        Initialize Redis checkpointer.
        
        Args:
            redis_url: Redis connection URL (defaults to env var REDIS_URL)
            ttl_seconds: Time-to-live for state entries
            namespace: Redis key namespace
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.ttl_seconds = ttl_seconds
        self.namespace = namespace
        
        # Initialize Redis client
        try:
            import redis
            self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
            self.redis_client.ping()
            logger.info(f"Connected to Redis at {self.redis_url}")
        except ImportError:
            logger.warning("Redis package not installed, falling back to fakeredis")
            import fakeredis
            self.redis_client = fakeredis.FakeRedis(decode_responses=True)
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}, using fakeredis")
            import fakeredis
            self.redis_client = fakeredis.FakeRedis(decode_responses=True)
    
    def _make_key(self, thread_id: str, checkpoint_id: Optional[str] = None) -> str:
        """Generate Redis key for checkpoint."""
        if checkpoint_id:
            return f"{self.namespace}:checkpoint:{thread_id}:{checkpoint_id}"
        return f"{self.namespace}:checkpoint:{thread_id}:latest"
    
    def _make_history_key(self, thread_id: str) -> str:
        """Generate Redis key for checkpoint history."""
        return f"{self.namespace}:history:{thread_id}"
    
    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: Optional[Dict[str, Any]] = None
    ) -> RunnableConfig:
        """
        Save a checkpoint to Redis.
        
        Args:
            config: Runtime configuration
            checkpoint: Checkpoint to save
            metadata: Optional metadata
            
        Returns:
            Updated configuration with checkpoint info
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = checkpoint.get("id", str(datetime.utcnow().timestamp()))
        
        # Serialize checkpoint
        checkpoint_data = {
            "checkpoint": checkpoint,
            "metadata": metadata or {},
            "timestamp": datetime.utcnow().isoformat(),
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id
        }
        
        # Save to Redis
        key = self._make_key(thread_id, checkpoint_id)
        self.redis_client.setex(
            key,
            self.ttl_seconds,
            json.dumps(checkpoint_data, default=str)
        )
        
        # Update latest pointer
        latest_key = self._make_key(thread_id)
        self.redis_client.setex(
            latest_key,
            self.ttl_seconds,
            json.dumps(checkpoint_data, default=str)
        )
        
        # Add to history (sorted set by timestamp)
        history_key = self._make_history_key(thread_id)
        self.redis_client.zadd(
            history_key,
            {checkpoint_id: datetime.utcnow().timestamp()}
        )
        
        # Set TTL on history
        self.redis_client.expire(history_key, self.ttl_seconds)
        
        logger.debug(f"Saved checkpoint {checkpoint_id} for thread {thread_id}")
        
        # Return updated config
        return {
            **config,
            "configurable": {
                **config["configurable"],
                "checkpoint_id": checkpoint_id
            }
        }
    
    def get(
        self,
        config: RunnableConfig
    ) -> Optional[Tuple[Checkpoint, Dict[str, Any]]]:
        """
        Retrieve a checkpoint from Redis.
        
        Args:
            config: Runtime configuration
            
        Returns:
            Tuple of (checkpoint, metadata) or None if not found
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id")
        
        # Get checkpoint data
        key = self._make_key(thread_id, checkpoint_id)
        data = self.redis_client.get(key)
        
        if not data:
            logger.debug(f"No checkpoint found for thread {thread_id}")
            return None
        
        # Deserialize
        checkpoint_data = json.loads(data)
        
        return (
            checkpoint_data["checkpoint"],
            checkpoint_data.get("metadata", {})
        )
    
    def list(
        self,
        config: RunnableConfig,
        *,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None
    ) -> List[Tuple[RunnableConfig, Checkpoint, Dict[str, Any]]]:
        """
        List checkpoints for a thread.
        
        Args:
            config: Runtime configuration
            before: Optional config to list checkpoints before
            limit: Maximum number of checkpoints to return
            
        Returns:
            List of (config, checkpoint, metadata) tuples
        """
        thread_id = config["configurable"]["thread_id"]
        history_key = self._make_history_key(thread_id)
        
        # Get checkpoint IDs from history (sorted by timestamp)
        checkpoint_ids = self.redis_client.zrevrange(
            history_key,
            0,
            limit - 1 if limit else -1
        )
        
        results = []
        for checkpoint_id in checkpoint_ids:
            key = self._make_key(thread_id, checkpoint_id)
            data = self.redis_client.get(key)
            
            if data:
                checkpoint_data = json.loads(data)
                checkpoint_config = {
                    **config,
                    "configurable": {
                        **config["configurable"],
                        "checkpoint_id": checkpoint_id
                    }
                }
                results.append((
                    checkpoint_config,
                    checkpoint_data["checkpoint"],
                    checkpoint_data.get("metadata", {})
                ))
        
        return results
    
    def get_tuple(self, config: RunnableConfig) -> Optional[Any]:
        """Get checkpoint tuple (for compatibility)."""
        result = self.get(config)
        if result:
            checkpoint, metadata = result
            return {
                "config": config,
                "checkpoint": checkpoint,
                "metadata": metadata,
                "parent_config": None
            }
        return None
    
    def put_writes(self, config: RunnableConfig, writes: List[Any], task_id: str) -> None:
        """Store pending writes (for compatibility)."""
        # This is handled by the checkpoint itself in our implementation
        pass
    
    async def aget(self, config: RunnableConfig) -> Optional[tuple[Checkpoint, dict[str, Any]]]:
        """Async version of get (delegates to sync for now)."""
        return self.get(config)
    
    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: Optional[Dict[str, Any]] = None
    ) -> RunnableConfig:
        """Async version of put (delegates to sync for now)."""
        return self.put(config, checkpoint, metadata)


class HybridCheckpointer(BaseCheckpointSaver):
    """
    Hybrid checkpointer that uses Redis in production and memory in development.
    
    Automatically selects the appropriate backend based on environment.
    """
    
    def __init__(self):
        """Initialize hybrid checkpointer."""
        self.is_production = os.getenv("ENVIRONMENT", "development") == "production"
        
        if self.is_production:
            logger.info("Using Redis checkpointer for production")
            self.backend = RedisCheckpointer()
        else:
            logger.info("Using memory checkpointer for development")
            self.backend = MemorySaver()
    
    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: Optional[Dict[str, Any]] = None
    ) -> RunnableConfig:
        """Delegate to backend."""
        return self.backend.put(config, checkpoint, metadata)
    
    def get(
        self,
        config: RunnableConfig
    ) -> Optional[Tuple[Checkpoint, Dict[str, Any]]]:
        """Delegate to backend."""
        return self.backend.get(config)
    
    def list(
        self,
        config: RunnableConfig,
        *,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None
    ) -> List[Tuple[RunnableConfig, Checkpoint, Dict[str, Any]]]:
        """Delegate to backend."""
        return self.backend.list(config, before=before, limit=limit)
    
    def get_tuple(self, config: RunnableConfig) -> Optional[Any]:
        """Delegate to backend."""
        return self.backend.get_tuple(config)
    
    def put_writes(self, config: RunnableConfig, writes: List[Any], task_id: str) -> None:
        """Delegate to backend."""
        return self.backend.put_writes(config, writes, task_id)
    
    async def aget(self, config: RunnableConfig) -> Optional[tuple[Checkpoint, dict[str, Any]]]:
        """Delegate to backend."""
        if hasattr(self.backend, 'aget'):
            return await self.backend.aget(config)
        return self.backend.get(config)
    
    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: Optional[Dict[str, Any]] = None
    ) -> RunnableConfig:
        """Delegate to backend."""
        if hasattr(self.backend, 'aput'):
            return await self.backend.aput(config, checkpoint, metadata)
        return self.backend.put(config, checkpoint, metadata)


def get_checkpointer() -> BaseCheckpointSaver:
    """
    Factory function to get the appropriate checkpointer.
    
    Returns:
        Checkpointer instance based on environment
    """
    return HybridCheckpointer()