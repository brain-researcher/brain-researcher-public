"""
Real-time SSE Streaming for Agent Chat (B.3)

Provides token-by-token streaming from LLM responses to SSE events.
Uses LangChain's .stream() method for compatible models.

Features (B.5.3):
- Heartbeat/keep-alive every ~15s to prevent connection timeouts
- Client disconnect detection with LLM abort
- Structured logging (thread_id, user_id, model, duration, tokens)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, Iterator, Optional

logger = logging.getLogger(__name__)

# Configuration
HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("SSE_HEARTBEAT_INTERVAL", "15"))
DEFAULT_MODEL = os.getenv("DEFAULT_LLM_MODEL", "gemini-3-flash-preview")


class StreamAbort(Exception):
    """Raised when streaming should be aborted (e.g., client disconnect)."""

    pass


@dataclass
class StreamMetrics:
    """Metrics for a streaming session."""

    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    model: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    token_count: int = 0
    total_chars: int = 0
    error: Optional[str] = None

    def duration_ms(self) -> int:
        """Get duration in milliseconds."""
        return int((time.time() - self.start_time) * 1000)

    def log_completion(self) -> None:
        """Log structured metrics on stream completion."""
        status = "error" if self.error else "success"
        logger.info(
            "stream_complete",
            extra={
                "thread_id": self.thread_id,
                "user_id": self.user_id,
                "model": self.model,
                "duration_ms": self.duration_ms(),
                "token_count": self.token_count,
                "total_chars": self.total_chars,
                "status": status,
                "error": self.error,
            },
        )


@contextmanager
def streaming_session(
    thread_id: Optional[str] = None,
    user_id: Optional[str] = None,
    model: Optional[str] = None,
):
    """
    Context manager for tracking streaming sessions.

    Logs structured metrics on completion.
    """
    metrics = StreamMetrics(
        thread_id=thread_id,
        user_id=user_id,
        model=model,
    )
    try:
        yield metrics
    except StreamAbort as e:
        metrics.error = f"aborted: {e}"
        raise
    except Exception as e:
        metrics.error = str(e)
        raise
    finally:
        metrics.log_completion()


def with_heartbeat(
    generator: Generator[str, None, None],
    interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS,
    abort_flag: Optional[threading.Event] = None,
) -> Generator[str, None, None]:
    """
    Wrap a generator with periodic heartbeat events.

    Emits SSE comments (`: heartbeat`) every interval_seconds to keep
    connections alive. Checks abort_flag to allow early termination.

    Args:
        generator: Source generator yielding SSE strings
        interval_seconds: Heartbeat interval (default from env)
        abort_flag: Optional threading.Event to signal abort

    Yields:
        SSE-formatted strings including heartbeats
    """
    last_heartbeat = time.time()

    # Use iterator for manual control
    gen_iter = iter(generator)

    while True:
        # Check abort flag
        if abort_flag and abort_flag.is_set():
            logger.debug("Streaming aborted via flag")
            yield f"event: abort\ndata: {json.dumps({'reason': 'client_disconnect'})}\n\n"
            break

        # Try to get next item with timeout behavior
        try:
            # Non-blocking approach: yield heartbeats while waiting
            now = time.time()
            if now - last_heartbeat >= interval_seconds:
                # Emit heartbeat comment (SSE comment format)
                yield ": heartbeat\n\n"
                last_heartbeat = now

            # Get next item from generator
            try:
                item = next(gen_iter)
                yield item
            except StopIteration:
                break

        except GeneratorExit:
            # Client disconnected
            logger.info("Client disconnected during streaming")
            break


@dataclass
class StreamEvent:
    """A single SSE event to send to the client.

    Supported event values now include coding loop progress events
    ("plan", "patch", "test", "done") in addition to the standard
    "token"/"metadata"/"error" stream markers.
    """

    event: str  # token | tool_start | tool_result | metadata | plan | patch | test | done | error | abort
    data: Dict[str, Any]

    def to_sse(self) -> str:
        """Format as SSE message."""
        return f"event: {self.event}\ndata: {json.dumps(self.data)}\n\n"


class StreamingChatHandler:
    """
    Handles streaming chat responses via LangChain's .stream() method.

    Yields StreamEvents that can be converted to SSE format.
    Tracks metrics for structured logging.
    """

    def __init__(
        self,
        model_hint: Optional[str] = None,
        thread_id: Optional[str] = None,
        user_id: Optional[str] = None,
        abort_flag: Optional[threading.Event] = None,
    ):
        self.model_hint = model_hint or DEFAULT_MODEL
        self.thread_id = thread_id
        self.user_id = user_id
        self.abort_flag = abort_flag
        self._accumulated_text = ""
        self._token_count = 0

    def stream_chat(
        self,
        message: str,
        *,
        history: Optional[list] = None,
    ) -> Generator[StreamEvent, None, None]:
        """
        Stream a chat response token by token.

        Yields:
            StreamEvent objects for each token, metadata, and completion.
        """
        from brain_researcher.services.agent.llm import get_llm
        from brain_researcher.services.agent.router import infer_provider

        start_time = time.time()
        self._accumulated_text = ""
        self._token_count = 0

        # Log stream start
        logger.info(
            "stream_start",
            extra={
                "thread_id": self.thread_id,
                "user_id": self.user_id,
                "model": self.model_hint,
                "message_length": len(message),
            },
        )

        # Emit start event
        yield StreamEvent(
            event="start",
            data={
                "thread_id": self.thread_id,
                "model": self.model_hint,
                "timestamp": time.time(),
            },
        )

        try:
            # Get LLM instance
            llm = get_llm(self.model_hint)
            provider = infer_provider(self.model_hint)

            # Check if streaming is supported
            if hasattr(llm, "stream"):
                # Use streaming
                for chunk in llm.stream(message):
                    # Check abort flag
                    if self.abort_flag and self.abort_flag.is_set():
                        logger.info("LLM streaming aborted by client disconnect")
                        raise StreamAbort("client_disconnect")

                    content = getattr(chunk, "content", None)
                    if content:
                        self._accumulated_text += content
                        self._token_count += 1
                        yield StreamEvent(
                            event="token",
                            data={
                                "content": content,
                                "accumulated_length": len(self._accumulated_text),
                            },
                        )
            else:
                # Fallback to non-streaming
                logger.info(
                    "Model %s does not support streaming, using invoke()",
                    self.model_hint,
                )
                response = llm.invoke(message)
                content = getattr(response, "content", None) or str(response)
                self._accumulated_text = content
                self._token_count = 1  # Count as single token for non-streaming

                # Send full response as single token event
                yield StreamEvent(
                    event="token",
                    data={
                        "content": content,
                        "accumulated_length": len(content),
                    },
                )

            # Emit metadata event
            latency_ms = int((time.time() - start_time) * 1000)
            yield StreamEvent(
                event="metadata",
                data={
                    "provider": provider,
                    "model": self.model_hint,
                    "latency_ms": latency_ms,
                    "total_length": len(self._accumulated_text),
                    "token_count": self._token_count,
                },
            )

            # Emit done event
            yield StreamEvent(
                event="done",
                data={
                    "thread_id": self.thread_id,
                    "total_length": len(self._accumulated_text),
                },
            )

            # Log completion
            logger.info(
                "stream_complete",
                extra={
                    "thread_id": self.thread_id,
                    "user_id": self.user_id,
                    "model": self.model_hint,
                    "duration_ms": latency_ms,
                    "token_count": self._token_count,
                    "total_chars": len(self._accumulated_text),
                    "status": "success",
                },
            )

        except StreamAbort:
            # Client disconnect - don't log as error
            yield StreamEvent(
                event="abort",
                data={
                    "reason": "client_disconnect",
                    "thread_id": self.thread_id,
                },
            )
            raise

        except Exception as exc:
            logger.exception("Streaming chat error: %s", exc)
            yield StreamEvent(
                event="error",
                data={
                    "error": str(exc),
                    "type": type(exc).__name__,
                },
            )

    def get_accumulated_text(self) -> str:
        """Get the full accumulated response text."""
        return self._accumulated_text

    def get_token_count(self) -> int:
        """Get the number of tokens streamed."""
        return self._token_count


def stream_thread_messages(
    thread_id: str,
    user_id: str,
    tenant_id: str = "default",
    new_message: Optional[str] = None,
    model_hint: Optional[str] = None,
    abort_flag: Optional[threading.Event] = None,
    enable_heartbeat: bool = True,
) -> Generator[str, None, None]:
    """
    Stream thread messages as SSE events.

    If new_message is provided, streams live LLM response.
    Otherwise, streams existing thread history.

    Args:
        thread_id: Thread identifier
        user_id: User ID for access control
        new_message: Optional new user message to process
        model_hint: Optional model override
        abort_flag: Optional threading.Event to signal abort
        enable_heartbeat: Whether to wrap with heartbeat (default True)

    Yields:
        SSE-formatted strings
    """
    from brain_researcher.services.agent.thread_store import get_thread_store

    store = get_thread_store()

    # Check access
    if not store.check_access(thread_id, user_id, tenant_id=tenant_id):
        yield StreamEvent(
            event="error",
            data={"error": "forbidden", "detail": "Access denied to thread"},
        ).to_sse()
        return

    def _inner_generator():
        """Inner generator without heartbeat wrapper."""
        if new_message:
            # Stream live LLM response
            handler = StreamingChatHandler(
                model_hint=model_hint,
                thread_id=thread_id,
                user_id=user_id,
                abort_flag=abort_flag,
            )

            # Get existing messages for context
            existing_messages = store.get_messages(thread_id)
            history = [
                {"role": m.role, "content": m.content} for m in existing_messages[-10:]
            ]

            try:
                for event in handler.stream_chat(new_message, history=history):
                    yield event.to_sse()

                # Save the accumulated response to thread
                if handler.get_accumulated_text():
                    import uuid

                    store.add_message(
                        thread_id=thread_id,
                        message_id=str(uuid.uuid4()),
                        role="assistant",
                        content=handler.get_accumulated_text(),
                        user_id=user_id,
                        tenant_id=tenant_id,
                    )
            except StreamAbort:
                # Client disconnected - already logged in handler
                logger.debug("Stream aborted for thread %s", thread_id)
                return
        else:
            # Stream existing messages (snapshot mode)
            messages = store.get_messages(thread_id)
            for msg in messages:
                yield StreamEvent(event="message", data=msg.to_dict()).to_sse()

            yield StreamEvent(
                event="done",
                data={"thread_id": thread_id, "message_count": len(messages)},
            ).to_sse()

    # Apply heartbeat wrapper if enabled
    inner = _inner_generator()
    if enable_heartbeat:
        yield from with_heartbeat(inner, abort_flag=abort_flag)
    else:
        yield from inner


def create_sse_response(
    generator: Generator[str, None, None],
) -> tuple:
    """
    Create Flask response tuple for SSE streaming.

    Args:
        generator: Generator yielding SSE-formatted strings

    Returns:
        Tuple of (generator, status_code, headers)
    """
    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # Disable nginx buffering
    }
    return generator, 200, headers
