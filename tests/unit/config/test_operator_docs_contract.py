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
    "docs/NICLIP_CONFIGURATION.md": (
        "/src/brain_researcher/services/agent/.env",
        "/src/brain_researcher/services/neurokg/.env",
        "http://localhost:5000",
        "`scripts/services/restart_services_with_niclip.sh`",
        "`src/brain_researcher/services/tools/neurokg_tools.py`",
    ),
    "docs/archive/neurokg_graph_schema.md": (
        "python -m brain_researcher.services.neurokg.etl.load_all",
        "`src/brain_researcher/services/neurokg/bulk_loader.py`",
        "`src/brain_researcher/services/neurokg/graph/graph_database.py`",
        "`src/brain_researcher/services/neurokg/models/fmri_text_alignment.py`",
    ),
    "scripts/deployment/health_check.sh": (
        '["nginx"]="80:/health"',
        '["orchestrator"]="3001:/health"',
        '["agent"]="8000:/health"',
        '["neurokg"]="5000:/health"',
        '["web-ui"]="3000:/api/health"',
        '["redis"]="6379:ping"',
    ),
    "scripts/deployment/deploy.sh": (
        '"nginx:80:/health"',
        '"orchestrator:3001:/health"',
        '"agent:8000:/health"',
        '"neurokg:5000:/health"',
        '"web-ui:3000:/api/health"',
        "http://localhost/health",
        "http://localhost:5000/health",
        "http://localhost:3000/api/health",
        "http://localhost/api/agent/health",
    ),
    "scripts/services/restart_services_with_niclip.sh": (
        'NEO4J_DATA_ROOT="$PROJECT_ROOT/data/neo4j"',
        'COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"',
        'export NEUROKG_API_URL="http://localhost:5000"',
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
    "docs/NICLIP_CONFIGURATION.md": (
        "/app/brain_researcher/brain_researcher/services/agent/.env",
        "/app/brain_researcher/brain_researcher/services/neurokg/.env",
        "`brain_researcher/services/neurokg/etl/mappers/niclip_spatial_mapper_improved.py`",
        "`brain_researcher/services/agent/tools/neurokg_tools.py`",
    ),
    "docs/archive/neurokg_graph_schema.md": (
        "python -m brain_researcher.core.ingestion.load_all",
        "python brain_researcher/core/ingestion/load_all.py",
        "`brain_researcher/services/neurokg/bulk_loader.py`",
        "`brain_researcher/services/neurokg/graph/graph_database.py`",
        "`brain_researcher/services/neurokg/models/fmri_text_alignment.py`",
        "`/brain_researcher/core/ingestion/load_all.py`",
        "`/brain_researcher/services/neurokg/bulk_loader.py`",
    ),
    "scripts/deployment/health_check.sh": (
        '["api-gateway"]="8080:/health"',
        '["nginx"]="18080:/health"',
        '["orchestrator"]="13001:/health"',
        '["agent"]="18000:/health"',
        '["neurokg"]="15001:/health"',
        '["redis"]="6380:ping"',
        "$0 nginx api-gateway",
    ),
    "scripts/deployment/deploy.sh": (
        '"api-gateway:8080"',
        "http://localhost:8080/health",
        "http://localhost:8080/services",
        "http://localhost:5001/health",
        "http://localhost:8080/api/orchestrator/health",
    ),
    "scripts/services/restart_services_with_niclip.sh": (
        'NEO4J_COMPOSE_DIR="$PROJECT_ROOT/brain_researcher/services/neurokg"',
        'export NEUROKG_API_URL="http://localhost:5001"',
        'export NEUROKG_URL="http://localhost:5001"',
        'kill_service "Web UI" "services/web_ui"',
        "neurokg-neo4j",
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
