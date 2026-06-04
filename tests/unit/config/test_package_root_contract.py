from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _legacy_service_script_path(script_name: str) -> str:
    return "/services/br_kg" + "/scripts/" + script_name


def _legacy_rel_service_script_path(script_name: str) -> str:
    return "services/br_kg" + "/scripts/" + script_name


def _legacy_root_script_path(script_name: str) -> str:
    return "scripts" + "/" + script_name


def _legacy_abs_root_script_path(script_name: str) -> str:
    return "/" + _legacy_root_script_path(script_name)


REQUIRED_SUBSTRINGS = {
    "docs/catalog_README.md": (
        "src/brain_researcher/services/shared/planner/models.py",
        "../src/brain_researcher/services/agent/planner/catalog_loader.py",
    ),
    "scripts/ci/generate_resources_schema.py": (
        "src/brain_researcher/services/shared/planner/models.py",
    ),
    "scripts/tools/generate_capabilities_from_agent_tools.py": (
        'Path("src/brain_researcher/services/tools")',
    ),
    "scripts/tools/migration/suggest_niwrap_aliases.py": (
        'pathlib.Path("src/brain_researcher/services/tools")',
    ),
    "scripts/dev/update_requirements_for_graph_viz.py": (
        "src/brain_researcher/services/br_kg/requirements.txt",
    ),
    "scripts/tools/ontologies/build_onvoc_mapping_rules.py": (
        'fallback=Path("configs/legacy/mappings/onvoc_crosswalk.yaml")',
    ),
    "scripts/services/br-kg/start_api_correct.sh": (
        'REPO_ROOT=$(cd -- "$SCRIPT_DIR/../../.." && pwd)',
        'export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"',
        "python -m brain_researcher.services.br_kg.api.graph_api",
    ),
    "scripts/services/br-kg/restart_api.sh": (
        'REPO_ROOT=$(cd -- "$SCRIPT_DIR/../../.." && pwd)',
        'export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"',
        "python -m brain_researcher.services.br_kg.api.graph_api",
    ),
    "src/brain_researcher/services/tools/niwrap/boutiques.py": (
        "src/brain_researcher/services/tools/niwrap/boutiques.py",
    ),
}

FORBIDDEN_SUBSTRINGS = {
    "docs/catalog_README.md": (
        "`brain_researcher/services/shared/planner/models.py`",
        "../brain_researcher/services/agent/planner/catalog_loader.py",
    ),
    "scripts/ci/generate_resources_schema.py": (
        "`brain_researcher/services/shared/planner/models.py`",
    ),
    "scripts/tools/generate_capabilities_from_agent_tools.py": (
        'Path("brain_researcher/services/agent/tools")',
        'Path("brain_researcher/services/tools")',
    ),
    "scripts/tools/migration/suggest_niwrap_aliases.py": (
        'pathlib.Path("brain_researcher/services/tools")',
    ),
    "scripts/dev/update_requirements_for_graph_viz.py": (
        "pip install -r services/br_kg/requirements.txt",
    ),
    "scripts/tools/ontologies/build_onvoc_mapping_rules.py": (
        'fallback=Path("brain_researcher/services/br_kg/mappings/onvoc_crosswalk.yaml")',
    ),
    "scripts/services/br-kg/start_api_correct.sh": (
        "/data/ECoG-foundation-model/mnndl_temp/brain_researcher/services/br_kg",
        "python -m api.graph_api",
    ),
    "scripts/services/br-kg/restart_api.sh": (
        "/data/ECoG-foundation-model/mnndl_temp/brain_researcher/services/br_kg",
        "python -m api.graph_api",
    ),
    "src/brain_researcher/services/tools/niwrap/boutiques.py": (
        "This file is at: brain_researcher/services/tools/niwrap/boutiques.py",
    ),
}


def test_active_docs_and_scripts_use_src_package_root() -> None:
    for relpath, expected_substrings in REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in expected_substrings:
            assert needle in text, f"Missing expected text in {relpath}: {needle}"


def test_active_docs_and_scripts_do_not_reintroduce_legacy_package_paths() -> None:
    for relpath, forbidden_substrings in FORBIDDEN_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in forbidden_substrings:
            assert needle not in text, f"Found stale text in {relpath}: {needle}"
