from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

LEGACY_REQUIRED_SUBSTRINGS = {
    "src/brain_researcher/cli/commands/services/gateway_launcher.py": (
        "Legacy launcher for the retired single-port gateway surface.",
        "Gateway runtime is retired.",
        "./scripts/services/start_services.sh",
    ),
    "src/brain_researcher/legacy/gateway/asgi_app.py": (
        "This module is no longer the canonical runtime path.",
        "split services (web, agent, orchestrator, br_kg)",
        "A separate legacy full reverse-proxy gateway lives under",
        "no longer mounts the",
        "Orchestrator HTTP API under `/orchestrator`",
        "brain_researcher.legacy.gateway",
    ),
    "src/brain_researcher/services/api_gateway/README.md": (
        "This package is the legacy full-gateway compatibility surface.",
        "canonical Python owner now lives under `src/brain_researcher/legacy/api_gateway/`",
        "The current default runtime path is split services",
        "This package is compatibility-only.",
    ),
    "src/brain_researcher/services/api_gateway/__init__.py": (
        "Legacy standalone API gateway compatibility surface.",
        "canonical Python owner now lives under `brain_researcher.legacy.api_gateway`",
        'API_GATEWAY_STATUS = "legacy_compatibility"',
        '__description__ = "Legacy standalone API gateway compatibility surface"',
        '"name": "Brain Researcher Legacy API Gateway"',
    ),
    "src/brain_researcher/legacy/api_gateway/__init__.py": (
        "Legacy standalone API gateway compatibility surface.",
        "canonical Python owner for the older full",
        "from brain_researcher.legacy.api_gateway import create_gateway",
    ),
    "tests/contracts/README.md": (
        "Legacy standalone `api_gateway` contract coverage is retained here as compatibility-only scaffolding.",
        "Legacy gateway contract coverage is opt-in:",
        "BR_ENABLE_LEGACY_GATEWAY_TESTS=1",
    ),
    "tests/contracts/pact_config.py": (
        'LEGACY_GATEWAY_CONTRACT_ENV = "BR_ENABLE_LEGACY_GATEWAY_TESTS"',
        "Return whether legacy API gateway contract coverage is explicitly enabled.",
        'base_url="http://localhost:5000"',
    ),
    "tests/contracts/consumers/test_api_gateway_contracts.py": (
        "Legacy consumer contract tests: API Gateway -> All Services.",
        "retired standalone gateway",
        "Legacy API gateway contract coverage is disabled by default.",
    ),
    "tests/contracts/providers/test_agent_provider.py": (
        "the contracts defined by its consumers (Orchestrator, legacy API Gateway).",
        "Legacy API gateway contract coverage is disabled by default.",
    ),
    "tests/contracts/providers/test_orchestrator_provider.py": (
        "the contracts defined by its consumers (Web UI, legacy API Gateway).",
        "Legacy API gateway contract coverage is disabled by default.",
    ),
    "tests/contracts/pact_broker/setup.sh": (
        "Legacy standalone API gateway contract coverage is opt-in only.",
        "BR_KG_URL=http://localhost:5000",
        "BR_ENABLE_LEGACY_GATEWAY_TESTS=0",
        "Optional legacy standalone gateway compatibility surface:",
    ),
    "tests/unit/api_gateway/test_job_submission.py": (
        "Legacy api_gateway compatibility tests for job submission helpers.",
        "Legacy api_gateway compatibility coverage is disabled by default.",
    ),
    "tests/unit/services/gateway/test_br_kg_proxy.py": (
        "Legacy gateway compatibility tests for the retired BR-KG proxy routes.",
        "Legacy gateway compatibility coverage is disabled by default.",
    ),
    "tests/integration/test_gateway_proxy_failopen.py": (
        "Legacy integration coverage for the retired standalone API gateway.",
        "Legacy api_gateway compatibility coverage is disabled by default.",
    ),
    "docs/standards/API_VERSIONING.md": (
        "The legacy standalone `api_gateway` Python package can also inject",
        "No standalone reverse-proxy config is shipped in the public tree.",
    ),
    "scripts/services/run_gateway.sh": (
        "scripts/services/run_gateway.sh has been retired.",
        "Gateway is no longer part of the active local service topology.",
    ),
}

