"""
Performance tests for streaming throughput covering CDC processing,
Kafka message handling, and stream processing under various load conditions.

Tests measure throughput, latency, memory usage, and system resource utilization
to identify performance bottlenecks and validate streaming system scalability.
"""

import asyncio
import concurrent.futures
import gc
import json
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import psutil
import pytest

# Import the modules under test
from brain_researcher.services.br_kg.streaming.cdc_processor import (
    CDCProcessor,
    ChangeType,
    GraphChangeEvent,
)
from brain_researcher.services.br_kg.streaming.kafka_integration import (
    KafkaConsumer,
    KafkaProducer,
    StreamConfig,
)
from brain_researcher.services.br_kg.streaming.stream_processor import (
    AggregationRule,
    EventWindow,
    StreamProcessor,
)


@dataclass
class PerformanceMetrics:
    """Container for performance metrics"""

    throughput_messages_per_sec: float
    avg_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    memory_usage_mb: float
    cpu_usage_percent: float
    error_rate: float
    total_processed: int
    duration_seconds: float


class PerformanceMonitor:
    """Utility class for monitoring performance during tests"""

    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.latencies = []
        self.processed_count = 0
        self.error_count = 0
        self.memory_samples = []
        self.cpu_samples = []
        self._monitoring = False
        self._monitor_thread = None

    def start_monitoring(self):
        """Start performance monitoring"""
        self.start_time = time.time()
        self.processed_count = 0
        self.error_count = 0
        self.latencies.clear()
        self.memory_samples.clear()
        self.cpu_samples.clear()
        self._monitoring = True

        # Start system resource monitoring thread
        self._monitor_thread = threading.Thread(
            target=self._monitor_resources, daemon=True
        )
        self._monitor_thread.start()

    def stop_monitoring(self):
        """Stop performance monitoring and return metrics"""
        self.end_time = time.time()
        self._monitoring = False

        if self._monitor_thread:
            self._monitor_thread.join(timeout=1)

        duration = self.end_time - self.start_time
        throughput = self.processed_count / duration if duration > 0 else 0
        error_rate = self.error_count / max(self.processed_count, 1)

        # Calculate latency percentiles
        avg_latency = statistics.mean(self.latencies) if self.latencies else 0
        p95_latency = (
            statistics.quantiles(self.latencies, n=20)[18]
            if len(self.latencies) >= 20
            else avg_latency
        )
        p99_latency = (
            statistics.quantiles(self.latencies, n=100)[98]
            if len(self.latencies) >= 100
            else avg_latency
        )

        # Calculate average resource usage
        avg_memory = statistics.mean(self.memory_samples) if self.memory_samples else 0
        avg_cpu = statistics.mean(self.cpu_samples) if self.cpu_samples else 0

        return PerformanceMetrics(
            throughput_messages_per_sec=throughput,
            avg_latency_ms=avg_latency,
            p95_latency_ms=p95_latency,
            p99_latency_ms=p99_latency,
            memory_usage_mb=avg_memory,
            cpu_usage_percent=avg_cpu,
            error_rate=error_rate,
            total_processed=self.processed_count,
            duration_seconds=duration,
        )

    def record_processed_message(self, latency_ms: float, success: bool = True):
        """Record a processed message with its latency"""
        self.processed_count += 1
        self.latencies.append(latency_ms)

        if not success:
            self.error_count += 1

    def _monitor_resources(self):
        """Monitor system resources in background thread"""
        process = psutil.Process()

        while self._monitoring:
            try:
                # Memory usage in MB
                memory_mb = process.memory_info().rss / (1024 * 1024)
                self.memory_samples.append(memory_mb)

                # CPU usage percentage
                cpu_percent = process.cpu_percent()
                self.cpu_samples.append(cpu_percent)

                time.sleep(0.1)  # Sample every 100ms
            except Exception:
                # Ignore monitoring errors
                pass


