"""Unit tests for thread store module."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_redis():
    """Create a fakeredis client for testing."""
    try:
        import fakeredis
        return fakeredis.FakeRedis(decode_responses=True)
    except ImportError:
        pytest.skip("fakeredis not installed")


@pytest.fixture
def thread_store(fake_redis):
    """Create a ThreadStore with fakeredis backend."""
    from brain_researcher.services.agent.thread_store import ThreadStore
    store = ThreadStore(redis_client=fake_redis, ttl_days=1, namespace="test_threads")
    try:
        yield store
    finally:
        store.close()
        try:
            fake_redis.close()
        except Exception:
            pass


class TestThreadCreation:
    """Tests for thread creation."""

    def test_create_thread_basic(self, thread_store):
        """Creating a thread should store it with owner."""
        thread = thread_store.create_thread(
            thread_id="test-thread-1",
            owner_id="user-123",
            title="Test Thread",
        )

        assert thread.id == "test-thread-1"
        assert thread.owner_id == "user-123"
        assert thread.title == "Test Thread"
        assert thread.messages == []
        assert thread.created_at is not None
        assert thread.updated_at is not None

    def test_create_thread_with_metadata(self, thread_store):
        """Thread should store additional metadata."""
        thread = thread_store.create_thread(
            thread_id="meta-thread",
            owner_id="user-456",
            metadata={"source": "web", "version": "1.0"},
        )

        assert thread.metadata["source"] == "web"
        assert thread.metadata["version"] == "1.0"

    def test_create_thread_stored_in_redis(self, thread_store, fake_redis):
        """Thread data should be persisted to Redis."""
        thread_store.create_thread(
            thread_id="persisted-thread",
            owner_id="user-789",
        )

        # Verify stored in Redis
        key = "test_threads:thread:persisted-thread"
        data = fake_redis.get(key)
        assert data is not None

        parsed = json.loads(data)
        assert parsed["id"] == "persisted-thread"
        assert parsed["owner_id"] == "user-789"


class TestThreadRetrieval:
    """Tests for retrieving threads."""

    def test_get_thread_existing(self, thread_store):
        """Getting existing thread should return Thread object."""
        thread_store.create_thread("existing-thread", "user-1")

        retrieved = thread_store.get_thread("existing-thread")

        assert retrieved is not None
        assert retrieved.id == "existing-thread"
        assert retrieved.owner_id == "user-1"

    def test_get_thread_nonexistent(self, thread_store):
        """Getting nonexistent thread should return None."""
        retrieved = thread_store.get_thread("nonexistent-thread")
        assert retrieved is None

    def test_get_or_create_existing(self, thread_store):
        """get_or_create should return existing thread."""
        thread_store.create_thread("existing-1", "owner-1", title="Original")

        retrieved = thread_store.get_or_create_thread(
            "existing-1", "owner-2", title="New"
        )

        # Should return original, not create new
        assert retrieved.owner_id == "owner-1"
        assert retrieved.title == "Original"

    def test_get_or_create_new(self, thread_store):
        """get_or_create should create thread if not exists."""
        thread = thread_store.get_or_create_thread(
            "new-thread", "owner-new", title="Created"
        )

        assert thread.id == "new-thread"
        assert thread.owner_id == "owner-new"
        assert thread.title == "Created"


class TestMessageOperations:
    """Tests for adding and retrieving messages."""

    def test_add_message_to_thread(self, thread_store):
        """Adding a message should store it in the thread."""
        thread_store.create_thread("msg-thread", "user-1")

        message = thread_store.add_message(
            thread_id="msg-thread",
            message_id="msg-1",
            role="user",
            content="Hello, world!",
            user_id="user-1",
        )

        assert message.id == "msg-1"
        assert message.role == "user"
        assert message.content == "Hello, world!"
        assert message.timestamp is not None

    def test_add_message_auto_creates_thread(self, thread_store):
        """Adding message to nonexistent thread should create it."""
        message = thread_store.add_message(
            thread_id="auto-thread",
            message_id="msg-auto",
            role="user",
            content="Auto-created",
            user_id="auto-user",
        )

        assert message.content == "Auto-created"

        # Thread should now exist
        thread = thread_store.get_thread("auto-thread")
        assert thread is not None
        assert thread.owner_id == "auto-user"

    def test_add_message_without_user_id_fails(self, thread_store):
        """Adding message without user_id to nonexistent thread should fail."""
        with pytest.raises(ValueError) as exc_info:
            thread_store.add_message(
                thread_id="no-user-thread",
                message_id="msg-fail",
                role="user",
                content="Will fail",
            )

        assert "not found" in str(exc_info.value).lower()

    def test_add_multiple_messages(self, thread_store):
        """Multiple messages should be stored in order."""
        thread_store.create_thread("multi-msg", "user-1")

        thread_store.add_message("multi-msg", "msg-1", "user", "First", user_id="user-1")
        thread_store.add_message("multi-msg", "msg-2", "assistant", "Second", user_id="user-1")
        thread_store.add_message("multi-msg", "msg-3", "user", "Third", user_id="user-1")

        messages = thread_store.get_messages("multi-msg")

        assert len(messages) == 3
        assert messages[0].content == "First"
        assert messages[1].content == "Second"
        assert messages[2].content == "Third"

    def test_get_messages_with_limit(self, thread_store):
        """get_messages should respect limit parameter."""
        thread_store.create_thread("limit-thread", "user-1")

        for i in range(10):
            thread_store.add_message(
                "limit-thread", f"msg-{i}", "user", f"Message {i}", user_id="user-1"
            )

        messages = thread_store.get_messages("limit-thread", limit=5)
        assert len(messages) == 5

    def test_get_messages_with_offset(self, thread_store):
        """get_messages should respect offset parameter."""
        thread_store.create_thread("offset-thread", "user-1")

        for i in range(5):
            thread_store.add_message(
                "offset-thread", f"msg-{i}", "user", f"Message {i}", user_id="user-1"
            )

        messages = thread_store.get_messages("offset-thread", offset=2)
        assert len(messages) == 3
        assert messages[0].content == "Message 2"

    def test_get_messages_nonexistent_thread(self, thread_store):
        """get_messages for nonexistent thread should return empty list."""
        messages = thread_store.get_messages("nonexistent")
        assert messages == []

    def test_message_with_tool_metadata(self, thread_store):
        """Message should store tool-related metadata."""
        thread_store.create_thread("tool-thread", "user-1")

        message = thread_store.add_message(
            thread_id="tool-thread",
            message_id="tool-msg",
            role="tool",
            content='{"result": "success"}',
            user_id="user-1",
            tool_call_id="call-123",
            tool_name="glm_analysis",
        )

        assert message.tool_call_id == "call-123"
        assert message.tool_name == "glm_analysis"


class TestAccessControl:
    """Tests for thread access control."""

    def test_check_access_owner(self, thread_store):
        """Owner should have access to their thread."""
        thread_store.create_thread("access-1", "owner-user")

        assert thread_store.check_access("access-1", "owner-user") is True

    def test_check_access_non_owner(self, thread_store):
        """Non-owner should not have access to thread."""
        thread_store.create_thread("access-2", "owner-user")

        assert thread_store.check_access("access-2", "other-user") is False

    def test_check_access_nonexistent(self, thread_store):
        """Nonexistent thread should allow access (for creation)."""
        assert thread_store.check_access("nonexistent", "any-user") is True


class TestListUserThreads:
    """Tests for listing user's threads."""

    def test_list_user_threads_basic(self, thread_store):
        """Should list threads owned by user."""
        thread_store.create_thread("user1-thread-1", "user-1", title="Thread 1")
        thread_store.create_thread("user1-thread-2", "user-1", title="Thread 2")
        thread_store.create_thread("user2-thread-1", "user-2", title="Other User")

        threads = thread_store.list_user_threads("user-1")

        assert len(threads) == 2
        thread_ids = [t["id"] for t in threads]
        assert "user1-thread-1" in thread_ids
        assert "user1-thread-2" in thread_ids
        assert "user2-thread-1" not in thread_ids

    def test_list_user_threads_with_limit(self, thread_store):
        """Should respect limit parameter."""
        for i in range(10):
            thread_store.create_thread(f"limited-{i}", "limit-user")

        threads = thread_store.list_user_threads("limit-user", limit=5)
        assert len(threads) == 5

    def test_list_user_threads_without_messages(self, thread_store):
        """By default, should not include messages in listing."""
        thread_store.create_thread("msg-thread", "user-1")
        thread_store.add_message("msg-thread", "msg-1", "user", "Hello", user_id="user-1")

        threads = thread_store.list_user_threads("user-1")

        assert len(threads) == 1
        assert "messages" not in threads[0]

    def test_list_user_threads_with_messages(self, thread_store):
        """With include_messages=True, should include messages."""
        thread_store.create_thread("msg-thread-2", "user-1")
        thread_store.add_message("msg-thread-2", "msg-1", "user", "Hello", user_id="user-1")

        threads = thread_store.list_user_threads("user-1", include_messages=True)

        assert len(threads) == 1
        assert "messages" in threads[0]
        assert len(threads[0]["messages"]) == 1


