# Resume Rebuild Runbook

As of March 10, 2026.

This runbook is the operational path for resuming `graph_substrate_readiness`
work after an interrupted or ambiguous BR-KG build.

## Purpose

Use this runbook to do three things in order:

1. reconnect to the live Neo4j-backed graph instead of trusting legacy SQLite
   artifacts
2. measure the actual live substrate before assuming the core backbone is
   missing
3. publish fresh counts and typed-path checks before any graph-learning work

## Do Not Start Here

Do not treat the following as authoritative rebuild evidence:

- `data/neurokg/neurokg_graph.db`
- `data/neurokg/dual_evidence.db`
- `docs/services/neurokg/EDGE_INTEGRATION_SUMMARY.md`
- `scripts/linking/run_node_matching.py`

Why:

- the local `.db` files in this workspace are stubs or mini-dev artifacts, not a
  reproducible substrate snapshot
- the integration summary is historical intent, not proof of current graph state
- `scripts/linking/run_node_matching.py` is still framed as a legacy SQLite-style script
  for `SAME_AS`, not a graph-substrate rebuild entrypoint

## Active Entry Points

Current active entrypoints are Neo4j-first:

- `br db init`
- `br db validate`
- `br db status`
- `br serve kg`
- `br query cypher`
- `python -m brain_researcher.services.neurokg.etl.load_all ...`
- `python scripts/neurokg/materialize_brainregion_hierarchy.py ...`

Current operational rule:

- any rebuild that cannot be validated against a live Neo4j target does not
  count as substrate recovery
- any bulk rebuild that starts before a fresh live baseline also does not count
  as careful recovery

## Required Environment

Minimum required environment:

```bash
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="..."
export NEO4J_DATABASE="${NEO4J_DATABASE:-neo4j}"
```

Recommended preflight:

```bash
br db validate
br db status
```

If the API is needed for quick stats:

```bash
br serve kg --port 5000
curl http://localhost:5000/health
curl http://localhost:5000/api/statistics
```

## Phase 0: Freeze A Fresh Baseline

Before rebuilding anything, capture the live counts that will be overwritten.

Recommended commands:

```bash
br db status
br query stats
br query cypher "MATCH (n:Publication) RETURN count(n) AS cnt"
br query cypher "MATCH (n:Coordinate) RETURN count(n) AS cnt"
br query cypher "MATCH (n:BrainRegion) RETURN count(n) AS cnt"
br query cypher "MATCH (n:Atlas) RETURN count(n) AS cnt"
br query cypher "MATCH ()-[r:HAS_COORDINATE]->() RETURN count(r) AS cnt"
br query cypher "MATCH ()-[r:IN_REGION]->() RETURN count(r) AS cnt"
br query cypher "MATCH ()-[r:PART_OF]->() RETURN count(r) AS cnt"
br query cypher "MATCH ()-[r:MEASURES]->() RETURN count(r) AS cnt"
br query cypher "MATCH ()-[r:CITES]->() RETURN count(r) AS cnt"
```

Publish those counts into `graph_baseline_report.md` before changing the graph.

Additional required shape checks:

```bash
br query cypher "MATCH (a)-[r:IN_REGION]->(b) RETURN labels(a) AS from_labels, labels(b) AS to_labels, count(r) AS cnt ORDER BY cnt DESC LIMIT 10"
br query cypher "MATCH (a)-[r:PART_OF]->(b) RETURN labels(a) AS from_labels, labels(b) AS to_labels, count(r) AS cnt ORDER BY cnt DESC LIMIT 10"
```

Tracked but nonblocking semantic-enrichment checks:

```bash
br query cypher "MATCH (n:Region) RETURN count(n) AS cnt"
br query cypher "MATCH ()-[r:ACTIVATES]->() RETURN count(r) AS cnt"
br query cypher "MATCH (a)-[r:ACTIVATES]->(b) RETURN labels(a) AS from_labels, labels(b) AS to_labels, count(r) AS cnt ORDER BY cnt DESC LIMIT 10"
```

Current live finding from this workspace:

- `HAS_COORDINATE` is already live at scale
- canonical `IN_REGION` is `StatsMap -> BrainRegion`
- live `PART_OF` currently exists only as `Dataset|DataResource -> Consortium`

Operational rule:

- do not start a rebuild just because an older planning doc says an edge family
  is missing
- first prove whether the issue is truly missing coverage or live contract drift

## Phase 1: Initialize Schema

