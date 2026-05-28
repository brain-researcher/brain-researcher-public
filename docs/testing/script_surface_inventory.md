# Script Surface Inventory

Date: 2026-05-20

This is a narrow cleanup inventory for `scripts/`. It is not a full repository
refactor plan. The goal is to keep active script entrypoints easy to find while
moving or deleting one-off code only when current evidence shows it is stale.

## Scan Scope

- Script files under `scripts/`: 624
- Root-level script files under `scripts/`: 57 before this pass
- Unit test files under `tests/unit/scripts/`: 113
- Active reference scan roots: `.github/`, `docs/`, `tests/`, `src/`,
  `configs/`, and `apps/`
- Ignored historical scan roots: `docs/archive/`, nested documentation
  checkouts, `tests/migration/`, and `__pycache__/`

## Active CI and Runtime Scripts

These are not cleanup candidates without a replacement plan:

| Path | Evidence |
| --- | --- |
| `scripts/ci/generate_resources_schema.py` | Called by CI and referenced from planner catalog docs. |
| `scripts/ci/validate_capabilities.py` | Called by CI and covered by planner schema unit tests. |
| `scripts/tools/audit_execution_recipes.py` | Called by CI after this pass; imported by MCP unit coverage. |
| `scripts/ci/generate_e2e_auth_token.py` | Called by CI e2e workflow. |
| `scripts/tools/dev/seed_from_dump.sh` | Called by CI Neo4j setup jobs. |
| `scripts/ops/run_harness_certification.py` | Called by harness certification workflow. |
| `scripts/mcp/selftest_probe.py` | Default MCP self-test script in runtime code. |
| `scripts/runtime/run_taskbeacon_task.sh` | Used by the orchestrator TaskBeacon adapter. |
| `scripts/runtime/start_marimo_singleuser.sh` | Used by the marimo runtime provisioner. |
| `scripts/workflows/run_workflow_realdata_gate.py` | Referenced by workflow runbooks and covered by unit tests. |
| `scripts/workflows/run_external_repo_minimal_execute_gate.py` | Referenced by workflow runbooks. |

## Tested Utility Surface

`tests/unit/scripts/` has 113 script-focused unit test files. Examples of
root-level script utilities covered by tests:

| Path | Test evidence |
| --- | --- |
| `scripts/calibrate_onvoc_thresholds.py` | `tests/unit/scripts/test_calibrate_onvoc_thresholds.py` |
| `scripts/cleanup_run_artifacts.py` | `tests/unit/scripts/test_cleanup_run_artifacts.py` and cleanup guardrail tests |
| `scripts/enrich_catalog_with_neurobagel.py` | `tests/unit/scripts/test_enrich_catalog_with_neurobagel.py` |
| `scripts/kggen_generate_from_manifest.py` | NeuroKG ETL unit coverage and agent pipeline references |
| `scripts/migrate_metadata_root.py` | `tests/unit/scripts/test_migrate_metadata_root.py` |
| `scripts/msc_schaefer_connectomes.py` | `tests/unit/scripts/test_msc_schaefer_connectomes.py` |
| `scripts/neurometabench_screening_pipeline.py` | NeuroMetaBench unit coverage |
| `scripts/demos/prepare_realtime_twophoton_demo.py` | `tests/unit/scripts/test_prepare_realtime_twophoton_demo.py` |

## Cleaned This Pass

Fixed current script references and CI script contracts:

| Path | Reason |
| --- | --- |
| `.github/workflows/ci.yml` | Corrected execution recipe audit path to `scripts/tools/audit_execution_recipes.py`. |
| `scripts/ci/generate_resources_schema.py` | Restored `ResourceType` as the canonical source for generated resource schema. |
| `configs/schemas/capabilities.schema.json` | Allowed current underscore tool IDs such as `code_agent` and `ibl_one`. |
| `scripts/dev/run_all_implementations.sh` | Updated stale script/doc paths for data download and pre-commit setup helpers. |

Removed root-level orphan scripts with no active references or tests:

| Path | Reason |
| --- | --- |
| `scripts/batch_add_literature_conf.py` | Hardcoded old local paths and no CLI/test/doc reference. |
| `scripts/batch_parcellate_and_fit_all.py` | Hardcoded old local data layout and no CLI/test/doc reference. |
| `scripts/debug_agent_health.py` | Ad hoc diagnostic with no stable CLI or reference. |
| `scripts/test_oauth_integration.py` | Live external OAuth/Gemini smoke in `scripts/`, not active pytest coverage. |

