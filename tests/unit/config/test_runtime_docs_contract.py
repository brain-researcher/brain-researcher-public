from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_SUBSTRINGS = {
    "docs/ENVIRONMENT_SETUP.md": (
        "automatically loads the nearest `.env` file",
        "`BRAIN_RESEARCHER_SKIP_DOTENV=1`",
        "br serve orchestrator --port 3001",
        "**Orchestrator service (port 3001)**",
        "curl http://localhost:3001/health",
        "Set `BR_ORCHESTRATOR_URL` explicitly",
    ),
    "src/brain_researcher/services/br_kg/RUN_INSTRUCTIONS.md": (
        "apps/web-ui",
        "br serve kg --port 5000",
        "br serve web",
        "br serve kg --port 5002",
    ),
    "docs/OPERATIONS.md": (
        # Verbatim service-launch snippets moved from README.md in commit 0f356bcbe
        # (academic-audience README rewrite). Keep them here as the canonical
        # runtime-instruction location.
        "br serve kg",
        "br serve orchestrator --port 3001",
        "br serve web",
        "NEXT_PUBLIC_USE_API_PROXY=true",
        "BR_ORCHESTRATOR_URL=http://127.0.0.1:3001",
        "BR_KG_URL=http://127.0.0.1:5000",
    ),
    "src/brain_researcher/services/br_kg/README.md": (
        "PORT=5000 python -m brain_researcher.services.br_kg.app",
        "# - GraphQL: http://localhost:5000/graphql",
        "# - REST API: http://localhost:5000/api/",
        "# - Health: http://localhost:5000/health",
        "Access the GraphiQL interface at `http://localhost:5000/graphql`",
        "curl http://localhost:5000/api/queries",
        "curl -X POST http://localhost:5000/api/queries/Q1_TASK_TO_REGION",
        "lsof -i :5000",
    ),
}

FORBIDDEN_SUBSTRINGS = {
    "docs/ENVIRONMENT_SETUP.md": (
        "`br serve` command **does not automatically load .env files**",
        "**Orchestrator**: mounted only when `BR_DEV_ORCH_COMPAT=1`; otherwise disabled.",
        "`BR_DEV_ORCH_COMPAT=1` is only needed",
    ),
    "src/brain_researcher/services/br_kg/RUN_INSTRUCTIONS.md": (
        "brain_researcher/services/web_ui",
        "br serve ui",
        "python -m brain_researcher.services.br_kg.app",
        "API on a specific port (e.g., 8000)",
    ),
    "docs/OPERATIONS.md": (
        "br serve kg                         # BR-KG API on port 5001",
        "- **BR-KG API**: http://localhost:5001",
        "- **Dashboard UI**: http://localhost:8050",
        "Expose a single public port via the canonical ASGI `gateway` service",
        "br serve gateway",
    ),
    "src/brain_researcher/services/br_kg/README.md": (
        "PORT=5001 python -m brain_researcher.services.br_kg.app",
        "http://localhost:5001/graphql",
        "http://localhost:5001/api/",
        "http://localhost:5001/health",
        "lsof -i :5001",
    ),
}


def test_runtime_docs_use_current_service_contracts() -> None:
    for relpath, expected_substrings in REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in expected_substrings:
            assert needle in text, f"Missing expected text in {relpath}: {needle}"


def test_runtime_docs_do_not_reintroduce_stale_runtime_guidance() -> None:
    for relpath, forbidden_substrings in FORBIDDEN_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in forbidden_substrings:
            assert needle not in text, f"Found stale text in {relpath}: {needle}"
