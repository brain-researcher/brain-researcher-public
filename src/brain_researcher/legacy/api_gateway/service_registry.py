"""
Service Registry for API Gateway.

Manages service discovery, registration, and health monitoring for all
Brain Researcher microservices.

Features:
- Service registration and deregistration
- Service discovery with load balancing
- Health check monitoring
- Service metadata management
- Instance management for scaling
- Event notifications for service changes
"""

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

import httpx
import redis
from httpx import AsyncClient, ConnectTimeout, ReadTimeout
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class ServiceStatus(str, Enum):
    """Service status enumeration."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    STARTING = "starting"
    STOPPING = "stopping"


class ServiceHealth(BaseModel):
    """Service health information."""

    status: ServiceStatus = Field(..., description="Service health status")
    last_check: datetime = Field(..., description="Last health check time")
    response_time_ms: Optional[float] = Field(
        None, description="Response time in milliseconds"
    )
    error_message: Optional[str] = Field(None, description="Error message if unhealthy")
    consecutive_failures: int = Field(0, description="Number of consecutive failures")
    consecutive_successes: int = Field(0, description="Number of consecutive successes")
    uptime_percentage: float = Field(100.0, description="Uptime percentage (24h)")


class ServiceInstance(BaseModel):
    """Individual service instance."""

    instance_id: str = Field(..., description="Unique instance identifier")
    url: str = Field(..., description="Service URL")
    weight: int = Field(100, description="Load balancing weight")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Instance metadata"
    )
    registered_at: datetime = Field(
        default_factory=datetime.utcnow, description="Registration time"
    )
    last_heartbeat: datetime = Field(
        default_factory=datetime.utcnow, description="Last heartbeat"
    )
    health: ServiceHealth = Field(
        default_factory=lambda: ServiceHealth(
            status=ServiceStatus.UNKNOWN, last_check=datetime.utcnow()
        ),
        description="Health information",
    )


class Service(BaseModel):
    """Service registration model."""

    name: str = Field(..., description="Service name")
    version: str = Field("1.0.0", description="Service version")
    description: Optional[str] = Field(None, description="Service description")
    url: str = Field(..., description="Primary service URL")
    health_check_path: str = Field("/health", description="Health check endpoint")
    health_check_interval: int = Field(
        30, description="Health check interval in seconds"
    )
    health_check_timeout: int = Field(5, description="Health check timeout in seconds")
    tags: List[str] = Field(default_factory=list, description="Service tags")
    instances: List[ServiceInstance] = Field(
        default_factory=list, description="Service instances"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        """Validate service name."""
        if not v or not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Service name must be alphanumeric with _ or -")
        return v.lower()

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        """Validate service URL."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("Service URL must start with http:// or https://")
        return v


class ServiceEvent(BaseModel):
    """Service registry event."""

    event_type: str = Field(..., description="Event type")
    service_name: str = Field(..., description="Service name")
    instance_id: Optional[str] = Field(None, description="Instance ID if applicable")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Event timestamp"
    )
    details: Dict[str, Any] = Field(default_factory=dict, description="Event details")


