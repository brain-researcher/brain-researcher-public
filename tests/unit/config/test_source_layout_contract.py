from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_SUBSTRINGS = {
    "AGENTS.md": (
        "`src/brain_researcher/`: canonical Python package",
        "`apps/web-ui/`: Next.js frontend",
        "`br serve agent|kg|web [-p PORT]`",
        "`br serve agent|kg|web|orchestrator|mcp [-p PORT]`",
    ),
    "docs/OPERATIONS.md": (
        # README rewrite (commit 0f356bcbe) moved verbatim repo-shape and
        # service-launch snippets from README.md into the operations guide.
        # Keep the source-layout contract anchored at the canonical location.
        "br serve web",
        "BR_AGENT_URL=http://127.0.0.1:8000",
        "BR_KG_URL=http://127.0.0.1:5000",
    ),
    # CLAUDE.md is intentionally a redirect to AGENTS.md ("Rule:
    # write repository instructions into AGENTS.md instead") — its
    # required-substring contract is consolidated into the AGENTS.md
    # block above.
    "scripts/services/start_services.sh": (
        'start_service "agent" 8000 "http://127.0.0.1:8000/health" 45 \\',
        'start_service "mcp" 7000 "http://127.0.0.1:7000/healthz" 45 \\',
        "br serve agent --host 0.0.0.0 --port 8000",
        "env BR_MCP_HOST=0.0.0.0 BR_MCP_PORT=7000 bash scripts/mcp/start_http_local.sh",
        'start_service "kg" 5000 "http://127.0.0.1:5000/health" 45 \\',
        "br serve kg --host 0.0.0.0 --port 5000",
    ),
}

FORBIDDEN_SUBSTRINGS = {
    "AGENTS.md": (
        "`brain_researcher/`: main package",
        "new modules live under `brain_researcher/`",
        "`agent/`, `br_kg/`, `web_ui/`",
        "`br serve agent|kg|ui [-p PORT]`",
        "`br serve agent|kg|web|orchestrator|gateway [-p PORT]`",
    ),
    "README.md": (
        "Frontend env for local dev (services/web_ui/.env.local):",
        "├── brain_researcher/     # Main package (like Biomni)",
        "│   │   └── web_ui/      # Next.js interface",
        "br serve ui                        # Dashboard UI on port 8050",
    ),
    "CLAUDE.md": (
        "black brain_researcher/ tests/",
        "ruff check brain_researcher/ --fix",
        "mypy brain_researcher/ --strict",
        "isort brain_researcher/ tests/",
        "`brain_researcher/cli/`",
        "`brain_researcher/services/`",
        "`brain_researcher/services/agent/`",
        "`brain_researcher/services/br_kg/`",
        "`brain_researcher/core/analysis/`",
        "br serve ui         # Dashboard on port 8050",
        "`gateway/`: legacy single-port compatibility gateway",
        "`api_gateway/`: legacy full-gateway compatibility assets",
    ),
    "scripts/services/start_services.sh": (
        "python brain_researcher/services/br_kg/app.py",
        "npm run start",
        "Agent-API",
        'start_service "Gateway" 8000 "http://127.0.0.1:8000/health" 45 \\',
        "br serve gateway --host 0.0.0.0 --port 8000",
    ),
}


def test_active_guidance_files_use_canonical_source_tree_paths() -> None:
    for relpath, expected_substrings in REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in expected_substrings:
            assert needle in text, f"Missing expected text in {relpath}: {needle}"


def test_active_guidance_files_do_not_reintroduce_stale_source_tree_paths() -> None:
    for relpath, forbidden_substrings in FORBIDDEN_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in forbidden_substrings:
            assert needle not in text, f"Found stale guidance in {relpath}: {needle}"


def test_top_level_legacy_brain_researcher_tree_has_no_python_sources() -> None:
    legacy_root = REPO_ROOT / "brain_researcher"
    legacy_py_files = sorted(
        str(path.relative_to(REPO_ROOT)) for path in legacy_root.rglob("*.py")
    )
    assert legacy_py_files == []

    legacy_pkg_markers = sorted(
        str(path.relative_to(REPO_ROOT)) for path in legacy_root.rglob("__init__.py")
    )
    assert legacy_pkg_markers == []
