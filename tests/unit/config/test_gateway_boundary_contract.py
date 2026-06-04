from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

LEGACY_REQUIRED_SUBSTRINGS = {
    "src/brain_researcher/cli/commands/services/gateway_launcher.py": (
        "Legacy launcher for the retired single-port gateway surface.",
        "Gateway runtime is retired.",
        "./scripts/services/start_services.sh",
    ),
    "src/brain_researcher/services/api_gateway/__init__.py": (
        "Legacy standalone API gateway compatibility surface.",
        "canonical Python owner now lives under `brain_researcher.legacy.api_gateway`",
        'API_GATEWAY_STATUS = "legacy_compatibility"',
        '__description__ = "Legacy standalone API gateway compatibility surface"',
        '"name": "Brain Researcher Legacy API Gateway"',
    ),
    "tests/unit/api_gateway/test_job_submission.py": (
        "Legacy api_gateway compatibility tests for job submission helpers.",
        "Legacy api_gateway compatibility coverage is disabled by default.",
    ),
    "tests/unit/services/gateway/test_br_kg_proxy.py": (
        "Legacy gateway compatibility tests for the retired BR-KG proxy routes.",
        "Legacy gateway compatibility coverage is disabled by default.",
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
    "tests/performance/k6/validate-setup.sh": (
        "Main API gateway and job orchestration service",
        "http://localhost:5001",
    ),
}

UPDATED_REQUIRED_SUBSTRINGS = {
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
