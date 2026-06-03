"""Backend selection logic for multi-backend runtime support."""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from .base_backend import (
    BaseBackend, ResourceRequirements, BackendCapacity,
    BackendUnavailableError
)

logger = logging.getLogger(__name__)


class SelectionStrategy(Enum):
    """Backend selection strategies."""
    FASTEST = "fastest"          # Select backend with shortest queue time
    CHEAPEST = "cheapest"        # Select backend with lowest cost
    MOST_AVAILABLE = "most_available"  # Select backend with most available resources
    PREFERRED = "preferred"      # Use preferred order with fallback
    LOAD_BALANCED = "load_balanced"    # Distribute load across backends


@dataclass
class BackendScore:
    """Scoring information for backend selection."""
    backend: BaseBackend
    score: float
    queue_time: int
    cost: float
    availability_ratio: float
    health_status: bool
    can_satisfy: bool
    reason: str


class BackendSelector:
    """Intelligent backend selection and failover management."""

    def __init__(self, backends: List[BaseBackend],
                 strategy: SelectionStrategy = SelectionStrategy.MOST_AVAILABLE,
                 preferred_order: Optional[List[str]] = None):
        """Initialize backend selector.

        Args:
            backends: List of available backends
            strategy: Default selection strategy
            preferred_order: Preferred backend order (names)
        """
        self.backends = {backend.name: backend for backend in backends}
        self.strategy = strategy
        self.preferred_order = preferred_order or []
        self._health_cache: Dict[str, Tuple[bool, float]] = {}
        self._capacity_cache: Dict[str, Tuple[BackendCapacity, float]] = {}
        self._last_selected: Dict[str, int] = {}  # For load balancing

        logger.info(f"Initialized backend selector with {len(backends)} backends")

    async def select_backend(self,
                           requirements: ResourceRequirements,
                           strategy: Optional[SelectionStrategy] = None,
                           excluded_backends: Optional[List[str]] = None) -> BaseBackend:
        """Select the best backend for given requirements.

        Args:
            requirements: Resource requirements for the job
            strategy: Selection strategy (uses default if None)
            excluded_backends: List of backend names to exclude

        Returns:
            Selected backend

        Raises:
            BackendUnavailableError: If no suitable backend available
        """
        strategy = strategy or self.strategy
        excluded_backends = excluded_backends or []

        # Filter available backends
        available_backends = [
            backend for name, backend in self.backends.items()
            if name not in excluded_backends
        ]

        if not available_backends:
            raise BackendUnavailableError("No backends available")

        # Score all backends
        backend_scores = await self._score_backends(available_backends, requirements)

        # Filter out backends that can't satisfy requirements
        suitable_backends = [score for score in backend_scores if score.can_satisfy]

        if not suitable_backends:
            reasons = [f"{score.backend.name}: {score.reason}"
                      for score in backend_scores if not score.can_satisfy]
            raise BackendUnavailableError(
                f"No backends can satisfy requirements. Reasons: {'; '.join(reasons)}"
            )

        # Apply selection strategy
        selected_score = self._apply_strategy(suitable_backends, strategy)

        logger.info(
            f"Selected backend '{selected_score.backend.name}' "
            f"(strategy: {strategy.value}, score: {selected_score.score:.2f}, "
            f"queue: {selected_score.queue_time}min, cost: ${selected_score.cost:.2f})"
        )

        # Update load balancing tracking
        self._last_selected[selected_score.backend.name] = \
            self._last_selected.get(selected_score.backend.name, 0) + 1

        return selected_score.backend

    async def select_with_failover(self,
                                 requirements: ResourceRequirements,
                                 max_attempts: int = 3,
                                 strategy: Optional[SelectionStrategy] = None) -> BaseBackend:
        """Select backend with automatic failover.

        Args:
            requirements: Resource requirements
            max_attempts: Maximum failover attempts
            strategy: Selection strategy

        Returns:
            Selected backend

        Raises:
            BackendUnavailableError: If all backends fail
        """
        excluded_backends = []
        last_error = None

        for attempt in range(max_attempts):
            try:
                backend = await self.select_backend(
                    requirements, strategy, excluded_backends
                )

                # Test backend health before returning
                if await backend.check_health():
                    return backend
                else:
                    logger.warning(f"Backend {backend.name} failed health check")
                    excluded_backends.append(backend.name)
                    last_error = f"Health check failed for {backend.name}"

            except BackendUnavailableError as e:
                last_error = str(e)
                if attempt == max_attempts - 1:
                    break

                # Wait before retry
                await asyncio.sleep(1.0 * (attempt + 1))

        raise BackendUnavailableError(
            f"All backends failed after {max_attempts} attempts. Last error: {last_error}"
        )

    async def _score_backends(self,
                            backends: List[BaseBackend],
                            requirements: ResourceRequirements) -> List[BackendScore]:
        """Score all backends for selection."""
        scores = []

        # Gather information concurrently
        tasks = []
        for backend in backends:
            tasks.append(self._score_backend(backend, requirements))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Error scoring backend {backends[i].name}: {result}")
                scores.append(BackendScore(
                    backend=backends[i],
                    score=0.0,
                    queue_time=9999,
                    cost=9999.0,
                    availability_ratio=0.0,
                    health_status=False,
                    can_satisfy=False,
                    reason=f"Error: {result}"
                ))
            else:
                scores.append(result)

        return scores

    async def _score_backend(self,
                           backend: BaseBackend,
                           requirements: ResourceRequirements) -> BackendScore:
        """Score a single backend."""
        try:
            # Check if backend can satisfy requirements
            can_satisfy = backend.supports_requirements(requirements)
            if not can_satisfy:
                return BackendScore(
                    backend=backend,
                    score=0.0,
                    queue_time=9999,
                    cost=9999.0,
                    availability_ratio=0.0,
                    health_status=False,
                    can_satisfy=False,
                    reason="Requirements not supported"
                )

            # Get health status (with caching)
            health_status = await self._get_cached_health(backend)
            if not health_status:
                return BackendScore(
                    backend=backend,
                    score=0.0,
                    queue_time=9999,
                    cost=9999.0,
                    availability_ratio=0.0,
                    health_status=False,
                    can_satisfy=False,
                    reason="Backend unhealthy"
                )

            # Get capacity information (with caching)
            capacity = await self._get_cached_capacity(backend)

            # Calculate availability ratio
            cpu_ratio = capacity.available_cpu / max(capacity.total_cpu, 1.0)
            memory_ratio = capacity.available_memory_gb / max(capacity.total_memory_gb, 1.0)
            availability_ratio = min(cpu_ratio, memory_ratio)

            # Check if enough resources available
            if (capacity.available_cpu < requirements.cpu or
                capacity.available_memory_gb < requirements.memory_gb):
                return BackendScore(
                    backend=backend,
                    score=0.0,
                    queue_time=capacity.queue_depth * 5,  # Estimate
                    cost=backend.get_cost_estimate(requirements),
                    availability_ratio=availability_ratio,
                    health_status=True,
                    can_satisfy=False,
                    reason="Insufficient resources available"
                )

            # Get queue time and cost estimates
            queue_time = backend.estimate_queue_time(requirements)
            cost = backend.get_cost_estimate(requirements)

            # Calculate composite score (0-100)
            score = self._calculate_score(
                availability_ratio, queue_time, cost, capacity.queue_depth
            )

            return BackendScore(
                backend=backend,
                score=score,
                queue_time=queue_time,
                cost=cost,
                availability_ratio=availability_ratio,
                health_status=True,
                can_satisfy=True,
                reason="Available"
            )

        except Exception as e:
            logger.error(f"Error scoring backend {backend.name}: {e}")
            return BackendScore(
                backend=backend,
                score=0.0,
                queue_time=9999,
                cost=9999.0,
                availability_ratio=0.0,
                health_status=False,
                can_satisfy=False,
                reason=f"Scoring error: {e}"
            )

    def _calculate_score(self, availability_ratio: float, queue_time: int,
                        cost: float, queue_depth: int) -> float:
        """Calculate composite score for backend."""
        # Normalize components (0-1)
        availability_score = availability_ratio

        # Queue time score (inverse, capped at 60 minutes)
        queue_score = max(0, 1 - (queue_time / 60.0))

        # Cost score (inverse, with reasonable cap)
        cost_score = max(0, 1 - (cost / 10.0))  # $10 cap for normalization

        # Queue depth score (inverse, capped at 100 jobs)
        depth_score = max(0, 1 - (queue_depth / 100.0))

        # Weighted combination
        score = (
            availability_score * 0.4 +
            queue_score * 0.3 +
            cost_score * 0.2 +
            depth_score * 0.1
        ) * 100

        return score

    def _apply_strategy(self,
                       backend_scores: List[BackendScore],
                       strategy: SelectionStrategy) -> BackendScore:
        """Apply selection strategy to choose backend."""

        if strategy == SelectionStrategy.FASTEST:
            return min(backend_scores, key=lambda x: x.queue_time)

        elif strategy == SelectionStrategy.CHEAPEST:
            return min(backend_scores, key=lambda x: x.cost)

        elif strategy == SelectionStrategy.MOST_AVAILABLE:
            return max(backend_scores, key=lambda x: x.availability_ratio)

        elif strategy == SelectionStrategy.PREFERRED:
            # Try preferred order first
            for preferred_name in self.preferred_order:
                for score in backend_scores:
                    if score.backend.name == preferred_name:
                        return score
            # Fall back to highest score
            return max(backend_scores, key=lambda x: x.score)

        elif strategy == SelectionStrategy.LOAD_BALANCED:
            # Select backend with least recent usage, but still good score
            weighted_scores = []
            for score in backend_scores:
                usage_count = self._last_selected.get(score.backend.name, 0)
                # Penalize heavily used backends
                usage_penalty = usage_count * 10
                weighted_score = score.score - usage_penalty
                weighted_scores.append((score, weighted_score))

            return max(weighted_scores, key=lambda x: x[1])[0]

        else:
            # Default to highest score
            return max(backend_scores, key=lambda x: x.score)

    async def _get_cached_health(self, backend: BaseBackend) -> bool:
        """Get cached health status or fetch if expired."""
        import time

        current_time = time.time()
        cache_key = backend.name

        if cache_key in self._health_cache:
            health, timestamp = self._health_cache[cache_key]
            if current_time - timestamp < 60:  # 1 minute cache
                return health

        # Fetch fresh health status
        try:
            health = await backend.check_health()
            self._health_cache[cache_key] = (health, current_time)
            return health
        except Exception as e:
            logger.error(f"Health check failed for {backend.name}: {e}")
            self._health_cache[cache_key] = (False, current_time)
            return False

    async def _get_cached_capacity(self, backend: BaseBackend) -> BackendCapacity:
        """Get cached capacity information or fetch if expired."""
        import time

        current_time = time.time()
        cache_key = backend.name

        if cache_key in self._capacity_cache:
            capacity, timestamp = self._capacity_cache[cache_key]
            if current_time - timestamp < 300:  # 5 minute cache
                return capacity

        # Fetch fresh capacity
        try:
            capacity = await backend.get_capacity()
            self._capacity_cache[cache_key] = (capacity, current_time)
            return capacity
        except Exception as e:
            logger.error(f"Capacity check failed for {backend.name}: {e}")
            # Return empty capacity
            capacity = BackendCapacity(0, 0, 0, 0, 0, 0, 0)
            self._capacity_cache[cache_key] = (capacity, current_time)
            return capacity

    async def get_backend_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all backends."""
        status = {}

        for name, backend in self.backends.items():
            try:
                health = await self._get_cached_health(backend)
                capacity = await self._get_cached_capacity(backend)

                status[name] = {
                    'name': name,
                    'type': backend.__class__.__name__,
                    'healthy': health,
                    'capacity': {
                        'total_cpu': capacity.total_cpu,
                        'available_cpu': capacity.available_cpu,
                        'total_memory_gb': capacity.total_memory_gb,
                        'available_memory_gb': capacity.available_memory_gb,
                        'total_gpu': capacity.total_gpu,
                        'available_gpu': capacity.available_gpu,
                        'queue_depth': capacity.queue_depth
                    },
                    'usage_count': self._last_selected.get(name, 0)
                }
            except Exception as e:
                status[name] = {
                    'name': name,
                    'type': backend.__class__.__name__,
                    'healthy': False,
                    'error': str(e)
                }

        return status

    def clear_cache(self):
        """Clear all cached information."""
        self._health_cache.clear()
        self._capacity_cache.clear()
        logger.info("Cleared backend selector cache")

    def add_backend(self, backend: BaseBackend):
        """Add a new backend to the selector."""
        self.backends[backend.name] = backend
        logger.info(f"Added backend: {backend.name}")

    def remove_backend(self, name: str):
        """Remove a backend from the selector."""
        if name in self.backends:
            del self.backends[name]
            self._health_cache.pop(name, None)
            self._capacity_cache.pop(name, None)
            self._last_selected.pop(name, None)
            logger.info(f"Removed backend: {name}")

    def get_backend_by_name(self, name: str) -> Optional[BaseBackend]:
        """Get backend by name."""
        return self.backends.get(name)