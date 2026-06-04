from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_TEST_ROOT = (REPO_ROOT / "tests/unit/config").resolve()

RETIRED_ARCHIVE_RELOCATIONS = {
    "src/brain_researcher/services/agent/ui": "archive/legacy/agent_ui",
    "src/brain_researcher/services/br_kg/api/backup": "archive/legacy/br_kg_api_backup",
    "src/brain_researcher/services/br_kg/deployment": "archive/legacy/br_kg_deployment",
    "src/brain_researcher/services/agent/Dockerfile.langgraph": (
        "archive/legacy/agent_deployment/Dockerfile.langgraph"
    ),
    "src/brain_researcher/services/agent/langgraph.env": (
        "archive/legacy/agent_deployment/langgraph.env"
    ),
    "scripts/services/agent/setup_env.sh": (
        "archive/legacy/agent_deployment/setup_env.sh"
    ),
    "src/brain_researcher/services/agent/docker-compose.langgraph.yml": (
        "archive/legacy/agent_deployment/docker-compose.langgraph.yml"
    ),
    "configs/runtime/docker-compose.langgraph.yml": (
        "archive/legacy/agent_deployment/docker-compose.langgraph.yml"
    ),
    "src/brain_researcher/legacy/api_gateway/legacy/README.md": (
        "archive/legacy/api_gateway_deployment/README.md"
    ),
    "src/brain_researcher/legacy/api_gateway/legacy/Dockerfile": (
        "archive/legacy/api_gateway_deployment/Dockerfile"
    ),
    "src/brain_researcher/legacy/api_gateway/legacy/config.yaml": (
        "archive/legacy/api_gateway_deployment/config.yaml"
    ),
    "src/brain_researcher/services/api_gateway/legacy/README.md": (
        "archive/legacy/api_gateway_deployment/README.md"
    ),
    "src/brain_researcher/services/api_gateway/legacy/Dockerfile": (
        "archive/legacy/api_gateway_deployment/Dockerfile"
    ),
    "src/brain_researcher/services/api_gateway/legacy/config.yaml": (
        "archive/legacy/api_gateway_deployment/config.yaml"
    ),
    "src/brain_researcher/services/br_kg/Procfile": (
        "archive/legacy/br_kg_deployment/standalone/Procfile"
    ),
    "src/brain_researcher/services/br_kg/nixpacks.toml": (
        "archive/legacy/br_kg_deployment/standalone/nixpacks.toml"
    ),
    "src/brain_researcher/services/br_kg/railway.toml": (
        "archive/legacy/br_kg_deployment/standalone/railway.toml"
    ),
    "src/brain_researcher/services/br_kg/railway_full.toml": (
        "archive/legacy/br_kg_deployment/standalone/railway_full.toml"
    ),
    "src/brain_researcher/services/br_kg/.railwayignore": (
        "archive/legacy/br_kg_deployment/standalone/.railwayignore"
    ),
    "src/brain_researcher/services/br_kg/CNAME_SETUP_GUIDE.md": (
        "archive/legacy/br_kg_deployment/standalone/CNAME_SETUP_GUIDE.md"
    ),
    "src/brain_researcher/services/br_kg/SETUP_INSTRUCTIONS.md": (
        "archive/legacy/br_kg_deployment/standalone/SETUP_INSTRUCTIONS.md"
    ),
    "src/brain_researcher/services/br_kg/RESTART_API_INSTRUCTIONS.md": (
        "archive/legacy/br_kg_deployment/standalone/RESTART_API_INSTRUCTIONS.md"
    ),
    "src/brain_researcher/services/br_kg/example_queries.py": (
        "archive/legacy/br_kg_deployment/standalone/example_queries.py"
    ),
    "src/brain_researcher/services/br_kg/requirements_loose.txt": (
        "archive/legacy/br_kg_deployment/standalone/requirements_loose.txt"
    ),
    "src/brain_researcher/services/br_kg/requirements_deployment.txt": (
        "archive/legacy/br_kg_deployment/standalone/requirements_deployment.txt"
    ),
    "src/brain_researcher/services/br_kg/requirements_deployment_full.txt": (
        "archive/legacy/br_kg_deployment/standalone/requirements_deployment_full.txt"
    ),
    "src/brain_researcher/services/br_kg/requirements_railway.txt": (
        "archive/legacy/br_kg_deployment/standalone/requirements_railway.txt"
    ),
}

