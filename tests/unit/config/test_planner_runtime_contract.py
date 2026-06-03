from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(relpath: str) -> str:
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


def test_active_planner_runtime_surfaces_are_catalog_only() -> None:
    web_service = _read("src/brain_researcher/services/agent/web_service.py")
    orchestrator = _read("src/brain_researcher/services/orchestrator/main_enhanced.py")
    models = _read("src/brain_researcher/services/shared/planner/models.py")

    assert "Active planner runtime only supports 'catalog'." in web_service
    assert "Active planner runtime only supports 'catalog'." in orchestrator
    assert "Only 'catalog' is supported" in models

    assert "get_tool_spec(" not in web_service
    assert "load_tool_catalog(" not in web_service
    assert 'if planner_mode == "legacy":' not in web_service
    assert "Must be 'legacy' or 'catalog'." not in web_service
    assert 'if mode not in ["legacy", "catalog"]' not in orchestrator
    assert "Planner mode: 'legacy' or 'catalog'" not in orchestrator
    assert "Planner mode: 'legacy' for template-based" not in models
    assert 'mode: Optional[Literal["catalog"]]' in models


def test_catalog_loader_retains_internal_legacy_merge_compatibility() -> None:
    catalog_loader = _read("src/brain_researcher/services/agent/planner/catalog_loader.py")

    assert "legacy_tool_to_capability" in catalog_loader
    assert "BR_PLANNER_INCLUDE_LEGACY" in catalog_loader
    assert "BR_PLANNER_MERGE_LEGACY" not in catalog_loader
    assert "load_tool_catalog()" in catalog_loader


def test_active_planner_docs_no_longer_advertise_legacy_runtime_mode() -> None:
    catalog_readme = _read("docs/catalog_README.md")

    assert "default: `legacy`" not in catalog_readme
    assert "BR_PLANNER_SOURCE=legacy" not in catalog_readme
    assert "legacy` (templates)" not in catalog_readme
    assert "Active runtime planner mode" in catalog_readme
