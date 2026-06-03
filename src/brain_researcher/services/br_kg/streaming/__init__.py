"""Graph streaming infrastructure for real-time graph updates.

This module provides change data capture (CDC), Kafka integration, and complex
event processing for the knowledge graph to enable streaming analytics and
real-time updates.

Key Components:
- CDC Processor: Captures changes from Neo4j
- Kafka Integration: Distributed streaming platform
- Stream Processor: Complex event processing and aggregation
"""

from .cdc_processor import CDCProcessor, GraphChangeEvent
from .kafka_integration import KafkaProducer, KafkaConsumer, StreamConfig
from .stream_processor import StreamProcessor, EventWindow, AggregationRule

__all__ = [
    "CDCProcessor",
    "GraphChangeEvent",
    "KafkaProducer",
    "KafkaConsumer",
    "StreamConfig",
    "StreamProcessor",
    "EventWindow",
    "AggregationRule"
]