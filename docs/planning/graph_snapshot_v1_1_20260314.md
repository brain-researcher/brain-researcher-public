# Graph Snapshot V1.1

Date: 2026-03-14

## Scope

This note explicitly binds the current graph-side freeze into the Step 4
readiness packet as `graph_snapshot_v1_1`.

This is a manifest-style binding artifact, not a new full database export.

## Artifact

Manifest:

- [graph_snapshot_v1_1_manifest.json](<repo>/data/neurokg/raw/graph_snapshot_v1_1/bound_20260314/graph_snapshot_v1_1_manifest.json)

Supporting graph-side evidence:

- [graph_baseline_report.md](<repo>/docs/planning/graph_baseline_report.md)
- [typed_path_regression_report.md](<repo>/docs/planning/typed_path_regression_report.md)
- [graph_contract_v1.md](<repo>/docs/planning/graph_contract_v1.md)

## Bound Freeze

This binding freezes the following graph-side readiness facts into one named
artifact:

- `Gate A1 = PASS`
- `Gate A2 = PASS`
- `Gate A overall = PASS`
- `TPR-01`, `TPR-02`, `TPR-03`, `TPR-04`, `TPR-07`, `TPR-08` all `pass`
- `canonical_part_of_edges = 317`
- `canonical_two_hop_spatial_hierarchy_paths = 121,261`

## Intended Use

This artifact exists so the readiness packet no longer has to infer
`graph_snapshot_v1_1` indirectly from multiple older reports.

It is sufficient for:

- packet-level Step 4 review
- explicit graph-side snapshot naming
- binding the current graph-side pass state into
  [readiness_packet_20260314.md](<repo>/docs/planning/readiness_packet_20260314.md)

It is not sufficient by itself for:

- declaring the full final gate passed
- claiming a fresh full-graph export was produced
- skipping the remaining Step 11/12 closeout artifacts

## Remaining Caveat

Binding `graph_snapshot_v1_1` removes one ambiguity from the readiness packet,
but it does not complete the whole final-gate bundle. The remaining gap is now
the downstream closeout layer:

- task charter
- train/dev/test split proposal
- final next-quarter roadmap / decision packet completeness
