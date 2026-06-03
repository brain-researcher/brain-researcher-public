# KG Evidence Writeback (Tool×TaskFamily Prior)

This repo supports a minimal closed loop where **plan execution outcomes** are persisted as evidence in Neo4j and then consumed as a **prior** during the next tool-selection run.

## Enable

Set the feature flag (default is off):

```bash
export BR_KG_WRITEBACK=1
```

Neo4j connection is taken from the standard env vars:
- `NEO4J_URI` (default `bolt://localhost:7687`)
- `NEO4J_USER` (default `neo4j`)
- `NEO4J_PASSWORD` (required to enable Neo4j-backed prior)
- `NEO4J_DATABASE` (optional)

## What gets written

Writeback runs after a **terminal** `plan_execution` job completes (success/fail/timeout/cancel). It aggregates per-run evidence and stores it as a **tool×task_family** bucket:

- `tool_id`
- `tool_version` (best-effort; from catalog `entrypoint` when available)
- `task_family` (prefer `snapshot.intent[0]`, else `context.pipeline`)
- `outcome` (`success` / `fail`)
- `latency_ms` (coarse plan duration)
- `failure_category` (best-effort; from `error_taxonomy.classify_failure`)

Storage model (Neo4j, additive):
- `(:ToolEvidence {tool_id, tool_version, task_family, success_count, fail_count, latency_ms_samples, failure_categories, updated_at})`
- Optional relationship: `(:Tool)-[:HAS_EVIDENCE]->(:ToolEvidence)` when the `:Tool` node exists.

Implementation:
- Aggregation: `brain_researcher/services/agent/planner/evidence.py`
- Neo4j store: `brain_researcher/services/agent/planner/evidence_neo4j.py`
- Worker hook: `brain_researcher/services/orchestrator/worker.py`

## How it affects ranking

The unified planner (`brain_researcher/services/agent/planner/unified_planner.py`) consumes evidence as a **soft prior**:

- Boost higher **smoothed success rate** (`success_count` / total with Beta smoothing)
- Penalize common **failure categories** (low-cardinality penalty)
- Prefer lower **p95 latency** when latency samples exist

If Neo4j is unavailable, the system logs and continues without applying priors.
