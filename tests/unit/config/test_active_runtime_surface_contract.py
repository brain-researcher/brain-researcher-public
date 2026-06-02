from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

ACTIVE_REQUIRED_SUBSTRINGS = {
    "apps/web-ui/next.config.development.js": (
        "Legacy compatibility shim.",
        "module.exports = require('./next.config.js')",
    ),
    "apps/web-ui/.env.example": (
        "NEXT_PUBLIC_BR_KG_API=http://localhost:5000",
        "BR_KG_PORT=5000",
        "WEB_UI_PORT=3000",
    ),
    "tests/conftest.py": (
        '"br_kg": {"host": "localhost", "port": 5000, "timeout": 30.0}',
        '"web_ui": {"host": "localhost", "port": 3000, "timeout": 10.0}',
        '"port": 5000,',
        '"port": 3001,',
    ),
    "tests/integration/test_e2e_workflow.py": ('return "http://localhost:3000"',),
    "tests/test_knowledge_graph_integration.js": (
        "http://localhost:5000",
        "port: 5000,",
    ),
    "tests/performance/k6/config/k6.config.js": ("http://localhost:5000",),
    "tests/performance/k6/scripts/run-smoke-test.sh": (
        'export BR_KG_URL=${BR_KG_URL:-"http://localhost:5000"}',
        "br serve kg            # Port 5000",
    ),
    "tests/performance/k6/scripts/run-load-test.sh": (
        'export BR_KG_URL=${BR_KG_URL:-"http://localhost:5000"}',
    ),
    "tests/performance/k6/scripts/run-all-tests.sh": (
        'export BR_KG_URL=${BR_KG_URL:-"http://localhost:5000"}',
        "br serve kg            # Port 5000",
    ),
    "tests/performance/k6/IMPLEMENTATION_SUMMARY.md": (
        "BR-KG Service (Port 5000)",
        'export BR_KG_URL="http://localhost:5000"',
    ),
    "tests/k8s/test_deployment_validation.py": (
        '("br_kg-service", "brain-researcher-core", 5000)',
    ),
    "tests/k8s/smoke/test_smoke_tests.py": (
        "http://br_kg-service.brain-researcher-core.svc.cluster.local:5000",
    ),
    "src/brain_researcher/services/orchestrator/health_monitor.py": (
        'url="http://localhost:3000"',
    ),
    "configs/runtime/service_mesh.yaml": ('url: "http://localhost:5000"',),
    "src/brain_researcher/cli/utils/http_client.py": ("http://localhost:3001",),
    "src/brain_researcher/cli/commands/cache_commands.py": ("get_orchestrator_url()",),
    "src/brain_researcher/services/orchestrator/.env.example": (
        "BR_KG_SERVICE_URL=http://localhost:5000",
        "OAUTH_REDIRECT_BASE_URL=http://localhost:3001",
    ),
    "infrastructure/docker/Dockerfile.orchestrator": (
        'CMD ["uvicorn", "brain_researcher.services.orchestrator.main_enhanced:app"',
        "EXPOSE 3001",
    ),
    "tests/security/owasp_zap/zap_baseline.conf": (
        '"http://localhost:8000/api/*"',
        '"http://localhost:3001/api/*"',
        '"http://localhost:5000/api/*"',
        '"http://localhost:3000/*"',
        'login_url = "http://localhost:3001/auth/login"',
    ),
    "tests/security/owasp_zap/zap_automation.yaml": (
        '- "http://localhost:8000"',
        '- "http://localhost:3001"',
        '- "http://localhost:5000"',
        '- "http://localhost:3000"',
    ),
    "infrastructure/haproxy/haproxy.cfg": (
        "server br-kg-1 br-kg:5000",
        "server br-kg-4 br-kg:5000",
        "use_backend web_ui_backend if is_api",
    ),
    "infrastructure/autoscaling/autoscaler.py": (
        "'name': 'agent'",
        "'name': 'web-ui'",
    ),
    "apps/web-ui/api/viz_service.py": ('allow_origins=["http://localhost:3000"]',),
    "Dockerfile": (
        "uvicorn brain_researcher.services.agent.asgi:app",
        "FROM base AS br-kg",
        'CMD ["brain-researcher", "serve", "kg", "--port", "5000", "--host", "0.0.0.0"]',
    ),
    "infrastructure/docker/Dockerfile.agent": (
        'CMD ["python", "-m", "brain_researcher.services.agent.web_service"]',
    ),
    "infrastructure/docker/Dockerfile.mcp": (
        'CMD ["python", "-m", "brain_researcher.services.mcp.server"]',
    ),
    "docker-compose.yml": (
        "dockerfile: infrastructure/docker/Dockerfile.orchestrator",
    ),
    "docker-compose.prod.yml": (
        "./infrastructure/nginx/brain-researcher-compose.conf:/etc/nginx/conf.d/default.conf:ro",
        "dockerfile: infrastructure/docker/Dockerfile.agent",
        "dockerfile: infrastructure/docker/Dockerfile.orchestrator",
        "dockerfile: infrastructure/docker/Dockerfile.mcp",
    ),
    "infrastructure/docker/compose/docker-compose.override.prod.yml": (
        "./infrastructure/nginx/brain-researcher-compose.conf:/etc/nginx/conf.d/default.conf:ro",
        "dockerfile: infrastructure/docker/Dockerfile.orchestrator",
    ),
    "infrastructure/docker/compose/docker-compose.override.test.yml": (
        "dockerfile: infrastructure/docker/Dockerfile.agent",
        "dockerfile: infrastructure/docker/Dockerfile.orchestrator",
    ),
    "infrastructure/docker/compose/docker-compose.override.swarm.yml": (
        "dockerfile: infrastructure/docker/Dockerfile.orchestrator",
    ),
    "configs/runtime/docker-compose.yml": (
        "context: ../..",
        "target: br-kg",
        "target: agent",
    ),
    "infrastructure/deployment/gce_k3s/QUICKSTART.md": (
        "infrastructure/docker/Dockerfile.agent",
        "infrastructure/docker/Dockerfile.orchestrator",
        "infrastructure/docker/Dockerfile.mcp",
    ),
    "infrastructure/deployment/gcp/GKE_QUICKSTART.md": (
        "infrastructure/docker/Dockerfile.orchestrator",
    ),
    "scripts/ops/mcp_docker_stdio.sh": ("infrastructure/docker/Dockerfile.mcp",),
}

