# Evidence Registry Parity Report

As of March 11, 2026.

This report captures the week-1 parity findings for the
`evidence_coverage_expansion` track.

## Scope

Checked surfaces:

- runtime validation in `src/brain_researcher/services/neurokg/bulk_loader.py`
- canonical relation mapping in
  `src/brain_researcher/services/neurokg/semantic/canonical_mapping.py`
- quality-profile governance in `configs/neurokg/thresholds.yaml`
- claim-first extraction behavior in
  `src/brain_researcher/services/neurokg/etl/loaders/gabriel_loader.py`
- task-panel handoff guidance in `scripts/build/build_task_panel_ingest_package.py`

## Resolved In This Iteration

1. `bulk_loader` parity for richer evidence nodes and edges

- `EntityValidator.VALID_NODE_TYPES` now includes:
  `Assumption`, `BrainRegion`, `Atlas`, `StatisticalMap`, `StatsMap`, `StatMap`
- `EntityValidator.VALID_RELATIONSHIP_TYPES` now includes:
  `ASSUMES`, `CHALLENGES_ASSUMPTION`, `CONTRADICTS`,
  `NULL_RESULT_FOR`, `REPLICATES`, `FAILED_REPLICATION_OF`
- This closes the direct mismatch with `gabriel_loader`, which already
  materializes these relation families.

2. Quality-profile governance parity

- `configs/neurokg/thresholds.yaml` now exposes both `kg_bootstrap` and
  `kg_task_panel` under `gabriel_quality_profiles`.
- Before this change, the CLI and loader supported these profiles, but the
  shared thresholds config did not.

3. Canonical relation parity for claim-first evidence

- `canonical_mapping.py` now canonicalizes claim-first relation families:
  `REPORTS_CLAIM`, `SUPPORTS`, `ASSUMES`,
  `CHALLENGES_ASSUMPTION`, `CONTRADICTS`,
  `NULL_RESULT_FOR`, `REPLICATES`, `FAILED_REPLICATION_OF`, and `GENERATED`.
- This prevents the richer claim-first lane from silently degrading into
  generic unmapped associations in downstream semantics helpers.

4. Task-panel handoff guidance

- The generated task-panel package README now recommends:
  `--quality-profile kg_task_panel`
- This matches the dedicated loader profile already implemented in
  `gabriel_loader.py` and tested in
  `tests/unit/neurokg/etl/test_gabriel_loader.py`.

## Remaining Open Gaps

1. `config.yml` status drift

- `configs/neurokg/config.yml` still marks `Claim`, `Assumption`,
  `EvidenceSpan`, and `MeasurementRun` as effectively planned/zero-state.
- That is stale relative to the live claim-spine ingest path and should be
  reconciled in a separate source-of-truth update.

2. Review queue accounting

- The raw `review_queue.jsonl` is still append-only and duplicate-prone.
- Coverage reporting should use unique candidate accounting, not raw line
  counts.

3. Task-panel lane dependency on ONVOC normalization

- The `task_panel` builder depends on `kggen_normalized_onvoc.jsonl`.
- Operationally, `br gabriel map-onvoc --no-normalize-targets` is incompatible
  with this lane and should be treated as a no-go configuration for task-panel
  expansion.

## Minimal Test Coverage Added

- `tests/services/neurokg/test_bulk_loader.py`
  now checks an `Assumption` node and a richer claim-first relation.
- `tests/unit/neurokg/test_canonical_mapping.py`
  now checks claim-first canonicalization behavior.
- `tests/unit/scripts/test_build_task_panel_ingest_package.py`
  now checks that generated package instructions use `kg_task_panel`.

## Current Readiness

Status: `partial unblock`

- Validator/config parity is now in place for the first expansion slice.
- The next blocker is no longer ingest surface drift.
- The next blocking work is operational:
  deduplicate review-queue accounting, run the broader candidate lane, and
  measure actual accepted-vs-queued lift.
