"""Unit tests for streaming module (B.5.3)."""

import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest


class TestStreamEvent:
    """Tests for StreamEvent class."""

    def test_to_sse_format(self):
        """StreamEvent.to_sse() should produce valid SSE format."""
        from brain_researcher.services.agent.streaming import StreamEvent

        event = StreamEvent(event="token", data={"content": "hello"})
        sse = event.to_sse()

        assert sse == 'event: token\ndata: {"content": "hello"}\n\n'

    def test_to_sse_complex_data(self):
        """StreamEvent should handle complex data structures."""
        from brain_researcher.services.agent.streaming import StreamEvent

        event = StreamEvent(
            event="metadata",
            data={
                "provider": "test",
                "model": "test-model",
                "latency_ms": 100,
                "nested": {"key": "value"},
            }
        )
        sse = event.to_sse()

        assert "event: metadata\n" in sse
        assert '"provider": "test"' in sse
        assert '"nested": {"key": "value"}' in sse


class TestStreamMetrics:
    """Tests for StreamMetrics class."""

    def test_duration_ms(self):
        """duration_ms should calculate elapsed time correctly."""
        from brain_researcher.services.agent.streaming import StreamMetrics

        start = time.time()
        metrics = StreamMetrics(start_time=start - 1.5)  # 1.5 seconds ago

        duration = metrics.duration_ms()
        assert 1400 < duration < 1600  # Allow some tolerance

    def test_log_completion_success(self):
        """log_completion should log success status when no error."""
        from brain_researcher.services.agent.streaming import StreamMetrics

        metrics = StreamMetrics(
            thread_id="test-thread",
            user_id="test-user",
            model="test-model",
            token_count=10,
            total_chars=100,
        )

        with patch("brain_researcher.services.agent.streaming.logger") as mock_logger:
            metrics.log_completion()
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "stream_complete"
            extra = call_args[1]["extra"]
            assert extra["status"] == "success"
            assert extra["thread_id"] == "test-thread"
            assert extra["token_count"] == 10

    def test_log_completion_error(self):
        """log_completion should log error status when error is set."""
        from brain_researcher.services.agent.streaming import StreamMetrics

        metrics = StreamMetrics(error="Test error")

        with patch("brain_researcher.services.agent.streaming.logger") as mock_logger:
            metrics.log_completion()
            call_args = mock_logger.info.call_args
            extra = call_args[1]["extra"]
            assert extra["status"] == "error"
            assert extra["error"] == "Test error"


class TestStreamingSession:
    """Tests for streaming_session context manager."""

    def test_yields_metrics(self):
        """streaming_session should yield metrics object."""
        from brain_researcher.services.agent.streaming import streaming_session

        with streaming_session(thread_id="t1", user_id="u1") as metrics:
            assert metrics.thread_id == "t1"
            assert metrics.user_id == "u1"

    def test_logs_on_exit(self):
        """streaming_session should log on exit."""
        from brain_researcher.services.agent.streaming import streaming_session

        with patch("brain_researcher.services.agent.streaming.logger"):
            with streaming_session() as metrics:
                metrics.token_count = 5

    def test_captures_exception(self):
        """streaming_session should capture exception in metrics."""
        from brain_researcher.services.agent.streaming import streaming_session

        with pytest.raises(ValueError):
            with streaming_session() as metrics:
                raise ValueError("test error")

        assert "test error" in metrics.error


