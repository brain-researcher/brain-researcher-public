"""
Migration Manager for Brain Researcher Istio Service Mesh Transition

This module manages the migration from direct service communication to Istio service mesh,
providing gradual rollout, rollback capabilities, and migration validation.
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

import aiohttp
import httpx
import kubernetes.client
import yaml
from kubernetes import config
from kubernetes.client.rest import ApiException

from brain_researcher.core.utils.tool import tool
from brain_researcher.services.communication.istio_bridge import (
    IstioBridge,
    SecurityPolicy,
    ServiceMeshConfig,
    TrafficPolicy,
)

logger = logging.getLogger(__name__)


class MigrationPhase(Enum):
    """Migration phases for service mesh transition"""

    NOT_STARTED = "not_started"
    PREPARATION = "preparation"
    PILOT_SERVICES = "pilot_services"
    GRADUAL_ROLLOUT = "gradual_rollout"
    TRAFFIC_SPLITTING = "traffic_splitting"
    FULL_MIGRATION = "full_migration"
    CLEANUP = "cleanup"
    COMPLETED = "completed"
    ROLLBACK = "rollback"
    FAILED = "failed"


@dataclass
class ServiceMigrationStatus:
    """Status of individual service migration"""

    service_name: str
    current_phase: MigrationPhase = MigrationPhase.NOT_STARTED
    sidecar_injected: bool = False
    policies_applied: bool = False
    traffic_split: int = 0  # Percentage of traffic going through mesh
    health_check_passed: bool = False
    rollback_available: bool = False
    last_updated: datetime = field(default_factory=datetime.now)
    migration_logs: List[str] = field(default_factory=list)

    def add_log(self, message: str):
        """Add a migration log entry"""
        self.migration_logs.append(f"{datetime.now().isoformat()}: {message}")
        self.last_updated = datetime.now()


@dataclass
class MigrationConfig:
    """Configuration for service mesh migration"""

    # Service priority order for migration
    service_migration_order: List[str] = field(
        default_factory=lambda: [
            "redis-service",  # Start with stateless cache
            "postgres-service",  # Database services
            "neo4j-service",
            "br_kg-service",  # Core API services
            "orchestrator-service",
            "agent-service",  # Complex processing services
            "web-ui-service",  # User-facing services last
        ]
    )

    # Traffic split increments during gradual rollout
    traffic_split_increments: List[int] = field(
        default_factory=lambda: [10, 25, 50, 75, 90, 100]
    )

    # Wait times between migration steps (seconds)
    phase_wait_times: Dict[str, int] = field(
        default_factory=lambda: {
            "sidecar_injection": 30,
            "policy_application": 15,
            "traffic_increment": 60,
            "health_validation": 45,
            "rollback_decision": 30,
        }
    )

    # Health check thresholds
    health_thresholds: Dict[str, float] = field(
        default_factory=lambda: {
            "success_rate_min": 0.95,
            "error_rate_max": 0.05,
            "latency_p95_max": 5000,  # milliseconds
            "health_score_min": 80,
        }
    )

    # Rollback triggers
    rollback_triggers: Dict[str, Any] = field(
        default_factory=lambda: {
            "consecutive_health_failures": 3,
            "error_rate_spike": 0.1,
            "latency_degradation": 2.0,  # multiplier
            "manual_trigger": False,
        }
    )

    # Namespace and mesh configuration
    namespace: str = "brain-researcher"
    backup_namespace: str = "brain-researcher-backup"
    mesh_config: ServiceMeshConfig = field(default_factory=ServiceMeshConfig)


class MigrationValidator:
    """Validates migration readiness and health"""

    def __init__(self, bridge: IstioBridge):
        self.bridge = bridge

    async def validate_prerequisites(self) -> Dict[str, Any]:
        """Validate that prerequisites for migration are met"""
        results = {
            "istio_installed": False,
            "namespace_exists": False,
            "services_ready": False,
            "backup_created": False,
            "monitoring_available": False,
            "errors": [],
        }

        try:
            # Check Istio installation
            if self.bridge.k8s_client:
                custom_api = kubernetes.client.CustomObjectsApi(self.bridge.k8s_client)
                try:
                    istiod = custom_api.list_namespaced_custom_object(
                        group="apps",
                        version="v1",
                        namespace="istio-system",
                        plural="deployments",
                    )
                    results["istio_installed"] = len(istiod.get("items", [])) > 0
                except ApiException:
                    results["errors"].append("Istio system not found")

                # Check namespace
                v1 = kubernetes.client.CoreV1Api(self.bridge.k8s_client)
                try:
                    namespace = v1.read_namespace(self.bridge.config.namespace)
                    results["namespace_exists"] = True
                except ApiException:
                    results["errors"].append(
                        f"Namespace {self.bridge.config.namespace} not found"
                    )

                # Check services
                try:
                    services = v1.list_namespaced_service(self.bridge.config.namespace)
                    results["services_ready"] = len(services.items) > 0
                except ApiException:
                    results["errors"].append("Could not list services")

            # Check monitoring
            if self.bridge.metrics:
                mesh_overview = await self.bridge.get_mesh_overview()
                results["monitoring_available"] = "error" not in mesh_overview
            else:
                results["errors"].append("Monitoring not available")

        except Exception as e:
            results["errors"].append(f"Validation error: {str(e)}")

        results["ready"] = (
            results["istio_installed"]
            and results["namespace_exists"]
            and results["services_ready"]
            and results["monitoring_available"]
            and not results["errors"]
        )

        return results

    async def validate_service_health(
        self, service_name: str, thresholds: Dict[str, float]
    ) -> Dict[str, Any]:
        """Validate service health against thresholds"""
        health_data = await self.bridge.get_service_health(service_name)

        if "error" in health_data:
            return {"healthy": False, "error": health_data["error"]}

        metrics = health_data.get("metrics", {})
        health_score = health_data.get("health_score", {})

        checks = {
            "success_rate": True,
            "error_rate": True,
            "latency": True,
            "overall_score": True,
        }

        issues = []

        # Check success rate
        success_data = metrics.get("success_rate", {}).get("data", {})
        if success_data.get("result"):
            success_rate = float(success_data["result"][0]["value"][1])
            if success_rate < thresholds["success_rate_min"]:
                checks["success_rate"] = False
                issues.append(f"Low success rate: {success_rate:.2%}")

        # Check error rate
        error_data = metrics.get("error_rate", {}).get("data", {})
        if error_data.get("result"):
            error_rate = float(error_data["result"][0]["value"][1])
            if error_rate > thresholds["error_rate_max"]:
                checks["error_rate"] = False
                issues.append(f"High error rate: {error_rate:.2%}")

        # Check latency
        latency_data = metrics.get("p95_latency", {}).get("data", {})
        if latency_data.get("result"):
            p95_latency = float(latency_data["result"][0]["value"][1])
            if p95_latency > thresholds["latency_p95_max"]:
                checks["latency"] = False
                issues.append(f"High P95 latency: {p95_latency:.0f}ms")

        # Check overall health score
        if health_score.get("score", 0) < thresholds["health_score_min"]:
            checks["overall_score"] = False
            issues.append(f"Low health score: {health_score.get('score', 0)}")

        return {
            "healthy": all(checks.values()),
            "checks": checks,
            "issues": issues,
            "metrics": metrics,
            "health_score": health_score,
        }


class MigrationManager:
    """Manages the complete service mesh migration process"""

    def __init__(self, config: Optional[MigrationConfig] = None):
        self.config = config or MigrationConfig()
        self.bridge = IstioBridge(self.config.mesh_config)
        self.validator = MigrationValidator(self.bridge)

        # Migration state
        self.current_phase = MigrationPhase.NOT_STARTED
        self.service_statuses: Dict[str, ServiceMigrationStatus] = {}
        self.migration_start_time: Optional[datetime] = None
        self.rollback_plan: List[Dict] = []

        # Initialize service statuses
        for service in self.config.service_migration_order:
            self.service_statuses[service] = ServiceMigrationStatus(
                service_name=service
            )

    async def initialize(self):
        """Initialize the migration manager"""
        await self.bridge.initialize()

    async def cleanup(self):
        """Cleanup resources"""
        await self.bridge.cleanup()

    @tool
    async def start_migration(self) -> Dict[str, Any]:
        """Start the service mesh migration process"""
        logger.info("Starting Brain Researcher service mesh migration")

        # Validate prerequisites
        validation = await self.validator.validate_prerequisites()
        if not validation["ready"]:
            return {
                "success": False,
                "error": "Prerequisites not met",
                "validation": validation,
            }

        self.current_phase = MigrationPhase.PREPARATION
        self.migration_start_time = datetime.now()

        try:
            # Create backup configurations
            backup_result = await self._create_backup_configurations()
            if not backup_result["success"]:
                return {
                    "success": False,
                    "error": "Failed to create backup configurations",
                    "details": backup_result,
                }

            # Start with pilot services
            self.current_phase = MigrationPhase.PILOT_SERVICES
            pilot_result = await self._migrate_pilot_services()

            if pilot_result["success"]:
                self.current_phase = MigrationPhase.GRADUAL_ROLLOUT
                return {
                    "success": True,
                    "phase": self.current_phase.value,
                    "pilot_services": pilot_result,
                    "next_steps": "Monitor pilot services, then proceed with gradual rollout",
                }
            else:
                return {
                    "success": False,
                    "error": "Pilot service migration failed",
                    "details": pilot_result,
                }

        except Exception as e:
            logger.error(f"Migration start failed: {e}")
            self.current_phase = MigrationPhase.FAILED
            return {
                "success": False,
                "error": str(e),
                "phase": self.current_phase.value,
            }

    async def _create_backup_configurations(self) -> Dict[str, Any]:
        """Create backup of current service configurations"""
        logger.info("Creating backup configurations")

        try:
            if not self.bridge.k8s_client:
                return {"success": False, "error": "Kubernetes client not available"}

            v1 = kubernetes.client.CoreV1Api(self.bridge.k8s_client)
            apps_v1 = kubernetes.client.AppsV1Api(self.bridge.k8s_client)

            backup_configs = {}

            # Backup services
            services = v1.list_namespaced_service(self.config.namespace)
            backup_configs["services"] = [
                {
                    "name": svc.metadata.name,
                    "spec": svc.spec.to_dict(),
                    "annotations": svc.metadata.annotations or {},
                }
                for svc in services.items
            ]

            # Backup deployments
            deployments = apps_v1.list_namespaced_deployment(self.config.namespace)
            backup_configs["deployments"] = [
                {
                    "name": dep.metadata.name,
                    "spec": dep.spec.to_dict(),
                    "annotations": dep.metadata.annotations or {},
                }
                for dep in deployments.items
            ]

            # Save backup to ConfigMap
            backup_cm = {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": "brain-researcher-migration-backup",
                    "namespace": self.config.namespace,
                    "labels": {
                        "app": "brain-researcher",
                        "component": "migration-backup",
                    },
                },
                "data": {
                    "backup.json": json.dumps(backup_configs, indent=2),
                    "timestamp": datetime.now().isoformat(),
                },
            }

            v1.create_namespaced_config_map(
                namespace=self.config.namespace, body=backup_cm
            )

            # Store rollback plan
            self.rollback_plan = backup_configs

            return {
                "success": True,
                "services_backed_up": len(backup_configs["services"]),
                "deployments_backed_up": len(backup_configs["deployments"]),
                "backup_name": "brain-researcher-migration-backup",
            }

        except Exception as e:
            logger.error(f"Backup creation failed: {e}")
            return {"success": False, "error": str(e)}

    async def _migrate_pilot_services(self) -> Dict[str, Any]:
        """Migrate pilot services (least critical first)"""
        pilot_services = self.config.service_migration_order[
            :2
        ]  # Start with first 2 services
        results = []

        for service_name in pilot_services:
            logger.info(f"Migrating pilot service: {service_name}")
            result = await self._migrate_single_service(service_name)
            results.append(result)

            if not result["success"]:
                # Rollback pilot services on failure
                await self._rollback_service(service_name)
                return {
                    "success": False,
                    "failed_service": service_name,
                    "results": results,
                }

        # Validate pilot services health
        await asyncio.sleep(self.config.phase_wait_times["health_validation"])

        health_ok = True
        health_results = []

        for service_name in pilot_services:
            health = await self.validator.validate_service_health(
                service_name, self.config.health_thresholds
            )
            health_results.append({"service": service_name, "health": health})

            if not health["healthy"]:
                health_ok = False

        if not health_ok:
            # Rollback if health checks fail
            for service_name in pilot_services:
                await self._rollback_service(service_name)

            return {
                "success": False,
                "error": "Pilot services health check failed",
                "health_results": health_results,
                "action": "rolled_back",
            }

        return {
            "success": True,
            "pilot_services": pilot_services,
            "results": results,
            "health_results": health_results,
        }

    async def _migrate_single_service(self, service_name: str) -> Dict[str, Any]:
        """Migrate a single service to the mesh"""
        status = self.service_statuses[service_name]

        try:
            # Step 1: Enable sidecar injection
            logger.info(f"Enabling sidecar injection for {service_name}")
            injection_result = await self._enable_sidecar_injection(service_name)
            if not injection_result["success"]:
                return injection_result

            status.sidecar_injected = True
            status.add_log("Sidecar injection enabled")

            # Step 2: Apply Istio policies
            logger.info(f"Applying Istio policies for {service_name}")
            policies_result = await self._apply_service_policies(service_name)
            if not policies_result["success"]:
                return policies_result

            status.policies_applied = True
            status.add_log("Istio policies applied")

            # Step 3: Start with 0% traffic through mesh (preparation)
            status.traffic_split = 0
            status.current_phase = MigrationPhase.TRAFFIC_SPLITTING
            status.add_log("Ready for traffic splitting")

            return {
                "success": True,
                "service": service_name,
                "steps_completed": ["sidecar_injection", "policy_application"],
                "next_step": "traffic_splitting",
            }

        except Exception as e:
            logger.error(f"Service migration failed for {service_name}: {e}")
            status.current_phase = MigrationPhase.FAILED
            status.add_log(f"Migration failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _enable_sidecar_injection(self, service_name: str) -> Dict[str, Any]:
        """Enable Istio sidecar injection for a service"""
        if not self.bridge.k8s_client:
            return {"success": False, "error": "Kubernetes client not available"}

        try:
            apps_v1 = kubernetes.client.AppsV1Api(self.bridge.k8s_client)

            # Get the deployment
            deployment = apps_v1.read_namespaced_deployment(
                name=service_name, namespace=self.config.namespace
            )

            # Add sidecar injection annotation
            if not deployment.spec.template.metadata.annotations:
                deployment.spec.template.metadata.annotations = {}

            deployment.spec.template.metadata.annotations["sidecar.istio.io/inject"] = (
                "true"
            )

            # Update deployment
            apps_v1.replace_namespaced_deployment(
                name=service_name, namespace=self.config.namespace, body=deployment
            )

            # Wait for rollout
            await asyncio.sleep(self.config.phase_wait_times["sidecar_injection"])

            # Verify sidecar injection
            updated_deployment = apps_v1.read_namespaced_deployment(
                name=service_name, namespace=self.config.namespace
            )

            ready_replicas = updated_deployment.status.ready_replicas or 0
            desired_replicas = updated_deployment.spec.replicas or 1

            if ready_replicas != desired_replicas:
                return {
                    "success": False,
                    "error": f"Deployment rollout incomplete: {ready_replicas}/{desired_replicas} ready",
                }

            return {
                "success": True,
                "sidecar_injected": True,
                "ready_replicas": ready_replicas,
            }

        except Exception as e:
            logger.error(f"Sidecar injection failed for {service_name}: {e}")
            return {"success": False, "error": str(e)}

    async def _apply_service_policies(self, service_name: str) -> Dict[str, Any]:
        """Apply Istio traffic and security policies for a service"""
        try:
            # Determine appropriate policies based on service type
            if (
                "database" in service_name
                or "redis" in service_name
                or "neo4j" in service_name
            ):
                # Database services
                traffic_policy = TrafficPolicy(
                    service_name=service_name,
                    load_balancer="LEAST_CONN",
                    connection_pool={
                        "tcp": {"maxConnections": 50, "connectTimeout": "10s"},
                        "http": {
                            "http1MaxPendingRequests": 20,
                            "maxRequestsPerConnection": 100,
                        },
                    },
                    circuit_breaker={
                        "consecutiveGatewayErrors": 2,
                        "interval": "30s",
                        "baseEjectionTime": "60s",
                        "maxEjectionPercent": 10,
                    },
                )

            elif "agent" in service_name:
                # LLM agent service
                traffic_policy = TrafficPolicy(
                    service_name=service_name,
                    load_balancer="ROUND_ROBIN",
                    connection_pool={
                        "tcp": {"maxConnections": 100, "connectTimeout": "60s"},
                        "http": {
                            "http1MaxPendingRequests": 50,
                            "maxRequestsPerConnection": 5,
                        },
                    },
                    timeout="300s",
                )

            else:
                # API services
                traffic_policy = TrafficPolicy(
                    service_name=service_name,
                    load_balancer="ROUND_ROBIN",
                    connection_pool={
                        "tcp": {"maxConnections": 100, "connectTimeout": "30s"},
                        "http": {
                            "http1MaxPendingRequests": 50,
                            "maxRequestsPerConnection": 10,
                        },
                    },
                )

            # Apply traffic policy
            traffic_result = await self.bridge.apply_traffic_policy(
                service_name, traffic_policy
            )
            if not traffic_result["success"]:
                return traffic_result

            # Security policy
            security_policy = SecurityPolicy(
                service_name=service_name,
                mtls_mode="STRICT",
                authorization_rules=[
                    {
                        "from": [
                            {
                                "source": {
                                    "principals": [
                                        f"cluster.local/ns/{self.config.namespace}/sa/*"
                                    ]
                                }
                            }
                        ],
                        "to": [
                            {"operation": {"methods": ["GET", "POST", "PUT", "DELETE"]}}
                        ],
                    }
                ],
            )

            security_result = await self.bridge.apply_security_policy(
                service_name, security_policy
            )
            if not security_result["success"]:
                return security_result

            return {
                "success": True,
                "traffic_policy": traffic_result,
                "security_policy": security_result,
            }

        except Exception as e:
            logger.error(f"Policy application failed for {service_name}: {e}")
            return {"success": False, "error": str(e)}

    @tool
    async def continue_migration(self) -> Dict[str, Any]:
        """Continue migration to the next phase"""
        if self.current_phase == MigrationPhase.GRADUAL_ROLLOUT:
            return await self._gradual_rollout()
        elif self.current_phase == MigrationPhase.TRAFFIC_SPLITTING:
            return await self._continue_traffic_splitting()
        elif self.current_phase == MigrationPhase.FULL_MIGRATION:
            return await self._complete_migration()
        else:
            return {
                "success": False,
                "error": f"Cannot continue from phase {self.current_phase.value}",
            }

    async def _gradual_rollout(self) -> Dict[str, Any]:
        """Gradually roll out remaining services"""
        remaining_services = self.config.service_migration_order[
            2:
        ]  # Skip pilot services
        batch_size = 2  # Migrate 2 services at a time

        for i in range(0, len(remaining_services), batch_size):
            batch = remaining_services[i : i + batch_size]
            logger.info(f"Migrating service batch: {batch}")

            # Migrate batch
            batch_results = []
            for service_name in batch:
                result = await self._migrate_single_service(service_name)
                batch_results.append(result)

                if not result["success"]:
                    return {
                        "success": False,
                        "failed_service": service_name,
                        "batch": batch,
                        "results": batch_results,
                    }

            # Validate batch health
            await asyncio.sleep(self.config.phase_wait_times["health_validation"])

            health_ok = True
            for service_name in batch:
                health = await self.validator.validate_service_health(
                    service_name, self.config.health_thresholds
                )
                if not health["healthy"]:
                    health_ok = False
                    break

            if not health_ok:
                return {
                    "success": False,
                    "error": "Batch health validation failed",
                    "batch": batch,
                    "action": "rollback_recommended",
                }

        self.current_phase = MigrationPhase.TRAFFIC_SPLITTING
        return {
            "success": True,
            "services_migrated": len(remaining_services),
            "next_phase": self.current_phase.value,
        }

    async def _continue_traffic_splitting(self) -> Dict[str, Any]:
        """Continue incrementing traffic through the mesh"""
        results = []

        for service_name in self.config.service_migration_order:
            status = self.service_statuses[service_name]

            if not status.sidecar_injected or not status.policies_applied:
                continue  # Skip services not ready

            # Find next traffic increment
            current_split = status.traffic_split
            next_split = None

            for increment in self.config.traffic_split_increments:
                if increment > current_split:
                    next_split = increment
                    break

            if next_split is None:
                continue  # Already at 100%

            # Apply traffic split
            logger.info(
                f"Updating traffic split for {service_name}: {current_split}% -> {next_split}%"
            )

            if current_split == 0:
                # Enable canary deployment
                canary_result = await self.bridge.enable_canary_deployment(
                    service_name, "mesh", next_split
                )
            else:
                # Update existing canary
                canary_result = await self.bridge.update_canary_traffic(
                    service_name, next_split
                )

            if canary_result["success"]:
                status.traffic_split = next_split
                status.add_log(f"Traffic split updated to {next_split}%")
                results.append({"service": service_name, "traffic_split": next_split})

                # Wait and validate
                await asyncio.sleep(self.config.phase_wait_times["traffic_increment"])

                health = await self.validator.validate_service_health(
                    service_name, self.config.health_thresholds
                )

                if not health["healthy"]:
                    # Rollback this service
                    rollback_result = await self._rollback_traffic_split(
                        service_name, current_split
                    )
                    return {
                        "success": False,
                        "error": f"Health degradation detected for {service_name}",
                        "rollback": rollback_result,
                    }

        # Check if all services are at 100%
        all_complete = all(
            status.traffic_split == 100
            for status in self.service_statuses.values()
            if status.sidecar_injected
        )

        if all_complete:
            self.current_phase = MigrationPhase.FULL_MIGRATION

        return {
            "success": True,
            "traffic_updates": results,
            "phase": self.current_phase.value,
            "all_services_at_100": all_complete,
        }

    async def _rollback_traffic_split(
        self, service_name: str, previous_split: int
    ) -> Dict[str, Any]:
        """Rollback traffic split for a service"""
        try:
            result = await self.bridge.update_canary_traffic(
                service_name, previous_split
            )
            if result["success"]:
                self.service_statuses[service_name].traffic_split = previous_split
                self.service_statuses[service_name].add_log(
                    f"Traffic rolled back to {previous_split}%"
                )

            return result
        except Exception as e:
            logger.error(f"Traffic rollback failed for {service_name}: {e}")
            return {"success": False, "error": str(e)}

    async def _complete_migration(self) -> Dict[str, Any]:
        """Complete the migration and cleanup"""
        logger.info("Completing service mesh migration")

        try:
            # Remove canary configurations (all traffic now through mesh)
            cleanup_results = []

            for service_name in self.config.service_migration_order:
                status = self.service_statuses[service_name]
                if status.traffic_split == 100:
                    # Remove VirtualService canary config
                    cleanup_result = await self._cleanup_canary_config(service_name)
                    cleanup_results.append(cleanup_result)

                    status.current_phase = MigrationPhase.COMPLETED
                    status.add_log("Migration completed")

            self.current_phase = MigrationPhase.COMPLETED

            # Generate migration report
            report = await self._generate_migration_report()

            return {
                "success": True,
                "phase": self.current_phase.value,
                "cleanup_results": cleanup_results,
                "migration_report": report,
                "completion_time": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Migration completion failed: {e}")
            return {"success": False, "error": str(e)}

    async def _cleanup_canary_config(self, service_name: str) -> Dict[str, Any]:
        """Remove canary VirtualService configuration"""
        if not self.bridge.k8s_client:
            return {"success": False, "error": "Kubernetes client not available"}

        try:
            custom_api = kubernetes.client.CustomObjectsApi(self.bridge.k8s_client)

            # Delete canary VirtualService
            custom_api.delete_namespaced_custom_object(
                group="networking.istio.io",
                version="v1beta1",
                namespace=self.config.namespace,
                plural="virtualservices",
                name=f"{service_name}-canary",
            )

            return {
                "success": True,
                "service": service_name,
                "action": "canary_config_removed",
            }

        except ApiException as e:
            if e.status == 404:
                return {"success": True, "action": "already_removed"}
            else:
                return {"success": False, "error": str(e)}

    @tool
    async def rollback_migration(
        self, service_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Rollback migration for a specific service or all services"""
        logger.warning(f"Rolling back migration for {service_name or 'all services'}")

        self.current_phase = MigrationPhase.ROLLBACK

        services_to_rollback = (
            [service_name] if service_name else self.config.service_migration_order
        )
        results = []

        for svc_name in services_to_rollback:
            result = await self._rollback_service(svc_name)
            results.append(result)

        return {
            "success": True,
            "phase": self.current_phase.value,
            "rollback_results": results,
        }

    async def _rollback_service(self, service_name: str) -> Dict[str, Any]:
        """Rollback a single service from the mesh"""
        status = self.service_statuses[service_name]

        try:
            rollback_steps = []

            # Remove traffic split
            if status.traffic_split > 0:
                traffic_result = await self.bridge.update_canary_traffic(
                    service_name, 0
                )
                rollback_steps.append(
                    {"step": "traffic_split_removed", "result": traffic_result}
                )
                status.traffic_split = 0

            # Remove Istio policies
            if status.policies_applied:
                policy_result = await self._remove_service_policies(service_name)
                rollback_steps.append(
                    {"step": "policies_removed", "result": policy_result}
                )
                status.policies_applied = False

            # Disable sidecar injection
            if status.sidecar_injected:
                sidecar_result = await self._disable_sidecar_injection(service_name)
                rollback_steps.append(
                    {"step": "sidecar_removed", "result": sidecar_result}
                )
                status.sidecar_injected = False

            status.current_phase = MigrationPhase.NOT_STARTED
            status.add_log("Service rolled back successfully")

            return {
                "success": True,
                "service": service_name,
                "rollback_steps": rollback_steps,
            }

        except Exception as e:
            logger.error(f"Rollback failed for {service_name}: {e}")
            status.add_log(f"Rollback failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _disable_sidecar_injection(self, service_name: str) -> Dict[str, Any]:
        """Disable Istio sidecar injection for a service"""
        if not self.bridge.k8s_client:
            return {"success": False, "error": "Kubernetes client not available"}

        try:
            apps_v1 = kubernetes.client.AppsV1Api(self.bridge.k8s_client)

            # Get deployment
            deployment = apps_v1.read_namespaced_deployment(
                name=service_name, namespace=self.config.namespace
            )

            # Remove sidecar injection annotation
            if deployment.spec.template.metadata.annotations:
                deployment.spec.template.metadata.annotations.pop(
                    "sidecar.istio.io/inject", None
                )

                # Update deployment
                apps_v1.replace_namespaced_deployment(
                    name=service_name, namespace=self.config.namespace, body=deployment
                )

            return {"success": True, "sidecar_injection_disabled": True}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _remove_service_policies(self, service_name: str) -> Dict[str, Any]:
        """Remove Istio policies for a service"""
        if not self.bridge.k8s_client:
            return {"success": False, "error": "Kubernetes client not available"}

        try:
            custom_api = kubernetes.client.CustomObjectsApi(self.bridge.k8s_client)
            results = []

            # Remove DestinationRule
            try:
                custom_api.delete_namespaced_custom_object(
                    group="networking.istio.io",
                    version="v1beta1",
                    namespace=self.config.namespace,
                    plural="destinationrules",
                    name=f"{service_name}-traffic-policy",
                )
                results.append("destination_rule_removed")
            except ApiException as e:
                if e.status != 404:
                    results.append(f"destination_rule_error: {e}")

            # Remove PeerAuthentication
            try:
                custom_api.delete_namespaced_custom_object(
                    group="security.istio.io",
                    version="v1beta1",
                    namespace=self.config.namespace,
                    plural="peerauthentications",
                    name=f"{service_name}-peer-auth",
                )
                results.append("peer_auth_removed")
            except ApiException as e:
                if e.status != 404:
                    results.append(f"peer_auth_error: {e}")

            # Remove AuthorizationPolicy
            try:
                custom_api.delete_namespaced_custom_object(
                    group="security.istio.io",
                    version="v1beta1",
                    namespace=self.config.namespace,
                    plural="authorizationpolicies",
                    name=f"{service_name}-auth-policy",
                )
                results.append("auth_policy_removed")
            except ApiException as e:
                if e.status != 404:
                    results.append(f"auth_policy_error: {e}")

            return {"success": True, "removed_policies": results}

        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool
    async def get_migration_status(self) -> Dict[str, Any]:
        """Get current migration status"""
        return {
            "current_phase": self.current_phase.value,
            "migration_start_time": (
                self.migration_start_time.isoformat()
                if self.migration_start_time
                else None
            ),
            "services": {
                name: {
                    "phase": status.current_phase.value,
                    "sidecar_injected": status.sidecar_injected,
                    "policies_applied": status.policies_applied,
                    "traffic_split": status.traffic_split,
                    "health_check_passed": status.health_check_passed,
                    "last_updated": status.last_updated.isoformat(),
                    "recent_logs": status.migration_logs[-5:],  # Last 5 log entries
                }
                for name, status in self.service_statuses.items()
            },
        }

    async def _generate_migration_report(self) -> Dict[str, Any]:
        """Generate comprehensive migration report"""
        duration = (
            datetime.now() - self.migration_start_time
            if self.migration_start_time
            else timedelta(0)
        )

        completed_services = [
            name
            for name, status in self.service_statuses.items()
            if status.current_phase == MigrationPhase.COMPLETED
        ]

        failed_services = [
            name
            for name, status in self.service_statuses.items()
            if status.current_phase == MigrationPhase.FAILED
        ]

        # Get final health metrics
        final_health = {}
        if self.bridge.metrics:
            for service_name in completed_services:
                health = await self.validator.validate_service_health(
                    service_name, self.config.health_thresholds
                )
                final_health[service_name] = health

        return {
            "migration_duration": str(duration),
            "total_services": len(self.service_statuses),
            "completed_services": len(completed_services),
            "failed_services": len(failed_services),
            "success_rate": len(completed_services) / len(self.service_statuses),
            "completed_service_list": completed_services,
            "failed_service_list": failed_services,
            "final_health_metrics": final_health,
            "configuration_summary": {
                "mesh_id": self.config.mesh_config.mesh_id,
                "namespace": self.config.namespace,
                "mtls_enabled": self.config.mesh_config.enable_mtls,
                "tracing_enabled": self.config.mesh_config.enable_tracing,
                "metrics_enabled": self.config.mesh_config.enable_metrics,
            },
        }


# Context manager for migration manager lifecycle
@asynccontextmanager
async def migration_manager(config: Optional[MigrationConfig] = None):
    """Context manager for migration manager with proper resource cleanup"""
    manager = MigrationManager(config)
    await manager.initialize()
    try:
        yield manager
    finally:
        await manager.cleanup()


# Convenience function for full migration
async def execute_brain_researcher_migration(dry_run: bool = False) -> Dict[str, Any]:
    """Execute complete Brain Researcher service mesh migration"""
    config = MigrationConfig()

    async with migration_manager(config) as manager:
        if dry_run:
            # Just validate prerequisites
            validation = await manager.validator.validate_prerequisites()
            return {
                "dry_run": True,
                "validation": validation,
                "migration_plan": {
                    "service_order": config.service_migration_order,
                    "traffic_increments": config.traffic_split_increments,
                    "estimated_duration": "2-4 hours",
                },
            }
        else:
            # Execute migration
            result = await manager.start_migration()
            return result
