"""
Istio Service Mesh Integration Bridge for Brain Researcher

This module provides a Python interface to interact with Istio service mesh
capabilities, including traffic management, security policies, and observability.
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Union, Callable
from datetime import datetime, timedelta
import yaml

import aiohttp
import kubernetes.client
from kubernetes.client.rest import ApiException
from kubernetes import config
import httpx
from prometheus_client.parser import text_string_to_metric_families

from brain_researcher.core.utils.tool import tool


logger = logging.getLogger(__name__)


@dataclass
class ServiceMeshConfig:
    """Configuration for Istio service mesh integration"""
    namespace: str = "brain-researcher"
    istio_namespace: str = "istio-system"
    mesh_id: str = "brain-researcher-mesh"
    cluster_name: str = "brain-researcher-primary"
    prometheus_url: str = "http://prometheus.brain-researcher.svc.cluster.local:9090"
    kiali_url: str = "http://kiali.istio-system.svc.cluster.local:20001"
    jaeger_url: str = "http://jaeger-query.istio-system:16686"
    enable_mtls: bool = True
    enable_tracing: bool = True
    enable_metrics: bool = True


@dataclass
class TrafficPolicy:
    """Traffic management policy configuration"""
    service_name: str
    load_balancer: str = "ROUND_ROBIN"  # ROUND_ROBIN, LEAST_CONN, RANDOM, PASSTHROUGH
    connection_pool: Optional[Dict] = None
    circuit_breaker: Optional[Dict] = None
    retry_policy: Optional[Dict] = None
    timeout: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to Kubernetes resource format"""
        policy = {
            "loadBalancer": {"simple": self.load_balancer}
        }

        if self.connection_pool:
            policy["connectionPool"] = self.connection_pool

        if self.circuit_breaker:
            policy["outlierDetection"] = self.circuit_breaker

        return policy


@dataclass
class SecurityPolicy:
    """Security policy configuration"""
    service_name: str
    mtls_mode: str = "STRICT"  # STRICT, PERMISSIVE, DISABLE
    authorization_rules: List[Dict] = None
    jwt_rules: List[Dict] = None

    def __post_init__(self):
        if self.authorization_rules is None:
            self.authorization_rules = []
        if self.jwt_rules is None:
            self.jwt_rules = []