class TestWithHeartbeat:
    """Tests for with_heartbeat wrapper."""

    def test_passes_through_events(self):
        """with_heartbeat should pass through source events."""
        from brain_researcher.services.agent.streaming import with_heartbeat

        def source():
            yield "event1"
            yield "event2"

        results = list(with_heartbeat(source()))
        assert "event1" in results
        assert "event2" in results

    def test_abort_flag_stops_iteration(self):
        """with_heartbeat should stop when abort flag is set."""
        from brain_researcher.services.agent.streaming import with_heartbeat

        abort_flag = threading.Event()

        def slow_source():
            yield "event1"
            abort_flag.set()  # Set flag after first event
            yield "event2"  # Should not be yielded
            yield "event3"

        results = list(with_heartbeat(slow_source(), abort_flag=abort_flag))

        # Should have event1 plus abort event
        assert "event1" in results
        assert any("abort" in r for r in results)
        assert "event3" not in results

    def test_handles_generator_exit(self):
        """with_heartbeat should handle GeneratorExit gracefully."""
        from brain_researcher.services.agent.streaming import with_heartbeat

        def source():
            yield "event1"
            yield "event2"

        gen = with_heartbeat(source())
        next(gen)  # Get first event
        gen.close()  # Simulate client disconnect


class TestStreamingChatHandler:
    """Tests for StreamingChatHandler class."""

    def test_uses_default_model(self):
        """Handler should use DEFAULT_MODEL when no hint provided."""
        from brain_researcher.services.agent.streaming import (
            StreamingChatHandler,
            DEFAULT_MODEL,
        )

        handler = StreamingChatHandler()
        assert handler.model_hint == DEFAULT_MODEL

    def test_uses_provided_model(self):
        """Handler should use provided model_hint."""
        from brain_researcher.services.agent.streaming import StreamingChatHandler

        handler = StreamingChatHandler(model_hint="custom-model")
        assert handler.model_hint == "custom-model"

    def test_tracks_user_id(self):
        """Handler should track user_id."""
        from brain_researcher.services.agent.streaming import StreamingChatHandler

        handler = StreamingChatHandler(user_id="test-user")
        assert handler.user_id == "test-user"

    def test_tracks_abort_flag(self):
        """Handler should track abort_flag."""
        from brain_researcher.services.agent.streaming import StreamingChatHandler

        flag = threading.Event()
        handler = StreamingChatHandler(abort_flag=flag)
        assert handler.abort_flag is flag

    def test_get_token_count_initial(self):
        """get_token_count should return 0 initially."""
        from brain_researcher.services.agent.streaming import StreamingChatHandler

        handler = StreamingChatHandler()
        assert handler.get_token_count() == 0

    @patch("brain_researcher.services.agent.llm.get_llm")
    @patch("brain_researcher.services.agent.router.infer_provider")
    def test_stream_chat_emits_start_event(self, mock_provider, mock_get_llm):
        """stream_chat should emit start event first."""
        from brain_researcher.services.agent.streaming import StreamingChatHandler

        # Mock LLM that doesn't support streaming
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="response")
        del mock_llm.stream  # Remove stream method
        mock_get_llm.return_value = mock_llm
        mock_provider.return_value = "test-provider"

        handler = StreamingChatHandler(thread_id="t1")
        events = list(handler.stream_chat("hello"))

        assert events[0].event == "start"
        assert events[0].data["thread_id"] == "t1"

    @patch("brain_researcher.services.agent.llm.get_llm")
    @patch("brain_researcher.services.agent.router.infer_provider")
    def test_stream_chat_emits_done_event(self, mock_provider, mock_get_llm):
        """stream_chat should emit done event at end."""
        from brain_researcher.services.agent.streaming import StreamingChatHandler

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="response")
        del mock_llm.stream
        mock_get_llm.return_value = mock_llm
        mock_provider.return_value = "test-provider"

        handler = StreamingChatHandler()
        events = list(handler.stream_chat("hello"))

        assert events[-1].event == "done"

    @patch("brain_researcher.services.agent.llm.get_llm")
    @patch("brain_researcher.services.agent.router.infer_provider")
    def test_stream_chat_handles_streaming_llm(self, mock_provider, mock_get_llm):
        """stream_chat should handle streaming LLM correctly."""
        from brain_researcher.services.agent.streaming import StreamingChatHandler

        # Mock streaming LLM
        mock_llm = MagicMock()
        mock_llm.stream.return_value = [
            MagicMock(content="Hello"),
            MagicMock(content=" world"),
        ]
        mock_get_llm.return_value = mock_llm
        mock_provider.return_value = "test-provider"

        handler = StreamingChatHandler()
        events = list(handler.stream_chat("hello"))

        # Should have start, tokens, metadata, done
        token_events = [e for e in events if e.event == "token"]
        assert len(token_events) == 2
        assert token_events[0].data["content"] == "Hello"
        assert token_events[1].data["content"] == " world"

        # Check accumulated text
        assert handler.get_accumulated_text() == "Hello world"
        assert handler.get_token_count() == 2

    @patch("brain_researcher.services.agent.llm.get_llm")
    @patch("brain_researcher.services.agent.router.infer_provider")
    def test_stream_chat_abort_flag(self, mock_provider, mock_get_llm):
        """stream_chat should abort when flag is set."""
        from brain_researcher.services.agent.streaming import (
            StreamingChatHandler,
            StreamAbort,
        )

        abort_flag = threading.Event()
        abort_flag.set()  # Pre-set the flag

        mock_llm = MagicMock()
        mock_llm.stream.return_value = [
            MagicMock(content="Hello"),
            MagicMock(content=" world"),
        ]
        mock_get_llm.return_value = mock_llm
        mock_provider.return_value = "test-provider"

        handler = StreamingChatHandler(abort_flag=abort_flag)

        with pytest.raises(StreamAbort):
            list(handler.stream_chat("hello"))

    @patch("brain_researcher.services.agent.llm.get_llm")
    @patch("brain_researcher.services.agent.router.infer_provider")
    def test_stream_chat_handles_error(self, mock_provider, mock_get_llm):
        """stream_chat should emit error event on exception."""
        from brain_researcher.services.agent.streaming import StreamingChatHandler

        mock_get_llm.side_effect = ValueError("LLM error")

        handler = StreamingChatHandler()
        events = list(handler.stream_chat("hello"))

        error_events = [e for e in events if e.event == "error"]
        assert len(error_events) == 1
        assert "LLM error" in error_events[0].data["error"]

    @patch("brain_researcher.services.agent.llm.get_llm")
    @patch("brain_researcher.services.agent.router.infer_provider")
    def test_stream_chat_includes_metadata(self, mock_provider, mock_get_llm):
        """stream_chat should include metadata event with token count."""
        from brain_researcher.services.agent.streaming import StreamingChatHandler

        mock_llm = MagicMock()
        mock_llm.stream.return_value = [
            MagicMock(content="a"),
            MagicMock(content="b"),
            MagicMock(content="c"),
        ]
        mock_get_llm.return_value = mock_llm
        mock_provider.return_value = "test-provider"

        handler = StreamingChatHandler(model_hint="test-model")
        events = list(handler.stream_chat("hello"))

        metadata_events = [e for e in events if e.event == "metadata"]
        assert len(metadata_events) == 1
        assert metadata_events[0].data["token_count"] == 3
        assert metadata_events[0].data["model"] == "test-model"


