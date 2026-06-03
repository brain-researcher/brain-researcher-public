"""
Communication Layer for Brain Researcher Services.

Provides unified inter-service communication protocols, service mesh capabilities,
and event-driven messaging infrastructure.

Components:
- gRPC service contracts for high-performance RPC
- Message queue integration (Redis/RabbitMQ)
- Service mesh configuration and monitoring
- Circuit breaker and retry patterns
- Request/response transformation
- Event-driven communication patterns
"""

from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .event_dispatcher import Event, EventDispatcher
from .grpc_contracts import BrainResearcherServiceStub, create_grpc_client
from .message_queue import EventBus, MessageQueue, QueueConfig
from .retry_policy import RetryConfig, RetryPolicy
from .service_mesh import MeshConfig, ServiceMesh, ServiceProxy
from .transformation import RequestTransformer, ResponseTransformer

__all__ = [
    # gRPC
    "BrainResearcherServiceStub",
    "create_grpc_client",
    # Messaging
    "MessageQueue",
    "EventBus",
    "QueueConfig",
    # Service Mesh
    "ServiceMesh",
    "MeshConfig",
    "ServiceProxy",
    # Resilience
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "RetryPolicy",
    "RetryConfig",
    # Events
    "EventDispatcher",
    "Event",
    # Transformation
    "RequestTransformer",
    "ResponseTransformer",
]
