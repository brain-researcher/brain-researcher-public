# Typed Path Regression Report

As of March 10, 2026.

This report freezes the first live typed-path regression results after the
BrainRegion-canonical substrate revision.

## Purpose

The canonical substrate is now:

- `Publication -> HAS_COORDINATE -> Coordinate`
- `StatsMap -> IN_REGION -> BrainRegion`
- `BrainRegion -> PART_OF -> BrainRegion`

This report measures those paths directly and separates:

- `A1 spatial backbone`
- `A2 anatomy hierarchy`
- tracked-but-nonblocking semantic enrichment

## Probe Status Vocabulary

- `pass`: required typed path resolves on deterministic eligible seeds
- `pending`: required path is canonical but not yet materialized
- `nonblocking`: tracked, but does not block `Gate A` in this revision

## Gate-Critical Probe Families

| Probe ID | Declared Path | Gate Role | Live Status |
|---|---|---|---|
| `TPR-01` | `Publication -> HAS_COORDINATE -> Coordinate` | `A1` | `pass` |
| `TPR-02` | `StatsMap -> IN_REGION -> BrainRegion` | `A1` | `pass` |
| `TPR-03` | `BrainRegion -> PART_OF -> BrainRegion` | `A2` | `pass` |
| `TPR-04` | `Task -> MEASURES -> Concept` | `A1` | `pass` |
| `TPR-07` | `Publication -> CITES -> Publication` | `A1` | `pass` |
| `TPR-08` | `StatsMap -> IN_REGION -> BrainRegion -> PART_OF -> BrainRegion` | `A2` | `pass` |

Tracked but nonblocking:

- `TPR-05`: `Task -> ACTIVATES -> Region|BrainRegion`
- `TPR-06`: `Concept -> ACTIVATES -> Region|BrainRegion`

## Deterministic Seed Policy

- Freeze lexical seeds only after filtering to nodes already eligible for the
  declared path.
- If no eligible seeds exist, record `pending`, not synthetic failure.

## First Live Execution

### `TPR-01`

Declared path: `Publication -> HAS_COORDINATE -> Coordinate`

Eligible-positive seeds produced `5/5` positive results.

Assessment: `pass`

### `TPR-02`

Declared path: `StatsMap -> IN_REGION -> BrainRegion`

Frozen seeds:

- `glmfitlins:ds000009:balloonanalogrisktask:allpumps:dataset:t:unknown:task-balloonanalogrisktask-node-datalevel-contrast-allpumps-stat-t-statmap-nii-gz`
- `glmfitlins:ds000009:balloonanalogrisktask:allpumps:dataset:z:unknown:task-balloonanalogrisktask-node-datalevel-contrast-allpumps-stat-z-statmap-nii-gz`
- `glmfitlins:ds000009:balloonanalogrisktask:allpumps:run:t:unknown:task-balloonanalogrisktask-node-runlevel-sub-01-sub-01-contrast-allpumps-stat-t-statmap-nii-gz`
- `glmfitlins:ds000009:balloonanalogrisktask:allpumps:run:t:unknown:task-balloonanalogrisktask-node-runlevel-sub-02-sub-02-contrast-allpumps-stat-t-statmap-nii-gz`
- `glmfitlins:ds000009:balloonanalogrisktask:allpumps:run:t:unknown:task-balloonanalogrisktask-node-runlevel-sub-03-sub-03-contrast-allpumps-stat-t-statmap-nii-gz`

Seed results: `5/5` positive

- `17`
- `17`
- `17`
- `17`
- `17`

Assessment: `pass`

### `TPR-03`

Declared path: `BrainRegion -> PART_OF -> BrainRegion`

Observed live count:

- `317` canonical anatomy `PART_OF` edges

Representative positive seeds:

- `atlas:schaefer2018_100_7n_2mm:1 -> atlas:schaefer2018_100_7n_2mm:network:vis`
- `atlas:schaefer2018_100_7n_2mm:10 -> atlas:schaefer2018_100_7n_2mm:network:sommot`
- `atlas:schaefer2018_100_7n_2mm:100 -> atlas:schaefer2018_100_7n_2mm:network:default`
- `yeo17:11 -> yeo17:parent:control`
- `yeo17:14 -> yeo17:parent:default`

Assessment: `pass`

### `TPR-04`

Declared path: `Task -> MEASURES -> Concept`

Eligible-positive seeds produced `5/5` positive results.

Assessment: `pass`

### `TPR-07`

Declared path: `Publication -> CITES -> Publication`

Eligible-positive seeds produced `5/5` positive results.

Assessment: `pass`

Operational warning:

- citation coverage remains sparse even though the path is queryable

### `TPR-08`

Declared path:
`StatsMap -> IN_REGION -> BrainRegion -> PART_OF -> BrainRegion`

Observed live count:

- `121,261` canonical two-hop spatial-hierarchy paths

Frozen seeds:

- `glmfitlins:ds000009:balloonanalogrisktask:allpumps:dataset:t:unknown:task-balloonanalogrisktask-node-datalevel-contrast-allpumps-stat-t-statmap-nii-gz`
- `glmfitlins:ds000009:balloonanalogrisktask:allpumps:dataset:z:unknown:task-balloonanalogrisktask-node-datalevel-contrast-allpumps-stat-z-statmap-nii-gz`
- `glmfitlins:ds000009:balloonanalogrisktask:allpumps:run:t:unknown:task-balloonanalogrisktask-node-runlevel-sub-01-sub-01-contrast-allpumps-stat-t-statmap-nii-gz`
- `glmfitlins:ds000009:balloonanalogrisktask:allpumps:run:t:unknown:task-balloonanalogrisktask-node-runlevel-sub-02-sub-02-contrast-allpumps-stat-t-statmap-nii-gz`
- `glmfitlins:ds000009:balloonanalogrisktask:allpumps:run:t:unknown:task-balloonanalogrisktask-node-runlevel-sub-03-sub-03-contrast-allpumps-stat-t-statmap-nii-gz`

Seed results: `5/5` positive

- `17`
- `17`
- `17`
- `17`
- `17`

Assessment: `pass`

## Gate Verdict

### `A1 Spatial Backbone`

Status: `PASS`

Passing probes:

- `TPR-01`
- `TPR-02`
- `TPR-04`
- `TPR-07`

### `A2 Anatomy Hierarchy`

Status: `PASS`

Passing probes:

- `TPR-03`
- `TPR-08`

### Overall `Gate A`

Status: `PASS`

Reason:

- the canonical spatial backbone is live
- the canonical anatomy hierarchy is now live
- all gate-critical typed paths are queryable on the current Neo4j snapshot

## Nonblocking Semantic Enrichment

The following remain visible but do not block substrate readiness:

- `ACTIVATES`
- `TPR-05`
- `TPR-06`

These will be canonicalized in a later semantic-enrichment pass, not in the
current substrate revision.
