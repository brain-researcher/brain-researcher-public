"""Agent Streaming Data Integration.

This module integrates the streaming data system (INGEST-020) with the agent service
to provide real-time data processing capabilities.

Relocated from ``services.agent`` to ``services.tools`` (round 2 services-layer
DAG work). It carries no agent-layer dependencies and is instantiated by
``tools.tool_registry``; relocating it removes a ``tools -> agent`` import
back-edge. The public symbols are re-exported from
``brain_researcher.services.agent.streaming_integration`` for backward
compatibility.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from brain_researcher.core.ingestion.streaming.real_time_streaming import (
    ProcessingResult,
    RealTimeStreaming,
    StreamMessage,
    StreamProcessor,
    StreamType,
)

logger = logging.getLogger(__name__)


class AgentStreamType(Enum):
    """Stream types specific to agent processing."""

    USER_QUERIES = "user_queries"
    ANALYSIS_REQUESTS = "analysis_requests"
    TOOL_EXECUTIONS = "tool_executions"
    RESULTS = "results"


@dataclass
class AgentStreamMessage:
    """Agent-specific stream message."""

    message_id: str
    thread_id: str
    user_id: str | None
    message_type: AgentStreamType
    payload: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    priority: int = 0


class AgentStreamProcessor(StreamProcessor):
    """Base processor for agent stream messages."""

    def __init__(self, agent_state_machine=None):
        """Initialize processor.

        Args:
            agent_state_machine: Reference to core agent state machine
        """
        self.agent = agent_state_machine

    async def process(self, message: StreamMessage) -> ProcessingResult:
        """Process a stream message.

        Args:
            message: Message to process

        Returns:
            Processing result
        """
        try:
            # Convert to agent message format
            agent_message = self._convert_to_agent_message(message)

            # Process based on message type
            if agent_message.message_type == AgentStreamType.USER_QUERIES:
                result = await self._process_user_query(agent_message)
            elif agent_message.message_type == AgentStreamType.ANALYSIS_REQUESTS:
                result = await self._process_analysis_request(agent_message)
            elif agent_message.message_type == AgentStreamType.TOOL_EXECUTIONS:
                result = await self._process_tool_execution(agent_message)
            else:
                result = await self._process_generic_message(agent_message)

            return ProcessingResult(
                message_id=message.message_id,
                success=True,
                processing_time_ms=result.get("processing_time", 0),
                output_data=result
            )

        except Exception as e:
            logger.error(f"Error processing agent stream message: {e}", exc_info=True)
            return ProcessingResult(
                message_id=message.message_id,
                success=False,
                error=str(e)
            )

    def _convert_to_agent_message(self, message: StreamMessage) -> AgentStreamMessage:
        """Convert stream message to agent message format."""
        return AgentStreamMessage(
            message_id=message.message_id,
            thread_id=message.value.get("thread_id", "unknown"),
            user_id=message.value.get("user_id"),
            message_type=AgentStreamType(message.value.get("type", "user_queries")),
            payload=message.value.get("payload", {}),
            timestamp=message.timestamp,
            priority=message.value.get("priority", 0)
        )

    async def _process_user_query(self, message: AgentStreamMessage) -> dict[str, Any]:
        """Process user query from stream."""
        start_time = datetime.now()

        query = message.payload.get("query", "")

        # If agent is available, process the query
        if self.agent:
            try:
                # Use the agent's run method to process the query
                result = await asyncio.to_thread(
                    self.agent.run,
                    query,
                    thread_id=message.thread_id
                )

                processing_time = (datetime.now() - start_time).total_seconds() * 1000

                return {
                    "type": "query_response",
                    "thread_id": message.thread_id,
                    "response": result,
                    "processing_time": processing_time
                }

            except Exception as e:
                logger.error(f"Error processing query through agent: {e}")
                return {
                    "type": "error",
                    "error": str(e),
                    "thread_id": message.thread_id
                }
        else:
            # Fallback processing without agent
            return {
                "type": "acknowledgment",
                "message": f"Received query: {query[:100]}...",
                "thread_id": message.thread_id
            }

    async def _process_analysis_request(self, message: AgentStreamMessage) -> dict[str, Any]:
        """Process analysis request from stream."""
        analysis_type = message.payload.get("analysis_type", "unknown")
        parameters = message.payload.get("parameters", {})

        logger.info(f"Processing analysis request: {analysis_type}")

        # Mock analysis processing
        await asyncio.sleep(0.1)  # Simulate processing

        return {
            "type": "analysis_started",
            "analysis_type": analysis_type,
            "analysis_id": f"analysis_{message.message_id}",
            "thread_id": message.thread_id,
            "parameters": parameters
        }

    async def _process_tool_execution(self, message: AgentStreamMessage) -> dict[str, Any]:
        """Process tool execution from stream."""
        tool_name = message.payload.get("tool_name", "unknown")
        tool_args = message.payload.get("tool_args", {})

        logger.info(f"Processing tool execution: {tool_name}")

        # If agent is available, execute the tool
        if self.agent and hasattr(self.agent, 'tool_registry'):
            try:
                tool = self.agent.tool_registry.get_tool(tool_name)
                if tool:
                    result = tool.run(**tool_args)

                    return {
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "result": result,
                        "thread_id": message.thread_id
                    }
                else:
                    return {
                        "type": "error",
                        "error": f"Tool {tool_name} not found",
                        "thread_id": message.thread_id
                    }

            except Exception as e:
                logger.error(f"Error executing tool {tool_name}: {e}")
                return {
                    "type": "error",
                    "error": str(e),
                    "thread_id": message.thread_id
                }
        else:
            return {
                "type": "acknowledgment",
                "message": f"Received tool execution request for {tool_name}",
                "thread_id": message.thread_id
            }

    async def _process_generic_message(self, message: AgentStreamMessage) -> dict[str, Any]:
        """Process generic message from stream."""
        return {
            "type": "processed",
            "message_type": message.message_type.value,
            "thread_id": message.thread_id,
            "payload": message.payload
        }


class AgentStreamingManager:
    """Manages streaming integration for agent service."""

    def __init__(self, agent_state_machine=None, kafka_config=None, redis_client=None):
        """Initialize streaming manager.

        Args:
            agent_state_machine: Core agent state machine
            kafka_config: Kafka configuration
            redis_client: Optional Redis client
        """
        self.agent = agent_state_machine
        self.streaming = RealTimeStreaming(kafka_config, redis_client)

        # Active stream configurations
        self.stream_configs = {}

        # Message handlers
        self.message_handlers: dict[str, Callable] = {}

        # Statistics
        self.stats = {
            "streams_configured": 0,
            "messages_processed": 0,
            "processing_errors": 0
        }

    async def setup_streams(self):
        """Set up default streams for agent processing."""

        # Configure user query stream
        await self._configure_query_stream()

        # Configure analysis request stream
        await self._configure_analysis_stream()

        # Configure tool execution stream
        await self._configure_tool_stream()

        # Configure results stream
        await self._configure_results_stream()

        # Register processors
        await self._register_processors()

        # Start streaming system
        await self.streaming.start()

        logger.info("Agent streaming integration setup completed")

    async def _configure_query_stream(self):
        """Configure user query stream."""
        config = self.streaming.configure_stream(
            topic="agent.queries",
            stream_type=StreamType.BEHAVIORAL,  # Closest match
            consumer_group="agent-service",
            batch_size=50,
            batch_timeout_ms=500
        )

        self.stream_configs["queries"] = config
        self.stats["streams_configured"] += 1

    async def _configure_analysis_stream(self):
        """Configure analysis request stream."""
        config = self.streaming.configure_stream(
            topic="agent.analysis",
            stream_type=StreamType.NEUROIMAGING,
            consumer_group="agent-service",
            batch_size=20,
            batch_timeout_ms=1000
        )

        self.stream_configs["analysis"] = config
        self.stats["streams_configured"] += 1

    async def _configure_tool_stream(self):
        """Configure tool execution stream."""
        config = self.streaming.configure_stream(
            topic="agent.tools",
            stream_type=StreamType.ANNOTATION,
            consumer_group="agent-service",
            batch_size=30,
            batch_timeout_ms=800
        )

        self.stream_configs["tools"] = config
        self.stats["streams_configured"] += 1

    async def _configure_results_stream(self):
        """Configure results stream."""
        config = self.streaming.configure_stream(
            topic="agent.results",
            stream_type=StreamType.NEUROIMAGING,
            consumer_group="agent-service",
            batch_size=25,
            batch_timeout_ms=1200
        )

        self.stream_configs["results"] = config
        self.stats["streams_configured"] += 1

    async def _register_processors(self):
        """Register stream processors."""

        # Create agent stream processor
        processor = AgentStreamProcessor(self.agent)

        # Register for all stream types
        for stream_type in [StreamType.BEHAVIORAL, StreamType.NEUROIMAGING, StreamType.ANNOTATION]:
            self.streaming.register_processor(stream_type, processor)

        logger.info("Registered agent stream processors")

    async def publish_query(
        self,
        thread_id: str,
        query: str,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None
    ):
        """Publish a user query to the stream.

        Args:
            thread_id: Thread ID
            query: User query
            user_id: Optional user ID
            metadata: Additional metadata
        """
        message_data = {
            "thread_id": thread_id,
            "user_id": user_id,
            "type": "user_queries",
            "payload": {
                "query": query,
                "metadata": metadata or {}
            },
            "timestamp": datetime.now().isoformat()
        }

        # In production, would publish to Kafka
        logger.info(f"Would publish query to stream: {query[:100]}...")
        self.stats["messages_processed"] += 1

    async def publish_analysis_request(
        self,
        thread_id: str,
        analysis_type: str,
        parameters: dict[str, Any],
        user_id: str | None = None
    ):
        """Publish an analysis request to the stream.

        Args:
            thread_id: Thread ID
            analysis_type: Type of analysis
            parameters: Analysis parameters
            user_id: Optional user ID
        """
        message_data = {
            "thread_id": thread_id,
            "user_id": user_id,
            "type": "analysis_requests",
            "payload": {
                "analysis_type": analysis_type,
                "parameters": parameters
            },
            "timestamp": datetime.now().isoformat()
        }

        logger.info(f"Would publish analysis request: {analysis_type}")
        self.stats["messages_processed"] += 1

    async def publish_tool_execution(
        self,
        thread_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        user_id: str | None = None
    ):
        """Publish a tool execution request to the stream.

        Args:
            thread_id: Thread ID
            tool_name: Tool name
            tool_args: Tool arguments
            user_id: Optional user ID
        """
        message_data = {
            "thread_id": thread_id,
            "user_id": user_id,
            "type": "tool_executions",
            "payload": {
                "tool_name": tool_name,
                "tool_args": tool_args
            },
            "timestamp": datetime.now().isoformat()
        }

        logger.info(f"Would publish tool execution: {tool_name}")
        self.stats["messages_processed"] += 1

    def register_message_handler(
        self,
        message_type: AgentStreamType,
        handler: Callable
    ):
        """Register a custom message handler.

        Args:
            message_type: Type of message to handle
            handler: Handler function
        """
        self.message_handlers[message_type.value] = handler
        logger.info(f"Registered handler for {message_type.value}")

    async def stop(self):
        """Stop the streaming system."""
        await self.streaming.stop()
        logger.info("Agent streaming system stopped")

    def get_statistics(self) -> dict[str, Any]:
        """Get streaming statistics."""
        streaming_stats = self.streaming.get_statistics()

        return {
            "agent_stats": self.stats,
            "streaming_stats": streaming_stats
        }


# Integration helper functions
async def setup_agent_streaming(
    agent_state_machine,
    kafka_config=None,
    redis_client=None
) -> AgentStreamingManager:
    """Set up agent streaming integration.

    Args:
        agent_state_machine: Core agent state machine
        kafka_config: Optional Kafka configuration
        redis_client: Optional Redis client

    Returns:
        Agent streaming manager
    """
    manager = AgentStreamingManager(agent_state_machine, kafka_config, redis_client)

    # Add streaming manager to state machine
    agent_state_machine.streaming_manager = manager

    # Set up streams
    await manager.setup_streams()

    logger.info("Agent streaming integration setup completed")

    return manager


class StreamingToolWrapper:
    """Wrapper to make agent tools work with streaming system."""

    def __init__(self, tool, streaming_manager: AgentStreamingManager):
        """Initialize wrapper.

        Args:
            tool: Original tool instance
            streaming_manager: Streaming manager
        """
        self.tool = tool
        self.streaming_manager = streaming_manager
        self.original_run = tool.run

        # Wrap the run method
        tool.run = self._streaming_run

    async def _streaming_run(self, *args, **kwargs):
        """Streaming-aware tool execution."""
        # Get thread_id from kwargs if available
        thread_id = kwargs.get("thread_id", "unknown")

        # Publish tool execution to stream
        await self.streaming_manager.publish_tool_execution(
            thread_id=thread_id,
            tool_name=self.tool.get_tool_name(),
            tool_args=kwargs
        )

        # Execute original tool
        result = await asyncio.to_thread(self.original_run, *args, **kwargs)

        # Could publish results to results stream here

        return result


def wrap_tools_for_streaming(
    tool_registry,
    streaming_manager: AgentStreamingManager
):
    """Wrap all tools in registry for streaming.

    Args:
        tool_registry: Tool registry to wrap
        streaming_manager: Streaming manager
    """
    for tool_name, tool in tool_registry.tools.items():
        wrapper = StreamingToolWrapper(tool, streaming_manager)
        logger.debug(f"Wrapped tool {tool_name} for streaming")

    logger.info(f"Wrapped {len(tool_registry.tools)} tools for streaming")
