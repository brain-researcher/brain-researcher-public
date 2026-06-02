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
    "docs/development/planner_catalog.md": (
        "src/brain_researcher/services/agent/planner/catalog_loader.py",
        "src/brain_researcher/services/shared/planner/models.py",
    ),
    "docs/catalog_README.md": (
        "src/brain_researcher/services/shared/planner/models.py",
        "../src/brain_researcher/services/agent/planner/catalog_loader.py",
    ),
    "docs/services/br-kg/kg_tool_schema.md": (
        "src/brain_researcher/services/br_kg/loader/tools_catalog_loader.py",
        "src/brain_researcher/cli/commands/br_kg_ingest.py",
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
    "docs/getting-started/configuration.md": ("# src/brain_researcher/config/",),
    "docs/standards/invariants.md": (
        "src/brain_researcher/services/br_kg/graph/neo4j_graph_database.py:79-84",
    ),
    "docs/standards/MATCHING_IMPLEMENTATION.md": (
        "src/brain_researcher/services/br_kg/matching/node_matcher.py",
    ),
    "docs/archive/TOOL_DISCOVERY_ENHANCEMENT_PLAN.md": (
        "src/brain_researcher/services/tools/spec.py",
        "src/brain_researcher/services/tools/args_resolver.py",
        "src/brain_researcher/services/agent/web_service.py",
    ),
    "docs/archive/TOOL_DISCOVERY_IMPLEMENTATION_SUMMARY.md": (
        "/src/brain_researcher/services/tools/spec.py",
        "/src/brain_researcher/services/tools/args_resolver.py",
        "/src/brain_researcher/services/agent/web_service.py",
        "the originally proposed standalone `nilearn_enhanced.py` and `nilearn_enhanced_part2.py` module split is not present in the current tree",
    ),
    "docs/standards/README.md": (
        "src/brain_researcher/services/br_kg/schemas/",
        "src/brain_researcher/services/br_kg/mappings/",
        "configs/legacy/mappings/task_synonyms.yaml",
        "python scripts/validation/validate_standards.py",
        "cat validation_report.json | jq '.summary'",
        "The active repo CI workflow is `.github/workflows/ci.yml`",
        "There is no dedicated GitHub Actions standards workflow checked in right now.",
        "gh run list --limit 5",
    ),
    "docs/PRD/prd_o2_kg_service.md": (
        "src/brain_researcher/services/br_kg/models/niclip.py",
        "src/brain_researcher/services/br_kg/models/fmri_text_alignment.py",
        "src/brain_researcher/services/tools/br_kg_tools.py",
    ),
    "docs/PRD/prd_o3_model_architecture.md": (
        "src/brain_researcher/services/br_kg/models/niclip.py",
        "src/brain_researcher/services/br_kg/models/fmri_text_alignment.py",
        "src/brain_researcher/services/tools/br_kg_tools.py",
        "from brain_researcher.services.br_kg.models.niclip import NiCLIPModel",
    ),
    "docs/br-kg/NICLIP_COMPLETE_INTEGRATION.md": (
        "src/brain_researcher/services/tools/br_kg_tools.py",
        "src/brain_researcher/services/br_kg/etl/strength_calculator.py",
        "src/brain_researcher/services/br_kg/etl/mappers/cross_source_linker.py",
        "src/brain_researcher/services/br_kg/etl/mappers/niclip_spatial_mapper.py",
        "src/brain_researcher/services/br_kg/etl/mappers/niclip_concept_hierarchy.py",
    ),
    "docs/archive/TODO.md": (
        "src/brain_researcher/services/tools/tool_registry.py",
        "src/brain_researcher/services/tools/grandmaster_tools.py",
    ),
    "scripts/tools/ontologies/build_onvoc_mapping_rules.py": (
        'fallback=Path("configs/legacy/mappings/onvoc_crosswalk.yaml")',
    ),
    "docs/architecture/H7_H8_cross_modal_glue.md": (
        "src/brain_researcher/services/tools/coreg_*.py",
        "src/brain_researcher/services/tools/auto.py",
        "src/brain_researcher/services/agent/web_service.py",
    ),
    "docs/archive/cli_migration_guide.md": (
        "scripts/br-kg/init_database.py",
        "scripts/br-kg/optimize_db.py",
        "scripts/br-kg/merge_databases.py",
    ),
    "docs/services/br-kg/node_label_linker_integration.md": (
        "/scripts/br-kg/link_duplicate_nodes.py",
        "/scripts/br-kg/init_database.py",
        "/scripts/br-kg/load_glmfitlins_to_kg.py",
        "/scripts/br-kg/load_openneuro_fitlins.py",
        "/scripts/br-kg/scheduled_cross_linker.py",
        "/scripts/br-kg/setup_cron_linker.sh",
        "/scripts/br-kg/ttl_edge_cleanup.py",
        "/scripts/br-kg/setup_cron_ttl_cleanup.sh",
    ),
    "docs/services/br-kg/EDGE_INTEGRATION_SUMMARY.md": (
        "scripts/br-kg/integrate_coordinate_relationships.py",
        "scripts/br-kg/integrate_study_concept_relationships.py",
        "scripts/br-kg/integrate_ontology_relationships.py",
        "scripts/br-kg/integrate_statistical_maps.py",
        "scripts/br-kg/integrate_subject_relationships.py",
        "scripts/br-kg/init_database.py",
    ),
    "docs/archive/services/orchestrator/UI_CONTRACTS_UPDATE.md": (
        "/src/brain_researcher/services/orchestrator/models.py",
        "/src/brain_researcher/services/orchestrator/main_enhanced.py",
    ),
    "docs/br-kg/SPATIAL_SEMANTIC_MAPPING_GUIDE.md": (
        "scripts/br-kg/create_in_region_edges.py",
        "src/brain_researcher/services/br_kg/spatial/create_in_region_edges.py",
        "src/brain_researcher/services/br_kg/etl/loaders/niclip_loader.py",
        "scripts/br-kg/calculate_strength.py",
        "src/brain_researcher/services/br_kg/scoring/calculate_strength.py",
        "tests/integration/mappers/test_spatial_semantic_mapping.py",
        "cd /path/to/brain_researcher",
        "src/brain_researcher/services/br_kg/etl/loaders/",
        "scripts/br-kg/",
        "src/brain_researcher/services/br_kg/spatial/",
        "heuristic concept-region association builder.",
        "direct model-weight extraction is still future work",
        "RUN_SPATIAL_SEMANTIC_MAPPING=1",
        "Direct trained-weight extraction is not implemented yet",
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
    "scripts/root_legacy/check_env.py": (
        "REPO_ROOT = Path(__file__).resolve().parents[2]",
        '"Agent .env": "src/brain_researcher/services/agent/.env"',
        '"BR-KG .env": "src/brain_researcher/services/br_kg/.env"',
        'print("  br serve web     # Next.js Web UI")',
    ),
    "docs/specs/dataset_task_unmatched_report.md": (
        "python scripts/br-kg/create_dataset_task_relationships.py",
        "python scripts/br-kg/build_dataset_task_review_pack.py",
        "python scripts/br-kg/build_dataset_task_decision_pack.py",
    ),
    "docs/planning/resume_rebuild_runbook.md": (
        "python scripts/br-kg/materialize_brainregion_hierarchy.py",
    ),
    "src/brain_researcher/services/tools/niwrap/boutiques.py": (
        "src/brain_researcher/services/tools/niwrap/boutiques.py",
    ),
}

FORBIDDEN_SUBSTRINGS = {
    "docs/development/planner_catalog.md": (
        "`brain_researcher/services/agent/planner/catalog_loader.py`",
        "`brain_researcher/services/shared/planner/models.py`",
    ),
    "docs/catalog_README.md": (
        "`brain_researcher/services/shared/planner/models.py`",
        "../brain_researcher/services/agent/planner/catalog_loader.py",
    ),
    "docs/services/br-kg/kg_tool_schema.md": (
        "`brain_researcher/services/br_kg/loader/tools_catalog_loader.py`",
        "`brain_researcher/cli/commands/br_kg_ingest.py`",
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
    "docs/getting-started/configuration.md": ("# brain_researcher/config.py",),
    "docs/standards/invariants.md": (
        "`brain_researcher/services/br_kg/graph/neo4j_graph_database.py:79-84`",
    ),
    "docs/standards/MATCHING_IMPLEMENTATION.md": (
        "**`brain_researcher/services/br_kg/matching/node_matcher.py`**",
    ),
    "docs/archive/TOOL_DISCOVERY_ENHANCEMENT_PLAN.md": (
        "`brain_researcher/services/agent/tools/spec.py`",
        "`brain_researcher/services/agent/tools/args_resolver.py`",
        "`brain_researcher/services/agent/web_service.py`",
    ),
    "docs/archive/TOOL_DISCOVERY_IMPLEMENTATION_SUMMARY.md": (
        "/brain_researcher/services/agent/tools/spec.py",
        "/brain_researcher/services/agent/tools/args_resolver.py",
        "/brain_researcher/services/agent/tools/nilearn_enhanced.py",
        "/brain_researcher/services/agent/tools/nilearn_enhanced_part2.py",
        "`/brain_researcher/services/agent/web_service.py`",
    ),
    "docs/standards/README.md": (
        "`brain_researcher/services/br_kg/schemas/`",
        "`brain_researcher/services/br_kg/mappings/`",
        "with open('mappings/task_synonyms.yaml') as f:",
        "vim mappings/task_synonyms.yaml",
        "python scripts/generate_validation_report.py",
        "All pull requests modifying data/ingestion code",
        "Daily scheduled runs",
        "GitHub Actions workflow runs on:",
        "gh run list --workflow=validate-standards.yml",
    ),
    "docs/PRD/prd_o2_kg_service.md": (
        "`brain_researcher/models/niclip.py`",
        "`brain_researcher/services/agent/tools/br_kg_tools.py`",
    ),
    "docs/PRD/prd_o3_model_architecture.md": (
        "`brain_researcher/models/niclip.py`",
        "`brain_researcher/models/fmri_text_alignment.py`",
        "`brain_researcher/services/agent/tools/br_kg_tools.py`",
        "from brain_researcher.models.niclip import NiCLIPModel",
    ),
    "docs/br-kg/NICLIP_COMPLETE_INTEGRATION.md": (
        "`brain_researcher/services/agent/tools/br_kg_tools.py`",
        "`brain_researcher/services/br_kg/etl/strength_calculator.py`",
        "`brain_researcher/services/br_kg/etl/mappers/cross_source_linker.py`",
        "`brain_researcher/services/br_kg/etl/mappers/niclip_spatial_mapper.py`",
        "`brain_researcher/services/br_kg/etl/mappers/niclip_concept_hierarchy.py`",
    ),
    "docs/archive/TODO.md": (
        "`brain_researcher/services/tools/tool_registry.py`",
        "`brain_researcher/services/tools/grandmaster_tools.py`",
    ),
    "scripts/tools/ontologies/build_onvoc_mapping_rules.py": (
        'fallback=Path("brain_researcher/services/br_kg/mappings/onvoc_crosswalk.yaml")',
    ),
    "docs/architecture/H7_H8_cross_modal_glue.md": (
        "`brain_researcher/services/agent/tools/coreg_*.py`",
        "`brain_researcher/services/agent/tools/auto.py`",
        "`brain_researcher/services/agent/web_service.py`",
    ),
    "docs/archive/cli_migration_guide.md": (
        _legacy_rel_service_script_path("init_database.py"),
        _legacy_rel_service_script_path("optimize_db.py"),
        _legacy_rel_service_script_path("merge_databases.py"),
    ),
    "docs/services/br-kg/node_label_linker_integration.md": (
        _legacy_service_script_path("link_duplicate_nodes.py"),
        _legacy_service_script_path("init_database.py"),
        _legacy_abs_root_script_path("load_glmfitlins_to_kg.py"),
        _legacy_abs_root_script_path("load_openneuro_fitlins.py"),
        _legacy_service_script_path("scheduled_cross_linker.py"),
        _legacy_service_script_path("setup_cron_linker.sh"),
        _legacy_service_script_path("ttl_edge_cleanup.py"),
        _legacy_service_script_path("setup_cron_ttl_cleanup.sh"),
    ),
    "docs/services/br-kg/EDGE_INTEGRATION_SUMMARY.md": (
        _legacy_root_script_path("integrate_coordinate_relationships.py"),
        _legacy_root_script_path("integrate_study_concept_relationships.py"),
        _legacy_root_script_path("integrate_ontology_relationships.py"),
        _legacy_root_script_path("integrate_statistical_maps.py"),
        _legacy_root_script_path("integrate_subject_relationships.py"),
        _legacy_root_script_path("init_database.py"),
    ),
    "docs/archive/services/orchestrator/UI_CONTRACTS_UPDATE.md": (
        "`/brain_researcher/services/orchestrator/models.py`",
        "`/brain_researcher/services/orchestrator/main_enhanced.py`",
    ),
    "docs/br-kg/SPATIAL_SEMANTIC_MAPPING_GUIDE.md": (
        "src/brain_researcher/services/br_kg/scripts/create_in_region_edges.py",
        "`brain_researcher/services/br_kg/scripts/create_in_region_edges.py`",
        "`brain_researcher/services/br_kg/etl/strength_calculator.py`",
        "python -m brain_researcher.services.br_kg.scripts.create_in_region_edges",
        "python -m brain_researcher.services.br_kg.etl.strength_calculator",
        "**Script**: `test_spatial_semantic_mapping.py`",
        "python test_spatial_semantic_mapping.py --test all",
        "python test_spatial_semantic_mapping.py --test coord --coord-limit 50",
        "python test_spatial_semantic_mapping.py --test niclip",
        "python test_spatial_semantic_mapping.py --test strength",
        "cd /data/ECoG-foundation-model/mnndl_temp/brain_researcher",
        "- Utility scripts in `src/brain_researcher/services/br_kg/scripts/`",
        "- Spatial utilities in `core/utils/spatial.py`",
        "using NiCLIP's learned associations.",
        "Currently uses synthetic associations for demonstration",
        "Real implementation would load trained PyTorch models",
    ),
    "scripts/services/br-kg/start_api_correct.sh": (
        "/data/ECoG-foundation-model/mnndl_temp/brain_researcher/services/br_kg",
        "python -m api.graph_api",
    ),
    "scripts/services/br-kg/restart_api.sh": (
        "/data/ECoG-foundation-model/mnndl_temp/brain_researcher/services/br_kg",
        "python -m api.graph_api",
    ),
    "scripts/root_legacy/check_env.py": (
        '"Agent .env": "brain_researcher/services/agent/.env"',
        '"BR-KG .env": "brain_researcher/services/br_kg/.env"',
        'print("  br serve ui      # Dashboard")',
    ),
    "docs/specs/dataset_task_unmatched_report.md": (
        "python brain_researcher/services/br_kg/scripts/create_dataset_task_relationships.py \\",
        "python brain_researcher/services/br_kg/scripts/build_dataset_task_review_pack.py \\",
        "python brain_researcher/services/br_kg/scripts/build_dataset_task_decision_pack.py",
    ),
    "docs/planning/resume_rebuild_runbook.md": (
        "python -m brain_researcher.services.br_kg.scripts.materialize_brainregion_hierarchy",
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
