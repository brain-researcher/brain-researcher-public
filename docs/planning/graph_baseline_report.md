# Graph Baseline Report

As of March 10, 2026.

This report is the first live Neo4j-derived baseline for
`graph_substrate_readiness`.

## Baseline Provenance

This baseline is DB-derived from the live local Neo4j target, not doc-derived.

Execution sources used:

- `br db validate`
- `br db status`
- `br query stats`
- direct read-only Neo4j queries through the repo `.env`

Contrast sources used only for drift analysis:

- `docs/standards/neurokg_graph_schema.md`
- `configs/neurokg/config.yml`
- `docs/services/neurokg/EDGE_INTEGRATION_SUMMARY.md`
- `docs/issues/03_neurokg_issues.md`

Operational conclusion:

- the repo is connected to a real live graph
- the live graph is much larger and denser than the older planning baseline
- the main problem is no longer "missing graph"
- the previous `A2` blocker was canonical anatomy hierarchy incompleteness on
  the BrainRegion contract
- the March 10, 2026 hierarchy materializer run closed that blocker on the live
  Neo4j graph

## Live Snapshot

Observed live snapshot from this workspace:

| Metric | Value |
|---|---:|
| Total nodes | `726,523` |
| Total relationships | `2,430,353` |
| Node labels | `85` |
| Relationship types | `81` |
| Node-to-edge ratio | `1:3.34` |

Interpretation:

- the graph is no longer edge-sparse
- the old `476,889` nodes / `51,188` edges planning baseline is stale
- the structural floor of `>300,000` total edges is already cleared

## Gate A1 / A2 Node Families

| Node Family | Live Count | Normalized Status | Notes |
|---|---:|---|---|
| `Publication` | `51,852` | `live` | Literature backbone exists |
| `Coordinate` | `447,499` | `live` | Spatial evidence node family exists at scale |
| `StatsMap` | `nonzero` | `live` | Canonical spatial source family for `IN_REGION` |
| `Task` | `34,935` | `live` | Large mixed task family |
| `Concept` | `2,596` | `live` | Semantic concept family exists |
| `Region` | `86` | `partial` | Exists, but not the dominant anatomy target in live spatial edges |
| `BrainRegion` | `845` | `live` | Canonical public anatomy target, including hierarchy parents |
| `Atlas` | `1` | `partial` | Exists, but only minimal atlas coverage is visible |
| `Embedding` | `23,865` | `live` | No longer functionally absent |

## Gate A1 / A2 Edge Families

| Edge Family | Live Count | Normalized Status | Notes |
|---|---:|---|---|
| `HAS_COORDINATE` | `447,499` | `live` | Main backbone edge is already materialized |
| `IN_REGION` | `121,261` | `live` | Canonical pattern is `StatsMap -> BrainRegion` |
| `PART_OF` | `416` | `live` | `317` canonical `BrainRegion -> BrainRegion` plus `99` compatibility consortium edges |
| `MEASURES` | `10,875` | `partial` | Path exists, but mostly not `Task -> Concept` |
| `CITES` | `3,397` | `partial` | Citation spine exists, but source coverage is still narrow |

Tracked but non-gating:

| Edge Family | Live Count | Normalized Status | Notes |
|---|---:|---|---|
| `ACTIVATES` | `6` | `partial` | Queryable but far too sparse for stable benchmark use; no longer part of Gate A |

Claim-spine-adjacent edge families already live:

| Edge Family | Live Count |
|---|---:|
| `REPORTS_CLAIM` | `10,268` |
| `SUPPORTS` | `10,408` |
| `GENERATED` | `20,892` |

## Coverage And Orphan Checks

Direct read-only live checks:

| Metric | Value |
|---|---:|
| Publications without coordinates | `37,629` |
| Coordinates without a publication parent | `0` |
| Tasks without `MEASURES -> Concept` | `34,238` |
| Publications with outgoing citations | `56` |

Interpretation:

- `HAS_COORDINATE` coverage is complete from the coordinate side, but not from
  the publication side
- about `72.6%` of publications currently have no coordinates
- only about `2.0%` of tasks currently participate in `Task -> MEASURES ->
  Concept`
- citation coverage exists, but is concentrated in a small subset of
  publications

## Canonical Contract State

The most important live findings are not raw counts. They are path semantics.

Direct live endpoint checks showed:

- all `IN_REGION` edges currently resolve as `StatsMap -> BrainRegion`
- there are `317` live canonical anatomy `BrainRegion -> PART_OF -> BrainRegion`
  edges
- `PART_OF` now resolves on both the canonical anatomy signature and the older
  `Dataset|DataResource -> Consortium` compatibility structure
- `ACTIVATES` currently resolves mostly as `Task -> Region` with only `5`
  matching edges
- the only observed concept-side `ACTIVATES` usage is `Concept -> Task` with
  count `1`

Operational conclusion:

- the live graph is populated
- the canonical spatial backbone is already present
- the canonical anatomy hierarchy is now present
- `Gate A` is no longer blocked on graph substrate structure

## Source Contradictions

The contradiction pattern changed after live measurement.

Before contract revision, the repo looked like a missing-edge problem.
After live measurement and the contract revision, the main contradiction is:

- older docs still describe a substrate centered on `Coordinate -> Region`
  and `Region -> PART_OF -> Region`
- the revised contract and live graph center substrate reasoning on
  `StatsMap -> BrainRegion`
- `docs/standards/neurokg_graph_schema.md` still reports an older sparse
  snapshot that is no longer representative of the live database

These sources no longer disagree only on counts. They disagree on the substrate
itself.

## Current Gate Verdict

`Gate A1` status: `PASS`

Reason:

- the graph now clears the structural edge-count floor
- the canonical spatial backbone now passes as `A1`
- `HAS_COORDINATE` is live at scale
- `ACTIVATES` is no longer a substrate blocker

`Gate A2` status: `PASS`

Reason:

- the canonical anatomy hierarchy is now materialized as `BrainRegion -> PART_OF -> BrainRegion`
- `TPR-03` and `TPR-08` both pass on the live snapshot
- claim-spine-adjacent edges remain live and now sit on top of a complete
  gate-critical graph substrate

Overall `Gate A` status: `PASS`

## Immediate Next Actions

- Freeze this live graph as the current baseline, not the old sparse snapshot.
- Keep `StatsMap -> IN_REGION -> BrainRegion` as the canonical spatial
  contract.
- Keep `BrainRegion -> PART_OF -> BrainRegion` as the canonical anatomy
  contract.
- Keep `Coordinate -> IN_REGION -> Region` only as future enrichment.
- Do not spend rebuild time recreating a coordinate-based spatial contract that
  is not needed for the current use case.
- Move the next gating focus to claim spine benchmark quality and post-`Gate A`
  operator evaluation, not substrate rebuild.
