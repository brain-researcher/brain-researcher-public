# Impact Report: Hardcoded `~` Paths -> Env-Driven Config

Generated: 2026-05-26 -- regenerated from current non-archived repo text after accidental deletion.

## Summary

- **Total string occurrences**: **9090** across **186** files
- **Python `config_loader` import edges** (from `codegraph_baseline.json`): 1
- **src/ production files** with hardcoded paths: 22

### Distribution by directory

| Directory | Occurrences |
|---|---:|
| configs/ | 7976 |
| docs/ | 510 |
| apps/ | 352 |
| tests/ | 128 |
| scripts/ | 67 |
| src/ (production) | 43 |
| other | 14 |

## src/ Production Files (22 files)

| File | Refs |
|---|---:|
| `src/brain_researcher/config/config_loader.py` | 8 |
| `src/brain_researcher/services/shared/dataset_mounts.py` | 5 |
| `src/brain_researcher/services/tools/openneuro_tool.py` | 4 |
| `src/brain_researcher/autoresearch/artifact_schema.py` | 2 |
| `src/brain_researcher/cli/agent/act.py` | 2 |
| `src/brain_researcher/core/ingestion/loaders/neurosynth_unified.py` | 2 |
| `src/brain_researcher/services/neurokg/etl/load_all.py` | 2 |
| `src/brain_researcher/services/neurokg/viz_api.py` | 2 |
| `src/brain_researcher/services/orchestrator/integration_endpoints.py` | 2 |
| `src/brain_researcher/services/orchestrator/main_enhanced.py` | 2 |
| `src/brain_researcher/cli/main.py` | 1 |
| `src/brain_researcher/core/ingestion/loaders/cognitive_atlas_unified.py` | 1 |
| `src/brain_researcher/core/ingestion/loaders/niclip_embeddings.py` | 1 |
| `src/brain_researcher/core/ingestion/loaders/openneuro_glm_loader.py` | 1 |
| `src/brain_researcher/core/ingestion/loaders/pubmed_unified.py` | 1 |
| `src/brain_researcher/core/literature/references.py` | 1 |
| `src/brain_researcher/services/knowledge/scoring/niclip_scorer.py` | 1 |
| `src/brain_researcher/services/neurokg/etl/loaders/dataset_index_loader.py` | 1 |
| `src/brain_researcher/services/neurokg/vector_api.py` | 1 |
| `src/brain_researcher/services/neurokg/vector_search.py` | 1 |
| `src/brain_researcher/services/tools/archive_tools.py` | 1 |
| `src/brain_researcher/services/tools/tribe_closed_loop_paths.py` | 1 |

## Top Files Overall

| File | Refs |
|---|---:|
| `configs/datasets/catalog_openneuro.jsonl` | 3955 |
| `configs/datasets/catalog.v1.jsonl` | 3955 |
| `apps/web-ui/public/benchmarks/neuroimage-meta-analysis.harbor.json` | 348 |
| `docs/planning/idea_mining_status_memo_20260313.md` | 100 |
| `docs/planning/idea_mining_failure_taxonomy_regression_note_20260316.md` | 38 |
| `configs/datasets/local_mounts.yaml` | 31 |
| `tests/fixtures/neurokg/gabriel_measurements.bootstrap_v3_lite.jsonl` | 30 |
| `docs/planning/promotion_policy_v1.md` | 26 |
| `configs/legacy/data_paths.yaml` | 25 |
| `docs/planning/readiness_packet_20260314.md` | 23 |
| `docs/planning/readiness_review.md` | 23 |
| `docs/planning/evidence_snapshot_alpha.md` | 20 |
| `docs/SHARE_FUNCTIONALITY_STATUS.md` | 18 |
| `tests/fixtures/neurokg/gabriel_measurements.bootstrap_v2.jsonl` | 15 |
| `docs/planning/task_charter.md` | 15 |
| `docs/planning/claim_snapshot_v4_downstream_task_manifest_20260314.md` | 15 |
| `docs/planning/go_no_go_memo.md` | 14 |
| `docs/REVIEW_GITHUB_ISSUES.md` | 13 |
| `docs/planning/neurokg_evidence_coverage_expansion_plan.md` | 13 |
| `docs/planning/claim_snapshot_v4_split_manifest_20260314.md` | 12 |
| `docs/planning/claim_snapshot_v4_b2_task_manifest_20260314.md` | 12 |
| `docs/NICLIP_CONFIGURATION.md` | 11 |
| `docs/planning/train_dev_test_split_proposal.md` | 11 |
| `docs/planning/claim_canonicalization_adr.md` | 11 |
| `docs/CALL_FOR_CONTRIBUTORS_EXPANDED.md` | 10 |
| `docs/planning/claim_snapshot_v4_20260314.md` | 10 |
| `docs/planning/idea_mining_hot_load_research_tool_v1.md` | 9 |
| `docs/planning/claim_snapshot_v4_b2_split_manifest_20260314.md` | 9 |
| `scripts/neurometabench_v1/layer_b_producer.py` | 8 |
| `scripts/neurometabench_v1/layer_b_producer_29484767.py` | 8 |
| `src/brain_researcher/config/config_loader.py` | 8 |
| `docs/planning/candidate_refinement_workflow_v1.md` | 8 |
| `docs/planning/pre_gate_b_claim_adjudication_pack_v1.jsonl` | 8 |
| `docs/specs/tool_retrieval_virtual_tools_spec.md` | 7 |
| `scripts/tools/etl/build_claim_snapshot_v4_b2_task_manifest.py` | 6 |
| `docs/proposals/THINKING_MODES_REASONING_PROFILE_PLAN.md` | 6 |
| `docs/review/expert_calibration_packet.md` | 5 |
| `src/brain_researcher/services/shared/dataset_mounts.py` | 5 |
| `docs/planning/claim_clustering_eval_plan.md` | 5 |
| `docs/planning/brain_researcher_agentic_maturity_map.md` | 5 |
| `docs/planning/idea_mining_line_conclusion_20260314.md` | 5 |
| `docs/planning/graph_snapshot_v1_1_20260314.md` | 5 |
| `infrastructure/deployment/gcp/values.prod.yaml` | 4 |
| `tests/misc/test_agent_logging.py` | 4 |
| `src/brain_researcher/services/tools/openneuro_tool.py` | 4 |
| `scripts/fix_stat_maps_links_ds000114_linebisection.sh` | 4 |
| `docs/E2E_DEMO_EXECUTION_PLAN.md` | 4 |
| `tests/integration/real_data/test_tools_basic.py` | 4 |
| `tests/integration/real_data/test_with_real_data.py` | 4 |
| `docs/specs/centaur_minitaur_integration_spec.md` | 4 |

## Notes

- Treat local benchmark captures and generated docs separately from production code.
- Prefer repo-relative paths, env vars, or documented placeholders for new code paths.