class TestDeleteThread:
    """Tests for thread deletion."""

    def test_delete_thread_by_owner(self, thread_store):
        """Owner should be able to delete their thread."""
        thread_store.create_thread("delete-me", "owner-1")

        result = thread_store.delete_thread("delete-me", "owner-1")

        assert result is True
        assert thread_store.get_thread("delete-me") is None

    def test_delete_thread_non_owner(self, thread_store):
        """Non-owner should not be able to delete thread."""
        thread_store.create_thread("protected", "owner-1")

        result = thread_store.delete_thread("protected", "attacker")

        assert result is False
        # Thread should still exist
        assert thread_store.get_thread("protected") is not None

    def test_delete_nonexistent_thread(self, thread_store):
        """Deleting nonexistent thread should return False."""
        result = thread_store.delete_thread("nonexistent", "anyone")
        assert result is False


class TestMessageToDict:
    """Tests for Message.to_dict() method."""

    def test_message_to_dict_basic(self):
        """to_dict should include all non-None fields."""
        from brain_researcher.services.agent.thread_store import Message

        msg = Message(
            id="msg-1",
            role="user",
            content="Test content",
            timestamp="2024-01-01T00:00:00",
            user_id="user-123",
        )

        d = msg.to_dict()

        assert d["id"] == "msg-1"
        assert d["role"] == "user"
        assert d["content"] == "Test content"
        assert d["timestamp"] == "2024-01-01T00:00:00"
        assert d["user_id"] == "user-123"

    def test_message_to_dict_excludes_none(self):
        """to_dict should exclude None fields."""
        from brain_researcher.services.agent.thread_store import Message

        msg = Message(
            id="msg-2",
            role="assistant",
            content="Response",
            timestamp="2024-01-01T00:00:00",
            # user_id is None
        )

        d = msg.to_dict()

        assert "user_id" not in d
        assert "tool_call_id" not in d
        assert "tool_name" not in d


