from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_SUBSTRINGS = {
    "DEPLOYMENT.md": (
        "`infrastructure/nginx/brain-researcher-compose.conf`",
        "Current `docker-compose.prod.yml` mounts this file directly;",
        "separate `api-gateway` container.",
        "http://localhost:5000/health",
        "http://localhost:3000/api/health",
        ":(80|443|3000|3001|5000|6379|7474|7687|8000)",
    ),
    "scripts/services/restart_services_with_niclip.sh": (
        'NEO4J_DATA_ROOT="$PROJECT_ROOT/data/neo4j"',
        'COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"',
        'export BR_KG_API_URL="http://localhost:5000"',
        "brain-researcher-neo4j",
        "nohup br serve kg --host 0.0.0.0 --port 5000",
        "nohup br serve web --host 0.0.0.0 --port 3000",
        "http://localhost:5000/health",
    ),
}

FORBIDDEN_SUBSTRINGS = {
    "DEPLOYMENT.md": (
        "API Gateway: http://localhost:8080/health",
        "http://localhost:8080/services",
        "`src/brain_researcher/services/api_gateway/nginx.conf`",
        "Port 5001",
        "│   (Port 5001)   │",
        "grep -E ':(80|443|3000|3001|5001|8000|8080)'",
    ),
    "scripts/services/restart_services_with_niclip.sh": (
        'NEO4J_COMPOSE_DIR="$PROJECT_ROOT/brain_researcher/services/br_kg"',
        'export BR_KG_API_URL="http://localhost:5001"',
        'export BR_KG_URL="http://localhost:5001"',
        'kill_service "Web UI" "services/web_ui"',
        "br_kg-neo4j",
        "nohup br serve kg --port 5001",
        "http://localhost:5001/health",
    ),
}


def test_operator_docs_and_scripts_use_current_runtime_contracts() -> None:
    for relpath, expected_substrings in REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in expected_substrings:
            assert needle in text, f"Missing expected text in {relpath}: {needle}"


def test_operator_docs_and_scripts_do_not_reintroduce_stale_paths_or_ports() -> None:
    for relpath, forbidden_substrings in FORBIDDEN_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in forbidden_substrings:
            assert needle not in text, f"Found stale text in {relpath}: {needle}"