RELOCATED_PATHS = {
    "src/brain_researcher/tests/unit/agent/test_ui_api_coding_stream.py": (
        "tests/unit/agent/test_ui_api_coding_stream.py"
    ),
    "src/brain_researcher/services/br_kg/scripts": "scripts/br-kg",
    "src/brain_researcher/services/agent/launch_agent.py": (
        "scripts/root_legacy/launch_agent.py"
    ),
    "src/brain_researcher/services/agent/run_langgraph.py": (
        "scripts/root_legacy/run_langgraph.py"
    ),
    "src/brain_researcher/services/agent/debug_services.py": (
        "scripts/root_legacy/debug_services.py"
    ),
    "src/brain_researcher/services/agent/working_tools_demo.py": (
        "scripts/root_legacy/working_tools_demo.py"
    ),
    "src/brain_researcher/services/agent/demo_enhanced_features.py": (
        "scripts/root_legacy/demo_enhanced_features.py"
    ),
    "src/brain_researcher/services/agent/Dockerfile": (
        "infrastructure/docker/Dockerfile.agent"
    ),
    "src/brain_researcher/services/agent/pytest.ini": (
        "configs/testing/agent.pytest.ini"
    ),
    "src/brain_researcher/services/infrastructure/monitoring": (
        "infrastructure/monitoring/service_stack"
    ),
    "src/brain_researcher/services/communication/config/service_mesh.yaml": (
        "configs/runtime/service_mesh.yaml"
    ),
    "src/brain_researcher/services/orchestrator/Dockerfile": (
        "infrastructure/docker/Dockerfile.orchestrator"
    ),
    "src/brain_researcher/services/agent/tool_mappings.yaml": (
        "configs/catalog/tool_mappings.yaml"
    ),
    "src/brain_researcher/services/agent/tool_synonyms.yaml": (
        "configs/catalog/tool_synonyms.yaml"
    ),
    "src/brain_researcher/services/agent/resources/copilot_examples.json": (
        "configs/agent/copilot_examples.json"
    ),
    "src/brain_researcher/services/br_kg/Dockerfile": "Dockerfile",
    "src/brain_researcher/services/br_kg/etl/glmfitlins_ingest/neo4j-import.sh": (
        "scripts/br-kg/neo4j_import_glmfitlins.sh"
    ),
}
DISALLOWED_PACKAGE_RUNTIME_DATA = {
    "src/brain_researcher/data/feedback/feedback.db",
    "src/brain_researcher/services/agent/data/parameter_database.json",
    "src/brain_researcher/services/agent/data/plan_memory.db",
    "src/brain_researcher/services/orchestrator/data/orchestrator/credits.sqlite",
}
DISALLOWED_PACKAGE_RUNTIME_DIRS = {
    "src/brain_researcher/data/agent_outputs",
    "src/brain_researcher/services/agent/data",
    "src/brain_researcher/services/agent/data/agent_outputs",
    "src/brain_researcher/services/agent/data/runs",
    "src/brain_researcher/services/agent/data/uploads",
    "src/brain_researcher/services/orchestrator/data",
    "src/brain_researcher/services/orchestrator/data/agent_outputs",
    "src/brain_researcher/services/orchestrator/data/runs",
    "src/brain_researcher/services/orchestrator/data/run_cards",
    "src/brain_researcher/services/orchestrator/data/uploads",
    "src/brain_researcher/services/orchestrator/data/orchestrator",
    "src/brain_researcher/services/br_kg/data/neo4j",
}


def _cwd_relative_data_path(*parts: str) -> str:
    return "/".join(("data", *parts))


def _quoted_cwd_relative_data_paths(*parts: str) -> tuple[str, str]:
    relpath = _cwd_relative_data_path(*parts)
    return (f'"{relpath}"', f"'{relpath}'")