class ServiceRegistry:
    """Service registry implementation."""

    def __init__(
        self,
        redis_client: redis.Redis,
        default_health_check_interval: int = 30,
        service_ttl: int = 300,  # 5 minutes
    ):
        """Initialize service registry.

        Args:
            redis_client: Redis client for persistence
            default_health_check_interval: Default health check interval
            service_ttl: Service TTL in seconds
        """
        self.redis = redis_client
        self.default_health_check_interval = default_health_check_interval
        self.service_ttl = service_ttl
        self.http_client = AsyncClient(timeout=httpx.Timeout(30.0))

        # Event listeners
        self.event_listeners: Dict[str, List[Callable]] = {}

        # Background tasks
        self._running = False
        self._tasks: List[asyncio.Task] = []

    def _set_with_ttl(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        """Persist a key with optional TTL handling."""
        effective_ttl = self.service_ttl if ttl is None else ttl
        if effective_ttl and effective_ttl > 0:
            self.redis.setex(key, effective_ttl, value)
        else:
            self.redis.set(key, value)

    async def register(self, service: Service) -> bool:
        """Register a service.

        Args:
            service: Service to register

        Returns:
            True if registered successfully
        """
        try:
            # Create primary instance if not exists
            if not service.instances:
                instance = ServiceInstance(
                    instance_id=f"{service.name}-primary", url=service.url
                )
                service.instances = [instance]

            # Store service data
            service_key = f"service:{service.name}"
            service_data = service.dict()
            service_data["registered_at"] = datetime.utcnow().isoformat()

            # Set with TTL
            self._set_with_ttl(service_key, json.dumps(service_data, default=str))

            # Add to service list
            self.redis.sadd("services:active", service.name)

            # Store instances
            for instance in service.instances:
                await self._register_instance(service.name, instance)

            # Emit event
            await self._emit_event(
                ServiceEvent(
                    event_type="service_registered",
                    service_name=service.name,
                    details={
                        "version": service.version,
                        "instances": len(service.instances),
                    },
                )
            )

            logger.info(
                f"Registered service: {service.name} with {len(service.instances)} instances"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to register service {service.name}: {e}")
            return False

    async def deregister(
        self, service_name: str, instance_id: Optional[str] = None
    ) -> bool:
        """Deregister a service or specific instance.

        Args:
            service_name: Service name to deregister
            instance_id: Specific instance ID to deregister

        Returns:
            True if deregistered successfully
        """
        try:
            if instance_id:
                # Deregister specific instance
                instance_key = f"service:{service_name}:instance:{instance_id}"
                self.redis.delete(instance_key)

                # Remove from instance set
                self.redis.srem(f"service:{service_name}:instances", instance_id)

                # Emit event
                await self._emit_event(
                    ServiceEvent(
                        event_type="instance_deregistered",
                        service_name=service_name,
                        instance_id=instance_id,
                    )
                )

                logger.info(f"Deregistered instance: {service_name}/{instance_id}")

                # Check if any instances remain
                remaining_instances = self.redis.scard(
                    f"service:{service_name}:instances"
                )
                if remaining_instances == 0:
                    # Deregister entire service
                    return await self.deregister(service_name)

            else:
                # Deregister entire service
                service_key = f"service:{service_name}"

                # Get all instances to clean up
                instance_ids = self.redis.smembers(f"service:{service_name}:instances")

                # Clean up instances
                for instance_id in instance_ids:
                    if isinstance(instance_id, bytes):
                        instance_id = instance_id.decode()
                    instance_key = f"service:{service_name}:instance:{instance_id}"
                    self.redis.delete(instance_key)

                # Clean up service data
                self.redis.delete(service_key)
                self.redis.delete(f"service:{service_name}:instances")
                self.redis.srem("services:active", service_name)

                # Emit event
                await self._emit_event(
                    ServiceEvent(
                        event_type="service_deregistered",
                        service_name=service_name,
                        details={"instances_removed": len(instance_ids)},
                    )
                )

                logger.info(f"Deregistered service: {service_name}")

            return True

        except Exception as e:
            logger.error(f"Failed to deregister {service_name}: {e}")
            return False

    async def get_service(self, service_name: str) -> Optional[Service]:
        """Get service information.

        Args:
            service_name: Service name

        Returns:
            Service information or None if not found
        """
        try:
            service_key = f"service:{service_name}"
            service_data = self.redis.get(service_key)

            if not service_data:
                return None

            # Parse service data
            data = json.loads(service_data)

            # Load instances
            instances = []
            instance_ids = self.redis.smembers(f"service:{service_name}:instances")

            for instance_id in instance_ids:
                if isinstance(instance_id, bytes):
                    instance_id = instance_id.decode()

                instance_data = self.redis.get(
                    f"service:{service_name}:instance:{instance_id}"
                )
                if instance_data:
                    instance_info = json.loads(instance_data)
                    # Convert datetime strings
                    for date_field in ["registered_at", "last_heartbeat"]:
                        if date_field in instance_info:
                            instance_info[date_field] = datetime.fromisoformat(
                                instance_info[date_field]
                            )

                    # Convert health last_check
                    if (
                        "health" in instance_info
                        and "last_check" in instance_info["health"]
                    ):
                        instance_info["health"]["last_check"] = datetime.fromisoformat(
                            instance_info["health"]["last_check"]
                        )

                    instances.append(ServiceInstance(**instance_info))

            # Update instances in service data
            data["instances"] = [instance.dict() for instance in instances]

            return Service(**data)

        except Exception as e:
            logger.error(f"Failed to get service {service_name}: {e}")
            return None

    async def get_all_services(self) -> Dict[str, Service]:
        """Get all registered services.

        Returns:
            Dictionary of service name to Service objects
        """
        services = {}

        try:
            service_names = self.redis.smembers("services:active")

            for service_name in service_names:
                if isinstance(service_name, bytes):
                    service_name = service_name.decode()

                service = await self.get_service(service_name)
                if service:
                    services[service_name] = service

        except Exception as e:
            logger.error(f"Failed to get all services: {e}")

        return services

    async def get_healthy_instances(self, service_name: str) -> List[ServiceInstance]:
        """Get healthy instances of a service.

        Args:
            service_name: Service name

        Returns:
            List of healthy service instances
        """
        service = await self.get_service(service_name)
        if not service:
            return []

        healthy_instances = []
        for instance in service.instances:
            if instance.health.status == ServiceStatus.HEALTHY:
                healthy_instances.append(instance)

        return healthy_instances

    async def update_instance_health(
        self, service_name: str, instance_id: str, health: ServiceHealth
    ) -> bool:
        """Update instance health information.

        Args:
            service_name: Service name
            instance_id: Instance ID
            health: Updated health information

        Returns:
            True if updated successfully
        """
        try:
            instance_key = f"service:{service_name}:instance:{instance_id}"
            instance_data = self.redis.get(instance_key)

            if not instance_data:
                return False

            # Update health
            data = json.loads(instance_data)
            data["health"] = health.dict()
            data["last_heartbeat"] = datetime.utcnow().isoformat()

            # Store updated instance
            self._set_with_ttl(instance_key, json.dumps(data, default=str))

            # Emit health change event if status changed
            previous_health = ServiceHealth(**data["health"])
            if previous_health.status != health.status:
                await self._emit_event(
                    ServiceEvent(
                        event_type="health_changed",
                        service_name=service_name,
                        instance_id=instance_id,
                        details={
                            "previous_status": previous_health.status.value,
                            "new_status": health.status.value,
                            "response_time_ms": health.response_time_ms,
                        },
                    )
                )

            return True

        except Exception as e:
            logger.error(
                f"Failed to update health for {service_name}/{instance_id}: {e}"
            )
            return False

    async def heartbeat(self, service_name: str, instance_id: str) -> bool:
        """Record service heartbeat.

        Args:
            service_name: Service name
            instance_id: Instance ID

        Returns:
            True if heartbeat recorded
        """
        try:
            instance_key = f"service:{service_name}:instance:{instance_id}"
            instance_data = self.redis.get(instance_key)

            if not instance_data:
                return False

            # Update heartbeat
            data = json.loads(instance_data)
            data["last_heartbeat"] = datetime.utcnow().isoformat()

            # Store updated instance
            self._set_with_ttl(instance_key, json.dumps(data, default=str))

            return True

        except Exception as e:
            logger.error(
                f"Failed to record heartbeat for {service_name}/{instance_id}: {e}"
            )
            return False

    async def add_event_listener(
        self, event_type: str, callback: Callable[[ServiceEvent], None]
    ):
        """Add event listener.

        Args:
            event_type: Event type to listen for
            callback: Callback function
        """
        if event_type not in self.event_listeners:
            self.event_listeners[event_type] = []

        self.event_listeners[event_type].append(callback)

    async def remove_event_listener(self, event_type: str, callback: Callable):
        """Remove event listener.

        Args:
            event_type: Event type
            callback: Callback function to remove
        """
        if event_type in self.event_listeners:
            try:
                self.event_listeners[event_type].remove(callback)
            except ValueError:
                pass

    async def start_background_tasks(self):
        """Start background monitoring tasks."""
        if self._running:
            return

        self._running = True

        # Start cleanup task
        self._tasks.append(asyncio.create_task(self._cleanup_expired_services()))

        logger.info("Service registry background tasks started")

    async def stop_background_tasks(self):
        """Stop background tasks."""
        self._running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()

        # Close HTTP client
        await self.http_client.aclose()

        logger.info("Service registry background tasks stopped")

    async def _register_instance(
        self, service_name: str, instance: ServiceInstance
    ) -> bool:
        """Register a service instance.

        Args:
            service_name: Service name
            instance: Instance to register

        Returns:
            True if registered successfully
        """
        try:
            # Store instance data
            instance_key = f"service:{service_name}:instance:{instance.instance_id}"
            instance_data = instance.dict()

            self._set_with_ttl(instance_key, json.dumps(instance_data, default=str))

            # Add to instance set
            self.redis.sadd(f"service:{service_name}:instances", instance.instance_id)

            # Emit event
            await self._emit_event(
                ServiceEvent(
                    event_type="instance_registered",
                    service_name=service_name,
                    instance_id=instance.instance_id,
                    details={"url": instance.url, "weight": instance.weight},
                )
            )

            return True

        except Exception as e:
            logger.error(
                f"Failed to register instance {service_name}/{instance.instance_id}: {e}"
            )
            return False

    async def _cleanup_expired_services(self):
        """Background task to clean up expired services."""
        while self._running:
            try:
                # Check for expired services
                current_time = time.time()

                service_names = self.redis.smembers("services:active")
                for service_name in service_names:
                    if isinstance(service_name, bytes):
                        service_name = service_name.decode()

                    service_key = f"service:{service_name}"
                    if not self.redis.exists(service_key):
                        # Service expired, clean up
                        logger.info(f"Cleaning up expired service: {service_name}")
                        await self.deregister(service_name)

                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                await asyncio.sleep(60)

    async def _emit_event(self, event: ServiceEvent):
        """Emit service registry event.

        Args:
            event: Event to emit
        """
        try:
            # Call registered listeners
            if event.event_type in self.event_listeners:
                for callback in self.event_listeners[event.event_type]:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(event)
                        else:
                            callback(event)
                    except Exception as e:
                        logger.error(f"Error in event callback: {e}")

            # Store event in Redis for audit trail
            event_key = f"events:{event.service_name}:{int(time.time())}"
            self.redis.setex(
                event_key, 86400, json.dumps(event.dict(), default=str)  # 24 hour TTL
            )

        except Exception as e:
            logger.error(f"Failed to emit event: {e}")


# Export components
__all__ = [
    "ServiceRegistry",
    "Service",
    "ServiceInstance",
    "ServiceHealth",
    "ServiceStatus",
    "ServiceEvent",
]
