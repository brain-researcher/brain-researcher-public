from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

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


def test_apps_tree_only_contains_web_ui_as_an_application_directory() -> None:
    apps_root = REPO_ROOT / "apps"
    app_directories = {path.name for path in apps_root.iterdir() if path.is_dir()}

    assert app_directories == {"web-ui"}
    assert (apps_root / "web-ui/package.json").is_file()


def test_removed_apps_index_is_not_required_as_runtime_documentation() -> None:
    assert not (REPO_ROOT / "apps/README.md").exists()


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