## One-Off Review Decisions

These were reviewed after the initial inventory and either archived, moved to a
topical subdirectory, documented in-place, or deleted:

| Path | Current signal | Suggested next action |
| --- | --- | --- |
| `docs/archive/scripts/manual_audit_meta_gt_sample.py` | Archived one-off manual GT correction script. | No longer active `scripts/` surface. |
| `docs/archive/scripts/manual_audit_meta_gt_remaining.py` | Archived dependent manual GT correction script. | No longer active `scripts/` surface. |
| `scripts/manuscript/generate_fig5_paradigmcraft_example.py` | Generates a figure payload but has no current active reference. | Kept as manuscript/figure artifact generator. |
| `scripts/cleanup_cvmfs_cache.sh` | Operational helper with machine-specific log path. | Deleted. |
| `scripts/neurokg/cleanup_measures_provenance.py` | Neo4j backfill utility referenced by NeuroKG rebuild notes. | Kept under NeuroKG scripts. |
| `scripts/analysis/compare_openneuro_glmfitlins_stat_maps.py` | Standalone stat-map comparison utility. | Kept under analysis scripts. |
| `scripts/setup/mount_openneuro_s3fs.sh` | Data setup helper referenced by legacy service launcher and paper2 notes. | Kept under setup scripts. |
| `scripts/setup/mount_public_buckets.sh` | General public S3 bucket mount helper. | Kept under setup scripts. |

## Known Stale Reference Backlog

This pass fixed the CI path for `scripts/tools/audit_execution_recipes.py` and
developer docs for `scripts/dev/setup_precommit.sh`.

Remaining stale script references are mostly older NeuroKG docs/contracts that
refer to historical root paths such as `scripts/init_database.py` and
`scripts/integrate_coordinate_relationships.py`. Those should be handled as a
separate NeuroKG documentation/path-contract cleanup because some current
contract tests intentionally mention old locations while asserting migration
guidance.

## Root-Level Candidate Backlog

After the one-off moves/deletes above, remaining root-level scripts with no
strong current active-reference signal should be reviewed in later topical
batches, not deleted as a group:

- `scripts/benchmark_claim_first_vs_mention_bootstrap.py`
- `scripts/convert_contrast_json.py`
- `scripts/deep_research_to_idea_cards.py`
- `scripts/fetch_pmc_oa_fulltext_pubget.py`
- `scripts/fix_stat_maps_links_ds000114_linebisection.sh`
- `scripts/generate_mappings.py`
- `scripts/generate_neurosynth_term_maps.py`
- `scripts/generate_r1_conflict_matrix.py`
- `scripts/index_codebase_with_google_file_search.py`
- `scripts/index_pubget_papers_with_google_file_search.py`
- `scripts/inspect_google_stores.py`
- `scripts/install_latest_containers.sh`
- `scripts/merge_pubget_runs.py`
- `scripts/migrate_folder_to_gcp.sh`
- `scripts/neo4j_restore.sh`
- `scripts/overlay_neurosynth_fast.py`
- `scripts/paperbanana_mcp_entry.py`
- `scripts/parcellate_and_fit_encoding_model.py`
- `scripts/plot_fig5_paradigmcraft.py`
- `scripts/plot_neurokg_concepts.py`
- `scripts/plot_neurokg_retrieval_results.py`
- `scripts/refactor_etl.py`
- `scripts/tribe_encoding_summarize_roi_contrasts.py`
- `scripts/update_imports.sh`
- `scripts/update_neurosynth_paths.py`

Review these by topic. For example, Google File Search scripts should be
handled together; Neo4j backup/restore scripts should be handled as ops; figure
and manuscript scripts should be handled with the artifact they reproduce.

## Cleanup Rule

Use this order before deleting future scripts:

1. Check active references in `.github/`, `src/`, `tests/`, `docs/`, `configs/`,
   and `apps/`.
2. Check whether `tests/unit/scripts/` or another focused test imports it.
3. If it is a one-off but reproduces a durable artifact, document the artifact
   and keep or move the script beside its topic.
4. If it is unreferenced, untested, undocumented, and machine-specific or
   obsolete, delete it or move it to an explicit archive with a reason.