Initialize the Neo4j schema before any backfill or source load:

```bash
br db init
```

Operational notes:

- `br db init` is the active replacement for the old `init_database.py` flow.
- `--force` is not supported for Neo4j schema initialization.
- This step only sets up schema objects; it does not restore graph coverage by
  itself.

## Phase 2: Restore The Publication-Coordinate Backbone

Do not run this step by default on the current live graph.

Why:

- the current live snapshot already has `447,499` `HAS_COORDINATE` edges
- the current problem is not missing publication-coordinate edges
- the current problem is that downstream spatial paths do not satisfy the
  declared contract

Only run this phase if:

- `HAS_COORDINATE` regresses in a future snapshot
- or a new environment is actually missing the publication-coordinate backbone

Preferred targeted path:

```bash
python scripts/tools/ingest/neurosynth_spine.py \
  --dataset-dir data/neurosynth_nimare/neurosynth_v7 \
  --neo4j-uri "$NEO4J_URI" \
  --neo4j-user "$NEO4J_USER" \
  --neo4j-password "$NEO4J_PASSWORD" \
  --neo4j-database "$NEO4J_DATABASE"
```

What this restores:

- `Publication`
- `Coordinate`
- `HAS_COORDINATE`
- `IN_SPACE`

Operational rule:

- Prefer this targeted recovery for the `HAS_COORDINATE` backbone instead of
  waiting for a monolithic full reload.

## Phase 3: Rebuild Core Source Nodes

If the live graph is missing core node families beyond the Neurosynth spine,
reload the core sources:

```bash
python -m brain_researcher.services.neurokg.etl.load_all \
  --sources pubmed neurosynth cognitive_atlas neurovault niclip \
  --full
```

If you need a config-driven run:

```bash
python -m brain_researcher.services.neurokg.etl.load_all \
  --sources pubmed neurosynth cognitive_atlas neurovault niclip \
  --config <path-to-config.json>
```

Operational notes:

- `--db` is deprecated and ignored; Neo4j env vars are required.
- This path is useful for node recovery, but it does not prove that the key
  edge families are already restored.

## Phase 4: Restore Atlas And BrainRegion Coverage

`BrainRegion` and `Atlas` are gating for the canonical substrate, while
`Region` is now a future-enrichment lane.

Current contract:

- `BrainRegion` is the canonical public spatial/anatomy node
- `Region` remains compatibility and future enrichment only

### 4A. Atlas Metadata Path

Load Yeo atlas metadata into Neo4j:

```bash
python scripts/load_yeo_atlas_to_neo4j.py
```

What this gives you:

- `Atlas`
- `Parcellation`
- `Parcel`
- atlas citation metadata

### 4B. Compatibility Region Backfill

If the current downstream graph still depends on legacy `Region`-style
compatibility objects,
the repo also includes:

```bash
python scripts/import_atlases_neo4j.py
```

Important warning:

- `import_atlases_neo4j.py` writes `BrainRegion`, not the `Region` contract used
  by older docs.
- In the current contract, this path is now aligned with the canonical anatomy
  target rather than a legacy exception.

### 4C. Canonical Anatomy Hierarchy Backfill

Use the dedicated materializer to create canonical
`BrainRegion -> PART_OF -> BrainRegion` edges:

```bash
python scripts/neurokg/materialize_brainregion_hierarchy.py \
  --base-path "${NEUROMAPS_ROOT:-data/atlases/neuromaps}"
```

What this gives you:

- explicit `PART_OF` edges from atlas metadata when parent-like columns exist
- atlas-native fallback parents for `Yeo17`
- atlas-local network parents for Schaefer variants

Operational rule:

- this is the scoped `A2` recovery step
- do not reopen `Coordinate -> Region` work to unblock `Gate A`
- rerun `typed_path_regression_report.md` after this step and verify `TPR-03`
  and `TPR-08`

Current live outcome from this workspace:

- the dedicated materializer produced `317` canonical
  `BrainRegion -> PART_OF -> BrainRegion` edges
- `TPR-03` and `TPR-08` both passed immediately after the run

## Phase 5: Restore Spatial Coverage

Once nonzero canonical `BrainRegion` coverage exists, spatial edge work can
resume.

Concrete repo path already in use:

```bash
scripts/ingest/run_openneuro_glmfitlins_ingest_neo4j.sh
scripts/ingest/run_openneuro_glmfitlins_yeo17_recompute.sh
```

This path is useful for:

