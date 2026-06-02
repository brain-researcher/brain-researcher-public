"""
API Gateway - Main application for unified service access.

This gateway provides a single entry point for all Brain Researcher services:
- Orchestrator: Port 3001 (FastAPI)
- Agent Service: Port 8000
- BR-KG Service: Port 5000
- NICLIP Service: Port 8001
- Web UI: Port 3000

Features:
- HTTP reverse proxy with routing rules
- Service discovery with health checks
- JWT authentication middleware
- Rate limiting and throttling
- Request/response transformation
- Circuit breaker pattern
- WebSocket proxy support
- Request logging and metrics
- CORS handling
- API versioning
"""

import asyncio
import gzip
import json
import logging
import re
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
import redis
import uvicorn
import websockets
import yaml
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from httpx import AsyncClient, ConnectTimeout, ReadTimeout
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from websockets.exceptions import ConnectionClosed

from .env import (
    AGENT_URL,
    BR_KG_URL,
    NICLIP_URL,
    ORCHESTRATOR_URL,
    REDIS_URL,
)
from .service_registry import Service, ServiceHealth, ServiceRegistry

try:
    from brain_researcher.services.shared.auth_middleware import (
        UserInfo,
        UserRole,
        get_current_user,
        require_roles,
    )
except ImportError:
    # Fallback for when auth_middleware has circular imports
    def get_current_user(*args, **kwargs):
        return None

    UserInfo = dict
    require_roles = lambda *args: lambda x: x
    UserRole = str

try:
    from .rate_limiter import RateLimiter, RateLimitExceeded
except ImportError:
    # Fallback rate limiter
    class RateLimitExceeded(Exception):
        def __init__(self, message, rate_limit_info, headers=None):
            super().__init__(message)
            self.headers = headers or {}

    class RateLimiter:
        def __init__(self, *args, **kwargs):
            pass

        async def check_rate_limit(self, *args, **kwargs):
            pass


try:
    from .request_transformer import RequestTransformer, ResponseTransformer
except ImportError:

    class RequestTransformer:
        def __init__(self, *args, **kwargs):
            pass

        async def transform(self, request, headers, body):
            return headers, body

    class ResponseTransformer:
        def __init__(self, *args, **kwargs):
            pass

        async def transform(self, response, headers, body):
            return headers, body


try:
    from .health_monitor import HealthMonitor
except ImportError:

    class HealthMonitor:
        def __init__(self, *args, **kwargs):
            pass

        async def check_all_services(self):
            pass


try:
    from .load_balancer import LoadBalancer, LoadBalancingStrategy
except ImportError:

    class LoadBalancingStrategy:
        ROUND_ROBIN = "round_robin"

    class LoadBalancer:
        def __init__(self, *args, **kwargs):
            pass

        def select_instance(self, service, strategy=None):
            if service and service.instances:
                return service.instances[0].url
            return None


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Hop-by-hop headers to exclude from proxy forwarding (RFC 2616)
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


class GatewayConfig(BaseModel):
    """Gateway configuration model."""

    port: int = Field(8080, description="Gateway port")
    debug: bool = Field(False, description="Debug mode")
    cors_origins: List[str] = Field(
        default_factory=lambda: ["*"], description="CORS origins"
    )
    max_request_size: int = Field(
        10 * 1024 * 1024, description="Max request size in bytes"
    )
    timeout_seconds: int = Field(30, description="Request timeout")
    circuit_breaker_failure_threshold: int = Field(
        5, description="Circuit breaker failure threshold"
    )
    circuit_breaker_reset_timeout: int = Field(
        60, description="Circuit breaker reset timeout"
    )
    enable_compression: bool = Field(True, description="Enable response compression")
    enable_request_logging: bool = Field(True, description="Enable request logging")
    enable_metrics: bool = Field(True, description="Enable metrics collection")
    redis_url: str = Field("redis://localhost:6379/0", description="Redis URL")


class RouteConfig(BaseModel):
    """Route configuration."""

    path: str = Field(..., description="Route path pattern")
    service: str = Field(..., description="Target service name")
    strip_path: bool = Field(True, description="Strip route path from request")
    rewrite_mode: Optional[str] = Field(
        None,
        description="Optional path rewrite mode (e.g. orchestrator_v1, agent_v1)",
    )
    preserve_host: bool = Field(False, description="Preserve original host header")
    timeout: Optional[int] = Field(None, description="Route-specific timeout")
    auth_required: bool = Field(True, description="Require authentication")
    roles_required: List[str] = Field(
        default_factory=list, description="Required roles"
    )
    rate_limit: Optional[Dict[str, int]] = Field(None, description="Rate limit config")
    cache_ttl: Optional[int] = Field(None, description="Cache TTL in seconds")