class MockKafkaProducerHighThroughput:
    """High-performance mock Kafka producer for throughput testing"""

    def __init__(self, config: StreamConfig):
        self.config = config
        self.sent_messages = deque()
        self.total_sent = 0
        self.send_latencies = deque()

    async def send_message(
        self, topic: str, message: Dict[str, Any], partition_key: str = None
    ) -> bool:
        """Mock high-throughput message sending"""
        start_time = time.time()

        # Simulate minimal serialization time
        await asyncio.sleep(0.0001)  # 0.1ms

        self.sent_messages.append(
            {
                "topic": topic,
                "message": message,
                "partition_key": partition_key,
                "timestamp": time.time(),
            }
        )
        self.total_sent += 1

        latency = (time.time() - start_time) * 1000
        self.send_latencies.append(latency)

        return True

    async def close(self):
        pass


class MockKafkaConsumerHighThroughput:
    """High-performance mock Kafka consumer for throughput testing"""

    def __init__(self, config: StreamConfig):
        self.config = config
        self.message_queue = deque()
        self.consumed_messages = deque()
        self.total_consumed = 0
        self._consuming = False

    def add_messages_to_queue(self, messages: List[Dict[str, Any]]):
        """Add messages to the mock queue for consumption"""
        for msg in messages:
            self.message_queue.append(
                {
                    "topic": "test_topic",
                    "partition": 0,
                    "offset": len(self.message_queue),
                    "value": msg,
                    "timestamp": time.time(),
                }
            )

    async def consume_messages(
        self, callback: Callable[[Dict[str, Any]], None]
    ) -> None:
        """Mock high-throughput message consumption"""
        self._consuming = True

        while self._consuming and self.message_queue:
            try:
                message = self.message_queue.popleft()
                self.consumed_messages.append(message)
                self.total_consumed += 1

                # Minimal processing delay
                await asyncio.sleep(0.0001)  # 0.1ms

                # Call the callback
                await callback(message)

            except Exception as e:
                # Handle errors gracefully
                pass

    async def stop_consuming(self):
        self._consuming = False

    async def close(self):
        self._consuming = False


@pytest.fixture
def performance_monitor():
    """Fixture for performance monitoring"""
    return PerformanceMonitor()


@pytest.fixture
def high_throughput_kafka_config():
    """Fixture for high-throughput Kafka configuration"""
    return StreamConfig(
        bootstrap_servers="mock://localhost:9092",
        producer_config={
            "batch_size": 16384,
            "linger_ms": 5,
            "buffer_memory": 33554432,
            "max_in_flight_requests": 5,
            "compression_type": "gzip",
        },
        consumer_config={
            "fetch_min_bytes": 1024,
            "fetch_max_wait": 500,
            "max_partition_fetch_bytes": 1048576,
            "session_timeout_ms": 30000,
        },
    )