ACTIVE_FORBIDDEN_SUBSTRINGS = {
    "apps/web-ui/next.config.development.js": (
        "http://127.0.0.1:5001",
        "http://127.0.0.1:8000', // legacy alias to agent",
    ),
    "apps/web-ui/.env.example": (
        "Default port is 5001",
        "BR_KG_PORT=5001",
    ),
    "tests/conftest.py": (
        '"port": 5001,',
        '"port": 8050,',
        '"port": 8080,',
    ),
    "tests/integration/test_e2e_workflow.py": ('return "http://localhost:8050"',),
    "tests/test_knowledge_graph_integration.js": (
        "http://localhost:5001",
        "port: 5001,",
    ),
    "tests/performance/k6/config/k6.config.js": ("http://localhost:5001",),
    "tests/performance/k6/scripts/run-smoke-test.sh": (
        "http://localhost:5001",
        "Port 5001",
    ),
    "tests/performance/k6/scripts/run-load-test.sh": ("http://localhost:5001",),
    "tests/performance/k6/scripts/run-all-tests.sh": (
        "http://localhost:5001",
        "Port 5001",
    ),
    "tests/performance/k6/IMPLEMENTATION_SUMMARY.md": (
        "Port 5001",
        "http://localhost:5001",
    ),
    "tests/k8s/test_deployment_validation.py": (
        '("br_kg-service", "brain-researcher-core", 5001)',
    ),
    "tests/k8s/smoke/test_smoke_tests.py": (
        "http://br_kg-service.brain-researcher-core.svc.cluster.local:5001",
    ),
    "src/brain_researcher/services/orchestrator/health_monitor.py": (
        'url="http://localhost:8050"',
    ),
    "configs/runtime/service_mesh.yaml": ('url: "http://localhost:5001"',),
    "src/brain_researcher/cli/utils/http_client.py": ("http://localhost:8080",),
    "src/brain_researcher/cli/commands/cache_commands.py": ("http://localhost:8002",),
    "src/brain_researcher/services/orchestrator/.env.example": (
        "BR_KG_SERVICE_URL=http://localhost:5001",
    ),
    "infrastructure/docker/Dockerfile.orchestrator": (
        "brain_researcher.services.gateway.asgi_app:app",
    ),
    "docker-compose.yml": ("src/brain_researcher/services/orchestrator/Dockerfile",),
    "docker-compose.prod.yml": (
        "dockerfile: docker/Dockerfile.agent",
        "dockerfile: docker/Dockerfile.mcp",
        "src/brain_researcher/services/orchestrator/Dockerfile",
        "./src/brain_researcher/services/api_gateway/nginx.conf:/etc/nginx/conf.d/default.conf:ro",
    ),
    "infrastructure/docker/compose/docker-compose.override.prod.yml": (
        "src/brain_researcher/services/orchestrator/Dockerfile",
        "./src/brain_researcher/services/api_gateway/nginx.conf:/etc/nginx/conf.d/default.conf:ro",
    ),
    "infrastructure/docker/compose/docker-compose.override.test.yml": (
        "src/brain_researcher/services/orchestrator/Dockerfile",
        "dockerfile: docker/Dockerfile.agent",
    ),
    "infrastructure/docker/compose/docker-compose.override.swarm.yml": (
        "src/brain_researcher/services/orchestrator/Dockerfile",
    ),
    "configs/runtime/docker-compose.yml": (
        "../services/br_kg",
        "../services/agent",
    ),
    "infrastructure/deployment/gce_k3s/QUICKSTART.md": (
        "-f docker/Dockerfile.agent",
        "-f docker/Dockerfile.mcp",
        "-f src/brain_researcher/services/orchestrator/Dockerfile",
    ),
    "infrastructure/deployment/gcp/GKE_QUICKSTART.md": (
        "src/brain_researcher/services/orchestrator/Dockerfile",
    ),
    "scripts/ops/mcp_docker_stdio.sh": ("-f docker/Dockerfile.mcp",),
    "Dockerfile": (
        "EXPOSE 5000 8050",
        "brain_researcher.services.gateway.asgi_app:app",
        "BR_DEV_ORCH_COMPAT",
        "python -m brain_researcher.services.br_kg.api.graph_api",
    ),
    "tests/security/owasp_zap/zap_baseline.conf": (
        '"http://localhost:8080/api/*"',
        '"http://localhost:5001/api/*"',
        '"http://localhost:8050/*"',
        'login_url = "http://localhost:8080/auth/login"',
    ),
    "tests/security/owasp_zap/zap_automation.yaml": (
        '- "http://localhost:8080"',
        '- "http://localhost:5001"',
        '- "http://localhost:8050"',
    ),
    "infrastructure/haproxy/haproxy.cfg": (
        "server br_kg-1 br_kg:5001",
        "use_backend api_gateway_backend if is_api",
        "server api-gw-1 api-gateway:8080",
    ),
    "apps/web-ui/api/viz_service.py": ("http://localhost:8050",),
    "apps/web-ui/src/lib/server/downstream.ts": (
        "BR_DEV_ORCH_COMPAT",
        "NEXT_PUBLIC_DEV_ORCH_COMPAT",
    ),
    "infrastructure/docker/Dockerfile.agent": ("web_service_langgraph",),
    "infrastructure/deployment/gce_k3s/values.prod.yaml": ("AGENT_USE_ASGI",),
    "infrastructure/autoscaling/autoscaler.py": ("'name': 'api-gateway'",),
}

LEGACY_REQUIRED_SUBSTRINGS = {
    "tests/integration/test_service_integration.py": (
        "Legacy full-stack integration suite",
        "pytest.skip(",
        "retired from active runtime coverage",
    ),
    "tests/e2e/browser_tests.py": (
        "Legacy browser automation scaffold",
        "pytest.skip(",
        "retired from active runtime coverage",
    ),
}


def test_active_runtime_surfaces_use_current_local_topology() -> None:
    for relpath, needles in ACTIVE_REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in needles:
            assert (
                needle in text
            ), f"Missing expected runtime text in {relpath}: {needle}"


def test_active_runtime_surfaces_do_not_reintroduce_stale_ports() -> None:
    for relpath, needles in ACTIVE_FORBIDDEN_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in needles:
            assert (
                needle not in text
            ), f"Found stale runtime text in {relpath}: {needle}"


def test_legacy_runtime_scaffolding_is_explicitly_marked() -> None:
    for relpath, needles in LEGACY_REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in needles:
            assert needle in text, f"Missing legacy marker in {relpath}: {needle}"
