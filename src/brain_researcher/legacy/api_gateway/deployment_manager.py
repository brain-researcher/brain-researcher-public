"""
Blue-Green Deployment Manager for API Gateway.

Provides blue-green deployment capabilities with traffic switching,
health monitoring, and rollback functionality.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
import redis.asyncio as redis

from .service_registry import (
    Service,
    ServiceHealth,
    ServiceInstance,
    ServiceRegistry,
    ServiceStatus,
)

logger = logging.getLogger(__name__)


class DeploymentState(str, Enum):
    """Deployment states."""

    INACTIVE = "inactive"
    PREPARING = "preparing"
    READY = "ready"
    ACTIVE = "active"
    DRAINING = "draining"
    FAILED = "failed"


class TrafficSplitStrategy(str, Enum):
    """Traffic split strategies."""

    ALL_OR_NOTHING = "all_or_nothing"
    GRADUAL = "gradual"
    CANARY = "canary"
    A_B_TEST = "a_b_test"


@dataclass
class DeploymentEnvironment:
    """Represents a deployment environment (blue or green)."""

    name: str  # "blue" or "green"
    services: Dict[str, Service] = field(default_factory=dict)
    state: DeploymentState = DeploymentState.INACTIVE
    version: str = "1.0.0"
    deployed_at: Optional[datetime] = None
    traffic_percentage: float = 0.0
    health_check_passed: bool = False
    readiness_checks: Dict[str, bool] = field(default_factory=dict)
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class DeploymentConfig:
    """Blue-green deployment configuration."""

    health_check_timeout_seconds: int = 300  # 5 minutes
    health_check_interval_seconds: int = 10
    readiness_timeout_seconds: int = 180  # 3 minutes
    traffic_switch_strategy: TrafficSplitStrategy = TrafficSplitStrategy.ALL_OR_NOTHING
    gradual_switch_duration_seconds: int = 300  # 5 minutes for gradual switch
    canary_percentage: float = 10.0  # 10% for canary
    rollback_on_failure: bool = True
    keep_previous_version: bool = True
    drain_timeout_seconds: int = 60
    required_readiness_checks: List[str] = field(default_factory=list)


@dataclass
class DeploymentPlan:
    """Deployment execution plan."""

    id: str
    target_environment: str  # "blue" or "green"
    services: Dict[str, Service]
    version: str
    strategy: TrafficSplitStrategy
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "pending"
    steps: List[Dict[str, Any]] = field(default_factory=list)
    rollback_plan: Optional["DeploymentPlan"] = None


class HealthChecker:
    """Performs health checks on deployment environments."""

    def __init__(self, http_client: httpx.AsyncClient):
        """Initialize health checker.

        Args:
            http_client: HTTP client for health checks
        """
        self.http_client = http_client

    async def check_environment_health(
        self, environment: DeploymentEnvironment, timeout_seconds: int = 30
    ) -> Tuple[bool, Dict[str, Any]]:
        """Check health of all services in environment.

        Args:
            environment: Environment to check
            timeout_seconds: Health check timeout

        Returns:
            Tuple of (is_healthy, health_details)
        """
        health_details = {}
        all_healthy = True

        for service_name, service in environment.services.items():
            service_healthy = await self.check_service_health(service, timeout_seconds)
            health_details[service_name] = {
                "healthy": service_healthy,
                "instances": len(service.instances),
                "healthy_instances": sum(
                    1
                    for instance in service.instances
                    if instance.health.status == ServiceStatus.HEALTHY
                ),
            }

            if not service_healthy:
                all_healthy = False

        return all_healthy, health_details

    async def check_service_health(
        self, service: Service, timeout_seconds: int = 30
    ) -> bool:
        """Check health of individual service.

        Args:
            service: Service to check
            timeout_seconds: Health check timeout

        Returns:
            True if service is healthy
        """
        if not service.instances:
            return False

        healthy_instances = 0

        for instance in service.instances:
            if await self.check_instance_health(instance, timeout_seconds):
                healthy_instances += 1

        # Require at least 50% of instances to be healthy
        required_healthy = max(1, len(service.instances) // 2)
        return healthy_instances >= required_healthy

    async def check_instance_health(
        self, instance: ServiceInstance, timeout_seconds: int = 30
    ) -> bool:
        """Check health of service instance.

        Args:
            instance: Instance to check
            timeout_seconds: Health check timeout

        Returns:
            True if instance is healthy
        """
        try:
            health_url = f"{instance.url.rstrip('/')}/health"

            response = await self.http_client.get(health_url, timeout=timeout_seconds)

            return response.status_code == 200

        except Exception as e:
            logger.warning(
                f"Health check failed for instance {instance.instance_id}: {e}"
            )
            return False


class TrafficSwitcher:
    """Manages traffic switching between environments."""

    def __init__(self, service_registry: ServiceRegistry):
        """Initialize traffic switcher.

        Args:
            service_registry: Service registry for updating routing
        """
        self.service_registry = service_registry

    async def switch_traffic(
        self,
        from_env: DeploymentEnvironment,
        to_env: DeploymentEnvironment,
        strategy: TrafficSplitStrategy,
        **strategy_params,
    ) -> bool:
        """Switch traffic between environments.

        Args:
            from_env: Source environment
            to_env: Target environment
            strategy: Traffic switch strategy
            **strategy_params: Strategy-specific parameters

        Returns:
            True if switch was successful
        """
        try:
            if strategy == TrafficSplitStrategy.ALL_OR_NOTHING:
                return await self._switch_all_traffic(from_env, to_env)

            elif strategy == TrafficSplitStrategy.GRADUAL:
                duration = strategy_params.get("duration_seconds", 300)
                return await self._switch_gradual_traffic(from_env, to_env, duration)

            elif strategy == TrafficSplitStrategy.CANARY:
                percentage = strategy_params.get("canary_percentage", 10.0)
                return await self._switch_canary_traffic(from_env, to_env, percentage)

            elif strategy == TrafficSplitStrategy.A_B_TEST:
                percentage = strategy_params.get("test_percentage", 50.0)
                return await self._switch_ab_test_traffic(from_env, to_env, percentage)

            else:
                logger.error(f"Unknown traffic switch strategy: {strategy}")
                return False

        except Exception as e:
            logger.error(f"Traffic switch failed: {e}")
            return False

    async def _switch_all_traffic(
        self, from_env: DeploymentEnvironment, to_env: DeploymentEnvironment
    ) -> bool:
        """Switch all traffic immediately."""
        # Update service registry to point to new environment
        for service_name, service in to_env.services.items():
            await self.service_registry.register(service)

        # Update traffic percentages
        from_env.traffic_percentage = 0.0
        to_env.traffic_percentage = 100.0

        logger.info(f"Switched all traffic from {from_env.name} to {to_env.name}")
        return True

    async def _switch_gradual_traffic(
        self,
        from_env: DeploymentEnvironment,
        to_env: DeploymentEnvironment,
        duration_seconds: int,
    ) -> bool:
        """Switch traffic gradually over time."""
        steps = 10  # Switch in 10% increments
        step_duration = duration_seconds / steps

        for step in range(1, steps + 1):
            percentage = (step / steps) * 100

            # Update traffic distribution
            from_env.traffic_percentage = 100.0 - percentage
            to_env.traffic_percentage = percentage

            # Update service weights in registry
            await self._update_service_weights(from_env, to_env)

            logger.info(
                f"Traffic switch step {step}/{steps}: {percentage}% to {to_env.name}"
            )

            if step < steps:
                await asyncio.sleep(step_duration)

        logger.info(f"Completed gradual traffic switch to {to_env.name}")
        return True

    async def _switch_canary_traffic(
        self,
        from_env: DeploymentEnvironment,
        to_env: DeploymentEnvironment,
        canary_percentage: float,
    ) -> bool:
        """Switch small percentage of traffic for canary testing."""
        from_env.traffic_percentage = 100.0 - canary_percentage
        to_env.traffic_percentage = canary_percentage

        await self._update_service_weights(from_env, to_env)

        logger.info(f"Started canary deployment: {canary_percentage}% to {to_env.name}")
        return True

    async def _switch_ab_test_traffic(
        self,
        from_env: DeploymentEnvironment,
        to_env: DeploymentEnvironment,
        test_percentage: float,
    ) -> bool:
        """Switch traffic for A/B testing."""
        from_env.traffic_percentage = 100.0 - test_percentage
        to_env.traffic_percentage = test_percentage

        await self._update_service_weights(from_env, to_env)

        logger.info(f"Started A/B test: {test_percentage}% to {to_env.name}")
        return True

    async def _update_service_weights(
        self, from_env: DeploymentEnvironment, to_env: DeploymentEnvironment
    ):
        """Update service instance weights based on traffic percentages."""
        # This is a simplified implementation
        # In practice, you'd update load balancer weights or service mesh configuration

        for service_name in to_env.services:
            # Update instances with new weights based on traffic percentage
            if service_name in from_env.services:
                from_service = from_env.services[service_name]
                to_service = to_env.services[service_name]

                # Update instance weights (simplified)
                for instance in from_service.instances:
                    instance.weight = int(from_env.traffic_percentage)

                for instance in to_service.instances:
                    instance.weight = int(to_env.traffic_percentage)

                # Re-register services with updated weights
                await self.service_registry.register(from_service)
                await self.service_registry.register(to_service)


class BlueGreenDeploymentManager:
    """Main blue-green deployment manager."""

    def __init__(
        self,
        service_registry: ServiceRegistry,
        redis_client: redis.Redis,
        config: Optional[DeploymentConfig] = None,
    ):
        """Initialize deployment manager.

        Args:
            service_registry: Service registry for managing services
            redis_client: Redis client for state persistence
            config: Deployment configuration
        """
        self.service_registry = service_registry
        self.redis = redis_client
        self.config = config or DeploymentConfig()

        # Deployment environments
        self.blue_environment = DeploymentEnvironment(name="blue")
        self.green_environment = DeploymentEnvironment(name="green")

        # Active environment tracking
        self.active_environment: Optional[str] = None

        # Components
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.health_checker = HealthChecker(self.http_client)
        self.traffic_switcher = TrafficSwitcher(service_registry)

        # Current deployment
        self.current_deployment: Optional[DeploymentPlan] = None

        # Background tasks
        self.monitoring_task: Optional[asyncio.Task] = None
        self.running = False

    async def start(self):
        """Start deployment manager."""
        if self.running:
            return

        self.running = True

        # Load state from Redis
        await self._load_state()

        # Start monitoring task
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())

        logger.info("Blue-green deployment manager started")

    async def stop(self):
        """Stop deployment manager."""
        if not self.running:
            return

        self.running = False

        # Cancel monitoring task
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass

        # Close HTTP client
        await self.http_client.aclose()

        logger.info("Blue-green deployment manager stopped")

    async def create_deployment_plan(
        self,
        services: Dict[str, Service],
        version: str,
        strategy: TrafficSplitStrategy = TrafficSplitStrategy.ALL_OR_NOTHING,
    ) -> DeploymentPlan:
        """Create new deployment plan.

        Args:
            services: Services to deploy
            version: Version identifier
            strategy: Traffic switch strategy

        Returns:
            Deployment plan
        """
        # Determine target environment
        if self.active_environment == "blue":
            target_env = "green"
        elif self.active_environment == "green":
            target_env = "blue"
        else:
            # No active environment, use blue
            target_env = "blue"

        # Create deployment plan
        plan = DeploymentPlan(
            id=f"deploy_{int(time.time())}",
            target_environment=target_env,
            services=services,
            version=version,
            strategy=strategy,
        )

        # Add deployment steps
        plan.steps = [
            {"step": "prepare_environment", "status": "pending"},
            {"step": "deploy_services", "status": "pending"},
            {"step": "health_checks", "status": "pending"},
            {"step": "readiness_checks", "status": "pending"},
            {"step": "traffic_switch", "status": "pending"},
            {"step": "cleanup", "status": "pending"},
        ]

        return plan

    async def execute_deployment(self, plan: DeploymentPlan) -> bool:
        """Execute deployment plan.

        Args:
            plan: Deployment plan to execute

        Returns:
            True if deployment was successful
        """
        if self.current_deployment:
            raise ValueError("Another deployment is already in progress")

        self.current_deployment = plan
        plan.started_at = datetime.utcnow()
        plan.status = "executing"

        try:
            logger.info(f"Starting deployment {plan.id} to {plan.target_environment}")

            # Execute deployment steps
            for step_info in plan.steps:
                step_name = step_info["step"]
                logger.info(f"Executing step: {step_name}")

                step_info["status"] = "executing"
                step_info["started_at"] = datetime.utcnow().isoformat()

                success = await self._execute_step(plan, step_name)

                if success:
                    step_info["status"] = "completed"
                    step_info["completed_at"] = datetime.utcnow().isoformat()
                else:
                    step_info["status"] = "failed"
                    step_info["failed_at"] = datetime.utcnow().isoformat()

                    # Handle failure
                    if self.config.rollback_on_failure:
                        logger.warning(
                            f"Deployment step {step_name} failed, initiating rollback"
                        )
                        await self._rollback_deployment(plan)

                    plan.status = "failed"
                    return False

            # Deployment successful
            plan.status = "completed"
            plan.completed_at = datetime.utcnow()

            # Update active environment
            self.active_environment = plan.target_environment

            await self._save_state()

            logger.info(f"Deployment {plan.id} completed successfully")
            return True

        except Exception as e:
            logger.error(f"Deployment {plan.id} failed with error: {e}")
            plan.status = "failed"

            if self.config.rollback_on_failure:
                await self._rollback_deployment(plan)

            return False

        finally:
            self.current_deployment = None

    async def _execute_step(self, plan: DeploymentPlan, step_name: str) -> bool:
        """Execute individual deployment step.

        Args:
            plan: Deployment plan
            step_name: Step name

        Returns:
            True if step was successful
        """
        try:
            if step_name == "prepare_environment":
                return await self._prepare_environment(plan)

            elif step_name == "deploy_services":
                return await self._deploy_services(plan)

            elif step_name == "health_checks":
                return await self._perform_health_checks(plan)

            elif step_name == "readiness_checks":
                return await self._perform_readiness_checks(plan)

            elif step_name == "traffic_switch":
                return await self._switch_traffic(plan)

            elif step_name == "cleanup":
                return await self._cleanup_old_environment(plan)

            else:
                logger.error(f"Unknown deployment step: {step_name}")
                return False

        except Exception as e:
            logger.error(f"Step {step_name} failed: {e}")
            return False

    async def _prepare_environment(self, plan: DeploymentPlan) -> bool:
        """Prepare target environment."""
        target_env = self._get_environment(plan.target_environment)

        # Reset environment state
        target_env.state = DeploymentState.PREPARING
        target_env.services = plan.services.copy()
        target_env.version = plan.version
        target_env.deployed_at = datetime.utcnow()
        target_env.traffic_percentage = 0.0
        target_env.health_check_passed = False
        target_env.readiness_checks = {}

        return True

    async def _deploy_services(self, plan: DeploymentPlan) -> bool:
        """Deploy services to target environment."""
        target_env = self._get_environment(plan.target_environment)

        # Register services in service registry
        for service_name, service in plan.services.items():
            # Update service metadata to indicate environment
            service.metadata = service.metadata or {}
            service.metadata["environment"] = plan.target_environment
            service.metadata["deployment_id"] = plan.id
            service.metadata["version"] = plan.version

            success = await self.service_registry.register(service)
            if not success:
                logger.error(f"Failed to register service {service_name}")
                return False

        target_env.state = DeploymentState.READY
        return True

    async def _perform_health_checks(self, plan: DeploymentPlan) -> bool:
        """Perform health checks on deployed services."""
        target_env = self._get_environment(plan.target_environment)

        start_time = time.time()
        timeout = self.config.health_check_timeout_seconds

        while time.time() - start_time < timeout:
            is_healthy, health_details = (
                await self.health_checker.check_environment_health(
                    target_env, self.config.health_check_interval_seconds
                )
            )

            if is_healthy:
                target_env.health_check_passed = True
                logger.info(f"Health checks passed for {plan.target_environment}")
                return True

            logger.debug(
                f"Health check failed, retrying in {self.config.health_check_interval_seconds}s"
            )
            await asyncio.sleep(self.config.health_check_interval_seconds)

        logger.error(f"Health checks timed out for {plan.target_environment}")
        return False

    async def _perform_readiness_checks(self, plan: DeploymentPlan) -> bool:
        """Perform readiness checks."""
        target_env = self._get_environment(plan.target_environment)

        # Perform required readiness checks
        for check_name in self.config.required_readiness_checks:
            success = await self._perform_readiness_check(target_env, check_name)
            target_env.readiness_checks[check_name] = success

            if not success:
                logger.error(f"Readiness check {check_name} failed")
                return False

        return True

    async def _perform_readiness_check(
        self, environment: DeploymentEnvironment, check_name: str
    ) -> bool:
        """Perform individual readiness check."""
        # This is a placeholder - implement specific readiness checks
        # based on your application requirements

        if check_name == "database_connectivity":
            # Check database connectivity
            pass
        elif check_name == "external_services":
            # Check external service connectivity
            pass
        elif check_name == "cache_warmup":
            # Check cache warmup completion
            pass

        # For now, assume all checks pass
        return True

    async def _switch_traffic(self, plan: DeploymentPlan) -> bool:
        """Switch traffic to new environment."""
        target_env = self._get_environment(plan.target_environment)
        source_env = self._get_environment(
            "green" if plan.target_environment == "blue" else "blue"
        )

        success = await self.traffic_switcher.switch_traffic(
            source_env,
            target_env,
            plan.strategy,
            duration_seconds=self.config.gradual_switch_duration_seconds,
            canary_percentage=self.config.canary_percentage,
        )

        if success:
            target_env.state = DeploymentState.ACTIVE
            if source_env.state == DeploymentState.ACTIVE:
                source_env.state = DeploymentState.DRAINING

        return success

    async def _cleanup_old_environment(self, plan: DeploymentPlan) -> bool:
        """Cleanup old environment."""
        if not self.config.keep_previous_version:
            # Deregister services from old environment
            old_env_name = "green" if plan.target_environment == "blue" else "blue"
            old_env = self._get_environment(old_env_name)

            for service_name in old_env.services:
                await self.service_registry.deregister(service_name)

            old_env.state = DeploymentState.INACTIVE
            old_env.services.clear()

        return True

    async def _rollback_deployment(self, failed_plan: DeploymentPlan):
        """Rollback failed deployment."""
        logger.info(f"Rolling back deployment {failed_plan.id}")

        # Switch traffic back to previous environment
        if self.active_environment:
            source_env = self._get_environment(failed_plan.target_environment)
            target_env = self._get_environment(self.active_environment)

            await self.traffic_switcher.switch_traffic(
                source_env, target_env, TrafficSplitStrategy.ALL_OR_NOTHING
            )

            # Clean up failed deployment
            source_env.state = DeploymentState.FAILED
            target_env.state = DeploymentState.ACTIVE

    def _get_environment(self, name: str) -> DeploymentEnvironment:
        """Get environment by name."""
        if name == "blue":
            return self.blue_environment
        elif name == "green":
            return self.green_environment
        else:
            raise ValueError(f"Unknown environment: {name}")

    async def _monitoring_loop(self):
        """Background monitoring loop."""
        while self.running:
            try:
                # Monitor active environment health
                if self.active_environment:
                    env = self._get_environment(self.active_environment)
                    is_healthy, _ = await self.health_checker.check_environment_health(
                        env
                    )

                    if not is_healthy:
                        logger.warning(
                            f"Active environment {self.active_environment} is unhealthy"
                        )

                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                await asyncio.sleep(60)

    async def _save_state(self):
        """Save deployment state to Redis."""
        state = {
            "active_environment": self.active_environment,
            "blue_environment": {
                "state": self.blue_environment.state.value,
                "version": self.blue_environment.version,
                "traffic_percentage": self.blue_environment.traffic_percentage,
            },
            "green_environment": {
                "state": self.green_environment.state.value,
                "version": self.green_environment.version,
                "traffic_percentage": self.green_environment.traffic_percentage,
            },
        }

        await self.redis.setex(
            "deployment_manager:state",
            3600,  # 1 hour TTL
            json.dumps(state, default=str),
        )

    async def _load_state(self):
        """Load deployment state from Redis."""
        try:
            state_data = await self.redis.get("deployment_manager:state")
            if state_data:
                state = json.loads(state_data)
                self.active_environment = state.get("active_environment")

                # Restore environment states
                if "blue_environment" in state:
                    blue_state = state["blue_environment"]
                    self.blue_environment.state = DeploymentState(
                        blue_state.get("state", "inactive")
                    )
                    self.blue_environment.version = blue_state.get("version", "1.0.0")
                    self.blue_environment.traffic_percentage = blue_state.get(
                        "traffic_percentage", 0.0
                    )

                if "green_environment" in state:
                    green_state = state["green_environment"]
                    self.green_environment.state = DeploymentState(
                        green_state.get("state", "inactive")
                    )
                    self.green_environment.version = green_state.get("version", "1.0.0")
                    self.green_environment.traffic_percentage = green_state.get(
                        "traffic_percentage", 0.0
                    )

        except Exception as e:
            logger.error(f"Failed to load deployment state: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get deployment manager status."""
        return {
            "active_environment": self.active_environment,
            "blue_environment": {
                "name": self.blue_environment.name,
                "state": self.blue_environment.state.value,
                "version": self.blue_environment.version,
                "traffic_percentage": self.blue_environment.traffic_percentage,
                "services": list(self.blue_environment.services.keys()),
                "health_check_passed": self.blue_environment.health_check_passed,
            },
            "green_environment": {
                "name": self.green_environment.name,
                "state": self.green_environment.state.value,
                "version": self.green_environment.version,
                "traffic_percentage": self.green_environment.traffic_percentage,
                "services": list(self.green_environment.services.keys()),
                "health_check_passed": self.green_environment.health_check_passed,
            },
            "current_deployment": (
                {
                    "id": self.current_deployment.id,
                    "status": self.current_deployment.status,
                    "target_environment": self.current_deployment.target_environment,
                    "steps": self.current_deployment.steps,
                }
                if self.current_deployment
                else None
            ),
        }


# Export components
__all__ = [
    "BlueGreenDeploymentManager",
    "DeploymentConfig",
    "DeploymentPlan",
    "DeploymentEnvironment",
    "DeploymentState",
    "TrafficSplitStrategy",
    "HealthChecker",
    "TrafficSwitcher",
]
