# Claim Snapshot V4 B2 Conflict Expansion

Date: 2026-03-14

## Purpose

This note records the bounded `v5_conflict` expansion used to lift `B2` beyond a
single conflict family.

The immediate goal was narrow and operational:

- add one more reviewed conflict family
- keep the expansion bounded and auditable
- make it possible for the downstream `B2` test split to contain real conflict
  rows

## Inputs

- [build_claim_snapshot_v4_b2_conflict_expansion_pack.py](<repo>/scripts/tools/etl/build_claim_snapshot_v4_b2_conflict_expansion_pack.py)
- live Neo4j `Claim` rows for the curated `concept:attention` family

## Artifacts

- [claim_snapshot_v4_b2_conflict_expansion_pack.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_b2_conflict_expansion/off400_live_attention_20260314/claim_snapshot_v4_b2_conflict_expansion_pack.jsonl)
- [claim_snapshot_v4_b2_conflict_expansion_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_b2_conflict_expansion/off400_live_attention_20260314/claim_snapshot_v4_b2_conflict_expansion_summary.json)

## Summary

Real expansion counts:

- `conflict_families_total = 1`
- `rows_total = 2`
- `target_type_Concept = 2`

The added family is a bounded live mixed-polarity `concept:attention` pair with
shared `top-down / bottom-up attention` language. It is intentionally small and
does not pretend to solve B2 scale.

## Interpretation

This pack is not a general conflict miner. It is a bounded adjudication bridge.

What is now true:

- the repo now has a concrete `v5_conflict` reviewed source pack
- `B2` conflict-family count is no longer capped at `1`
- the downstream split can place one conflict family in `dev` and another in
  `test`

What is still not true:

- this is not a benchmark-scale conflict slice
- the new family still comes from a manually curated live-claim selection

## Next Move

The next useful move is no longer “make test contain conflict at all.”

The next useful move is:

- add more than one bounded conflict-expansion family
- or make the next B2 baseline less dependent on review metadata