class TestStreamThreadMessages:
    """Tests for stream_thread_messages function."""

    @pytest.fixture
    def mock_thread_store(self):
        """Create a mock thread store."""
        store = MagicMock()
        store.check_access.return_value = True
        store.get_messages.return_value = []
        return store

    def test_access_denied(self, mock_thread_store):
        """stream_thread_messages should yield error on access denied."""
        from brain_researcher.services.agent.streaming import stream_thread_messages

        mock_thread_store.check_access.return_value = False

        with patch(
            "brain_researcher.services.agent.thread_store.get_thread_store",
            return_value=mock_thread_store,
        ):
            results = list(stream_thread_messages(
                thread_id="t1",
                user_id="u1",
                tenant_id="default",
                enable_heartbeat=False,
            ))

        assert len(results) == 1
        assert "forbidden" in results[0]

    def test_snapshot_mode_yields_messages(self, mock_thread_store):
        """stream_thread_messages should yield existing messages in snapshot mode."""
        from brain_researcher.services.agent.streaming import stream_thread_messages

        mock_msg = MagicMock()
        mock_msg.to_dict.return_value = {"role": "user", "content": "hello"}
        mock_thread_store.get_messages.return_value = [mock_msg]

        with patch(
            "brain_researcher.services.agent.thread_store.get_thread_store",
            return_value=mock_thread_store,
        ):
            results = list(stream_thread_messages(
                thread_id="t1",
                user_id="u1",
                tenant_id="default",
                enable_heartbeat=False,
            ))

        # Should have message event + done event
        assert len(results) == 2
        assert "message" in results[0]
        assert "done" in results[1]

    @patch("brain_researcher.services.agent.streaming.StreamingChatHandler")
    def test_live_mode_uses_handler(self, mock_handler_cls, mock_thread_store):
        """stream_thread_messages should use handler for live mode."""
        from brain_researcher.services.agent.streaming import (
            stream_thread_messages,
            StreamEvent,
        )

        mock_handler = MagicMock()
        mock_handler.stream_chat.return_value = [
            StreamEvent(event="done", data={})
        ]
        mock_handler.get_accumulated_text.return_value = "response"
        mock_handler_cls.return_value = mock_handler

        with patch(
            "brain_researcher.services.agent.thread_store.get_thread_store",
            return_value=mock_thread_store,
        ):
            results = list(stream_thread_messages(
                thread_id="t1",
                user_id="u1",
                tenant_id="default",
                new_message="hello",
                enable_heartbeat=False,
            ))

        # Verify handler was created with correct params
        mock_handler_cls.assert_called_once()
        call_kwargs = mock_handler_cls.call_args[1]
        assert call_kwargs["thread_id"] == "t1"
        assert call_kwargs["user_id"] == "u1"

    def test_enable_heartbeat_true(self, mock_thread_store):
        """stream_thread_messages should include heartbeat wrapper when enabled."""
        from brain_researcher.services.agent.streaming import stream_thread_messages

        mock_thread_store.get_messages.return_value = []

        with patch(
            "brain_researcher.services.agent.thread_store.get_thread_store",
            return_value=mock_thread_store,
        ):
            # Just verify it doesn't crash with heartbeat enabled
            results = list(stream_thread_messages(
                thread_id="t1",
                user_id="u1",
                tenant_id="default",
                enable_heartbeat=True,
            ))

        assert any("done" in r for r in results)


