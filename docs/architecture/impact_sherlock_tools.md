# Impact Report: Sherlock -> SLURM Rename

Generated: 2026-05-26 -- regenerated from `codegraph_baseline.json` plus current non-archived repo text after accidental deletion.

## Summary

- **Python `import` edges** (true blast radius): **5** edges from **3** modules
- **String references**: **383** occurrences across **47** files
- **Production code imports**: 3 files

### Distribution by directory

| Directory | String refs |
|---|---:|
| src/ (production) | 123 |
| docs/ | 86 |
| configs/ | 56 |
| tests/ | 55 |
| skills/ | 39 |
| scripts/ | 21 |
| other | 3 |

## Python Import Edges

| File | Line | Imported |
|---|---:|---|
| `src/brain_researcher/services/mcp/execution_recipes.py` | 14 | `brain_researcher.services.mcp.sherlock_tools` |
| `src/brain_researcher/services/mcp/execution_recipes.py` | 17 | `brain_researcher.services.mcp.sherlock_tools` |
| `src/brain_researcher/services/mcp/server.py` | 124 | `brain_researcher.services.mcp.sherlock_tools` |
| `src/brain_researcher/services/mcp/server.py` | 127 | `brain_researcher.services.mcp.sherlock_tools` |
| `src/brain_researcher/services/orchestrator/monitor_runtime.py` | 24 | `brain_researcher.services.mcp.sherlock_tools` |

## String References by File (top 50)

| File | Ref count |
|---|---:|
| `src/brain_researcher/services/mcp/sherlock_tools.py` | 53 |
| `src/brain_researcher/services/mcp/server.py` | 28 |
| `docs/mcp/brain_researcher_mcp_reader_question_inventory.md` | 26 |
| `tests/unit/mcp/test_sherlock_mcp_tools.py` | 25 |
| `docs/appendices/04_appendix_D_tool_registry.md` | 19 |
| `skills/sherlock-oak-workflow/SKILL.md` | 18 |
| `src/brain_researcher/services/mcp/execution_recipes.py` | 16 |
| `src/brain_researcher/services/tools/registry.py` | 16 |
| `configs/datasets/catalog.v1.jsonl` | 15 |
| `tests/unit/tools/test_executor.py` | 12 |
| `scripts/analysis/cognitive_control/sherlock/README.md` | 12 |
| `docs/mcp_tools.schema.json` | 11 |
| `tests/unit/mcp/test_mcp_surface_tiering.py` | 10 |
| `configs/datasets/catalog_openneuro.jsonl` | 9 |
| `configs/tools_catalog_overrides.yaml` | 8 |
| `skills/sherlock-oak-workflow/references/login-and-access.md` | 7 |
| `skills/sherlock-oak-workflow/scripts/sherlock_preflight.sh` | 7 |
| `docs/mcp.md` | 7 |
| `docs/api/mcp_surface_tiering.md` | 7 |
| `configs/datasets/catalog_manual.jsonl` | 6 |
| `src/brain_researcher/services/orchestrator/monitor_runtime.py` | 5 |
| `docs/runbooks/fitlins_multiverse_external_import.md` | 5 |
| `skills/sherlock-oak-workflow/agents/openai.yaml` | 4 |
| `configs/catalog/chat_tool_schemas.yaml` | 4 |
| `scripts/analysis/cognitive_control/sherlock/sync_patrick_control_to_sherlock.sh` | 4 |
| `docs/proposals/onvoc_catalog_proposals.yaml` | 4 |
| `configs/legacy/mappings/onvoc_crosswalk.yaml` | 4 |
| `configs/legacy/mappings/task_synonyms.yaml` | 4 |
| `skills/sherlock-oak-workflow/references/poldracklab-data-assets.md` | 3 |
| `AGENTS.md` | 3 |
| `scripts/analysis/cognitive_control/sherlock/dmcc_fmriprep_array.sbatch` | 3 |
| `tests/unit/orchestrator/test_monitor_runtime.py` | 3 |
| `tests/unit/mcp/test_local_mcp_server.py` | 2 |
| `src/brain_researcher/services/tools/executor.py` | 2 |
| `scripts/root_legacy/mount_oak.sh` | 2 |
| `configs/catalog/exposed_tools.yaml` | 2 |
| `tests/unit/agent/test_tool_allowlist.py` | 2 |
| `docs/proposals/onvoc_non_openneuro_proposals.yaml` | 2 |
| `docs/specs/br_mcp_mode_profile_spec.md` | 2 |
| `configs/grandmaster/toolset_vfinal.yaml` | 2 |
| `configs/runtime/execution_recipes.yaml` | 2 |
| `src/brain_researcher/services/agent/tool_allowlist_loader.py` | 2 |
| `docs/appendices/03_appendix_C_dataset_resource.md` | 1 |
| `src/brain_researcher/core/memory/memory_selector.py` | 1 |
| `tests/unit/test_memory_system.py` | 1 |
| `docs/specs/self_managed_onboarding_spec.md` | 1 |
| `docs/runbooks/workflow_fitlins_multiverse_yeo17.md` | 1 |

## Notes

- Rename/import compatibility should be handled separately from user-facing wording.
- Keep production imports and public tool names as separate migration surfaces.