FORBIDDEN_CWD_RELATIVE_RUNTIME_DEFAULTS = {
    "src/brain_researcher/services/agent/telemetry.py": _quoted_cwd_relative_data_paths(
        "agent_outputs", "sessions"
    ),
    "src/brain_researcher/services/agent/usage_aggregator.py": _quoted_cwd_relative_data_paths(
        "agent_outputs", "sessions"
    ),
    "src/brain_researcher/services/agent/logging/migration.py": _quoted_cwd_relative_data_paths(
        "agent_outputs"
    ),
    "src/brain_researcher/services/agent/plan_memory.py": _quoted_cwd_relative_data_paths(
        "plan_memory.db"
    ),
    "src/brain_researcher/services/agent/utils/agent_output_collector.py": (
        "/app/brain_researcher/data/agent_outputs",
    ),
    "src/brain_researcher/services/orchestrator/feedback_repository.py": _quoted_cwd_relative_data_paths(
        "feedback"
    ),
    "src/brain_researcher/services/orchestrator/main_enhanced.py": (
        *_quoted_cwd_relative_data_paths("uploads", "chat"),
        *_quoted_cwd_relative_data_paths("run_cards"),
        *_quoted_cwd_relative_data_paths("orchestrator", "jobs.sqlite"),
    ),
    "src/brain_researcher/services/orchestrator/integration_endpoints.py": _quoted_cwd_relative_data_paths(
        "run_cards"
    ),
    "src/brain_researcher/services/orchestrator/job_store_factory.py": _quoted_cwd_relative_data_paths(
        "orchestrator", "jobs.sqlite"
    ),
    "src/brain_researcher/services/orchestrator/state_store.py": _quoted_cwd_relative_data_paths(
        "orchestrator", "state.sqlite"
    ),
    "src/brain_researcher/services/orchestrator/endpoints/credits.py": _quoted_cwd_relative_data_paths(
        "orchestrator", "credits.sqlite"
    ),
    "src/brain_researcher/services/orchestrator/endpoints/benchmark.py": _quoted_cwd_relative_data_paths(
        "orchestrator", "jobs.sqlite"
    ),
    "src/brain_researcher/services/orchestrator/studio_assistant_runtime.py": _quoted_cwd_relative_data_paths(
        "orchestrator", "state.sqlite"
    ),
    "src/brain_researcher/services/telemetry/storage.py": _quoted_cwd_relative_data_paths(
        "telemetry"
    ),
}

OLD_BR_KG_SCRIPTS_DIR = REPO_ROOT / "src/brain_researcher/services/br_kg/scripts"
NEW_BR_KG_SCRIPTS_DIR = REPO_ROOT / "scripts/br-kg"
OLD_NEUROMAPS_IMPORT = (
    "brain_researcher.services.br_kg.scripts.load_neuromaps_parcellations"
)
OLD_FETCH_NEUROMAPS_IMPORT = (
    "brain_researcher.services.br_kg.scripts.fetch_all_neuromaps"
)
OLD_BACKFILL_FAILED_ON_IMPORT = (
    "brain_researcher.services.br_kg.scripts.backfill_failed_on"
)
OLD_CALCULATE_STRENGTH_IMPORT = (
    "brain_researcher.services.br_kg.scripts.calculate_strength"
)
OLD_CREATE_IN_REGION_IMPORT = (
    "brain_researcher.services.br_kg.scripts.create_in_region_edges"
)
OLD_CREATE_IN_REGION_MASK_IMPORT = (
    "brain_researcher.services.br_kg.scripts.create_in_region_edges_mask"
)
OLD_OVERLAY_IMPORT = "brain_researcher.services.br_kg.scripts.overlay_statmaps_yeo17"
OLD_DOWNLOAD_OSF_IMPORT = (
    "brain_researcher.services.br_kg.scripts.download_osf_resources"
)
OLD_DATASET_TASK_REL_IMPORT = (
    "brain_researcher.services.br_kg.scripts.create_dataset_task_relationships"
)
OLD_CREATE_ACTIVATION_SCRIPT_IMPORT = "scripts.create_activation_edges"


def _should_skip_scan(path: Path, compatibility_root: Path) -> bool:
    resolved_path = path.resolve()
    if resolved_path == Path(__file__).resolve():
        return True
    if resolved_path.parent == compatibility_root:
        return True
    return resolved_path.is_relative_to(CONTRACT_TEST_ROOT)


def _tracked_paths_under(relpath: str) -> tuple[str, ...]:
    output = subprocess.check_output(
        ["git", "ls-files", "--", relpath],
        cwd=REPO_ROOT,
        text=True,
    )
    return tuple(line.strip() for line in output.splitlines() if line.strip())


def test_non_runtime_package_content_moves_to_canonical_roots() -> None:
    for old_relpath, new_relpath in RELOCATED_PATHS.items():
        old_path = REPO_ROOT / old_relpath
        new_path = REPO_ROOT / new_relpath
        assert new_path.exists(), f"Missing relocated path: {new_relpath}"
        assert (
            not old_path.exists()
        ), f"Legacy package path should be removed: {old_relpath}"


def test_retired_archive_legacy_targets_are_not_public_shipped() -> None:
    assert not _tracked_paths_under(
        "archive/legacy"
    ), "archive/legacy is an ignored local archive, not a public shipped surface."
    for old_relpath, retired_relpath in RETIRED_ARCHIVE_RELOCATIONS.items():
        assert not (
            REPO_ROOT / old_relpath
        ).exists(), f"Legacy package path should be removed: {old_relpath}"
        assert not _tracked_paths_under(
            retired_relpath
        ), f"Retired archive target should not be tracked: {retired_relpath}"


