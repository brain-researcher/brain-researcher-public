# Metadata Runtime Migration Plan

## Why this needs a dedicated migration

The repo-root `metadata/` directory is not just scratch output. It is the
current default runtime sink for agent/planner JSONL logs and session history.
That means it should not be deleted casually, but it also does not belong in
the repository root long-term.

Current code paths that still default to the literal `metadata` path include:

- `RunRecorder.get_recorder(...)` in
  `src/brain_researcher/services/agent/logging/run_recorder.py`
- `PlannerEventLogger(..., base_path="metadata")` in
  `src/brain_researcher/services/agent/planner_state.py`
- `EnhancedAgentOrchestrator.run_recorder = RunRecorder(base_path="metadata")`
  in `src/brain_researcher/services/agent/enhanced_integration.py`
- `LogMigrator(target_path or "metadata")` in
  `src/brain_researcher/services/agent/logging/migration.py`
- `LogExporter(log_path="metadata")` in
  `src/brain_researcher/services/agent/logging/export.py`

Today the root directory contains:

- `metadata/sessions/*.jsonl`
- `metadata/agent/executions.jsonl`
- `metadata/planner/executions.jsonl`

## Recommended target state

Move runtime log storage out of repo root and into:

- `artifacts/metadata/`

Reasoning:

- these files are generated runtime artifacts, not source code
- `artifacts/` is already the repo’s clearer “generated output” bucket
- `data/` should stay biased toward datasets and research payloads, not local
  execution traces

## Proposed config contract

Introduce a single resolver for metadata log storage:

- env: `BR_METADATA_DIR`
- default: `artifacts/metadata`
- legacy read fallback: `metadata`

The important distinction is:

- writes should move to the new root
- reads/export/migration tools should tolerate both roots during a compatibility
  window

## Safe migration shape

### Phase 1: centralize path resolution

Add one shared helper, for example under:

- `src/brain_researcher/config/runtime_paths.py`
  or
- `src/brain_researcher/services/agent/logging/paths.py`

It should expose:

- `get_metadata_root()`
- `get_metadata_roots_for_read()`

Resolution order:

1. `BR_METADATA_DIR`
2. canonical default `artifacts/metadata`
3. legacy fallback `metadata` for read compatibility only

### Phase 2: switch default writers

Update writer defaults to use the shared helper instead of hardcoded
`"metadata"`:

- `run_recorder.py`
- `planner_state.py`
- `enhanced_integration.py`

At this phase, new records land under `artifacts/metadata`.

### Phase 3: keep read/export compatibility

Update tools that inspect or migrate logs so they can read both locations:

- `logging/export.py`
- `logging/migration.py`
- any CLI/debug utilities that assume the literal root path

This avoids breaking users who still have historical logs only under
`metadata/`.

### Phase 4: one-time filesystem migration

Add a small script, for example:

- `scripts/migrate_metadata_root.py`

Behavior:

- detect legacy `metadata/`
- copy or move `sessions/`, `agent/`, `planner/` into `artifacts/metadata/`
- no-op if destination already contains newer files
- print a concise summary

This should be explicit and operator-driven, not hidden inside service startup.

## What not to do

- do not silently delete root `metadata/`
- do not switch all defaults without a read-compat layer
- do not place these logs under `data/` unless the project wants runtime
  telemetry mixed with research datasets
- do not rely on a root symlink as the primary long-term solution

## Acceptance criteria

- new runtime sessions/logs write to `artifacts/metadata`
- exporter/migration utilities can still read historical `metadata/` logs
- tests no longer hardcode the repo-root `metadata` path unless explicitly
  testing legacy compatibility
- repo root no longer needs a live `metadata/` directory for normal operation

## Suggested implementation order

1. add shared metadata-root resolver
2. switch writer defaults
3. add read compatibility for exporter/migrator
4. add one explicit migration script
5. after one compatibility window, stop mentioning root `metadata/` in docs
