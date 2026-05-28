# Graph Contract v1

As of March 10, 2026.

This document is the source-of-truth contract for
`graph_substrate_readiness`.

Its purpose is to stop graph-learning work from starting on top of a substrate
contract that no longer matches the real graph or the real Brain Researcher
workflow.

## Purpose

`graph_contract_v1` defines:

- the canonical node and edge families for substrate readiness
- which signatures are `Gate A` blocking versus future enrichment
- how readiness statuses are normalized
- which probes must pass before graph-learning work starts
- how to treat compatibility paths that remain in the graph but are not part of
  the canonical substrate

## Authority Order

Use this precedence order when sources disagree:

1. `configs/neurokg/config.yml`
2. live Neo4j measurement
3. planning reports in `docs/planning/`
4. historical integration summaries and older sparse-snapshot docs

Operational rule:

- if a doc says `Coordinate -> Region` is canonical but live execution and the
  active toolchain use `StatsMap -> BrainRegion`, the contract must follow the
  toolchain, not the stale doc

## Canonical Substrate Decision

The canonical spatial/anatomy substrate is:

- `Publication -> HAS_COORDINATE -> Coordinate`
- `StatsMap -> IN_REGION -> BrainRegion`
- `BrainRegion -> PART_OF -> BrainRegion`

The compatibility and future-enrichment lane is:

- `Coordinate -> IN_REGION -> Region`

Operational rule:

- `Coordinate -> IN_REGION -> Region` remains allowed, but it is not required
  for `Gate A`
- `ACTIVATES` is not part of substrate readiness in this contract revision

## Normalized Status Labels

- `live`
  Exists in the current graph at usable scale and is queryable.
- `partial`
  Exists, but not yet benchmark-stable or not yet complete enough for the full
  intended role.
- `missing`
  Should exist for the canonical contract, but is absent on that signature.
- `blocked`
  Cannot be materialized yet because a prerequisite family is missing.
- `planned`
  Designed but not yet part of the operational graph.
- `waived`
  Intentionally excluded from the current gate with written rationale.

## In-Scope Node Families

| Node Family | Contract Role | Current Status | Notes |
|---|---|---|---|
| `Publication` | literature backbone | `live` | Remains canonical |
| `Coordinate` | literature spatial evidence | `live` | Kept as a first-class backbone node |
| `StatsMap` | canonical voxel-level spatial evidence | `live` | Canonical source for substrate spatial reasoning |
| `BrainRegion` | canonical spatial/anatomy target | `live` | Public canonical region label |
| `Task` | semantic grounding | `live` | Required for `MEASURES` probe |
| `Concept` | semantic grounding | `live` | Required for `MEASURES` probe |
| `Region` | compatibility / enrichment only | `partial` | Not canonical for `Gate A` |
| `Atlas` | anatomy metadata | `partial` | Supports hierarchy materialization |

Not gating for this contract revision:

- `Dataset`
- `Subject`
- `Phenotype`
- `Author`
- `File`

## In-Scope Edge Families

| Edge Family | Canonical Signature | Contract Status | Gate Role |
|---|---|---|---|
| `HAS_COORDINATE` | `Publication -> Coordinate` | `live` | `A1` blocking |
| `IN_REGION` | `StatsMap -> BrainRegion` | `live` | `A1` blocking |
| `PART_OF` | `BrainRegion -> BrainRegion` | `missing` | `A2` blocking |
| `MEASURES` | `Task -> Concept` | `partial` | `A1` blocking |
| `CITES` | `Publication -> Publication` | `partial` | `A1` blocking |
| `ACTIVATES` | `Task|Concept -> Region|BrainRegion` | `partial` | tracked, nonblocking |

Compatibility / future-enrichment signatures:

- `Coordinate -> IN_REGION -> Region`
- non-anatomy `PART_OF` uses such as `Dataset|DataResource -> Consortium`

Operational rule:

- compatibility signatures may exist in the graph without satisfying `Gate A`

## Gate A Structure

`Gate A` is split into two sub-gates.

### `A1`: Spatial Backbone

Pass only if all of the following are true:

- `Publication -> HAS_COORDINATE -> Coordinate` is queryable
- `StatsMap -> IN_REGION -> BrainRegion` is queryable
- `Task -> MEASURES -> Concept` is queryable
- first-pass `Publication -> CITES -> Publication` is queryable
- the graph clears the structural floor for a learnable substrate

### `A2`: Anatomy Hierarchy

Pass only if all of the following are true:

- `BrainRegion -> PART_OF -> BrainRegion` exists at usable scale
- the two-hop path
  `StatsMap -> IN_REGION -> BrainRegion -> PART_OF -> BrainRegion`
  is queryable

### Overall Gate Rule

- `A1` may pass before `A2`
- downstream hypothesis-evidence improvements may start once `A1` passes
- graph-learning work remains blocked until both `A1` and `A2` pass

## Fixed Probe Contract

The gate-critical probe set is:

- `TPR-01`: `Publication -> HAS_COORDINATE -> Coordinate`
- `TPR-02`: `StatsMap -> IN_REGION -> BrainRegion`
- `TPR-03`: `BrainRegion -> PART_OF -> BrainRegion`
- `TPR-04`: `Task -> MEASURES -> Concept`
- `TPR-07`: `Publication -> CITES -> Publication`
- `TPR-08`: `StatsMap -> IN_REGION -> BrainRegion -> PART_OF -> BrainRegion`

Tracked but nonblocking:

- `TPR-05`
- `TPR-06`

Operational rule:

- `ACTIVATES` probes remain visible, but they do not block substrate readiness
  in this revision

## Required Metrics

- total node count
- total edge count
- `Publication` count
- `Coordinate` count
- `StatsMap` count
- `BrainRegion` count
- `Region` count
- `Atlas` count
- `HAS_COORDINATE` count
- canonical `IN_REGION` count
- canonical anatomy `PART_OF` count
- `MEASURES` count
- `CITES` count
- orphan publication rate
- orphan coordinate rate
- fixed-seed typed path availability for `TPR-01`, `TPR-02`, `TPR-03`,
  `TPR-04`, `TPR-07`, and `TPR-08`

## Known Contradictions To Resolve

- older standards docs still describe `Coordinate -> Region` as canonical
- live graph and GLM FitLins/OpenNeuro flows already operate on
  `StatsMap -> BrainRegion`
- `PART_OF` exists live, but not yet on the canonical anatomy signature
- `ACTIVATES` exists only as sparse mixed evidence and should not be treated as
  substrate proof

## No-Go Rule

Do not start graph-learning work if either of the following remains true:

- `A1` has not passed on the canonical BrainRegion-based substrate
- `A2` has not passed because anatomy hierarchy edges are still missing

## Outputs Required Next

- `graph_baseline_report.md`
- `typed_path_regression_report.md`
- `resume_rebuild_runbook.md`
- `graph_snapshot_v1`