def test_package_internal_runtime_data_files_do_not_reappear() -> None:
    for relpath in DISALLOWED_PACKAGE_RUNTIME_DATA:
        assert not (
            REPO_ROOT / relpath
        ).exists(), (
            f"Package-internal runtime data should not live under src/: {relpath}"
        )


def test_package_internal_runtime_data_dirs_do_not_reappear() -> None:
    for relpath in DISALLOWED_PACKAGE_RUNTIME_DIRS:
        assert not (
            REPO_ROOT / relpath
        ).exists(), f"Package-internal runtime data directory should not live under src/: {relpath}"


def test_runtime_defaults_do_not_depend_on_current_working_directory_data() -> None:
    for (
        relpath,
        forbidden_substrings,
    ) in FORBIDDEN_CWD_RELATIVE_RUNTIME_DEFAULTS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in forbidden_substrings:
            assert needle not in text, (
                "Runtime defaults should resolve through the repo data root or an "
                f"explicit env var, not cwd-relative data paths: {relpath} -> {needle}"
            )


def test_tracked_service_tree_configs_are_limited_to_env_examples() -> None:
    output = subprocess.check_output(
        ["git", "ls-files", "src/brain_researcher/services/**"],
        cwd=REPO_ROOT,
        text=True,
    )
    tracked_config_paths = {
        line.strip()
        for line in output.splitlines()
        if line.strip().endswith((".yaml", ".yml", ".json", ".toml", ".ini", ".cfg"))
        or line.strip().endswith(".env.example")
    }
    allowed = {
        "src/brain_researcher/services/agent/.env.example",
        "src/brain_researcher/services/br_kg/.env.example",
        "src/brain_researcher/services/orchestrator/.env.example",
    }
    assert tracked_config_paths == allowed, (
        "Tracked repo-owned config files should live under configs/ or archive/, "
        f"not active service trees: {sorted(tracked_config_paths - allowed)}"
    )


def test_services_api_gateway_tree_is_reduced_to_package_marker() -> None:
    api_gateway_dir = REPO_ROOT / "src/brain_researcher/services/api_gateway"
    remaining_files = {
        str(path.relative_to(REPO_ROOT))
        for path in api_gateway_dir.iterdir()
        if path.is_file()
    }
    assert remaining_files == {
        "src/brain_researcher/services/api_gateway/__init__.py",
    }, (
        "services/api_gateway should only retain the package marker and README; "
        f"found extra files: {sorted(remaining_files)}"
    )


def test_old_br_kg_script_root_is_removed() -> None:
    assert not OLD_BR_KG_SCRIPTS_DIR.exists(), (
        "Legacy BR-KG script compatibility tree should be removed once active "
        "callers are migrated to scripts/br-kg."
    )


def test_canonical_br_kg_script_root_contains_relocated_scripts() -> None:
    canonical_script_names = {
        p.name for p in NEW_BR_KG_SCRIPTS_DIR.iterdir() if p.is_file()
    }
    assert "create_in_region_edges.py" in canonical_script_names
    assert "create_dataset_task_relationships.py" in canonical_script_names
    assert "materialize_brainregion_hierarchy.py" in canonical_script_names


def test_active_code_no_longer_imports_neuromaps_loader_from_legacy_script_namespace() -> (
    None
):
    active_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
    ]
    compatibility_root = OLD_BR_KG_SCRIPTS_DIR.resolve()
    offenders: list[str] = []

    for root in active_roots:
        for path in root.rglob("*.py"):
            if _should_skip_scan(path, compatibility_root):
                continue
            if OLD_NEUROMAPS_IMPORT in path.read_text():
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "Active code should import Neuromaps loader utilities from the runtime module, "
        f"not the legacy script namespace: {offenders}"
    )


def test_active_code_no_longer_imports_yeo17_overlay_from_legacy_script_namespace() -> (
    None
):
    active_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
    ]
    compatibility_root = OLD_BR_KG_SCRIPTS_DIR.resolve()
    offenders: list[str] = []

    for root in active_roots:
        for path in root.rglob("*.py"):
            if _should_skip_scan(path, compatibility_root):
                continue
            if OLD_OVERLAY_IMPORT in path.read_text():
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "Active code should import the Yeo17 overlay helper from the runtime module, "
        f"not the legacy script namespace: {offenders}"
    )