- `StatsMap` ingest
- Yeo17 summary generation
- `IN_REGION` edge recomputation for GLM FitLins maps

Operational warning:

- this is now the canonical spatial lane for substrate readiness
- do not treat missing `Coordinate -> Region` as a blocker for current
  readiness work

## Phase 6: Restore Semantic Coverage

After the spatial backbone is no longer blocked:

- restore or validate `MEASURES`
- add first-pass `CITES`
- track `ACTIVATES` separately as post-`Gate A` enrichment

Current live execution finding:

- `MEASURES` exists at `10,875`
- `ACTIVATES` exists at only `6`
- `CITES` exists at `3,397`, but only `56` source publications currently cite
  another publication

Operational rule:

- treat `CITES` as a sparse-coverage improvement problem
- treat `ACTIVATES` as a separate semantic-enrichment track, not a substrate
  blocker

Useful repo paths:

- `scripts/neurokg/cleanup_measures_provenance.py`
- `scripts/tools/jobs/promote_suggestions.py`
- `br niclip load ...` for NiCLIP-derived edges

Practical note on `br niclip load`:

- the current CLI still requires a `--db` path argument for parsing, but the
  implementation ignores it and uses Neo4j env vars at runtime
- use it only after the publication/concept/task backbone is already present

## Phase 7: Validate Coverage Recovery

After every rebuild stage, rerun counts and typed-path probes.

Minimum count checks:

```bash
br query cypher "MATCH (n:Publication) RETURN count(n) AS cnt"
br query cypher "MATCH (n:Coordinate) RETURN count(n) AS cnt"
br query cypher "MATCH (n:BrainRegion) RETURN count(n) AS cnt"
br query cypher "MATCH (n:Atlas) RETURN count(n) AS cnt"
br query cypher "MATCH ()-[r:HAS_COORDINATE]->() RETURN count(r) AS cnt"
br query cypher "MATCH ()-[r:IN_REGION]->() RETURN count(r) AS cnt"
br query cypher "MATCH ()-[r:PART_OF]->() RETURN count(r) AS cnt"
br query cypher "MATCH ()-[r:MEASURES]->() RETURN count(r) AS cnt"
br query cypher "MATCH ()-[r:CITES]->() RETURN count(r) AS cnt"
```

Minimum shape checks:

```bash
br query cypher "MATCH (a)-[r:IN_REGION]->(b) RETURN labels(a) AS from_labels, labels(b) AS to_labels, count(r) AS cnt ORDER BY cnt DESC LIMIT 10"
br query cypher "MATCH (a)-[r:PART_OF]->(b) RETURN labels(a) AS from_labels, labels(b) AS to_labels, count(r) AS cnt ORDER BY cnt DESC LIMIT 10"
```

Tracked but nonblocking semantic-enrichment checks:

```bash
br query cypher "MATCH (n:Region) RETURN count(n) AS cnt"
br query cypher "MATCH ()-[r:ACTIVATES]->() RETURN count(r) AS cnt"
br query cypher "MATCH (a)-[r:ACTIVATES]->(b) RETURN labels(a) AS from_labels, labels(b) AS to_labels, count(r) AS cnt ORDER BY cnt DESC LIMIT 10"
```

Minimum connectivity checks:

```bash
curl http://localhost:5000/api/statistics/connectivity
curl http://localhost:5000/api/statistics
```

Publish the result into:

- `graph_baseline_report.md`
- `typed_path_regression_report.md`

## Resume Rules

- If schema init succeeded, do not restart from legacy SQLite initialization.
- If the publication-coordinate backbone is missing, start with
  `neurosynth_spine.py` before broader ingest.
- If `HAS_COORDINATE` is already present at scale, do not rerun Neurosynth spine
  until the live snapshot is backed up and the real gap is confirmed.
- If a source-specific ingest has checkpoints or manifests, resume from that
  source-specific entrypoint rather than re-running unrelated loaders.
- If live counts and docs disagree, trust live Neo4j counts and update the
  planning docs immediately.

## Stop Conditions

Stop and do not continue to graph learning if any of the following remain true:

- canonical `BrainRegion` count is still `0`
- `Atlas` count is still `0`
- `HAS_COORDINATE` is still absent or near-zero
- canonical `StatsMap -> IN_REGION -> BrainRegion` is not queryable
- canonical `BrainRegion -> PART_OF -> BrainRegion` is still absent
- live counts still cannot reproduce a usable typed path
- the hierarchy blocker for `A2` is still unresolved