ACTIVE_FORBIDDEN_SUBSTRINGS = {
    "AGENTS.md": (
        "`services/gateway/`",
        "`services/api_gateway/`",
    ),
    "README.md": (
        "`scripts/services/run_gateway.sh` is retired and exits with guidance.",
        "`src/brain_researcher/services/gateway/` is a legacy single-port compatibility",
        "`src/brain_researcher/services/api_gateway/` is the older full-gateway",
    ),
    "src/brain_researcher/services/orchestrator/README.md": (
        "single-port compatibility gateway",
        "services/api_gateway/legacy",
        "Legacy gateway launcher",
    ),
    "src/brain_researcher/services/orchestrator/__init__.py": ("Unified API gateway",),
    "src/brain_researcher/services/orchestrator/app_factory.py": (
        "gateway consistency",
    ),
    "src/brain_researcher/services/orchestrator/kg_evidence_service.py": (
        "either gateway or direct BR-KG",
    ),
    "src/brain_researcher/services/orchestrator/job_store_factory.py": (
        "gateway deployments",
    ),
    "src/brain_researcher/services/orchestrator/main_enhanced.py": (
        "same value as gateway",
    ),
    "src/brain_researcher/services/agent/asgi.py": ("gateway/reverse-proxy",),
    "src/brain_researcher/services/agent/job_service.py": ("In gateway deployments",),
    "src/brain_researcher/services/agent/kg_resolution.py": ("API gateway code.",),
    "docs/telemetry_enablement.md": (
        "legacy Orchestrator sidecar",
        "or gateway URL",
    ),
    "tests/performance/k6/README.md": (
        "Main API gateway and job orchestration",
        "Port 5001",
    ),
    "tests/performance/k6/validate-setup.sh": (
        "Main API gateway and job orchestration service",
        "http://localhost:5001",
    ),
    "docs/specs/tool-selection-gateway-ws.md": (
        "single-port `gateway` service is the canonical runtime path",
        "gateway aggregates",
        "Dev gateway (single-port, local only)",
        "gateway parses cookie",
        "active gateway surfaces",
    ),
}

UPDATED_REQUIRED_SUBSTRINGS = {
    "docs/specs/tool-selection-gateway-ws.md": (
        "active split-service surfaces",
        "Web UI + Agent + Orchestrator + BR-KG",
        "### Dev split-services",
        "browser-facing layer parses cookie/session",
    ),
    "tests/performance/k6/README.md": (
        "**Orchestrator Service** (Port 3001) - Job orchestration and analysis APIs",
        "**BR-KG Service** (Port 5000) - Knowledge graph and data APIs",
    ),
    "src/brain_researcher/services/br_kg/api/graph_api.py": (
        "This unified API combines the best features from earlier BR-KG API variants:",
        "retired standalone predecessor",
    ),
    "tests/performance/k6/validate-setup.sh": (
        'BR_KG_URL=${BR_KG_URL:-"http://localhost:5000"}',
        "Job orchestration and analysis API service",
    ),
}


def test_legacy_gateway_surfaces_remain_explicitly_documented() -> None:
    for relpath, required in LEGACY_REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in required:
            assert (
                needle in text
            ), f"Missing expected legacy text in {relpath}: {needle}"


def test_active_surfaces_do_not_treat_gateway_as_current_runtime() -> None:
    for relpath, forbidden in ACTIVE_FORBIDDEN_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in forbidden:
            assert (
                needle not in text
            ), f"Found stale gateway text in {relpath}: {needle}"


def test_updated_active_surfaces_use_split_service_language() -> None:
    for relpath, required in UPDATED_REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in required:
            assert (
                needle in text
            ), f"Missing expected updated text in {relpath}: {needle}"