def test_active_code_no_longer_imports_osf_download_helpers_from_legacy_script_namespace() -> (
    None
):
    active_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
    ]
    compatibility_root = OLD_BR_KG_SCRIPTS_DIR.resolve()
    offenders: list[str] = []

    for root in active_roots:
        for path in root.rglob("*.py"):
            if _should_skip_scan(path, compatibility_root):
                continue
            if OLD_DOWNLOAD_OSF_IMPORT in path.read_text():
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "Active code should import OSF download helpers from the runtime module, "
        f"not the legacy script namespace: {offenders}"
    )


def test_active_code_no_longer_imports_dataset_task_linker_script_namespace() -> None:
    active_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
    ]
    compatibility_root = OLD_BR_KG_SCRIPTS_DIR.resolve()
    offenders: list[str] = []

    for root in active_roots:
        for path in root.rglob("*.py"):
            if _should_skip_scan(path, compatibility_root):
                continue
            if OLD_DATASET_TASK_REL_IMPORT in path.read_text():
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "Active code should import dataset-task relationship helpers from the runtime module, "
        f"not the legacy script namespace: {offenders}"
    )


def test_active_code_no_longer_imports_neuromaps_fetcher_from_legacy_script_namespace() -> (
    None
):
    active_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
    ]
    compatibility_root = OLD_BR_KG_SCRIPTS_DIR.resolve()
    offenders: list[str] = []

    for root in active_roots:
        for path in root.rglob("*.py"):
            if _should_skip_scan(path, compatibility_root):
                continue
            if OLD_FETCH_NEUROMAPS_IMPORT in path.read_text():
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "Active code should import the Neuromaps fetcher from the runtime module, "
        f"not the legacy script namespace: {offenders}"
    )


def test_active_code_no_longer_imports_failed_on_backfill_from_legacy_script_namespace() -> (
    None
):
    active_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
    ]
    compatibility_root = OLD_BR_KG_SCRIPTS_DIR.resolve()
    offenders: list[str] = []

    for root in active_roots:
        for path in root.rglob("*.py"):
            if _should_skip_scan(path, compatibility_root):
                continue
            if OLD_BACKFILL_FAILED_ON_IMPORT in path.read_text():
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "Active code should import FAILED_ON backfill helpers from the runtime module, "
        f"not the legacy script namespace: {offenders}"
    )


def test_active_code_no_longer_imports_coordinate_region_mapper_from_legacy_script_namespace() -> (
    None
):
    active_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
    ]
    compatibility_root = OLD_BR_KG_SCRIPTS_DIR.resolve()
    offenders: list[str] = []

    for root in active_roots:
        for path in root.rglob("*.py"):
            if _should_skip_scan(path, compatibility_root):
                continue
            if OLD_CREATE_IN_REGION_IMPORT in path.read_text():
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "Active code should import coordinate-region mapping helpers from the runtime module, "
        f"not the legacy script namespace: {offenders}"
    )


def test_active_code_no_longer_imports_strength_cli_helpers_from_legacy_script_namespace() -> (
    None
):
    active_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
    ]
    compatibility_root = OLD_BR_KG_SCRIPTS_DIR.resolve()
    offenders: list[str] = []

    for root in active_roots:
        for path in root.rglob("*.py"):
            if _should_skip_scan(path, compatibility_root):
                continue
            if OLD_CALCULATE_STRENGTH_IMPORT in path.read_text():
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "Active code should import strength CLI helpers from the runtime module, "
        f"not the legacy script namespace: {offenders}"
    )


def test_active_code_no_longer_imports_mask_mapping_helpers_from_legacy_script_namespace() -> (
    None
):
    active_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
    ]
    compatibility_root = OLD_BR_KG_SCRIPTS_DIR.resolve()
    offenders: list[str] = []

    for root in active_roots:
        for path in root.rglob("*.py"):
            if _should_skip_scan(path, compatibility_root):
                continue
            if OLD_CREATE_IN_REGION_MASK_IMPORT in path.read_text():
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "Active code should import mask-mapping helpers from the runtime module, "
        f"not the legacy script namespace: {offenders}"
    )


def test_active_code_no_longer_imports_activation_edge_helpers_from_script_namespace() -> (
    None
):
    active_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
    ]
    compatibility_root = OLD_BR_KG_SCRIPTS_DIR.resolve()
    offenders: list[str] = []

    for root in active_roots:
        for path in root.rglob("*.py"):
            if _should_skip_scan(path, compatibility_root):
                continue
            if (
                path.resolve()
                == (REPO_ROOT / "scripts/br-kg/create_activation_edges.py").resolve()
            ):
                continue
            if OLD_CREATE_ACTIVATION_SCRIPT_IMPORT in path.read_text():
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "Active code should import ACTIVATES edge helpers from the runtime module, "
        f"not the script namespace: {offenders}"
    )
