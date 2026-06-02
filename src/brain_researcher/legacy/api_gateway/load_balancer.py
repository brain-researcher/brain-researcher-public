"""
Load Balancer for API Gateway.

Implements multiple load balancing strategies for distributing requests
across healthy service instances:

Strategies:
- Round Robin: Equal distribution across instances
- Weighted Round Robin: Distribution based on instance weights
- Least Connections: Route to instance with fewest active connections
- Least Response Time: Route to fastest responding instance
- Random: Random selection of healthy instances
- Hash-based: Consistent hashing for session affinity
- Health-aware: Only route to healthy instances

Features:
- Session affinity (sticky sessions)
- Circuit breaker integration
- Instance weight management
- Connection tracking
- Performance metrics integration
- Graceful instance removal
- Failure detection and recovery
"""

import hashlib
import logging
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from .service_registry import Service, ServiceInstance, ServiceStatus

logger = logging.getLogger(__name__)


class LoadBalancingStrategy(str, Enum):
    """Load balancing strategy types."""

    ROUND_ROBIN = "round_robin"
    WEIGHTED_ROUND_ROBIN = "weighted_round_robin"
    LEAST_CONNECTIONS = "least_connections"
    LEAST_RESPONSE_TIME = "least_response_time"
    RANDOM = "random"
    HASH = "hash"
    IP_HASH = "ip_hash"
    LEAST_LOAD = "least_load"


class AffinityType(str, Enum):
    """Session affinity types."""

    NONE = "none"
    CLIENT_IP = "client_ip"
    SESSION_ID = "session_id"
    USER_ID = "user_id"
    CUSTOM = "custom"


@dataclass
class LoadBalancerConfig:
    """Load balancer configuration."""

    strategy: LoadBalancingStrategy = LoadBalancingStrategy.ROUND_ROBIN
    health_check_enabled: bool = True
    session_affinity: AffinityType = AffinityType.NONE
    affinity_timeout_seconds: int = 3600  # 1 hour
    max_connections_per_instance: int = 1000
    connection_timeout_seconds: int = 30
    enable_circuit_breaker: bool = True
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_time: int = 60
    sticky_session_cookie: str = "GATEWAY_SESSION"
    hash_key_header: Optional[str] = None  # For custom hash-based routing


@dataclass
class InstanceMetrics:
    """Metrics for a service instance."""

    active_connections: int = 0
    total_requests: int = 0
    total_failures: int = 0
    average_response_time_ms: float = 0.0
    last_request_time: Optional[datetime] = None
    last_failure_time: Optional[datetime] = None
    consecutive_failures: int = 0
    circuit_breaker_open: bool = False
    circuit_breaker_open_time: Optional[datetime] = None
    load_score: float = 0.0  # Calculated load score

    def update_response_time(self, response_time_ms: float):
        """Update average response time with new measurement."""
        if self.total_requests == 0:
            self.average_response_time_ms = response_time_ms
        else:
            # Exponential moving average
            alpha = 0.1
            self.average_response_time_ms = (
                alpha * response_time_ms + (1 - alpha) * self.average_response_time_ms
            )

    def calculate_load_score(self, instance: ServiceInstance) -> float:
        """Calculate load score for this instance."""
        # Factors: active connections, response time, failure rate, weight
        connection_factor = self.active_connections / max(1, instance.weight)
        response_time_factor = (
            self.average_response_time_ms / 1000.0
        )  # Convert to seconds

        failure_rate = (
            self.total_failures / max(1, self.total_requests)
            if self.total_requests > 0
            else 0
        )

        # Lower score is better
        self.load_score = (
            connection_factor * 0.4 + response_time_factor * 0.3 + failure_rate * 0.3
        )

        return self.load_score


@dataclass
class SessionAffinity:
    """Session affinity information."""

    session_key: str
    instance_id: str
    created_at: datetime
    last_access: datetime
    request_count: int = 0

    def is_expired(self, timeout_seconds: int) -> bool:
        """Check if session affinity has expired."""
        return (datetime.utcnow() - self.last_access).total_seconds() > timeout_seconds

    def update_access(self):
        """Update last access time and increment request count."""
        self.last_access = datetime.utcnow()
        self.request_count += 1