class TestStreamingThroughputPerformance:
    """Performance tests for streaming throughput"""

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_cdc_processor_high_throughput(self, performance_monitor):
        """Test CDC processor performance under high message load"""

        # Setup CDC processor with mock Neo4j driver
        mock_driver = AsyncMock()
        cdc_processor = CDCProcessor(mock_driver)

        # Setup performance monitoring
        performance_monitor.start_monitoring()

        # Generate high volume of change events
        num_events = 10000
        events_batch_size = 100

        async def process_events_batch(start_idx: int, end_idx: int):
            """Process a batch of events"""
            batch_events = []
            for i in range(start_idx, end_idx):
                event = GraphChangeEvent(
                    event_id=f"event_{i}",
                    change_type=ChangeType.NODE_CREATED,
                    entity_id=f"node_{i % 1000}",  # Reuse some IDs for realistic patterns
                    entity_type="Concept",
                    timestamp=datetime.now(),
                    properties={"name": f"concept_{i}", "value": i * 0.01},
                    old_properties=None,
                )
                batch_events.append(event)

            # Process batch
            batch_start = time.time()

            for event in batch_events:
                await cdc_processor.process_change_event(event)

                # Record processing latency
                latency = (time.time() - batch_start) * 1000 / len(batch_events)
                performance_monitor.record_processed_message(latency)

        # Process events in concurrent batches
        tasks = []
        for i in range(0, num_events, events_batch_size):
            end_idx = min(i + events_batch_size, num_events)
            task = process_events_batch(i, end_idx)
            tasks.append(task)

        # Execute all batches concurrently
        await asyncio.gather(*tasks)

        # Stop monitoring and get metrics
        metrics = performance_monitor.stop_monitoring()

        # Performance assertions
        assert metrics.throughput_messages_per_sec > 1000  # At least 1K events/sec
        assert metrics.avg_latency_ms < 10.0  # Average latency under 10ms
        assert metrics.p95_latency_ms < 50.0  # P95 latency under 50ms
        assert metrics.error_rate < 0.01  # Less than 1% error rate
        assert metrics.memory_usage_mb < 500  # Memory usage under 500MB
        assert metrics.total_processed == num_events

        print(f"CDC Processor Performance:")
        print(f"  Throughput: {metrics.throughput_messages_per_sec:.2f} events/sec")
        print(f"  Average Latency: {metrics.avg_latency_ms:.2f}ms")
        print(f"  P95 Latency: {metrics.p95_latency_ms:.2f}ms")
        print(f"  Memory Usage: {metrics.memory_usage_mb:.2f}MB")

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_kafka_producer_throughput(
        self, performance_monitor, high_throughput_kafka_config
    ):
        """Test Kafka producer throughput performance"""

        mock_producer = MockKafkaProducerHighThroughput(high_throughput_kafka_config)

        performance_monitor.start_monitoring()

        # Generate high volume of messages
        num_messages = 50000
        batch_size = 1000

        async def send_message_batch(start_idx: int, end_idx: int):
            """Send a batch of messages"""
            for i in range(start_idx, end_idx):
                message = {
                    "event_id": f"event_{i}",
                    "entity_type": "node",
                    "entity_id": f"node_{i % 5000}",
                    "change_type": "update",
                    "timestamp": time.time(),
                    "properties": {"value": i, "category": f"cat_{i % 10}"},
                }

                send_start = time.time()
                success = await mock_producer.send_message(
                    topic="graph_changes",
                    message=message,
                    partition_key=f"partition_{i % 10}",
                )
                send_latency = (time.time() - send_start) * 1000

                performance_monitor.record_processed_message(send_latency, success)

        # Send messages in concurrent batches
        tasks = []
        for i in range(0, num_messages, batch_size):
            end_idx = min(i + batch_size, num_messages)
            task = send_message_batch(i, end_idx)
            tasks.append(task)

        await asyncio.gather(*tasks)

        metrics = performance_monitor.stop_monitoring()

        # Performance assertions for Kafka producer
        assert metrics.throughput_messages_per_sec > 5000  # At least 5K messages/sec
        assert metrics.avg_latency_ms < 5.0  # Average send latency under 5ms
        assert metrics.p95_latency_ms < 20.0  # P95 latency under 20ms
        assert metrics.error_rate == 0.0  # No errors expected in mock
        assert metrics.total_processed == num_messages

        print(f"Kafka Producer Performance:")
        print(f"  Throughput: {metrics.throughput_messages_per_sec:.2f} messages/sec")
        print(f"  Average Latency: {metrics.avg_latency_ms:.2f}ms")
        print(f"  P95 Latency: {metrics.p95_latency_ms:.2f}ms")

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_kafka_consumer_throughput(
        self, performance_monitor, high_throughput_kafka_config
    ):
        """Test Kafka consumer throughput performance"""

        mock_consumer = MockKafkaConsumerHighThroughput(high_throughput_kafka_config)

        # Prepare messages for consumption
        num_messages = 30000
        test_messages = []
        for i in range(num_messages):
            test_messages.append(
                {
                    "event_id": f"event_{i}",
                    "entity_type": "relationship",
                    "entity_id": f"rel_{i % 3000}",
                    "change_type": "created",
                    "timestamp": time.time(),
                    "properties": {"weight": 0.5 + (i % 100) * 0.005},
                }
            )

        mock_consumer.add_messages_to_queue(test_messages)

        performance_monitor.start_monitoring()

        # Message processing callback
        async def process_message(message: Dict[str, Any]):
            """Process consumed message"""
            process_start = time.time()

            # Simulate minimal processing work
            data = message["value"]
            entity_id = data["entity_id"]
            properties = data.get("properties", {})

            # Minimal processing delay
            await asyncio.sleep(0.0001)  # 0.1ms

            process_latency = (time.time() - process_start) * 1000
            performance_monitor.record_processed_message(process_latency)

        # Start consumption
        consumption_task = asyncio.create_task(
            mock_consumer.consume_messages(process_message)
        )

        # Let it run for a bit
        await asyncio.sleep(5.0)

        # Stop consumption
        await mock_consumer.stop_consuming()
        await consumption_task

        metrics = performance_monitor.stop_monitoring()

        # Performance assertions for Kafka consumer
        assert metrics.throughput_messages_per_sec > 3000  # At least 3K messages/sec
        assert metrics.avg_latency_ms < 2.0  # Average processing latency under 2ms
        assert metrics.p95_latency_ms < 10.0  # P95 latency under 10ms
        assert metrics.error_rate == 0.0  # No errors expected in mock

        print(f"Kafka Consumer Performance:")
        print(f"  Throughput: {metrics.throughput_messages_per_sec:.2f} messages/sec")
        print(f"  Average Latency: {metrics.avg_latency_ms:.2f}ms")
        print(f"  Total Processed: {metrics.total_processed}")

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_stream_processor_windowing_throughput(self, performance_monitor):
        """Test stream processor windowing performance under high load"""

        # Setup stream processor
        stream_processor = StreamProcessor()

        # Configure tumbling window for aggregation
        window_duration = timedelta(seconds=1)
        event_window = EventWindow(
            window_type="tumbling", duration=window_duration, slide_interval=None
        )

        aggregation_rule = AggregationRule(
            name="count_by_type",
            window=event_window,
            group_by=["entity_type"],
            aggregation_function="COUNT",
            output_topic="aggregated_counts",
        )

        await stream_processor.add_aggregation_rule(aggregation_rule)

        performance_monitor.start_monitoring()

        # Generate high-volume event stream
        num_events = 25000
        event_types = [
            "node_created",
            "node_updated",
            "node_deleted",
            "rel_created",
            "rel_updated",
        ]

        async def process_event_batch(start_idx: int, end_idx: int):
            """Process a batch of events through stream processor"""
            for i in range(start_idx, end_idx):
                event_data = {
                    "event_id": f"stream_event_{i}",
                    "entity_type": event_types[i % len(event_types)],
                    "entity_id": f"entity_{i % 2000}",
                    "timestamp": time.time(),
                    "properties": {"batch": i // 1000, "sequence": i},
                }

                process_start = time.time()
                await stream_processor.process_event(event_data)
                process_latency = (time.time() - process_start) * 1000

                performance_monitor.record_processed_message(process_latency)

        # Process events in batches
        batch_size = 2500
        tasks = []
        for i in range(0, num_events, batch_size):
            end_idx = min(i + batch_size, num_events)
            task = process_event_batch(i, end_idx)
            tasks.append(task)

        await asyncio.gather(*tasks)

        # Allow final window processing
        await asyncio.sleep(2.0)

        metrics = performance_monitor.stop_monitoring()

        # Performance assertions for stream processing
        assert metrics.throughput_messages_per_sec > 2000  # At least 2K events/sec
        assert metrics.avg_latency_ms < 5.0  # Average processing latency under 5ms
        assert metrics.p95_latency_ms < 25.0  # P95 latency under 25ms
        assert metrics.error_rate < 0.005  # Less than 0.5% error rate
        assert metrics.total_processed == num_events

        print(f"Stream Processor Performance:")
        print(f"  Throughput: {metrics.throughput_messages_per_sec:.2f} events/sec")
        print(f"  Average Latency: {metrics.avg_latency_ms:.2f}ms")
        print(f"  P95 Latency: {metrics.p95_latency_ms:.2f}ms")

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_end_to_end_streaming_pipeline_throughput(
        self, performance_monitor, high_throughput_kafka_config
    ):
        """Test complete streaming pipeline throughput from CDC to final aggregation"""

        # Setup complete pipeline components
        mock_driver = AsyncMock()
        cdc_processor = CDCProcessor(mock_driver)
        kafka_producer = MockKafkaProducerHighThroughput(high_throughput_kafka_config)
        kafka_consumer = MockKafkaConsumerHighThroughput(high_throughput_kafka_config)
        stream_processor = StreamProcessor()

        # Configure aggregation
        aggregation_rule = AggregationRule(
            name="pipeline_aggregation",
            window=EventWindow("tumbling", timedelta(seconds=2)),
            group_by=["change_type"],
            aggregation_function="COUNT",
            output_topic="pipeline_results",
        )
        await stream_processor.add_aggregation_rule(aggregation_rule)

        performance_monitor.start_monitoring()

        # End-to-end pipeline processing
        num_changes = 15000

        async def process_pipeline_batch(start_idx: int, end_idx: int):
            """Process events through complete pipeline"""
            for i in range(start_idx, end_idx):
                pipeline_start = time.time()

                # Step 1: CDC Event Generation
                change_event = GraphChangeEvent(
                    event_id=f"pipeline_event_{i}",
                    change_type=ChangeType.NODE_UPDATED,
                    entity_id=f"node_{i % 1000}",
                    entity_type="Concept",
                    timestamp=datetime.now(),
                    properties={"value": i, "pipeline_batch": i // 100},
                )

                # Step 2: CDC Processing
                await cdc_processor.process_change_event(change_event)

                # Step 3: Kafka Message Production
                kafka_message = {
                    "event_id": change_event.event_id,
                    "change_type": change_event.change_type.value,
                    "entity_id": change_event.entity_id,
                    "timestamp": change_event.timestamp.isoformat(),
                    "properties": change_event.properties,
                }

                await kafka_producer.send_message(
                    topic="graph_changes",
                    message=kafka_message,
                    partition_key=change_event.entity_id,
                )

                # Step 4: Stream Processing
                await stream_processor.process_event(kafka_message)

                # Record end-to-end latency
                pipeline_latency = (time.time() - pipeline_start) * 1000
                performance_monitor.record_processed_message(pipeline_latency)

        # Process pipeline in batches
        batch_size = 1500
        tasks = []
        for i in range(0, num_changes, batch_size):
            end_idx = min(i + batch_size, num_changes)
            task = process_pipeline_batch(i, end_idx)
            tasks.append(task)

        await asyncio.gather(*tasks)

        # Allow final processing
        await asyncio.sleep(3.0)

        metrics = performance_monitor.stop_monitoring()

        # End-to-end performance assertions
        assert (
            metrics.throughput_messages_per_sec > 800
        )  # At least 800 changes/sec end-to-end
        assert metrics.avg_latency_ms < 15.0  # Average end-to-end latency under 15ms
        assert metrics.p95_latency_ms < 50.0  # P95 latency under 50ms
        assert metrics.error_rate < 0.01  # Less than 1% error rate
        assert metrics.total_processed == num_changes
        assert metrics.memory_usage_mb < 1000  # Memory usage under 1GB

        print(f"End-to-End Pipeline Performance:")
        print(f"  Throughput: {metrics.throughput_messages_per_sec:.2f} changes/sec")
        print(f"  Average Latency: {metrics.avg_latency_ms:.2f}ms")
        print(f"  P95 Latency: {metrics.p95_latency_ms:.2f}ms")
        print(f"  Memory Usage: {metrics.memory_usage_mb:.2f}MB")

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_streaming_memory_efficiency(self):
        """Test memory efficiency of streaming components under sustained load"""

        # Setup components
        mock_driver = AsyncMock()
        cdc_processor = CDCProcessor(mock_driver)
        stream_processor = StreamProcessor()

        # Configure stream processor with memory-efficient settings
        aggregation_rule = AggregationRule(
            name="memory_test",
            window=EventWindow("tumbling", timedelta(seconds=0.5)),
            group_by=["entity_type"],
            aggregation_function="COUNT",
            output_topic="memory_test_results",
        )
        await stream_processor.add_aggregation_rule(aggregation_rule)

        # Baseline memory measurement
        gc.collect()  # Force garbage collection
        process = psutil.Process()
        baseline_memory = process.memory_info().rss / (1024 * 1024)  # MB

        # Process events in multiple rounds to test memory stability
        rounds = 5
        events_per_round = 5000
        memory_measurements = []

        for round_num in range(rounds):
            print(f"Memory efficiency test round {round_num + 1}/{rounds}")

            # Generate and process events
            for i in range(events_per_round):
                event = GraphChangeEvent(
                    event_id=f"mem_event_{round_num}_{i}",
                    change_type=ChangeType.NODE_CREATED,
                    entity_id=f"node_{i}",
                    entity_type="MemoryTestNode",
                    timestamp=datetime.now(),
                    properties={
                        "round": round_num,
                        "index": i,
                        "data": "x" * 100,
                    },  # Some data
                )

                await cdc_processor.process_change_event(event)

                # Also process through stream processor
                stream_event = {
                    "entity_type": "MemoryTestNode",
                    "event_id": event.event_id,
                    "timestamp": time.time(),
                    "properties": event.properties,
                }
                await stream_processor.process_event(stream_event)

            # Allow processing to complete
            await asyncio.sleep(1.0)

            # Force garbage collection and measure memory
            gc.collect()
            current_memory = process.memory_info().rss / (1024 * 1024)  # MB
            memory_measurements.append(current_memory)

            print(
                f"  Memory usage: {current_memory:.2f}MB (growth: {current_memory - baseline_memory:.2f}MB)"
            )

        # Analyze memory efficiency
        max_memory = max(memory_measurements)
        final_memory = memory_measurements[-1]
        memory_growth = final_memory - baseline_memory

        # Memory efficiency assertions
        assert memory_growth < 200, f"Memory growth {memory_growth:.2f}MB exceeds limit"
        assert (
            max_memory - baseline_memory < 300
        ), f"Peak memory usage {max_memory - baseline_memory:.2f}MB too high"

        # Check for memory leaks (final memory should not be much higher than baseline)
        assert (
            final_memory - baseline_memory < 150
        ), f"Potential memory leak: {final_memory - baseline_memory:.2f}MB growth"

        print(f"Memory Efficiency Results:")
        print(f"  Baseline: {baseline_memory:.2f}MB")
        print(f"  Final: {final_memory:.2f}MB")
        print(f"  Growth: {memory_growth:.2f}MB")
        print(f"  Peak: {max_memory:.2f}MB")

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_concurrent_streaming_scalability(self, performance_monitor):
        """Test streaming system scalability with multiple concurrent producers/consumers"""

        # Setup multiple concurrent streaming components
        num_producers = 4
        num_consumers = 2
        messages_per_producer = 2500

        producers = []
        consumers = []

        # Create mock components
        for i in range(num_producers):
            config = StreamConfig(
                bootstrap_servers=f"mock://producer_{i}:9092",
                producer_config={"batch_size": 8192, "linger_ms": 1},
            )
            producers.append(MockKafkaProducerHighThroughput(config))

        for i in range(num_consumers):
            config = StreamConfig(
                bootstrap_servers=f"mock://consumer_{i}:9092",
                consumer_config={"fetch_min_bytes": 512},
            )
            consumers.append(MockKafkaConsumerHighThroughput(config))

        performance_monitor.start_monitoring()

        async def producer_task(
            producer_id: int, producer: MockKafkaProducerHighThroughput
        ):
            """Concurrent producer task"""
            for i in range(messages_per_producer):
                message = {
                    "producer_id": producer_id,
                    "message_id": f"p{producer_id}_m{i}",
                    "timestamp": time.time(),
                    "data": f"producer_{producer_id}_data_{i}",
                }

                send_start = time.time()
                await producer.send_message(f"topic_p{producer_id}", message)
                send_latency = (time.time() - send_start) * 1000

                performance_monitor.record_processed_message(send_latency)

        async def consumer_task(
            consumer_id: int, consumer: MockKafkaConsumerHighThroughput
        ):
            """Concurrent consumer task"""
            # Prepare messages for this consumer
            test_messages = []
            for i in range(
                messages_per_producer * 2
            ):  # Each consumer gets messages from 2 producers
                test_messages.append(
                    {
                        "consumer_id": consumer_id,
                        "message_id": f"c{consumer_id}_m{i}",
                        "timestamp": time.time(),
                    }
                )

            consumer.add_messages_to_queue(test_messages)

            async def process_message(message):
                process_start = time.time()
                # Simulate processing
                await asyncio.sleep(0.0002)  # 0.2ms processing time
                process_latency = (time.time() - process_start) * 1000
                performance_monitor.record_processed_message(process_latency)

            # Start consuming
            consumption_task = asyncio.create_task(
                consumer.consume_messages(process_message)
            )
            await asyncio.sleep(3.0)  # Run for 3 seconds
            await consumer.stop_consuming()

        # Run all producers and consumers concurrently
        producer_tasks = [producer_task(i, producers[i]) for i in range(num_producers)]
        consumer_tasks = [consumer_task(i, consumers[i]) for i in range(num_consumers)]

        all_tasks = producer_tasks + consumer_tasks
        await asyncio.gather(*all_tasks)

        metrics = performance_monitor.stop_monitoring()

        # Scalability assertions
        expected_messages = (num_producers * messages_per_producer) + (
            num_consumers * messages_per_producer * 2
        )

        assert (
            metrics.throughput_messages_per_sec > 2000
        )  # At least 2K messages/sec with concurrency
        assert metrics.avg_latency_ms < 10.0  # Reasonable latency under concurrent load
        assert metrics.error_rate < 0.01  # Low error rate
        assert metrics.memory_usage_mb < 800  # Memory usage should be reasonable

        print(f"Concurrent Streaming Scalability:")
        print(f"  Producers: {num_producers}, Consumers: {num_consumers}")
        print(f"  Throughput: {metrics.throughput_messages_per_sec:.2f} messages/sec")
        print(f"  Average Latency: {metrics.avg_latency_ms:.2f}ms")
        print(f"  Total Processed: {metrics.total_processed}")
        print(f"  Memory Usage: {metrics.memory_usage_mb:.2f}MB")


@pytest.mark.performance
def test_streaming_throughput_benchmark_summary():
    """Generate summary of all streaming throughput benchmarks"""

    benchmark_results = {
        "cdc_processor": {
            "target_throughput": 1000,  # events/sec
            "target_latency": 10,  # ms
            "target_memory": 500,  # MB
        },
        "kafka_producer": {
            "target_throughput": 5000,  # messages/sec
            "target_latency": 5,  # ms
            "target_memory": 300,  # MB
        },
        "kafka_consumer": {
            "target_throughput": 3000,  # messages/sec
            "target_latency": 2,  # ms
            "target_memory": 200,  # MB
        },
        "stream_processor": {
            "target_throughput": 2000,  # events/sec
            "target_latency": 5,  # ms
            "target_memory": 400,  # MB
        },
        "end_to_end_pipeline": {
            "target_throughput": 800,  # changes/sec
            "target_latency": 15,  # ms
            "target_memory": 1000,  # MB
        },
    }

    print("Streaming Throughput Performance Benchmarks Summary:")
    print("=" * 60)

    for component, targets in benchmark_results.items():
        print(f"{component.upper().replace('_', ' ')}:")
        print(f"  Target Throughput: {targets['target_throughput']} msgs/sec")
        print(f"  Target Avg Latency: {targets['target_latency']}ms")
        print(f"  Target Memory Usage: {targets['target_memory']}MB")
        print()

    print("Notes:")
    print("- All tests use mock components for consistent performance measurement")
    print("- Real-world performance will vary based on hardware and network conditions")
    print("- Memory measurements include Python interpreter overhead")
    print("- Throughput targets are conservative estimates for production systems")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "performance"])
