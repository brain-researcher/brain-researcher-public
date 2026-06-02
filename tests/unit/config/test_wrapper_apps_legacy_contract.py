from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_SUBSTRINGS = {
    "apps/README.md": ("`web-ui/`: active Next.js web application",),
}

FORBIDDEN_SUBSTRINGS = {
    "apps/README.md": (
        "`agent/`: legacy module-wrapper shim for the Agent service",
        "`orchestrator/`: legacy module-wrapper shim for the Orchestrator service",
        "`br_kg/`: legacy module-wrapper shim for the BR-KG service",
        "`mcp/`: legacy module-wrapper shim for the MCP service",
        "`agent/`: Agent service wrapper and docs",
        "`orchestrator/`: Orchestrator service wrapper and docs",
        "`br_kg/`: BR-KG service wrapper and docs",
        "`mcp/`: MCP service wrapper and docs",
    ),
}

REMOVED_WRAPPER_FILES = (
    "apps/agent/README.md",
    "apps/agent/main.py",
    "apps/mcp/README.md",
    "apps/mcp/main.py",
    "apps/br_kg/README.md",
    "apps/br_kg/main.py",
    "apps/orchestrator/README.md",
    "apps/orchestrator/main.py",
)
REMOVED_WRAPPER_DIRS = (
    "apps/agent",
    "apps/mcp",
    "apps/br_kg",
    "apps/orchestrator",
)


def test_apps_tree_only_advertises_web_ui_as_active_app() -> None:
    for relpath, required in REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in required:
            assert (
                needle in text
            ), f"Missing expected wrapper-app text in {relpath}: {needle}"


def test_wrapper_apps_do_not_read_as_active_entrypoints() -> None:
    for relpath, forbidden in FORBIDDEN_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in forbidden:
            assert (
                needle not in text
            ), f"Found stale wrapper-app text in {relpath}: {needle}"


def test_wrapper_app_files_are_removed_from_tracked_surface() -> None:
    for relpath in REMOVED_WRAPPER_FILES:
        assert not (
            REPO_ROOT / relpath
        ).exists(), f"Legacy wrapper file still exists: {relpath}"


def test_wrapper_app_dirs_are_removed_from_apps_tree() -> None:
    for relpath in REMOVED_WRAPPER_DIRS:
        assert not (
            REPO_ROOT / relpath
        ).exists(), f"Legacy wrapper dir still exists: {relpath}"
