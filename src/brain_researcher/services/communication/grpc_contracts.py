"""
gRPC Service Contracts for Brain Researcher Services.

Defines high-performance RPC contracts for inter-service communication
with support for streaming, authentication, and service discovery.
"""

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Union

import grpc
import jwt
from google.protobuf.json_format import MessageToDict, ParseDict
from grpc import aio

logger = logging.getLogger(__name__)


# Data Models (would typically be generated from .proto files)


@dataclass
class ServiceRequest:
    """Base service request."""

    request_id: str
    service_name: str
    method: str
    payload: Dict[str, Any]
    metadata: Dict[str, str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.metadata is None:
            self.metadata = {}


@dataclass
class ServiceResponse:
    """Base service response."""

    request_id: str
    success: bool
    data: Dict[str, Any] = None
    error: str = None
    metadata: Dict[str, str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.metadata is None:
            self.metadata = {}
        if self.data is None:
            self.data = {}


@dataclass
class StreamingRequest:
    """Streaming request wrapper."""

    session_id: str
    chunk_id: int
    data: Any
    metadata: Dict[str, str] = None
    is_final: bool = False


@dataclass
class HealthCheckRequest:
    """Health check request."""

    service: str = ""


@dataclass
class HealthCheckResponse:
    """Health check response."""

    status: str  # SERVING, NOT_SERVING, UNKNOWN
    message: str = ""


class BrainResearcherServicer:
    """Base gRPC servicer for Brain Researcher services."""

    def __init__(self, service_name: str, auth_enabled: bool = True):
        """Initialize servicer.

        Args:
            service_name: Name of the service
            auth_enabled: Whether to enable JWT authentication
        """
        self.service_name = service_name
        self.auth_enabled = auth_enabled
        self._handlers = {}
        self._interceptors = []

    def add_handler(self, method: str, handler):
        """Add method handler.

        Args:
            method: Method name
            handler: Handler function
        """
        self._handlers[method] = handler

    def add_interceptor(self, interceptor):
        """Add request interceptor.

        Args:
            interceptor: Interceptor function
        """
        self._interceptors.append(interceptor)

    async def UnaryCall(self, request, context) -> ServiceResponse:
        """Handle unary RPC calls."""
        try:
            # Parse request
            req_data = MessageToDict(request)
            service_request = ServiceRequest(**req_data)

            # Apply interceptors
            for interceptor in self._interceptors:
                service_request = await interceptor(service_request, context)

            # Authenticate if enabled
            if self.auth_enabled:
                await self._authenticate(context)

            # Route to handler
            handler = self._handlers.get(service_request.method)
            if not handler:
                return ServiceResponse(
                    request_id=service_request.request_id,
                    success=False,
                    error=f"Method {service_request.method} not found",
                )

            # Execute handler
            result = await handler(service_request.payload)

            return ServiceResponse(
                request_id=service_request.request_id, success=True, data=result
            )

        except Exception as e:
            logger.error(f"gRPC unary call error: {e}")
            return ServiceResponse(
                request_id=getattr(service_request, "request_id", "unknown"),
                success=False,
                error=str(e),
            )

    async def StreamingCall(
        self, request_iterator, context
    ) -> AsyncIterator[ServiceResponse]:
        """Handle streaming RPC calls."""
        try:
            if self.auth_enabled:
                await self._authenticate(context)

            session_id = None
            async for request in request_iterator:
                req_data = MessageToDict(request)
                streaming_request = StreamingRequest(**req_data)

                if session_id is None:
                    session_id = streaming_request.session_id

                # Process streaming data
                handler = self._handlers.get("streaming")
                if handler:
                    result = await handler(streaming_request.data)

                    yield ServiceResponse(
                        request_id=f"{session_id}_{streaming_request.chunk_id}",
                        success=True,
                        data=result,
                    )

                if streaming_request.is_final:
                    break

        except Exception as e:
            logger.error(f"gRPC streaming call error: {e}")
            yield ServiceResponse(
                request_id="streaming_error", success=False, error=str(e)
            )

    async def HealthCheck(self, request, context) -> HealthCheckResponse:
        """Handle health check requests."""
        try:
            # Check service health
            is_healthy = await self._check_health()

            return HealthCheckResponse(
                status="SERVING" if is_healthy else "NOT_SERVING",
                message="Service is healthy" if is_healthy else "Service is unhealthy",
            )

        except Exception as e:
            logger.error(f"Health check error: {e}")
            return HealthCheckResponse(status="UNKNOWN", message=str(e))

    async def _authenticate(self, context):
        """Authenticate request using JWT token."""
        try:
            metadata = dict(context.invocation_metadata())
            token = metadata.get("authorization", "").replace("Bearer ", "")

            if not token:
                await context.abort(
                    grpc.StatusCode.UNAUTHENTICATED, "No token provided"
                )
                return

            # Decode JWT token (simplified - use proper secret in production)
            decoded = jwt.decode(token, "secret", algorithms=["HS256"])
            context.user_id = decoded.get("user_id")

        except jwt.InvalidTokenError:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid token")
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            await context.abort(grpc.StatusCode.INTERNAL, "Authentication failed")

    async def _check_health(self) -> bool:
        """Check service health."""
        # Override in subclasses with actual health checks
        return True


class BrainResearcherServiceStub:
    """gRPC client stub for Brain Researcher services."""

    def __init__(self, channel, service_name: str, auth_token: Optional[str] = None):
        """Initialize client stub.

        Args:
            channel: gRPC channel
            service_name: Target service name
            auth_token: JWT authentication token
        """
        self.channel = channel
        self.service_name = service_name
        self.auth_token = auth_token
        self.stub = None  # Would be generated from .proto files

    async def call_method(
        self, method: str, payload: Dict[str, Any], timeout: float = 30.0
    ) -> ServiceResponse:
        """Call remote method.

        Args:
            method: Method name
            payload: Request payload
            timeout: Request timeout

        Returns:
            Service response
        """
        try:
            request = ServiceRequest(
                request_id=f"req_{asyncio.current_task().get_name()}_{int(datetime.utcnow().timestamp())}",
                service_name=self.service_name,
                method=method,
                payload=payload,
            )

            # Add authentication metadata
            metadata = []
            if self.auth_token:
                metadata.append(("authorization", f"Bearer {self.auth_token}"))

            # Make gRPC call (simplified - would use generated stub)
            response = await asyncio.wait_for(
                self._make_grpc_call(request, metadata), timeout=timeout
            )

            return response

        except asyncio.TimeoutError:
            return ServiceResponse(
                request_id=request.request_id, success=False, error="Request timeout"
            )
        except Exception as e:
            logger.error(f"gRPC call error: {e}")
            return ServiceResponse(
                request_id=getattr(request, "request_id", "unknown"),
                success=False,
                error=str(e),
            )

    async def stream_data(
        self, data_iterator: AsyncIterator[Any], session_id: str
    ) -> AsyncIterator[ServiceResponse]:
        """Stream data to service.

        Args:
            data_iterator: Data to stream
            session_id: Session identifier

        Yields:
            Service responses
        """
        try:
            metadata = []
            if self.auth_token:
                metadata.append(("authorization", f"Bearer {self.auth_token}"))

            async def request_generator():
                chunk_id = 0
                async for data in data_iterator:
                    yield StreamingRequest(
                        session_id=session_id,
                        chunk_id=chunk_id,
                        data=data,
                        is_final=False,
                    )
                    chunk_id += 1

                # Send final chunk
                yield StreamingRequest(
                    session_id=session_id, chunk_id=chunk_id, data={}, is_final=True
                )

            # Make streaming call (simplified)
            async for response in self._make_streaming_call(
                request_generator(), metadata
            ):
                yield response

        except Exception as e:
            logger.error(f"gRPC streaming error: {e}")
            yield ServiceResponse(
                request_id=f"stream_error_{session_id}", success=False, error=str(e)
            )

    async def health_check(self) -> HealthCheckResponse:
        """Check service health.

        Returns:
            Health check response
        """
        try:
            request = HealthCheckRequest(service=self.service_name)

            # Make health check call (simplified)
            response = await self._make_health_check(request)
            return response

        except Exception as e:
            logger.error(f"Health check error: {e}")
            return HealthCheckResponse(status="UNKNOWN", message=str(e))

    async def _make_grpc_call(
        self, request: ServiceRequest, metadata: List
    ) -> ServiceResponse:
        """Make actual gRPC call (placeholder - would use generated stubs)."""
        # This would use the actual generated gRPC stubs
        # For now, simulate a successful call
        await asyncio.sleep(0.01)  # Simulate network delay

        return ServiceResponse(
            request_id=request.request_id,
            success=True,
            data={"message": f"Method {request.method} executed successfully"},
        )

    async def _make_streaming_call(
        self, request_generator, metadata
    ) -> AsyncIterator[ServiceResponse]:
        """Make streaming gRPC call (placeholder)."""
        # This would use actual gRPC streaming
        async for request in request_generator:
            yield ServiceResponse(
                request_id=f"{request.session_id}_{request.chunk_id}",
                success=True,
                data={"processed": True},
            )

    async def _make_health_check(
        self, request: HealthCheckRequest
    ) -> HealthCheckResponse:
        """Make health check call (placeholder)."""
        await asyncio.sleep(0.01)

        return HealthCheckResponse(status="SERVING", message="Service is healthy")


class ServiceDiscoveryIntegration:
    """Integration with service discovery for gRPC clients."""

    def __init__(self, registry_client):
        """Initialize with service registry client.

        Args:
            registry_client: Service registry client
        """
        self.registry_client = registry_client
        self._channels = {}
        self._stubs = {}

    async def get_client(
        self, service_name: str, auth_token: Optional[str] = None
    ) -> BrainResearcherServiceStub:
        """Get gRPC client for service.

        Args:
            service_name: Service name
            auth_token: Authentication token

        Returns:
            gRPC client stub
        """
        if service_name not in self._stubs:
            # Get service instance from registry
            service = await self.registry_client.get_service(service_name)
            if not service:
                raise ValueError(f"Service {service_name} not found in registry")

            # Create gRPC channel
            channel = await self._create_channel(service.url)
            self._channels[service_name] = channel

            # Create stub
            stub = BrainResearcherServiceStub(channel, service_name, auth_token)
            self._stubs[service_name] = stub

        return self._stubs[service_name]

    async def _create_channel(self, service_url: str):
        """Create gRPC channel for service URL.

        Args:
            service_url: Service URL

        Returns:
            gRPC channel
        """
        # Parse URL and create gRPC channel
        # For now, create a simple channel (would need proper configuration)
        host_port = service_url.replace("http://", "").replace("https://", "")

        return aio.insecure_channel(host_port)

    async def close_all(self):
        """Close all gRPC channels."""
        for channel in self._channels.values():
            await channel.close()

        self._channels.clear()
        self._stubs.clear()


async def create_grpc_client(
    service_name: str, service_url: str, auth_token: Optional[str] = None
) -> BrainResearcherServiceStub:
    """Create gRPC client for service.

    Args:
        service_name: Service name
        service_url: Service URL
        auth_token: Authentication token

    Returns:
        gRPC client stub
    """
    # Parse URL and create channel
    host_port = service_url.replace("http://", "").replace("https://", "")
    channel = aio.insecure_channel(host_port)

    return BrainResearcherServiceStub(channel, service_name, auth_token)


async def create_grpc_server(
    servicer: BrainResearcherServicer, port: int, max_workers: int = 10
) -> grpc.aio.Server:
    """Create gRPC server with servicer.

    Args:
        servicer: Service implementation
        port: Server port
        max_workers: Maximum worker threads

    Returns:
        gRPC server instance
    """
    server = aio.server()

    # Add servicer to server (would use generated add_servicer_to_server)
    # server.add_insecure_port(f'[::]:{port}')

    return server


# Export components
__all__ = [
    "BrainResearcherServicer",
    "BrainResearcherServiceStub",
    "ServiceRequest",
    "ServiceResponse",
    "StreamingRequest",
    "HealthCheckRequest",
    "HealthCheckResponse",
    "ServiceDiscoveryIntegration",
    "create_grpc_client",
    "create_grpc_server",
]
