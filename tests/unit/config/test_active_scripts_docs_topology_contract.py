from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_SUBSTRINGS = {
    "scripts/services/start_services.sh": (
        'start_service "kg" 5000 "http://127.0.0.1:5000/health" 45',
        'start_service "orchestrator" 3001 "http://127.0.0.1:3001/health" 45',
        'start_service "agent" 8000 "http://127.0.0.1:8000/health" 45',
        'start_service "mcp" 7000 "http://127.0.0.1:7000/healthz" 45',
        'start_service "web" 3000 "http://127.0.0.1:3000/api/health" 90',
        'env BR_MCP_HOST=0.0.0.0 BR_MCP_PORT=7000 bash scripts/mcp/start_http_local.sh',
        'br serve agent --host 0.0.0.0 --port 8000',
        'br serve web --host 0.0.0.0 --port 3000',
        'BR_MCP_HTTP_URL="${BR_MCP_HTTP_URL:-http://localhost:7000/mcp}"',
    ),
    "scripts/services/stop_services.sh": (
        'stop_service "web"',
        'stop_service "mcp"',
        'stop_service "orchestrator"',
        'stop_service "agent"',
        'stop_service "kg"',
        'for port in 3000 7000 3001 8000 5000; do',
    ),
    "scripts/services/run_gateway.sh": (
        'scripts/services/run_gateway.sh has been retired.',
        'Gateway is no longer part of the active local service topology.',
        'br serve agent --host 0.0.0.0 --port 8000',
        'br serve orchestrator --host 0.0.0.0 --port 3001',
        'bash scripts/mcp/start_http_local.sh',
        './scripts/services/start_services.sh',
    ),
}

FORBIDDEN_SUBSTRINGS = {
    "scripts/services/start_services.sh": (
        'Gateway',
        'br serve gateway --host 0.0.0.0 --port 8000',
        'Port 8080',
        'api.brain-researcher.com',
        'kg.brain-researcher.com',
    ),
    "scripts/services/stop_services.sh": (
        'stop_service "Gateway"',
        'for port in 3000 8000 5000 8080; do',
    ),
    "scripts/services/run_gateway.sh": (
        'uvicorn',
        'brain_researcher.services.gateway.asgi_app:app',
        'PYTHONPATH=',
    ),
}


def test_active_scripts_use_current_topology_contracts() -> None:
    for relpath, required in REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in required:
            assert needle in text, f"Missing expected text in {relpath}: {needle}"



def test_active_scripts_do_not_reintroduce_gateway_runtime_contracts() -> None:
    for relpath, forbidden in FORBIDDEN_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"Found stale text in {relpath}: {needle}"
