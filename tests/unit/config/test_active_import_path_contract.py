from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

ACTIVE_RUNTIME_FILES = {
    "src/brain_researcher/cli/main.py",
    "src/brain_researcher/cli/doctor.py",
    "src/brain_researcher/cli/utils.py",
    "src/brain_researcher/cli/commands/cache_commands.py",
    "src/brain_researcher/cli/commands/data_commands.py",
    "src/brain_researcher/cli/commands/db_commands.py",
    "src/brain_researcher/cli/commands/query_commands.py",
    "src/brain_researcher/cli/commands/sessions_commands.py",
    "src/brain_researcher/cli/commands/standards_commands.py",
    "src/brain_researcher/cli/commands/service_commands.py",
    "src/brain_researcher/cli/commands/services/agent_launcher.py",
    "src/brain_researcher/cli/commands/services/kg_launcher.py",
    "src/brain_researcher/cli/commands/services/orchestrator_launcher.py",
    "src/brain_researcher/cli/commands/services/web_launcher.py",
    "src/brain_researcher/services/agent/preflight.py",
    "src/brain_researcher/services/agent/chat_orchestrator.py",
    "src/brain_researcher/services/agent/pipeline_catalog.py",
    "src/brain_researcher/services/agent/recovery_policy.py",
    "src/brain_researcher/services/agent/tool_allowlist_loader.py",
    "src/brain_researcher/services/agent/tool_catalog_loader.py",
    "src/brain_researcher/services/agent/tool_retriever.py",
    "src/brain_researcher/services/agent/tool_router.py",
    "src/brain_researcher/services/agent/web_service.py",
    "src/brain_researcher/services/agent/adapters/plan_to_pydra.py",
    "src/brain_researcher/services/agent/planner/catalog_loader.py",
    "src/brain_researcher/services/agent/planner/config_loader.py",
    "src/brain_researcher/services/agent/planner/prior_config.py",
    "src/brain_researcher/services/agent/planner/synonyms_loader.py",
    "src/brain_researcher/services/br_kg/app.py",
    "src/brain_researcher/services/br_kg/viz_api.py",
    "src/brain_researcher/services/br_kg/evidence/caveats.py",
    "src/brain_researcher/services/br_kg/knowledge/sources/niclip.py",
    "src/brain_researcher/services/br_kg/niclip/coordinate_mapper.py",
    "src/brain_researcher/services/br_kg/utils/matching_profile.py",
    "src/brain_researcher/services/br_kg/utils/node_label_linker.py",
    "src/brain_researcher/services/br_kg/utils/onvoc_linker.py",
    "src/brain_researcher/services/br_kg/utils/task_matcher.py",
    "src/brain_researcher/services/orchestrator/copilot_endpoints.py",
    "src/brain_researcher/services/orchestrator/preflight_endpoints.py",
    "src/brain_researcher/services/tools/env_desc.py",
    "src/brain_researcher/services/br_kg/etl/load_all.py",
}

FORBIDDEN_SUBSTRINGS = (
    "sys.path.insert(",
    "sys.path.append(",
    'env["PYTHONPATH"]',
    'os.environ["PYTHONPATH"]',
    "Path(__file__).resolve().parents[",
)


def test_active_cli_runtime_files_do_not_use_path_bootstrap_hacks() -> None:
    for relpath in sorted(ACTIVE_RUNTIME_FILES):
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in FORBIDDEN_SUBSTRINGS:
            assert (
                needle not in text
            ), f"Found forbidden path bootstrap in {relpath}: {needle}"
