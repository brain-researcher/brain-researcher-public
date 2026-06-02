from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_SUBSTRINGS = {
    "apps/web-ui/README.md": (
        "cd apps/web-ui",
        "[Main Documentation](../../README.md)",
        "[CLI Documentation](../../docs/user-guide/cli.md)",
    ),
    "apps/web-ui/README-real-pipeline.md": ("cd apps/web-ui",),
    "apps/web-ui/INTEGRATION.md": (
        "`apps/web-ui/.env.local`",
        "cd apps/web-ui",
    ),
    "apps/web-ui/TESTING_3D_VIEWER.md": (
        "br serve agent",
        "br serve kg",
        "br serve web",
        "cd apps/web-ui",
        "http://localhost:3000/api/demo/peaks/",
        "http://localhost:3000/api/demo/real-evidence/",
    ),
    "apps/web-ui/CLOUDFLARE_DEPLOYMENT.md": ("Root directory: apps/web-ui",),
    "apps/web-ui/STORYBOOK_SETUP.md": ("apps/web-ui/",),
    "apps/web-ui/CHART_COMPONENTS_DEMO.md": (
        "cd apps/web-ui",
        "npm run dev -- --port 3002",
    ),
    "src/brain_researcher/services/agent/README.md": (
        "src/brain_researcher/services/agent/",
        'PORT=8000 gunicorn -w 1 -b 0.0.0.0:8000 "brain_researcher.services.agent.web_service:app"',
        "`src/brain_researcher/services/tools/`",
        "`ruff check src/brain_researcher/services/agent/`",
    ),
    "src/brain_researcher/services/api_gateway/README.md": (
        "legacy full-gateway compatibility surface",
        "The current default runtime path is split services",
        "No standalone reverse-proxy config or Docker image is shipped in the public tree.",
        "python -m brain_researcher.legacy.api_gateway.cli --help",
    ),
    "src/brain_researcher/services/br_kg/README.md": ("br serve web",),
    "src/brain_researcher/services/br_kg/api/README.md": (
        "python -m brain_researcher.services.br_kg.api.graph_api",
        "pytest tests/unit/br_kg/test_api.py -v",
        "`apps/web-ui`",
    ),
    "src/brain_researcher/services/orchestrator/README.md": (
        "uvicorn brain_researcher.services.orchestrator.main_enhanced:app --host 0.0.0.0 --port 3001 --reload",
    ),
    "src/brain_researcher/services/telemetry/README.md": (
        "python -m brain_researcher.services.telemetry.example_usage",
        "pytest tests/unit/telemetry/ tests/integration/telemetry/ -v",
        "../../../../apps/web-ui/src/components/telemetry/",
    ),
}

FORBIDDEN_SUBSTRINGS = {
    "apps/web-ui/README.md": ("cd brain_researcher/services/web_ui",),
    "apps/web-ui/README-real-pipeline.md": ("cd brain_researcher/services/web_ui",),
    "apps/web-ui/INTEGRATION.md": (
        "`services/web_ui/.env.local`",
        "cd brain_researcher/services/web_ui",
    ),
    "apps/web-ui/TESTING_3D_VIEWER.md": (
        "scripts/launch_services_clean.sh",
        "cd brain_researcher/services/web_ui",
        "http://localhost:3101/api/demo/peaks/",
        "http://localhost:3101/api/demo/real-evidence/",
    ),
    "apps/web-ui/CLOUDFLARE_DEPLOYMENT.md": (
        "Root directory: brain_researcher/services/web_ui",
    ),
    "apps/web-ui/STORYBOOK_SETUP.md": ("brain_researcher/services/web_ui/",),
    "apps/web-ui/CHART_COMPONENTS_DEMO.md": (
        "/app/brain_researcher/brain_researcher/services/web_ui",
    ),
    "src/brain_researcher/services/agent/README.md": (
        "cd brain_researcher",
        "uvicorn services.agent.web_service:app --reload --port 8000",
        "`brain_researcher/services/tools/`",
        "`ruff check brain_researcher/services/agent/`",
        "AGENT_USE_ASGI=1 PORT=8000 python start_agent.py",
    ),
    "src/brain_researcher/services/api_gateway/README.md": (
        "cp src/brain_researcher/services/api_gateway/config.yaml my-config.yaml",
        "python -m brain_researcher.services.api_gateway.cli serve --config src/brain_researcher/services/api_gateway/config.yaml",
        "black src/brain_researcher/services/api_gateway/",
        "br serve gateway",
    ),
    "src/brain_researcher/services/br_kg/README.md": ("br serve ui",),
    "src/brain_researcher/services/br_kg/api/README.md": (
        "cd brain_researcher/services/br_kg",
        "python -m api.graph_api",
        "python -m pytest tests/test_api.py -v",
        "`brain_researcher/services/web_ui`",
    ),
    "src/brain_researcher/services/orchestrator/README.md": (
        "cd brain_researcher/services/orchestrator",
        "uvicorn main:app --host 0.0.0.0 --port 3001 --reload",
    ),
    "src/brain_researcher/services/telemetry/README.md": (
        "cd brain_researcher/services/telemetry",
        "pytest brain_researcher/services/telemetry/tests/ -v",
        "../web_ui/src/components/telemetry/",
    ),
}


def test_active_service_docs_use_canonical_paths() -> None:
    for relpath, expected_substrings in REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in expected_substrings:
            assert needle in text, f"Missing expected text in {relpath}: {needle}"


def test_active_service_docs_do_not_reintroduce_legacy_paths() -> None:
    for relpath, forbidden_substrings in FORBIDDEN_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in forbidden_substrings:
            assert needle not in text, f"Found stale text in {relpath}: {needle}"