class TestThreadToDict:
    """Tests for Thread.to_dict() method."""

    def test_thread_to_dict_basic(self, thread_store):
        """Thread.to_dict should include message_count."""
        thread = thread_store.create_thread("dict-thread", "user-1", title="Test")

        d = thread.to_dict()

        assert d["id"] == "dict-thread"
        assert d["owner_id"] == "user-1"
        assert d["title"] == "Test"
        assert d["message_count"] == 0
        assert d["messages"] == []

    def test_thread_to_dict_with_messages(self, thread_store):
        """Thread.to_dict should serialize messages."""
        thread_store.create_thread("msg-dict", "user-1")
        thread_store.add_message("msg-dict", "m1", "user", "Hello", user_id="user-1")

        thread = thread_store.get_thread("msg-dict")
        d = thread.to_dict()

        assert d["message_count"] == 1
        assert len(d["messages"]) == 1
        assert d["messages"][0]["content"] == "Hello"


class TestSingletonInstance:
    """Tests for singleton get_thread_store() function."""

    def test_get_thread_store_returns_instance(self):
        """get_thread_store should return a ThreadStore instance."""
        from brain_researcher.services.agent.thread_store import get_thread_store

        store = get_thread_store()
        assert store is not None

    def test_get_thread_store_is_singleton(self):
        """Multiple calls should return the same instance."""
        from brain_researcher.services.agent.thread_store import get_thread_store

        store1 = get_thread_store()
        store2 = get_thread_store()

        assert store1 is store2