class LoadBalancer:
    """Main load balancer implementation."""

    def __init__(self, config: Optional[LoadBalancerConfig] = None):
        """Initialize load balancer.

        Args:
            config: Load balancer configuration
        """
        self.config = config or LoadBalancerConfig()

        # Instance metrics tracking
        self.instance_metrics: Dict[str, InstanceMetrics] = defaultdict(InstanceMetrics)

        # Session affinity tracking
        self.session_affinities: Dict[str, SessionAffinity] = {}

        # Round-robin state
        self._round_robin_counters: Dict[str, int] = defaultdict(int)

        # Weighted round-robin state
        self._weighted_counters: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

        # Connection tracking
        self.active_connections: Dict[str, Set[str]] = defaultdict(set)

        # Custom load balancing functions
        self.custom_selectors: Dict[str, Callable] = {}

    def select_instance(
        self,
        service: Service,
        strategy: Optional[LoadBalancingStrategy] = None,
        client_ip: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        hash_key: Optional[str] = None,
    ) -> Optional[str]:
        """Select a service instance using the configured strategy.

        Args:
            service: Service to select instance from
            strategy: Override load balancing strategy
            client_ip: Client IP for IP-based affinity/hashing
            session_id: Session ID for session affinity
            user_id: User ID for user-based affinity
            hash_key: Custom hash key

        Returns:
            Selected instance URL or None if no healthy instances
        """
        if not service.instances:
            return None

        # Filter healthy instances
        healthy_instances = self._get_healthy_instances(service)
        if not healthy_instances:
            logger.warning(f"No healthy instances for service {service.name}")
            return None

        # Use provided strategy or default
        used_strategy = strategy or self.config.strategy

        # Check session affinity first
        if self.config.session_affinity != AffinityType.NONE:
            affinity_key = self._get_affinity_key(client_ip, session_id, user_id)
            if affinity_key:
                instance_url = self._check_session_affinity(
                    affinity_key, healthy_instances
                )
                if instance_url:
                    return instance_url

        # Apply load balancing strategy
        selected_instance = None

        if used_strategy == LoadBalancingStrategy.ROUND_ROBIN:
            selected_instance = self._round_robin_select(
                service.name, healthy_instances
            )

        elif used_strategy == LoadBalancingStrategy.WEIGHTED_ROUND_ROBIN:
            selected_instance = self._weighted_round_robin_select(
                service.name, healthy_instances
            )

        elif used_strategy == LoadBalancingStrategy.LEAST_CONNECTIONS:
            selected_instance = self._least_connections_select(healthy_instances)

        elif used_strategy == LoadBalancingStrategy.LEAST_RESPONSE_TIME:
            selected_instance = self._least_response_time_select(healthy_instances)

        elif used_strategy == LoadBalancingStrategy.RANDOM:
            selected_instance = self._random_select(healthy_instances)

        elif used_strategy == LoadBalancingStrategy.HASH:
            selected_instance = self._hash_select(healthy_instances, hash_key)

        elif used_strategy == LoadBalancingStrategy.IP_HASH:
            selected_instance = self._ip_hash_select(healthy_instances, client_ip)

        elif used_strategy == LoadBalancingStrategy.LEAST_LOAD:
            selected_instance = self._least_load_select(healthy_instances)

        if selected_instance:
            # Update session affinity if enabled
            if self.config.session_affinity != AffinityType.NONE:
                affinity_key = self._get_affinity_key(client_ip, session_id, user_id)
                if affinity_key:
                    self._create_session_affinity(
                        affinity_key, selected_instance.instance_id
                    )

            return selected_instance.url

        return None

    def record_request_start(self, instance_url: str, connection_id: str):
        """Record the start of a request to an instance.

        Args:
            instance_url: Target instance URL
            connection_id: Unique connection identifier
        """
        instance_id = self._url_to_instance_id(instance_url)
        if instance_id:
            metrics = self.instance_metrics[instance_id]
            metrics.active_connections += 1
            metrics.total_requests += 1
            metrics.last_request_time = datetime.utcnow()

            # Track active connection
            self.active_connections[instance_id].add(connection_id)

    def record_request_end(
        self,
        instance_url: str,
        connection_id: str,
        response_time_ms: float,
        success: bool = True,
    ):
        """Record the completion of a request.

        Args:
            instance_url: Target instance URL
            connection_id: Unique connection identifier
            response_time_ms: Request response time in milliseconds
            success: Whether the request was successful
        """
        instance_id = self._url_to_instance_id(instance_url)
        if instance_id:
            metrics = self.instance_metrics[instance_id]

            # Update connection count
            if metrics.active_connections > 0:
                metrics.active_connections -= 1

            # Remove from active connections
            self.active_connections[instance_id].discard(connection_id)

            # Update response time
            metrics.update_response_time(response_time_ms)

            # Update failure tracking
            if not success:
                metrics.total_failures += 1
                metrics.consecutive_failures += 1
                metrics.last_failure_time = datetime.utcnow()

                # Check circuit breaker
                if self.config.enable_circuit_breaker:
                    self._check_circuit_breaker(instance_id, metrics)
            else:
                metrics.consecutive_failures = 0

    def get_instance_metrics(self, instance_id: str) -> Optional[InstanceMetrics]:
        """Get metrics for a specific instance.

        Args:
            instance_id: Instance identifier

        Returns:
            Instance metrics or None if not found
        """
        return self.instance_metrics.get(instance_id)

    def get_all_metrics(self) -> Dict[str, InstanceMetrics]:
        """Get metrics for all instances.

        Returns:
            Dictionary of instance_id -> InstanceMetrics
        """
        return dict(self.instance_metrics)

    def cleanup_expired_sessions(self):
        """Clean up expired session affinities."""
        expired_keys = []

        for key, affinity in self.session_affinities.items():
            if affinity.is_expired(self.config.affinity_timeout_seconds):
                expired_keys.append(key)

        for key in expired_keys:
            del self.session_affinities[key]

        logger.debug(f"Cleaned up {len(expired_keys)} expired session affinities")

    def add_custom_selector(self, name: str, selector_func: Callable):
        """Add custom load balancing selector function.

        Args:
            name: Selector name
            selector_func: Function that takes (instances, **kwargs) and returns selected instance
        """
        self.custom_selectors[name] = selector_func

    def _get_healthy_instances(self, service: Service) -> List[ServiceInstance]:
        """Get list of healthy service instances.

        Args:
            service: Service to check

        Returns:
            List of healthy instances
        """
        healthy = []

        for instance in service.instances:
            # Check health status
            if self.config.health_check_enabled:
                if instance.health.status != ServiceStatus.HEALTHY:
                    continue

            # Check circuit breaker
            if self.config.enable_circuit_breaker:
                instance_id = instance.instance_id
                metrics = self.instance_metrics[instance_id]

                if metrics.circuit_breaker_open:
                    # Check if recovery time has passed
                    if (
                        metrics.circuit_breaker_open_time
                        and (
                            datetime.utcnow() - metrics.circuit_breaker_open_time
                        ).total_seconds()
                        < self.config.circuit_breaker_recovery_time
                    ):
                        continue
                    else:
                        # Allow traffic for circuit breaker recovery test
                        metrics.circuit_breaker_open = False
                        metrics.circuit_breaker_open_time = None

            # Check connection limits
            instance_metrics = self.instance_metrics[instance.instance_id]
            if (
                instance_metrics.active_connections
                >= self.config.max_connections_per_instance
            ):
                continue

            healthy.append(instance)

        return healthy

    def _get_affinity_key(
        self,
        client_ip: Optional[str],
        session_id: Optional[str],
        user_id: Optional[str],
    ) -> Optional[str]:
        """Get session affinity key based on configuration.

        Args:
            client_ip: Client IP address
            session_id: Session identifier
            user_id: User identifier

        Returns:
            Affinity key or None
        """
        if self.config.session_affinity == AffinityType.CLIENT_IP and client_ip:
            return f"ip:{client_ip}"
        elif self.config.session_affinity == AffinityType.SESSION_ID and session_id:
            return f"session:{session_id}"
        elif self.config.session_affinity == AffinityType.USER_ID and user_id:
            return f"user:{user_id}"

        return None

    def _check_session_affinity(
        self, affinity_key: str, healthy_instances: List[ServiceInstance]
    ) -> Optional[str]:
        """Check if there's an existing session affinity.

        Args:
            affinity_key: Session affinity key
            healthy_instances: List of healthy instances

        Returns:
            Instance URL if affinity exists and instance is healthy
        """
        if affinity_key in self.session_affinities:
            affinity = self.session_affinities[affinity_key]

            # Check if affinity is expired
            if affinity.is_expired(self.config.affinity_timeout_seconds):
                del self.session_affinities[affinity_key]
                return None

            # Check if instance is still healthy
            for instance in healthy_instances:
                if instance.instance_id == affinity.instance_id:
                    affinity.update_access()
                    return instance.url

            # Instance is not healthy, remove affinity
            del self.session_affinities[affinity_key]

        return None

    def _create_session_affinity(self, affinity_key: str, instance_id: str):
        """Create new session affinity.

        Args:
            affinity_key: Session affinity key
            instance_id: Target instance ID
        """
        self.session_affinities[affinity_key] = SessionAffinity(
            session_key=affinity_key,
            instance_id=instance_id,
            created_at=datetime.utcnow(),
            last_access=datetime.utcnow(),
        )

    def _round_robin_select(
        self, service_name: str, instances: List[ServiceInstance]
    ) -> Optional[ServiceInstance]:
        """Select instance using round-robin strategy."""
        if not instances:
            return None

        counter = self._round_robin_counters[service_name]
        selected = instances[counter % len(instances)]
        self._round_robin_counters[service_name] = (counter + 1) % len(instances)

        return selected

    def _weighted_round_robin_select(
        self, service_name: str, instances: List[ServiceInstance]
    ) -> Optional[ServiceInstance]:
        """Select instance using weighted round-robin strategy."""
        if not instances:
            return None

        # Calculate total weight
        total_weight = sum(instance.weight for instance in instances)
        if total_weight == 0:
            # Fall back to regular round-robin
            return self._round_robin_select(service_name, instances)

        # Use current weight approach for smooth weighted round-robin
        counters = self._weighted_counters[service_name]

        # Find instance with highest current weight
        best_instance = None
        best_weight = -1

        for instance in instances:
            instance_id = instance.instance_id
            counters[instance_id] += instance.weight

            if counters[instance_id] > best_weight:
                best_weight = counters[instance_id]
                best_instance = instance

        if best_instance:
            # Reduce current weight by total weight
            counters[best_instance.instance_id] -= total_weight

        return best_instance

    def _least_connections_select(
        self, instances: List[ServiceInstance]
    ) -> Optional[ServiceInstance]:
        """Select instance with least active connections."""
        if not instances:
            return None

        min_connections = float("inf")
        selected_instance = None

        for instance in instances:
            metrics = self.instance_metrics[instance.instance_id]

            if metrics.active_connections < min_connections:
                min_connections = metrics.active_connections
                selected_instance = instance

        return selected_instance

    def _least_response_time_select(
        self, instances: List[ServiceInstance]
    ) -> Optional[ServiceInstance]:
        """Select instance with lowest average response time."""
        if not instances:
            return None

        min_response_time = float("inf")
        selected_instance = None

        for instance in instances:
            metrics = self.instance_metrics[instance.instance_id]

            # Consider both response time and active connections
            adjusted_time = metrics.average_response_time_ms * (
                1 + metrics.active_connections * 0.1
            )

            if adjusted_time < min_response_time:
                min_response_time = adjusted_time
                selected_instance = instance

        return selected_instance

    def _random_select(
        self, instances: List[ServiceInstance]
    ) -> Optional[ServiceInstance]:
        """Select random instance."""
        if not instances:
            return None

        return random.choice(instances)

    def _hash_select(
        self, instances: List[ServiceInstance], hash_key: Optional[str]
    ) -> Optional[ServiceInstance]:
        """Select instance using consistent hashing."""
        if not instances or not hash_key:
            return self._random_select(instances)

        # Use MD5 hash for consistent distribution
        hash_value = int(hashlib.md5(hash_key.encode()).hexdigest(), 16)
        selected_index = hash_value % len(instances)

        return instances[selected_index]

    def _ip_hash_select(
        self, instances: List[ServiceInstance], client_ip: Optional[str]
    ) -> Optional[ServiceInstance]:
        """Select instance using IP-based hashing."""
        return self._hash_select(instances, client_ip)

    def _least_load_select(
        self, instances: List[ServiceInstance]
    ) -> Optional[ServiceInstance]:
        """Select instance with lowest calculated load score."""
        if not instances:
            return None

        min_load = float("inf")
        selected_instance = None

        for instance in instances:
            metrics = self.instance_metrics[instance.instance_id]
            load_score = metrics.calculate_load_score(instance)

            if load_score < min_load:
                min_load = load_score
                selected_instance = instance

        return selected_instance

    def _check_circuit_breaker(self, instance_id: str, metrics: InstanceMetrics):
        """Check and update circuit breaker status.

        Args:
            instance_id: Instance identifier
            metrics: Instance metrics
        """
        if (
            metrics.consecutive_failures
            >= self.config.circuit_breaker_failure_threshold
        ):
            if not metrics.circuit_breaker_open:
                metrics.circuit_breaker_open = True
                metrics.circuit_breaker_open_time = datetime.utcnow()
                logger.warning(f"Circuit breaker opened for instance {instance_id}")

    def _url_to_instance_id(self, url: str) -> Optional[str]:
        """Convert instance URL to instance ID.

        Args:
            url: Instance URL

        Returns:
            Instance ID or None if not found
        """
        # This is a simplified mapping - in practice, you'd maintain
        # a proper URL to instance ID mapping
        return url.replace("http://", "").replace("https://", "").replace(":", "_")


# Export components
__all__ = [
    "LoadBalancer",
    "LoadBalancerConfig",
    "LoadBalancingStrategy",
    "AffinityType",
    "InstanceMetrics",
    "SessionAffinity",
]