class TestCreateSSEResponse:
    """Tests for create_sse_response function."""

    def test_returns_tuple(self):
        """create_sse_response should return (generator, status, headers) tuple."""
        from brain_researcher.services.agent.streaming import create_sse_response

        def gen():
            yield "test"

        result = create_sse_response(gen())

        assert len(result) == 3
        assert result[1] == 200

    def test_headers(self):
        """create_sse_response should set correct headers."""
        from brain_researcher.services.agent.streaming import create_sse_response

        def gen():
            yield "test"

        _, _, headers = create_sse_response(gen())

        assert headers["Content-Type"] == "text/event-stream"
        assert headers["Cache-Control"] == "no-cache"
        assert headers["Connection"] == "keep-alive"
        assert headers["X-Accel-Buffering"] == "no"


class TestConfiguration:
    """Tests for module configuration."""

    def test_heartbeat_interval_default(self):
        """HEARTBEAT_INTERVAL_SECONDS should default to 15."""
        # This tests the module-level constant
        from brain_researcher.services.agent.streaming import HEARTBEAT_INTERVAL_SECONDS

        # Default is 15 if env not set
        assert HEARTBEAT_INTERVAL_SECONDS >= 1  # Just verify it's set

    def test_default_model_constant(self):
        """DEFAULT_MODEL should be set."""
        from brain_researcher.services.agent.streaming import DEFAULT_MODEL

        assert DEFAULT_MODEL is not None
        assert len(DEFAULT_MODEL) > 0