class TestRedisKeyGeneration:
    """Tests for Redis key generation."""

    def test_thread_key_format(self, thread_store):
        """Thread keys should follow namespace:thread:id pattern."""
        key = thread_store._thread_key("my-thread")
        assert key == "test_threads:thread:my-thread"

    def test_user_threads_key_format(self, thread_store):
        """User threads keys should follow namespace:user:id:threads pattern."""
        key = thread_store._user_threads_key("user-123")
        assert key == "test_threads:user:user-123:threads"


class TestThreadStoreConfiguration:
    """Tests for ThreadStore environment configuration."""

    def test_ttl_from_env(self, monkeypatch, fake_redis):
        """TTL should be read from THREAD_STORE_TTL_DAYS env var."""
        from brain_researcher.services.agent.thread_store import ThreadStore

        monkeypatch.setenv('THREAD_STORE_TTL_DAYS', '7')
        store = ThreadStore(redis_client=fake_redis)

        # 7 days in seconds
        assert store.ttl_seconds == 7 * 24 * 3600

    def test_ttl_default(self, fake_redis, monkeypatch):
        """TTL should default to 30 days if not set."""
        from brain_researcher.services.agent.thread_store import ThreadStore

        # Ensure env var is not set
        monkeypatch.delenv('THREAD_STORE_TTL_DAYS', raising=False)
        store = ThreadStore(redis_client=fake_redis)

        # 30 days in seconds
        assert store.ttl_seconds == 30 * 24 * 3600

    def test_ttl_explicit_overrides_env(self, monkeypatch, fake_redis):
        """Explicit ttl_days parameter should override env var."""
        from brain_researcher.services.agent.thread_store import ThreadStore

        monkeypatch.setenv('THREAD_STORE_TTL_DAYS', '7')
        store = ThreadStore(redis_client=fake_redis, ttl_days=14)

        # Should use explicit 14 days, not env's 7
        assert store.ttl_seconds == 14 * 24 * 3600

    def test_is_persistent_false_for_fakeredis(self, fake_redis):
        """is_persistent should be False for fakeredis."""
        from brain_researcher.services.agent.thread_store import ThreadStore

        store = ThreadStore(redis_client=fake_redis)
        assert store.is_persistent is False

    def test_close_no_error(self, thread_store):
        """close() should not raise even if called multiple times."""
        # Should not raise
        thread_store.close()
        thread_store.close()

    def test_close_with_no_close_method(self):
        """close() should handle Redis clients without close method."""
        from brain_researcher.services.agent.thread_store import ThreadStore
        from unittest.mock import MagicMock

        # Mock a Redis client without close method
        mock_redis = MagicMock(spec=['get', 'set', 'delete', 'ping', 'expire', 'sadd', 'srem', 'smembers'])
        store = ThreadStore(redis_client=mock_redis, ttl_days=1)

        # Should not raise even without close method
        store.close()

    def test_redis_url_env_fallback(self, monkeypatch):
        """Should fall back to REDIS_URL if THREAD_STORE_REDIS_URL not set."""
        from brain_researcher.services.agent.thread_store import ThreadStore
        from unittest.mock import patch, MagicMock

        monkeypatch.delenv('THREAD_STORE_REDIS_URL', raising=False)
        monkeypatch.setenv('REDIS_URL', 'redis://fallback:6379/1')

        mock_client = MagicMock()
        mock_client.ping.return_value = True

        with patch('redis.from_url', return_value=mock_client) as mock_from_url:
            store = ThreadStore()
            # Should have called with REDIS_URL value
            mock_from_url.assert_called_once()
            call_args = mock_from_url.call_args
            assert call_args[0][0] == 'redis://fallback:6379/1'

    def test_thread_store_redis_url_priority(self, monkeypatch):
        """THREAD_STORE_REDIS_URL should take priority over REDIS_URL."""
        from brain_researcher.services.agent.thread_store import ThreadStore
        from unittest.mock import patch, MagicMock

        monkeypatch.setenv('THREAD_STORE_REDIS_URL', 'redis://dedicated:6379/2')
        monkeypatch.setenv('REDIS_URL', 'redis://fallback:6379/1')

        mock_client = MagicMock()
        mock_client.ping.return_value = True

        with patch('redis.from_url', return_value=mock_client) as mock_from_url:
            store = ThreadStore()
            # Should have called with THREAD_STORE_REDIS_URL value
            mock_from_url.assert_called_once()
            call_args = mock_from_url.call_args
            assert call_args[0][0] == 'redis://dedicated:6379/2'