class CircuitBreakerState:
    """Circuit breaker state management."""

    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open

    def record_success(self):
        """Record successful request."""
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self):
        """Record failed request."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = "open"

    def can_request(self) -> bool:
        """Check if request can proceed."""
        if self.state == "closed":
            return True

        if self.state == "open":
            if time.time() - self.last_failure_time >= self.reset_timeout:
                self.state = "half-open"
                return True
            return False

        # half-open state
        return True

    def is_open(self) -> bool:
        """Check if circuit is open."""
        return self.state == "open"


class RequestMetrics(BaseModel):
    """Request metrics model."""

    request_id: str
    method: str
    path: str
    service: Optional[str]
    status_code: int
    duration_ms: float
    request_size: int
    response_size: int
    user_id: Optional[str]
    timestamp: datetime
    error: Optional[str] = None


class APIGatewayMiddleware(BaseHTTPMiddleware):
    """Main gateway middleware for request processing."""

    def __init__(self, app: ASGIApp, gateway: "APIGateway"):
        super().__init__(app)
        self.gateway = gateway

    async def dispatch(self, request: Request, call_next: Callable):
        """Process request through gateway pipeline."""
        request_id = str(uuid.uuid4())
        start_time = time.time()

        # Add request ID to headers
        request.state.request_id = request_id

        try:
            # Log incoming request
            if self.gateway.config.enable_request_logging:
                logger.info(f"[{request_id}] {request.method} {request.url}")

            response = await call_next(request)

            # Log response
            duration = (time.time() - start_time) * 1000
            if self.gateway.config.enable_request_logging:
                logger.info(f"[{request_id}] {response.status_code} - {duration:.2f}ms")

            # Collect metrics
            if self.gateway.config.enable_metrics:
                await self.gateway._collect_metrics(
                    request, response, duration, request_id
                )

            return response

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            logger.error(f"[{request_id}] Error: {str(e)}")

            # Collect error metrics
            if self.gateway.config.enable_metrics:
                error_response = Response(status_code=500)
                await self.gateway._collect_metrics(
                    request, error_response, duration, request_id, str(e)
                )

            raise


class APIGateway:
    """Main API Gateway class."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize API Gateway.

        Args:
            config_path: Path to configuration file
        """
        self.config = self._load_config(config_path)
        self.app = FastAPI(
            title="Brain Researcher API Gateway",
            description="Unified API Gateway for Brain Researcher Services",
            version="1.0.0",
            docs_url="/docs",
            redoc_url="/redoc",
        )

        # Initialize components
        self.redis_client = self._init_redis()
        self.service_registry = ServiceRegistry(self.redis_client, service_ttl=0)
        self.rate_limiter = RateLimiter(self.redis_client)
        self.request_transformer = RequestTransformer()
        self.response_transformer = ResponseTransformer()
        self.health_monitor = HealthMonitor(self.service_registry)
        self.load_balancer = LoadBalancer()

        # Blue-green deployment manager
        try:
            from .deployment_manager import BlueGreenDeploymentManager

            self.deployment_manager = BlueGreenDeploymentManager(
                self.service_registry, self.redis_client
            )
        except ImportError:
            logger.warning("Deployment manager not available")
            self.deployment_manager = None

        # Service mesh integration
        try:
            from ..communication.service_mesh import MeshConfig, ServiceMesh

            self.service_mesh = self._init_service_mesh()
        except ImportError:
            logger.warning("Service mesh not available")
            self.service_mesh = None

        # Circuit breakers per service
        self.circuit_breakers: Dict[str, CircuitBreakerState] = {}

        # HTTP client for proxying
        self.http_client = AsyncClient(
            timeout=httpx.Timeout(self.config.timeout_seconds),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=10),
        )

        # Route configurations
        self.routes = self._load_routes()

        # Setup middleware and routes
        self._setup_middleware()
        self._setup_routes()

        # Track background tasks so we can cancel them on shutdown
        self._background_tasks: List[asyncio.Task] = []
        self._register_lifecycle_events()

    def _init_service_mesh(self):
        """Initialize service mesh if available."""
        try:
            from brain_researcher.config.paths import resolve_from_config

            from ..communication.service_mesh import MeshConfig, ServiceMesh

            # Load service mesh configuration
            mesh_config_path = resolve_from_config("runtime", "service_mesh.yaml")
            if mesh_config_path.exists():
                import yaml

                with open(mesh_config_path, "r") as f:
                    mesh_config_data = yaml.safe_load(f)

                # Create mesh config (simplified - would need proper mapping)
                mesh_config = MeshConfig(
                    cluster_name=mesh_config_data.get(
                        "cluster_name", "brain_researcher"
                    ),
                    enable_mtls=mesh_config_data.get("settings", {}).get(
                        "enable_mtls", False
                    ),
                    enable_tracing=mesh_config_data.get("settings", {}).get(
                        "enable_tracing", True
                    ),
                    enable_metrics=mesh_config_data.get("settings", {}).get(
                        "enable_metrics", True
                    ),
                    redis_url=mesh_config_data.get("settings", {}).get(
                        "redis_url", "redis://localhost:6379/1"
                    ),
                )

                return ServiceMesh(mesh_config)
        except Exception as e:
            logger.warning(f"Failed to initialize service mesh: {e}")

        return None

    def _load_config(self, config_path: Optional[str]) -> GatewayConfig:
        """Load gateway configuration."""
        if config_path and Path(config_path).exists():
            with open(config_path, "r") as f:
                config_data = yaml.safe_load(f)
            return GatewayConfig(**config_data)
        else:
            return GatewayConfig()

    def _init_redis(self) -> redis.Redis:
        """Initialize Redis client."""
        redis_url = REDIS_URL or self.config.redis_url
        try:
            client = redis.from_url(redis_url, decode_responses=False)
            client.ping()
            return client
        except:
            try:
                import fakeredis

                logger.warning("Using fake Redis for development")
                return fakeredis.FakeRedis(decode_responses=False)
            except ImportError:
                logger.error("Redis not available and fakeredis not installed")
                raise

    def _load_routes(self) -> List[RouteConfig]:
        """Load route configurations."""
        # Default routes for Brain Researcher services
        # NOTE: Order matters - more specific routes should come first
        default_routes = [
            # Canonical v1 routes (preferred)
            RouteConfig(
                path="/api/orchestrator/v1/**",
                service="orchestrator",
                strip_path=True,
                rewrite_mode="orchestrator_v1",
                auth_required=False,
                rate_limit=None,
            ),
            RouteConfig(
                path="/api/agent/v1/**",
                service="agent",
                strip_path=True,
                rewrite_mode="agent_v1",
                auth_required=True,
                rate_limit=None,
            ),
            RouteConfig(
                path="/api/kg/v1/**",
                service="br_kg",
                strip_path=True,
                rewrite_mode="kg_v1",
                auth_required=True,
                rate_limit=None,
            ),
            RouteConfig(
                path="/api/niclip/v1/**",
                service="niclip",
                strip_path=True,
                rewrite_mode="niclip_v1",
                auth_required=True,
                rate_limit=None,
            ),
            # Auth routes - FIRST to win routing, no auth check, no rate limiting
            RouteConfig(
                path="/auth/**",
                service="orchestrator",
                strip_path=False,  # Keep /auth prefix
                auth_required=False,
                rate_limit=None,
            ),
            # Agent Service
            RouteConfig(
                path="/api/agent/**",
                service="agent",
                strip_path=True,
                auth_required=True,
                rate_limit=None,
            ),
            # BR-KG Service
            RouteConfig(
                path="/api/kg/**",
                service="br_kg",
                strip_path=True,
                auth_required=True,
                rate_limit=None,
            ),
            # NICLIP Service
            RouteConfig(
                path="/api/niclip/**",
                service="niclip",
                strip_path=True,
                auth_required=True,
                rate_limit=None,
            ),
            # Orchestrator
            RouteConfig(
                path="/api/orchestrator/**",
                service="orchestrator",
                strip_path=True,
                auth_required=False,  # Public endpoints
                rate_limit=None,
            ),
            # Job management (from existing gateway)
            RouteConfig(
                path="/api/v1/jobs/**",
                service="gateway",
                strip_path=False,
                auth_required=True,
            ),
            RouteConfig(
                path="/api/v1/run",
                service="gateway",
                strip_path=False,
                auth_required=True,
            ),
        ]

        return default_routes

    def _setup_middleware(self):
        """Setup FastAPI middleware."""
        # CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=self.config.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Compression
        if self.config.enable_compression:
            self.app.add_middleware(GZipMiddleware, minimum_size=1000)

        # Custom gateway middleware
        self.app.add_middleware(APIGatewayMiddleware, gateway=self)

    def _setup_routes(self):
        """Setup gateway routes."""

        # Health check endpoint
        @self.app.get("/health")
        async def health_check():
            """Gateway health check."""
            return {
                "status": "healthy",
                "timestamp": datetime.utcnow().isoformat(),
                "version": "1.0.0",
                "services": await self.service_registry.get_all_services(),
            }

        # Service registry endpoint
        @self.app.get("/services")
        async def list_services():
            """List registered services."""
            return await self.service_registry.get_all_services()

        # Metrics endpoint
        @self.app.get("/metrics")
        async def get_metrics():
            """Get gateway metrics."""
            return await self._get_metrics_summary()

        # Deployment management endpoints
        if self.deployment_manager:

            @self.app.get("/deployment/status")
            async def get_deployment_status():
                """Get deployment status."""
                return self.deployment_manager.get_status()

            @self.app.post("/deployment/deploy")
            async def create_deployment(deployment_request: Dict[str, Any]):
                """Create and execute deployment."""
                try:
                    # This would need proper request validation and service parsing
                    services = deployment_request.get("services", {})
                    version = deployment_request.get("version", "1.0.0")
                    strategy = deployment_request.get("strategy", "all_or_nothing")

                    from .deployment_manager import TrafficSplitStrategy

                    strategy_enum = TrafficSplitStrategy(strategy)

                    # Create deployment plan
                    plan = await self.deployment_manager.create_deployment_plan(
                        services, version, strategy_enum
                    )

                    # Execute deployment
                    success = await self.deployment_manager.execute_deployment(plan)

                    return {
                        "deployment_id": plan.id,
                        "success": success,
                        "status": plan.status,
                    }
                except Exception as e:
                    return {"error": str(e)}

            @self.app.post("/deployment/rollback")
            async def rollback_deployment():
                """Rollback current deployment."""
                # Implementation would depend on specific rollback logic
                return {"message": "Rollback initiated"}

        # Service mesh endpoints
        if self.service_mesh:

            @self.app.get("/mesh/status")
            async def get_mesh_status():
                """Get service mesh status."""
                return await self.service_mesh.get_mesh_status()

        # Dynamic proxy routes
        @self.app.api_route(
            "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
        )
        async def proxy_request(request: Request, path: str):
            """Proxy request to appropriate service."""
            return await self._proxy_request(request, path)

        # WebSocket proxy (canonical /ws/{service}/... plus legacy /ws/* alias)
        @self.app.websocket("/ws/{path:path}")
        async def proxy_websocket(websocket: WebSocket, path: str):
            """Proxy WebSocket connections (service inferred from path)."""
            segments = [segment for segment in path.split("/") if segment]
            if segments and segments[0] in {"orchestrator", "agent", "br_kg", "niclip"}:
                service = segments[0]
                subpath = "/".join(segments[1:]) if len(segments) > 1 else ""
            else:
                # Legacy /ws/* defaults to orchestrator
                service = "orchestrator"
                subpath = path
            await self._proxy_websocket(websocket, service, subpath)

    def _register_lifecycle_events(self) -> None:
        """Register FastAPI startup/shutdown hooks for background tasks."""

        @self.app.on_event("startup")
        async def _startup_tasks() -> None:
            await self._register_default_services()

            # Periodic monitoring loops
            self._background_tasks.append(
                asyncio.create_task(self._health_check_loop())
            )
            self._background_tasks.append(
                asyncio.create_task(self._metrics_cleanup_loop())
            )

            if self.service_mesh:
                start_coro = getattr(self.service_mesh, "start", None)
                if callable(start_coro):
                    self._background_tasks.append(asyncio.create_task(start_coro()))

            if self.deployment_manager:
                start_coro = getattr(self.deployment_manager, "start", None)
                if callable(start_coro):
                    self._background_tasks.append(asyncio.create_task(start_coro()))

        @self.app.on_event("shutdown")
        async def _shutdown_tasks() -> None:
            for task in self._background_tasks:
                task.cancel()

            if self._background_tasks:
                await asyncio.gather(*self._background_tasks, return_exceptions=True)

            if self.service_mesh:
                stop_coro = getattr(self.service_mesh, "stop", None)
                if callable(stop_coro):
                    try:
                        await stop_coro()
                    except Exception as exc:
                        logger.warning("Failed to stop service mesh cleanly: %s", exc)

            if self.deployment_manager:
                stop_coro = getattr(self.deployment_manager, "stop", None)
                if callable(stop_coro):
                    try:
                        await stop_coro()
                    except Exception as exc:
                        logger.warning(
                            "Failed to stop deployment manager cleanly: %s", exc
                        )

            await self.http_client.aclose()

    async def _register_default_services(self):
        """Register default Brain Researcher services."""
        default_services = [
            Service(
                name="orchestrator",
                url=ORCHESTRATOR_URL,
                health_check_path="/health",
                version="1.0.0",
            ),
            Service(
                name="agent",
                url=AGENT_URL,
                health_check_path="/health",
                version="1.0.0",
            ),
            Service(
                name="br_kg", url=BR_KG_URL, health_check_path="/", version="1.0.0"
            ),
            Service(
                name="niclip",
                url=NICLIP_URL,
                health_check_path="/health",
                version="1.0.0",
            ),
        ]

        for service in default_services:
            await self.service_registry.register(service)

    async def _health_check_loop(self):
        """Background health checking loop."""
        while True:
            try:
                await self.health_monitor.check_all_services()
                await asyncio.sleep(30)  # Check every 30 seconds
            except Exception as e:
                logger.error(f"Health check error: {e}")
                await asyncio.sleep(60)

    async def _metrics_cleanup_loop(self):
        """Background metrics cleanup loop."""
        while True:
            try:
                # Clean up old metrics data
                cutoff_time = time.time() - 3600  # 1 hour
                self.redis_client.zremrangebyscore("metrics:requests", 0, cutoff_time)
                await asyncio.sleep(1800)  # Clean every 30 minutes
            except Exception as e:
                logger.error(f"Metrics cleanup error: {e}")
                await asyncio.sleep(3600)

    def _rewrite_proxy_path(self, route: RouteConfig, proxy_path: str) -> str:
        """Apply service-specific path rewrites for canonical v1 routes."""
        if not route.rewrite_mode:
            return proxy_path

        normalized = "/" + proxy_path.lstrip("/")

        def _apply_api_prefix(root_passthrough: List[str]) -> str:
            for prefix in root_passthrough:
                if normalized == prefix or normalized.startswith(prefix + "/"):
                    return normalized
            if normalized.startswith("/api/"):
                return normalized
            return "/api" + normalized

        if route.rewrite_mode == "orchestrator_v1":
            return _apply_api_prefix(["/health", "/metrics", "/docs", "/openapi.json"])
        if route.rewrite_mode == "agent_v1":
            return _apply_api_prefix(["/health", "/tools"])
        if route.rewrite_mode == "kg_v1":
            return _apply_api_prefix(["/health", "/"])
        if route.rewrite_mode == "niclip_v1":
            return _apply_api_prefix(["/health", "/"])
        return normalized

    async def _proxy_request(self, request: Request, path: str) -> Response:
        """Proxy HTTP request to appropriate service."""
        # Special handling for auth routes - delegate to auth proxy for proper cookie handling
        if path.startswith("auth/") or path == "auth":
            return await self._proxy_auth_request(request, path)

        # Find matching route
        route = self._find_route(request.method, f"/{path}")

        if not route:
            raise HTTPException(
                status_code=404, detail=f"No route found for {request.method} /{path}"
            )

        # Check authentication
        current_user = None
        if route.auth_required:
            try:
                current_user = await get_current_user(request)
            except HTTPException:
                raise HTTPException(status_code=401, detail="Authentication required")
            except AttributeError:
                # Fallback when dependency injector didn't populate credentials
                current_user = None

        # Check rate limits
        if route.rate_limit:
            identifier = (
                current_user.user_id if current_user else str(request.client.host)
            )
            try:
                await self.rate_limiter.check_rate_limit(
                    identifier,
                    route.rate_limit["requests"],
                    route.rate_limit.get("window", 3600),
                )
            except RateLimitExceeded as e:
                raise HTTPException(
                    status_code=429, detail="Rate limit exceeded", headers=e.headers
                )

        # Get target service
        if route.service == "gateway":
            # Handle internal gateway routes (job management)
            return await self._handle_internal_route(request, route)

        service = await self.service_registry.get_service(route.service)
        if not service:
            raise HTTPException(
                status_code=503, detail=f"Service {route.service} not available"
            )

        # Check circuit breaker
        circuit_breaker = self.circuit_breakers.get(route.service)
        if not circuit_breaker:
            circuit_breaker = CircuitBreakerState(
                self.config.circuit_breaker_failure_threshold,
                self.config.circuit_breaker_reset_timeout,
            )
            self.circuit_breakers[route.service] = circuit_breaker

        if not circuit_breaker.can_request():
            raise HTTPException(
                status_code=503,
                detail=f"Service {route.service} temporarily unavailable",
            )

        # Load balance if multiple instances
        target_url = self.load_balancer.select_instance(
            service, LoadBalancingStrategy.ROUND_ROBIN
        )
        if not target_url:
            logger.warning(
                "No healthy instances available for service %s during route %s %s",
                route.service,
                request.method,
                path,
            )
            raise HTTPException(
                status_code=503,
                detail=f"Service {route.service} not available",
            )

        # Transform request
        proxy_path = path
        if route.strip_path:
            # Remove route prefix
            route_prefix = route.path.replace("/**", "").replace("/*", "")
            if path.startswith(route_prefix.lstrip("/")):
                proxy_path = path[len(route_prefix.lstrip("/")) :]

        proxy_path = self._rewrite_proxy_path(route, proxy_path)

        target_url = f"{target_url.rstrip('/')}/{proxy_path.lstrip('/')}"

        # Prepare headers
        headers = dict(request.headers)
        if not route.preserve_host:
            headers.pop("host", None)

        # Transform request
        headers, body = await self.request_transformer.transform(
            request, headers, await request.body()
        )

        try:
            # Make proxied request
            response = await self.http_client.request(
                request.method,
                target_url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
                timeout=route.timeout or self.config.timeout_seconds,
            )

            circuit_breaker.record_success()

            # Transform response
            response_headers, response_content = (
                await self.response_transformer.transform(
                    response, dict(response.headers), response.content
                )
            )

            # Create FastAPI response
            return Response(
                content=response_content,
                status_code=response.status_code,
                headers=response_headers,
            )

        except Exception as e:
            circuit_breaker.record_failure()
            logger.error(f"Proxy error for {route.service}: {e}")

            if isinstance(e, (ConnectTimeout, ReadTimeout)):
                raise HTTPException(status_code=504, detail="Gateway timeout")
            else:
                raise HTTPException(status_code=502, detail="Bad gateway")

    async def _proxy_auth_request(self, request: Request, path: str) -> Response:
        """Proxy auth requests with proper Set-Cookie preservation.

        This method is used for /auth/* routes to ensure refresh token
        cookies are properly passed through from orchestrator.
        """
        # Filter hop-by-hop headers
        forward_headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in HOP_BY_HOP_HEADERS
        }

        # Get orchestrator URL
        target_url = f"{ORCHESTRATOR_URL}/{path}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=forward_headers,
                    content=await request.body(),
                    params=dict(request.query_params),
                )

                # Build response preserving content-type
                response = Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    media_type=resp.headers.get("content-type"),
                )

                # Preserve ALL Set-Cookie headers (may be multiple)
                for key, value in resp.headers.multi_items():
                    if key.lower() == "set-cookie":
                        response.headers.append(key, value)

                return response

        except Exception as e:
            logger.error(f"Auth proxy error: {e}")
            if isinstance(e, (ConnectTimeout, ReadTimeout)):
                raise HTTPException(status_code=504, detail="Gateway timeout")
            else:
                raise HTTPException(status_code=502, detail="Bad gateway")

    def _build_websocket_target_url(
        self, service_info: Service, path: str, query_items
    ) -> str:
        """Construct upstream WebSocket URL including /ws prefix and query params."""
        split = urlsplit(service_info.url)
        scheme = "wss" if split.scheme == "https" else "ws"

        base_segments = (
            [segment for segment in split.path.strip("/").split("/") if segment]
            if split.path
            else []
        )
        target_segments = base_segments + ["ws", path.lstrip("/")]
        cleaned_segments = [
            segment.strip("/") for segment in target_segments if segment
        ]
        full_path = "/" + "/".join(cleaned_segments)

        query_string = urlencode(list(query_items), doseq=True) if query_items else ""
        return urlunsplit((scheme, split.netloc, full_path, query_string, ""))

    async def _proxy_websocket(self, websocket: WebSocket, service: str, path: str):
        """Proxy WebSocket connection to service."""
        service_info = await self.service_registry.get_service(service)
        if not service_info:
            await websocket.close(code=1003, reason=f"Service {service} not found")
            return

        try:
            subprotocol_header = websocket.headers.get("sec-websocket-protocol")
            requested_subprotocols = (
                [
                    proto.strip()
                    for proto in subprotocol_header.split(",")
                    if proto.strip()
                ]
                if subprotocol_header
                else None
            )

            await websocket.accept(
                subprotocol=(
                    requested_subprotocols[0] if requested_subprotocols else None
                )
            )

            target_url = self._build_websocket_target_url(
                service_info,
                path,
                websocket.query_params.multi_items(),
            )

            additional_headers = {}
            origin = websocket.headers.get("origin")
            if origin:
                additional_headers["Origin"] = origin

            async with websockets.connect(
                target_url,
                additional_headers=additional_headers or None,
                subprotocols=requested_subprotocols,
                ping_interval=None,
                proxy=None,
            ) as upstream_ws:

                async def proxy_to_target():
                    try:
                        while True:
                            message = await websocket.receive()
                            message_type = message.get("type")

                            if message_type == "websocket.receive":
                                text_data = message.get("text")
                                bytes_data = message.get("bytes")
                                if text_data is not None:
                                    await upstream_ws.send(text_data)
                                elif bytes_data is not None:
                                    await upstream_ws.send(bytes_data)
                            elif message_type == "websocket.disconnect":
                                await upstream_ws.close(
                                    code=message.get("code") or 1000
                                )
                                break
                    except WebSocketDisconnect:
                        await upstream_ws.close()
                    except Exception as exc:
                        logger.debug("Client->upstream WebSocket proxy error: %s", exc)
                        await upstream_ws.close()

                async def proxy_to_client():
                    try:
                        while True:
                            data = await upstream_ws.recv()
                            if isinstance(data, str):
                                await websocket.send_text(data)
                            else:
                                await websocket.send_bytes(data)
                    except ConnectionClosed as exc:
                        await websocket.close(
                            code=exc.code or 1000,
                            reason=exc.reason or "Upstream closed",
                        )
                    except Exception as exc:
                        logger.error("Upstream->client WebSocket proxy error: %s", exc)
                        await websocket.close(code=1011, reason="Proxy failure")

                await asyncio.gather(
                    proxy_to_target(),
                    proxy_to_client(),
                    return_exceptions=True,
                )

        except WebSocketDisconnect:
            return
        except Exception as e:
            logger.error(f"WebSocket proxy error: {e}")
            await websocket.close(code=1011, reason="Internal error")

    def _find_route(self, method: str, path: str) -> Optional[RouteConfig]:
        """Find matching route configuration with intelligent path matching."""
        import re

        # Sort routes by specificity (more specific patterns first)
        sorted_routes = sorted(
            self.routes, key=lambda r: (-r.path.count("/"), -len(r.path))
        )

        for route in sorted_routes:
            # Convert route pattern to regex
            pattern = self._convert_route_pattern_to_regex(route.path)

            if re.match(pattern, path):
                return route

        return None

    def _convert_route_pattern_to_regex(self, pattern: str) -> str:
        """Convert route pattern to regex with intelligent matching.

        Patterns:
        - /api/agent/** -> matches /api/agent/anything/more
        - /api/kg/* -> matches /api/kg/something
        - /api/exact -> matches /api/exact only
        - /api/{service}/health -> matches /api/agent/health, /api/kg/health
        """
        # Escape regex special characters except our placeholders
        escaped = re.escape(pattern)

        # Replace escaped patterns back to regex
        regex_pattern = escaped
        regex_pattern = regex_pattern.replace(r"\*\*", ".*")  # ** -> match anything
        regex_pattern = regex_pattern.replace(r"\*", "[^/]*")  # * -> match segment
        regex_pattern = regex_pattern.replace(
            r"\{[^}]+\}", "[^/]+"
        )  # {param} -> match segment

        # Ensure exact match
        if not regex_pattern.endswith(".*"):
            regex_pattern += "$"

        # Ensure starts with beginning of string
        if not regex_pattern.startswith("^"):
            regex_pattern = "^" + regex_pattern

        return regex_pattern

    async def _handle_internal_route(
        self, request: Request, route: RouteConfig
    ) -> Response:
        """Handle internal gateway routes (job management)."""
        # This would integrate with existing job submission/status functionality
        from .job_status import router as status_router
        from .job_submission import router as job_router

        # For now, return a placeholder
        return JSONResponse(
            content={
                "message": "Internal gateway route",
                "path": str(request.url.path),
                "method": request.method,
            }
        )

    async def _collect_metrics(
        self,
        request: Request,
        response: Response,
        duration: float,
        request_id: str,
        error: Optional[str] = None,
    ):
        """Collect request metrics."""
        try:
            # Determine service from route
            service = None
            route = self._find_route(request.method, request.url.path)
            if route:
                service = route.service

            # Get user ID if available
            user_id = None
            try:
                user = await get_current_user(request)
                user_id = user.user_id
            except:
                pass

            # Create metrics record
            metrics = RequestMetrics(
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                service=service,
                status_code=response.status_code,
                duration_ms=duration,
                request_size=int(request.headers.get("content-length", 0)),
                response_size=len(response.body) if hasattr(response, "body") else 0,
                user_id=user_id,
                timestamp=datetime.utcnow(),
                error=error,
            )

            # Store in Redis
            metrics_key = f"metrics:request:{request_id}"
            self.redis_client.setex(
                metrics_key, 3600, json.dumps(metrics.dict(), default=str)  # 1 hour TTL
            )

            # Add to time series for aggregation
            timestamp = int(time.time())
            self.redis_client.zadd("metrics:requests", {request_id: timestamp})

        except Exception as e:
            logger.error(f"Error collecting metrics: {e}")

    async def _get_metrics_summary(self) -> Dict[str, Any]:
        """Get aggregated metrics summary."""
        try:
            # Get recent requests
            now = int(time.time())
            hour_ago = now - 3600

            recent_request_ids = self.redis_client.zrangebyscore(
                "metrics:requests", hour_ago, now
            )

            # Aggregate metrics
            total_requests = len(recent_request_ids)
            status_codes = {}
            avg_duration = 0
            error_count = 0

            if total_requests > 0:
                durations = []
                for request_id in recent_request_ids:
                    if isinstance(request_id, bytes):
                        request_id = request_id.decode()

                    metrics_data = self.redis_client.get(
                        f"metrics:request:{request_id}"
                    )
                    if metrics_data:
                        metrics = json.loads(metrics_data)
                        status_code = metrics.get("status_code", 0)
                        status_codes[status_code] = status_codes.get(status_code, 0) + 1
                        durations.append(metrics.get("duration_ms", 0))
                        if metrics.get("error"):
                            error_count += 1

                avg_duration = sum(durations) / len(durations) if durations else 0

            return {
                "total_requests_last_hour": total_requests,
                "average_duration_ms": round(avg_duration, 2),
                "status_code_distribution": status_codes,
                "error_count": error_count,
                "error_rate": (
                    round(error_count / total_requests * 100, 2)
                    if total_requests > 0
                    else 0
                ),
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error generating metrics summary: {e}")
            return {"error": str(e)}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("API Gateway starting up...")
    yield
    # Shutdown
    logger.info("API Gateway shutting down...")


def create_gateway(config_path: Optional[str] = None) -> FastAPI:
    """Create and configure API Gateway application."""
    gateway = APIGateway(config_path)
    return gateway.app


def main():
    """Run API Gateway server."""
    import argparse

    parser = argparse.ArgumentParser(description="Brain Researcher API Gateway")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--port", type=int, default=8080, help="Server port")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")

    args = parser.parse_args()

    # Create gateway app
    app = create_gateway(args.config)

    # Run server
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.debug,
        log_level="debug" if args.debug else "info",
        access_log=args.debug,
    )


if __name__ == "__main__":
    main()