class IstioMetrics:
    """Interface for Istio metrics collection and analysis"""

    def __init__(self, prometheus_url: str):
        self.prometheus_url = prometheus_url
        self.client = httpx.AsyncClient(timeout=30.0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def query_metric(self, query: str, time_range: Optional[str] = None) -> Dict:
        """Query Prometheus metrics"""
        try:
            params = {"query": query}
            if time_range:
                params["time"] = time_range

            response = await self.client.get(
                f"{self.prometheus_url}/api/v1/query",
                params=params
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Failed to query metric {query}: {e}")
            return {"status": "error", "error": str(e)}

    async def get_service_metrics(self, service_name: str, namespace: str) -> Dict:
        """Get comprehensive metrics for a specific service"""
        metrics = {}

        # Request rate
        query = f'rate(istio_requests_total{{destination_service_name="{service_name}",destination_service_namespace="{namespace}"}}[5m])'
        metrics["request_rate"] = await self.query_metric(query)

        # Success rate
        query = f'rate(istio_requests_total{{destination_service_name="{service_name}",destination_service_namespace="{namespace}",response_code!~"5.*"}}[5m]) / rate(istio_requests_total{{destination_service_name="{service_name}",destination_service_namespace="{namespace}"}}[5m])'
        metrics["success_rate"] = await self.query_metric(query)

        # Response time percentiles
        query = f'histogram_quantile(0.99, rate(istio_request_duration_milliseconds_bucket{{destination_service_name="{service_name}",destination_service_namespace="{namespace}"}}[5m]))'
        metrics["p99_latency"] = await self.query_metric(query)

        query = f'histogram_quantile(0.95, rate(istio_request_duration_milliseconds_bucket{{destination_service_name="{service_name}",destination_service_namespace="{namespace}"}}[5m]))'
        metrics["p95_latency"] = await self.query_metric(query)

        query = f'histogram_quantile(0.50, rate(istio_request_duration_milliseconds_bucket{{destination_service_name="{service_name}",destination_service_namespace="{namespace}"}}[5m]))'
        metrics["p50_latency"] = await self.query_metric(query)

        # Error rate by response code
        query = f'rate(istio_requests_total{{destination_service_name="{service_name}",destination_service_namespace="{namespace}",response_code=~"5.*"}}[5m])'
        metrics["error_rate"] = await self.query_metric(query)

        return metrics

    async def get_mesh_overview(self) -> Dict:
        """Get overview metrics for the entire service mesh"""
        overview = {}

        # Total request rate across mesh
        query = 'sum(rate(istio_requests_total[5m]))'
        overview["total_request_rate"] = await self.query_metric(query)

        # Success rate across mesh
        query = 'sum(rate(istio_requests_total{response_code!~"5.*"}[5m])) / sum(rate(istio_requests_total[5m]))'
        overview["overall_success_rate"] = await self.query_metric(query)

        # Service count
        query = 'count(count by (destination_service_name)(istio_requests_total))'
        overview["service_count"] = await self.query_metric(query)

        # Active connections
        query = 'sum(istio_tcp_connections_opened_total) - sum(istio_tcp_connections_closed_total)'
        overview["active_connections"] = await self.query_metric(query)

        return overview


class IstioTracing:
    """Interface for Istio distributed tracing"""

    def __init__(self, jaeger_url: str):
        self.jaeger_url = jaeger_url
        self.client = httpx.AsyncClient(timeout=30.0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def get_traces(
        self,
        service: str,
        operation: Optional[str] = None,
        lookback: str = "1h",
        limit: int = 100
    ) -> List[Dict]:
        """Get traces for a service"""
        try:
            params = {
                "service": service,
                "lookback": lookback,
                "limit": limit
            }
            if operation:
                params["operation"] = operation

            response = await self.client.get(
                f"{self.jaeger_url}/api/traces",
                params=params
            )
            response.raise_for_status()
            return response.json().get("data", [])

        except Exception as e:
            logger.error(f"Failed to get traces for {service}: {e}")
            return []

    async def get_service_operations(self, service: str) -> List[str]:
        """Get available operations for a service"""
        try:
            response = await self.client.get(
                f"{self.jaeger_url}/api/services/{service}/operations"
            )
            response.raise_for_status()
            data = response.json()
            return [op["operationName"] for op in data.get("data", [])]

        except Exception as e:
            logger.error(f"Failed to get operations for {service}: {e}")
            return []

    async def analyze_trace_performance(
        self,
        service: str,
        time_range: str = "1h"
    ) -> Dict:
        """Analyze performance patterns from traces"""
        traces = await self.get_traces(service, lookback=time_range)

        if not traces:
            return {"error": "No traces found"}

        durations = []
        error_count = 0
        span_counts = []

        for trace in traces:
            for span in trace.get("spans", []):
                if span.get("operationName") == service:
                    duration = span.get("duration", 0)
                    durations.append(duration)

                    # Check for errors
                    tags = span.get("tags", [])
                    for tag in tags:
                        if tag.get("key") == "error" and tag.get("value") is True:
                            error_count += 1
                            break

            span_counts.append(len(trace.get("spans", [])))

        if not durations:
            return {"error": "No duration data found"}

        durations.sort()
        n = len(durations)

        return {
            "total_traces": len(traces),
            "total_spans": sum(span_counts),
            "avg_spans_per_trace": sum(span_counts) / len(span_counts) if span_counts else 0,
            "error_count": error_count,
            "error_rate": error_count / n if n > 0 else 0,
            "duration_stats": {
                "min": min(durations),
                "max": max(durations),
                "mean": sum(durations) / n,
                "p50": durations[int(n * 0.5)],
                "p95": durations[int(n * 0.95)],
                "p99": durations[int(n * 0.99)]
            }
        }


class IstioBridge:
    """Main Istio service mesh integration bridge"""

    def __init__(self, config: Optional[ServiceMeshConfig] = None):
        self.config = config or ServiceMeshConfig()
        self.k8s_client = None
        self.metrics = None
        self.tracing = None
        self._setup_kubernetes()

    def _setup_kubernetes(self):
        """Setup Kubernetes client"""
        try:
            config.load_incluster_config()
        except config.ConfigException:
            try:
                config.load_kube_config()
            except config.ConfigException:
                logger.warning("Could not load Kubernetes config")
                return

        self.k8s_client = kubernetes.client.ApiClient()

    async def initialize(self):
        """Initialize the bridge with async components"""
        if self.config.enable_metrics:
            self.metrics = IstioMetrics(self.config.prometheus_url)

        if self.config.enable_tracing:
            self.tracing = IstioTracing(self.config.jaeger_url)

    async def cleanup(self):
        """Cleanup async resources"""
        if self.metrics:
            await self.metrics.__aexit__(None, None, None)
        if self.tracing:
            await self.tracing.__aexit__(None, None, None)

    @tool
    async def apply_traffic_policy(
        self,
        service_name: str,
        policy: TrafficPolicy
    ) -> Dict[str, Any]:
        """Apply traffic management policy to a service"""
        if not self.k8s_client:
            return {"error": "Kubernetes client not available"}

        try:
            # Create DestinationRule
            destination_rule = {
                "apiVersion": "networking.istio.io/v1beta1",
                "kind": "DestinationRule",
                "metadata": {
                    "name": f"{service_name}-traffic-policy",
                    "namespace": self.config.namespace,
                    "labels": {
                        "app": "brain-researcher",
                        "managed-by": "istio-bridge"
                    }
                },
                "spec": {
                    "host": f"{service_name}.{self.config.namespace}.svc.cluster.local",
                    "trafficPolicy": policy.to_dict()
                }
            }

            # Apply using kubectl
            custom_api = kubernetes.client.CustomObjectsApi(self.k8s_client)

            try:
                # Try to get existing resource
                existing = custom_api.get_namespaced_custom_object(
                    group="networking.istio.io",
                    version="v1beta1",
                    namespace=self.config.namespace,
                    plural="destinationrules",
                    name=f"{service_name}-traffic-policy"
                )

                # Update existing
                result = custom_api.replace_namespaced_custom_object(
                    group="networking.istio.io",
                    version="v1beta1",
                    namespace=self.config.namespace,
                    plural="destinationrules",
                    name=f"{service_name}-traffic-policy",
                    body=destination_rule
                )
                action = "updated"

            except ApiException as e:
                if e.status == 404:
                    # Create new
                    result = custom_api.create_namespaced_custom_object(
                        group="networking.istio.io",
                        version="v1beta1",
                        namespace=self.config.namespace,
                        plural="destinationrules",
                        body=destination_rule
                    )
                    action = "created"
                else:
                    raise

            return {
                "success": True,
                "action": action,
                "resource": result["metadata"]["name"]
            }

        except Exception as e:
            logger.error(f"Failed to apply traffic policy: {e}")
            return {"error": str(e)}

    @tool
    async def apply_security_policy(
        self,
        service_name: str,
        policy: SecurityPolicy
    ) -> Dict[str, Any]:
        """Apply security policy to a service"""
        if not self.k8s_client:
            return {"error": "Kubernetes client not available"}

        try:
            custom_api = kubernetes.client.CustomObjectsApi(self.k8s_client)
            results = []

            # Apply PeerAuthentication for mTLS
            peer_auth = {
                "apiVersion": "security.istio.io/v1beta1",
                "kind": "PeerAuthentication",
                "metadata": {
                    "name": f"{service_name}-peer-auth",
                    "namespace": self.config.namespace,
                    "labels": {
                        "app": "brain-researcher",
                        "managed-by": "istio-bridge"
                    }
                },
                "spec": {
                    "selector": {
                        "matchLabels": {
                            "app": service_name
                        }
                    },
                    "mtls": {
                        "mode": policy.mtls_mode
                    }
                }
            }

            try:
                result = custom_api.create_namespaced_custom_object(
                    group="security.istio.io",
                    version="v1beta1",
                    namespace=self.config.namespace,
                    plural="peerauthentications",
                    body=peer_auth
                )
                results.append({"type": "PeerAuthentication", "action": "created", "name": result["metadata"]["name"]})
            except ApiException as e:
                if e.status == 409:  # Already exists
                    results.append({"type": "PeerAuthentication", "action": "exists", "name": f"{service_name}-peer-auth"})
                else:
                    raise

            # Apply AuthorizationPolicy if rules provided
            if policy.authorization_rules:
                auth_policy = {
                    "apiVersion": "security.istio.io/v1beta1",
                    "kind": "AuthorizationPolicy",
                    "metadata": {
                        "name": f"{service_name}-auth-policy",
                        "namespace": self.config.namespace,
                        "labels": {
                            "app": "brain-researcher",
                            "managed-by": "istio-bridge"
                        }
                    },
                    "spec": {
                        "selector": {
                            "matchLabels": {
                                "app": service_name
                            }
                        },
                        "rules": policy.authorization_rules
                    }
                }

                try:
                    result = custom_api.create_namespaced_custom_object(
                        group="security.istio.io",
                        version="v1beta1",
                        namespace=self.config.namespace,
                        plural="authorizationpolicies",
                        body=auth_policy
                    )
                    results.append({"type": "AuthorizationPolicy", "action": "created", "name": result["metadata"]["name"]})
                except ApiException as e:
                    if e.status == 409:
                        results.append({"type": "AuthorizationPolicy", "action": "exists", "name": f"{service_name}-auth-policy"})
                    else:
                        raise

            return {"success": True, "applied_policies": results}

        except Exception as e:
            logger.error(f"Failed to apply security policy: {e}")
            return {"error": str(e)}

    @tool
    async def get_service_health(self, service_name: str) -> Dict[str, Any]:
        """Get comprehensive health status for a service"""
        if not self.metrics:
            return {"error": "Metrics not available"}

        try:
            # Get metrics
            service_metrics = await self.metrics.get_service_metrics(
                service_name,
                self.config.namespace
            )

            # Get trace analysis if tracing enabled
            trace_analysis = {}
            if self.tracing:
                trace_analysis = await self.tracing.analyze_trace_performance(
                    service_name
                )

            # Calculate health score based on metrics
            health_score = await self._calculate_health_score(service_metrics)

            return {
                "service": service_name,
                "namespace": self.config.namespace,
                "health_score": health_score,
                "metrics": service_metrics,
                "trace_analysis": trace_analysis,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to get service health for {service_name}: {e}")
            return {"error": str(e)}

    async def _calculate_health_score(self, metrics: Dict) -> Dict:
        """Calculate health score based on service metrics"""
        score = 100
        factors = []

        # Success rate factor
        success_rate_data = metrics.get("success_rate", {}).get("data", {})
        if success_rate_data.get("result"):
            success_rate = float(success_rate_data["result"][0]["value"][1])
            if success_rate < 0.95:
                penalty = (0.95 - success_rate) * 100
                score -= penalty
                factors.append(f"Low success rate: {success_rate:.2%}")

        # Latency factor
        p99_data = metrics.get("p99_latency", {}).get("data", {})
        if p99_data.get("result"):
            p99_latency = float(p99_data["result"][0]["value"][1])
            if p99_latency > 5000:  # 5 seconds
                penalty = min(20, (p99_latency - 5000) / 1000)
                score -= penalty
                factors.append(f"High P99 latency: {p99_latency:.0f}ms")

        # Error rate factor
        error_rate_data = metrics.get("error_rate", {}).get("data", {})
        if error_rate_data.get("result"):
            error_rate = float(error_rate_data["result"][0]["value"][1])
            if error_rate > 0.01:  # 1% error rate
                penalty = error_rate * 500  # Scale penalty
                score -= penalty
                factors.append(f"High error rate: {error_rate:.2%}")

        return {
            "score": max(0, int(score)),
            "status": "healthy" if score >= 80 else "degraded" if score >= 60 else "unhealthy",
            "factors": factors
        }

    @tool
    async def get_mesh_overview(self) -> Dict[str, Any]:
        """Get overview of the entire service mesh"""
        if not self.metrics:
            return {"error": "Metrics not available"}

        try:
            overview = await self.metrics.get_mesh_overview()

            # Get service list
            if self.k8s_client:
                v1 = kubernetes.client.CoreV1Api(self.k8s_client)
                services = v1.list_namespaced_service(self.config.namespace)
                service_list = [svc.metadata.name for svc in services.items]
            else:
                service_list = []

            # Get Istio configuration status
            config_status = await self._get_istio_config_status()

            return {
                "mesh_id": self.config.mesh_id,
                "cluster_name": self.config.cluster_name,
                "namespace": self.config.namespace,
                "services": service_list,
                "metrics": overview,
                "config_status": config_status,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to get mesh overview: {e}")
            return {"error": str(e)}

    async def _get_istio_config_status(self) -> Dict:
        """Get status of Istio configuration objects"""
        if not self.k8s_client:
            return {"error": "Kubernetes client not available"}

        try:
            custom_api = kubernetes.client.CustomObjectsApi(self.k8s_client)
            status = {}

            # Count different Istio resources
            resource_types = [
                ("VirtualService", "virtualservices"),
                ("DestinationRule", "destinationrules"),
                ("Gateway", "gateways"),
                ("PeerAuthentication", "peerauthentications"),
                ("AuthorizationPolicy", "authorizationpolicies")
            ]

            for resource_type, plural in resource_types:
                try:
                    resources = custom_api.list_namespaced_custom_object(
                        group="networking.istio.io" if "authentication" not in plural else "security.istio.io",
                        version="v1beta1",
                        namespace=self.config.namespace,
                        plural=plural
                    )
                    status[resource_type] = len(resources.get("items", []))
                except ApiException:
                    status[resource_type] = "unknown"

            return status

        except Exception as e:
            logger.error(f"Failed to get config status: {e}")
            return {"error": str(e)}

    @tool
    async def enable_canary_deployment(
        self,
        service_name: str,
        canary_version: str,
        traffic_split: int = 10
    ) -> Dict[str, Any]:
        """Enable canary deployment for a service"""
        if not self.k8s_client:
            return {"error": "Kubernetes client not available"}

        try:
            custom_api = kubernetes.client.CustomObjectsApi(self.k8s_client)

            # Create VirtualService for traffic splitting
            virtual_service = {
                "apiVersion": "networking.istio.io/v1beta1",
                "kind": "VirtualService",
                "metadata": {
                    "name": f"{service_name}-canary",
                    "namespace": self.config.namespace,
                    "labels": {
                        "app": "brain-researcher",
                        "managed-by": "istio-bridge",
                        "deployment-type": "canary"
                    }
                },
                "spec": {
                    "hosts": [f"{service_name}.{self.config.namespace}.svc.cluster.local"],
                    "http": [
                        {
                            "match": [{"headers": {"X-Canary": {"exact": "true"}}}],
                            "route": [{
                                "destination": {
                                    "host": f"{service_name}.{self.config.namespace}.svc.cluster.local",
                                    "subset": "canary"
                                }
                            }]
                        },
                        {
                            "route": [
                                {
                                    "destination": {
                                        "host": f"{service_name}.{self.config.namespace}.svc.cluster.local",
                                        "subset": "stable"
                                    },
                                    "weight": 100 - traffic_split
                                },
                                {
                                    "destination": {
                                        "host": f"{service_name}.{self.config.namespace}.svc.cluster.local",
                                        "subset": "canary"
                                    },
                                    "weight": traffic_split
                                }
                            ]
                        }
                    ]
                }
            }

            result = custom_api.create_namespaced_custom_object(
                group="networking.istio.io",
                version="v1beta1",
                namespace=self.config.namespace,
                plural="virtualservices",
                body=virtual_service
            )

            return {
                "success": True,
                "canary_enabled": True,
                "service": service_name,
                "canary_version": canary_version,
                "traffic_split": f"{100 - traffic_split}% stable, {traffic_split}% canary",
                "virtual_service": result["metadata"]["name"]
            }

        except Exception as e:
            logger.error(f"Failed to enable canary deployment: {e}")
            return {"error": str(e)}

    @tool
    async def update_canary_traffic(
        self,
        service_name: str,
        new_traffic_split: int
    ) -> Dict[str, Any]:
        """Update traffic split for canary deployment"""
        if not self.k8s_client:
            return {"error": "Kubernetes client not available"}

        try:
            custom_api = kubernetes.client.CustomObjectsApi(self.k8s_client)

            # Get existing VirtualService
            vs_name = f"{service_name}-canary"
            existing_vs = custom_api.get_namespaced_custom_object(
                group="networking.istio.io",
                version="v1beta1",
                namespace=self.config.namespace,
                plural="virtualservices",
                name=vs_name
            )

            # Update traffic weights
            http_routes = existing_vs["spec"]["http"]
            if len(http_routes) > 1 and len(http_routes[1]["route"]) == 2:
                http_routes[1]["route"][0]["weight"] = 100 - new_traffic_split
                http_routes[1]["route"][1]["weight"] = new_traffic_split

            # Apply update
            result = custom_api.replace_namespaced_custom_object(
                group="networking.istio.io",
                version="v1beta1",
                namespace=self.config.namespace,
                plural="virtualservices",
                name=vs_name,
                body=existing_vs
            )

            return {
                "success": True,
                "service": service_name,
                "updated_traffic_split": f"{100 - new_traffic_split}% stable, {new_traffic_split}% canary",
                "virtual_service": result["metadata"]["name"]
            }

        except Exception as e:
            logger.error(f"Failed to update canary traffic: {e}")
            return {"error": str(e)}

    @tool
    async def get_canary_metrics(self, service_name: str) -> Dict[str, Any]:
        """Get metrics comparison between stable and canary versions"""
        if not self.metrics:
            return {"error": "Metrics not available"}

        try:
            # Get metrics for stable version
            stable_query = f'rate(istio_requests_total{{destination_service_name="{service_name}",destination_service_namespace="{self.config.namespace}",destination_version="stable"}}[5m])'
            stable_metrics = await self.metrics.query_metric(stable_query)

            # Get metrics for canary version
            canary_query = f'rate(istio_requests_total{{destination_service_name="{service_name}",destination_service_namespace="{self.config.namespace}",destination_version="canary"}}[5m])'
            canary_metrics = await self.metrics.query_metric(canary_query)

            # Get error rates
            stable_errors = await self.metrics.query_metric(
                f'rate(istio_requests_total{{destination_service_name="{service_name}",destination_service_namespace="{self.config.namespace}",destination_version="stable",response_code=~"5.*"}}[5m])'
            )

            canary_errors = await self.metrics.query_metric(
                f'rate(istio_requests_total{{destination_service_name="{service_name}",destination_service_namespace="{self.config.namespace}",destination_version="canary",response_code=~"5.*"}}[5m])'
            )

            # Get latency metrics
            stable_latency = await self.metrics.query_metric(
                f'histogram_quantile(0.95, rate(istio_request_duration_milliseconds_bucket{{destination_service_name="{service_name}",destination_service_namespace="{self.config.namespace}",destination_version="stable"}}[5m]))'
            )

            canary_latency = await self.metrics.query_metric(
                f'histogram_quantile(0.95, rate(istio_request_duration_milliseconds_bucket{{destination_service_name="{service_name}",destination_service_namespace="{self.config.namespace}",destination_version="canary"}}[5m]))'
            )

            return {
                "service": service_name,
                "comparison": {
                    "stable": {
                        "request_rate": stable_metrics,
                        "error_rate": stable_errors,
                        "p95_latency": stable_latency
                    },
                    "canary": {
                        "request_rate": canary_metrics,
                        "error_rate": canary_errors,
                        "p95_latency": canary_latency
                    }
                },
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to get canary metrics: {e}")
            return {"error": str(e)}


# Context manager for bridge lifecycle
@asynccontextmanager
async def istio_bridge(config: Optional[ServiceMeshConfig] = None):
    """Context manager for Istio bridge with proper resource cleanup"""
    bridge = IstioBridge(config)
    await bridge.initialize()
    try:
        yield bridge
    finally:
        await bridge.cleanup()


# Convenience functions for common operations
async def apply_brain_researcher_policies():
    """Apply default Brain Researcher service mesh policies"""
    config = ServiceMeshConfig()

    async with istio_bridge(config) as bridge:
        results = []

        # Apply policies for each service
        services = [
            ("br_kg-service", "LEAST_CONN"),
            ("agent-service", "ROUND_ROBIN"),
            ("web-ui-service", "LEAST_CONN"),
            ("orchestrator-service", "ROUND_ROBIN")
        ]

        for service_name, lb_policy in services:
            # Traffic policy
            traffic_policy = TrafficPolicy(
                service_name=service_name,
                load_balancer=lb_policy,
                connection_pool={
                    "tcp": {"maxConnections": 100, "connectTimeout": "30s"},
                    "http": {"http1MaxPendingRequests": 50, "maxRequestsPerConnection": 10}
                },
                circuit_breaker={
                    "consecutiveGatewayErrors": 5,
                    "interval": "30s",
                    "baseEjectionTime": "30s"
                },
                timeout="60s"
            )

            result = await bridge.apply_traffic_policy(service_name, traffic_policy)
            results.append({"service": service_name, "traffic_policy": result})

            # Security policy
            security_policy = SecurityPolicy(
                service_name=service_name,
                mtls_mode="STRICT",
                authorization_rules=[{
                    "from": [{"source": {"principals": ["cluster.local/ns/brain-researcher/sa/*"]}}],
                    "to": [{"operation": {"methods": ["GET", "POST"]}}]
                }]
            )

            result = await bridge.apply_security_policy(service_name, security_policy)
            results.append({"service": service_name, "security_policy": result})

        return results