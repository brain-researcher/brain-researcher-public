# Review Queue Dedup Report

As of March 11, 2026.

This report captures the current duplicate pressure in the bounded GABRIEL
review queue.

## File Inspected

- `data/neurokg/raw/gabriel/review_queue.jsonl`

## Snapshot Counts

- raw rows: `2`
- unique candidates under a stable content key: `1`
- duplicate rows: `1`
- duplicate rate: `50%`

## What Is Duplicated

Both current rows are the same rejected candidate:

- `run_id`: `run-20260224-003`
- `paper.id`: `pmid:40000003`
- target label: `Executive Control`
- claim text: `Results may suggest a weak trend.`
- identical rejection reasons and identical computed variables

The only material difference is `queued_at`.

## Why This Matters

- raw queue length currently overstates adjudication work by `2x`
- promotion metrics based on raw line counts would misreport candidate volume
- any adjudication pack built from the raw file without deduplication will risk
  repeated review of the same rejected evidence unit

## Recommended Dedup Key

Use a stable content hash over:

- `record.run.run_id`
- `record.paper.id`
- `record.target.type`
- `record.target.id` or `record.target.label`
- `record.claim.text`
- `record.claim.polarity`
- `record.evidence.quote`
- `reasons`
- `variables`

Explicitly exclude:

- `queued_at`

## Recommended Operating Rule

- keep the raw queue as an append-only audit log
- compute a deduplicated view before:
  adjudication-pack generation,
  queue-size reporting,
  promotion-rate reporting,
  and weekly coverage metrics

## Current Decision

No raw queue rewrite was performed in this iteration.

This artifact only freezes the accounting finding:
coverage-expansion reporting must use unique-candidate counts, not raw review
queue rows.
