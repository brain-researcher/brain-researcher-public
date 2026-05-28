"""
Thread Storage for Brain Researcher Agent UI API (B.2)

Redis-backed storage for chat threads and messages with ownership tracking.
Falls back to fakeredis for development without Redis.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """A single chat message within a thread."""
    id: str
    role: str  # "user", "assistant", "system", "tool"
    content: str
    timestamp: str
    user_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Thread:
    """A chat thread with messages and ownership."""
    id: str
    owner_id: str
    tenant_id: str = "default"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    title: Optional[str] = None
    messages: List[Message] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "owner_id": self.owner_id,
            "tenant_id": self.tenant_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "title": self.title,
            "messages": [m.to_dict() for m in self.messages],
            "message_count": len(self.messages),
            "metadata": self.metadata,
        }


class ThreadStore:
    """
    Redis-backed storage for chat threads.

    Features:
    - Store threads with owner tracking
    - Append messages to threads
    - List threads by user
    - TTL for cleanup (configurable via THREAD_STORE_TTL_DAYS, default 30 days)
    - Fallback to fakeredis for development

    Environment Variables:
    - THREAD_STORE_REDIS_URL: Redis URL (falls back to REDIS_URL)
    - THREAD_STORE_TTL_DAYS: TTL in days (default 30)
    """

    def __init__(
        self,
        redis_client=None,
        ttl_days: int = None,
        namespace: str = "agent_threads"
    ):
        """
        Initialize thread store.

        Args:
            redis_client: Optional Redis client (creates one if not provided)
            ttl_days: Time to live for threads in days (reads from env if None)
            namespace: Redis key namespace prefix
        """
        self.namespace = namespace
        # Read TTL from env if not explicitly provided
        if ttl_days is None:
            ttl_days = int(os.getenv('THREAD_STORE_TTL_DAYS', '30'))
        self.ttl_seconds = ttl_days * 24 * 3600
        self._lock = threading.Lock()
        self._is_persistent = True  # Will be set by _create_redis_client or client detection

        if redis_client:
            self.redis = redis_client
            # Detect if it's fakeredis
            self._is_persistent = 'Fake' not in type(redis_client).__name__
        else:
            self.redis = self._create_redis_client()

        logger.info(f"ThreadStore initialized: namespace={namespace}, ttl_days={ttl_days}, persistent={self._is_persistent}")

    def _create_redis_client(self):
        """Create Redis client with fakeredis fallback."""
        try:
            import redis
            # Prefer dedicated THREAD_STORE_REDIS_URL, fall back to REDIS_URL
            redis_url = os.getenv('THREAD_STORE_REDIS_URL') or os.getenv('REDIS_URL', 'redis://localhost:6379/2')
            client = redis.from_url(redis_url, decode_responses=True)
            client.ping()
            logger.info(f"ThreadStore connected to Redis at {redis_url}")
            self._is_persistent = True
            return client
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            logger.warning("Using in-memory storage (NOT DURABLE - data will be lost on restart)")
            self._is_persistent = False
            try:
                import fakeredis
                return fakeredis.FakeRedis(decode_responses=True)
            except ImportError:
                logger.error("Neither redis nor fakeredis available")
                raise RuntimeError("No Redis backend available. Install redis or fakeredis.")

    def _thread_key(self, thread_id: str) -> str:
        return f"{self.namespace}:thread:{thread_id}"

    def _user_threads_key(self, user_id: str, tenant_id: str = "default") -> str:
        if tenant_id and tenant_id != "default":
            return f"{self.namespace}:tenant:{tenant_id}:user:{user_id}:threads"
        return f"{self.namespace}:user:{user_id}:threads"

    def create_thread(
        self,
        thread_id: str,
        owner_id: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tenant_id: str = "default",
    ) -> Thread:
        """
        Create a new thread.

        Args:
            thread_id: Unique thread identifier
            owner_id: User ID who owns this thread
            title: Optional thread title
            metadata: Optional additional metadata

        Returns:
            Created Thread object
        """
        now = datetime.utcnow().isoformat()
        thread = Thread(
            id=thread_id,
            owner_id=owner_id,
            tenant_id=tenant_id,
            created_at=now,
            updated_at=now,
            title=title,
            messages=[],
            metadata=metadata or {},
        )

        thread_key = self._thread_key(thread_id)
        user_key = self._user_threads_key(owner_id, tenant_id)

        with self._lock:
            # Store thread data
            self.redis.set(thread_key, json.dumps(thread.to_dict()))
            self.redis.expire(thread_key, self.ttl_seconds)

            # Add to user's thread list
            self.redis.sadd(user_key, thread_id)
            self.redis.expire(user_key, self.ttl_seconds)

        logger.debug(f"Created thread {thread_id} for user {owner_id}")
        return thread

    def get_thread(self, thread_id: str) -> Optional[Thread]:
        """
        Get a thread by ID.

        Args:
            thread_id: Thread identifier

        Returns:
            Thread object or None if not found
        """
        thread_key = self._thread_key(thread_id)
        data = self.redis.get(thread_key)

        if not data:
            return None

        try:
            parsed = json.loads(data)
            messages = [Message(**m) for m in parsed.get("messages", [])]
            return Thread(
                id=parsed["id"],
                owner_id=parsed["owner_id"],
                tenant_id=parsed.get("tenant_id", "default"),
                created_at=parsed["created_at"],
                updated_at=parsed["updated_at"],
                title=parsed.get("title"),
                messages=messages,
                metadata=parsed.get("metadata", {}),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse thread {thread_id}: {e}")
            return None

    def get_or_create_thread(
        self,
        thread_id: str,
        owner_id: str,
        title: Optional[str] = None,
        tenant_id: str = "default",
    ) -> Thread:
        """
        Get existing thread or create new one.

        Args:
            thread_id: Thread identifier
            owner_id: User ID (used if creating)
            title: Optional title (used if creating)

        Returns:
            Thread object
        """
        thread = self.get_thread(thread_id)
        if thread:
            return thread
        return self.create_thread(thread_id, owner_id, title, tenant_id=tenant_id)

    def add_message(
        self,
        thread_id: str,
        message_id: str,
        role: str,
        content: str,
        user_id: Optional[str] = None,
        tenant_id: str = "default",
        **extra: Any
    ) -> Message:
        """
        Add a message to a thread.

        Args:
            thread_id: Thread to add message to
            message_id: Unique message identifier
            role: Message role (user, assistant, system, tool)
            content: Message content
            user_id: Optional user ID for ownership
            **extra: Additional message metadata

        Returns:
            Created Message object

        Raises:
            ValueError: If thread doesn't exist
        """
        thread = self.get_thread(thread_id)
        if not thread:
            # Auto-create thread if it doesn't exist
            if user_id:
                thread = self.create_thread(thread_id, user_id, tenant_id=tenant_id)
            else:
                raise ValueError(f"Thread {thread_id} not found and no user_id to create")

        now = datetime.utcnow().isoformat()
        message = Message(
            id=message_id,
            role=role,
            content=content,
            timestamp=now,
            user_id=user_id,
            tool_call_id=extra.get("tool_call_id"),
            tool_name=extra.get("tool_name"),
            metadata={k: v for k, v in extra.items() if k not in ("tool_call_id", "tool_name")},
        )

        thread.messages.append(message)
        thread.updated_at = now

        # Update in Redis
        thread_key = self._thread_key(thread_id)
        with self._lock:
            self.redis.set(thread_key, json.dumps(thread.to_dict()))
            self.redis.expire(thread_key, self.ttl_seconds)

        logger.debug(f"Added message {message_id} to thread {thread_id}")
        return message

    def get_messages(
        self,
        thread_id: str,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[Message]:
        """
        Get messages from a thread.

        Args:
            thread_id: Thread identifier
            limit: Maximum number of messages to return
            offset: Number of messages to skip

        Returns:
            List of Message objects
        """
        thread = self.get_thread(thread_id)
        if not thread:
            return []

        messages = thread.messages[offset:]
        if limit:
            messages = messages[:limit]
        return messages

    def list_user_threads(
        self,
        user_id: str,
        tenant_id: str = "default",
        limit: int = 50,
        include_messages: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List threads owned by a user.

        Args:
            user_id: User identifier
            limit: Maximum number of threads to return
            include_messages: Whether to include full message list

        Returns:
            List of thread dictionaries
        """
        user_key = self._user_threads_key(user_id, tenant_id)
        thread_ids = self.redis.smembers(user_key)

        threads = []
        for tid in thread_ids:
            thread = self.get_thread(tid)
            if thread:
                data = thread.to_dict()
                if not include_messages:
                    data.pop("messages", None)
                threads.append(data)

        # Sort by updated_at descending
        threads.sort(key=lambda t: t.get("updated_at", ""), reverse=True)
        return threads[:limit]

    def check_access(self, thread_id: str, user_id: str, tenant_id: str = "default") -> bool:
        """
        Check if user has access to thread.

        Args:
            thread_id: Thread identifier
            user_id: User identifier

        Returns:
            True if user has access (owner or thread doesn't exist)
        """
        thread = self.get_thread(thread_id)
        if not thread:
            return True  # Non-existent threads can be created
        return thread.owner_id == user_id and thread.tenant_id == tenant_id

    def delete_thread(self, thread_id: str, user_id: str, tenant_id: str = "default") -> bool:
        """
        Delete a thread (only if user is owner).

        Args:
            thread_id: Thread identifier
            user_id: User identifier (must be owner)

        Returns:
            True if deleted, False otherwise
        """
        thread = self.get_thread(thread_id)
        if not thread or thread.owner_id != user_id or thread.tenant_id != tenant_id:
            return False

        thread_key = self._thread_key(thread_id)
        user_key = self._user_threads_key(user_id, tenant_id)

        with self._lock:
            self.redis.delete(thread_key)
            self.redis.srem(user_key, thread_id)

        logger.debug(f"Deleted thread {thread_id}")
        return True

    @property
    def is_persistent(self) -> bool:
        """
        Check if ThreadStore is using persistent storage.

        Returns:
            True if using real Redis, False if using fakeredis (in-memory)
        """
        return self._is_persistent

    def close(self):
        """
        Close the Redis connection.

        Safe to call multiple times. Logs any errors but doesn't raise.
        """
        if hasattr(self.redis, 'close'):
            try:
                self.redis.close()
                logger.info("ThreadStore connection closed")
            except Exception as e:
                logger.warning(f"Error closing ThreadStore connection: {e}")


# Singleton instance
_thread_store: Optional[ThreadStore] = None
_thread_store_lock = threading.Lock()


def get_thread_store() -> ThreadStore:
    """
    Get the global ThreadStore instance.

    Returns:
        ThreadStore singleton
    """
    global _thread_store
    if _thread_store is None:
        with _thread_store_lock:
            if _thread_store is None:
                _thread_store = ThreadStore()
    return _thread_store
