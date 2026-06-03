ok# BR-KG Agent×KG Closed-Loop Specification (v0.1)

## Scope
Wire execution results (success/failure/latency) back into Neo4j with stable Tool/Dataset/Version anchors, and make the catalog planner consume those priors plus KG constraints. Target components: `services/agent/*`, `services/orchestrator/*`, `services/agent/planner/*`, `services/agent/web_service.py`.

## KG Facts (from 2026-01-05 snapshot)
- Tool: uniqueness on `id` and `tool_id`; current data has `id == tool_id`.
- ToolVersion: uniqueness on `version_id` and `id`; has `tool_id`, `container_image`.
- Dataset: uniqueness on `id`; `dataset_id` sometimes differs (`38` rows where `id != dataset_id`), e.g. `id=hash`, `dataset_id=ds000001`.
- ResourceType/Modality vocab present; Modality is case-mixed (`fmri`, `fMRI`, `PET`, `pet`).
- Run and Plan nodes currently absent (`count(Run)=0`, `count(Plan)=0`).

## Problem
Planning is only partially KG-aware; execution writeback is incomplete (no dataset/task, noisy latency, no aggregation). We need a closed loop where:
1) Plans and runs resolve Tool/Dataset/Version deterministically.
2) Execution outcomes are written back as event + aggregate evidence.
3) Planner uses KG constraints + run priors to filter/score tools with explainable confidence.

## Design Principles
- **Canonical IDs**: Tool key = `tool_id` (fallback `id`); Dataset key = `id` (fallback `dataset_id`); ToolVersion key = `version_id` (fallback `id`).
- **Normalization**: Modality lowercased; Dataset aliases resolved; avoid OR scans—use UNION to stay index-friendly.
- **Run Anchor**: Upsert `(:Run {id: run_id})` per execution; hang evidence/failures on Run + Tool + Dataset (+Version).
- **Dual Evidence Layers**: Event node for audit; aggregate edge for fast planner penalties.
- **Feature Flags**: Split for evidence/failure/aggregate; planner use of priors/constraints is gated.

## Deliverables (PR-ordered)

### PR1 – ID Normalization & Dataset Canonicalization
- Add helpers: `resolve_tool_key`, `resolve_dataset_key`, `resolve_version_key` (favor `tool_id`/`Dataset.id`/`version_id`; UNION lookup).
- Flow dataset_id from `query_understanding` → plan payload → run payload.
- Add modality lowercasing before KG constraint queries.
- Tests: unit mocks for resolution; ensure no OR in Cypher.

### PR2 – Failure Writeback with Dataset & Aggregates
- Extend FailureKGRecord: `dataset_id`, `task_family`, `run_id`, `tool_version_id`, keep taxonomy fields.
- Cypher:
  - MERGE `(:ExecutionFailure {failure_id})` with Tool/Dataset/Run links.
  - MERGE `(t)-[:FAILED_ON {task_family,error_category}]->(d)` increment `fail_count`, set `last_seen`.
- Flags: `BR_KG_FAILURE_WRITEBACK` (event), `BR_KG_FAILURE_AGG_WRITEBACK` (aggregate) default off→on.
- Migration: indexes on `ExecutionFailure.failure_id`, optional index on `FAILED_ON` props.
- Tests: unit for payload extraction; neo4j mocked writer.

### PR3 – Evidence Writeback (per-step latency, version-aware)
- In `aggregate_plan_job_evidence`, use step-level `duration_ms` when present; fallback to total.
- Include `tool_version_id` (from ToolVersion if resolvable; else tool entrypoint).
- Upsert `ToolEvidence` keyed by `(tool_id, tool_version, task_family)`; keep p95 latency, success/fail counts, failure_categories windowed.
- Flag: `BR_KG_EVIDENCE_WRITEBACK` (default off→on).
- Tests: unit aggregation; writer mock.

### PR4 – Planner KG Constraints (dataset-aware)
- Build constraints from `query_understanding`: dataset modalities → `kg_modalities`; optional consumes/produces mapping; mode = relaxed by default.
- Apply before scoring via `get_tool_ids_for_constraints`; auto-relax on empty match unless strict flag set.
- Tests: unit with mocked KG bridge for strict/relaxed and empty-match behaviors.
- Flag: `BR_PLANNER_USE_KG_CONSTRAINTS` (default off).

### PR5 – Failure/Agg Prior in Scoring & Confidence
- Read FAILED_ON aggregates to penalize recent/high-count failures per (tool,dataset,task_family).
- Attach to candidates: `failure_penalty`, `failed_on_count`, `last_failed_at`.
- Extend `compute_confidence_summary` explain with sources: `kg_score`, `prior_success_rate`, `evidence_n`, `failure_penalty`, `constraints_applied`.
- Flag: `BR_PLANNER_USE_FAILURE_PRIOR` (default off).
- Tests: unit for scoring blend and confidence explain.

### PR6 – Backfill & Observability
- Script: replay historical jobs/PlanMemory → ToolEvidence + ExecutionFailure + FAILED_ON.
- Metrics: writeback_success/fail/timeout, evidence_coverage, constraint_filter_rate, failure_prior_hits.
- Docs/runbook updates.

## Minimal Viable Closed Loop (fastest path)
1) Ship PR1+PR3: stable IDs + evidence writeback with per-step latency; turn on `BR_KG_EVIDENCE_WRITEBACK`.
2) Ship PR2: dataset-aware failure writeback + FAILED_ON aggregate; turn on `BR_KG_FAILURE_WRITEBACK` then `BR_KG_FAILURE_AGG_WRITEBACK`.
3) Ship PR5 (light): use FAILED_ON penalty in planner; turn on `BR_PLANNER_USE_FAILURE_PRIOR`.
4) Optional: PR4 strict KG constraints once modality/resource normalization is proven.

## Open Points / Caveats
- Dataset alias resolution: need policy for `ds000001` vs hashed `id`; propose preference order `id` match → `dataset_id` match → alias.
- Step duration: current DAG executor lacks timing; either add timing emit or accept total-duration fallback until instrumented.
- Modality duplicates: keep lowercasing; consider dedup map (`fmri`→`fMRI`) if KG data cleans later.
