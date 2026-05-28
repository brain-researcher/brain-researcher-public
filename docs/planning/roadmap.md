# Brain Researcher Active Roadmap

As of March 10, 2026.

This document is the human-readable companion to `configs/planning/active_tracks.yaml`.
The YAML is the compact machine-readable registry for automation and validation.
This document explains why each track is active, what is in scope now, and what
counts as done.

## Operating Rules

- Keep `track_id` values stable once published.
- Keep only active, at-risk, or blocked work in the YAML registry.
- When a track closes, remove it from the active registry and summarize the
  outcome in the relevant issue, release note, or archive document.
- Update this document and the YAML in the same change so the validator can keep
  them aligned.

## Current Tracks

### `graph_substrate_readiness`

Track title: BR-KG graph substrate readiness before graph learning

- Status: `active`
- Priority: `P0`
- Owner: `neurokg-architecture`
- Target: April 21, 2026

Goal:
Turn BR-KG into a structurally usable typed graph before any new graph
learning or relation-operator work starts.

Current scope:
- Reconcile config, docs, and actual snapshot counts into one source of truth.
- Freeze `BrainRegion` as the canonical public spatial/anatomy node for the
  substrate contract.
- Treat `StatsMap -> IN_REGION -> BrainRegion` as the canonical spatial path.
- Keep `Publication -> HAS_COORDINATE -> Coordinate` as the literature
  backbone.
- Split `Gate A` into `A1 spatial backbone` and `A2 anatomy hierarchy`.
- Treat `ACTIVATES` as tracked semantic enrichment, not a substrate blocker.

Done when:
- The graph clears the minimum structural floor defined in the execution plan.
- `A1 spatial backbone` passes on the canonical BrainRegion contract.
- `A2 anatomy hierarchy` is either passed or isolated as the only remaining
  blocker with a scoped follow-up task.
- Config, docs, and snapshot counts agree closely enough for benchmark use.
- A frozen `graph_snapshot_v1` exists with typed path probes and coverage
  diagnostics.

### `claim_spine_readiness`

Track title: BR-KG claim-centric spine and claim-first verification readiness

- Status: `active`
- Priority: `P0`
- Owner: `neurokg-quality`
- Target: May 5, 2026

Goal:
Make claim-first evidence a real audited runtime path rather than a planned
schema surface.

Current scope:
- Keep the bounded GABRIEL ingest path green for `Claim`, `EvidenceSpan`, and
  `MeasurementRun`.
- Materialize `MENTIONS`, `MENTIONS_REGION`, `REPORTS_CLAIM`, `SUPPORTS`, and
  `GENERATED` with provenance-complete payloads.
- Benchmark `kg_verify_hypothesis` in claim-first mode against mention-level
  fallback.
- Design around cross-paper claim fragmentation before support/conflict
  aggregation is treated as scientific signal.

Done when:
- Claim-first verification is operational and auditable end to end.
- Required claim/evidence/run fields are present and validated on ingest.
- The bounded benchmark shows claim-first evidence is better than or materially
  more auditable than mention fallback.
- A frozen `claim_snapshot_v1` exists with reviewed examples and provenance
  outputs.

### `evidence_coverage_expansion`

Track title: BR-KG evidence coverage expansion with guarded candidate lanes

- Status: `active`
- Priority: `P0`
- Owner: `neurokg-quality`
- Target: May 19, 2026

Goal:
Increase auditable evidence coverage without treating raw candidate generation
as graph truth and without contaminating the benchmark lane.

Current scope:
- Keep `GABRIEL high_precision` as the benchmark lane.
- Use `balanced_marginal` and `kg_bootstrap` only as guarded candidate lanes.
- Use `KGGEN -> ONVOC -> task-panel -> GABRIEL ingest` as the normalization
  bridge for expanding task coverage.
- Reconcile richer claim-first relation families across edge schemas, bulk
  validation, and canonical mapping before scaling them.
- Deduplicate review-queue accounting and route promotion through tracked
  adjudication and re-ingest paths only.

Done when:
- Accepted claim/evidence/run objects grow materially without changing the
  benchmark-lane contract.
- ONVOC-backed normalization produces measurable `Task` coverage growth.
- Richer relation families such as contradiction, null-result, replication, and
  challenged-assumption edges appear at usable nonzero counts.
- Claim-first runtime paths measurably use those richer evidence objects rather
  than silently collapsing back to mention-only behavior.

### `hypothesis_quality`

Track title: Hypothesis sampler quality, gating, and exact resolution

- Status: `active`
- Priority: `P0`
- Owner: `neurokg-quality`
- Target: March 17, 2026

Goal:
Keep the main line on grounded hypothesis generation by improving sampler
quality, preserving meaningful rejections, and stabilizing exact entity
resolution.

Current scope:
- Preserve and expose real rejection diagnostics rather than inferring them from
  empty outputs.
- Keep exact-ID entity resolution precedence stable in the presence of task and
  subject name collisions.
- Use local probe paths to validate quality gates before making new
  architecture decisions.

Done when:
- At least one representative probe returns a grounded non-empty candidate or
  an explicit explained rejection.
- Exact-ID regression remains green for known collision cases.
- Quality-gate behavior is visible in tests and local probe diagnostics.

### `dataset_asset_browse`

Track title: Browse-first dataset asset surface

- Status: `active`
- Priority: `P1`
- Owner: `datasets-runtime`
- Target: March 24, 2026

Goal:
Add a browse-first dataset asset surface that complements dataset resource
summary tools and strict asset resolution, while keeping provenance stable
across browse and resolve.

Current scope:
- Lock the public browse contract for raw BIDS files, events, confounds,
  derivative roots, and stat maps.
- Reuse existing dataset resolution helpers rather than creating another
  catalog or matching path.
- Add focused unit and MCP coverage for browse behavior and safe defaults.
- Normalize `canonical_id`, `source`, `relative_path`, `checksum`,
  `estimator`, and `level` across browse/resolve outputs.

Done when:
- Browse and resolve responsibilities are clearly separated.
- The browse contract is stable enough for hosted exposure and agent usage.
- Exact-path requests still bypass browse safely.

### `novelty_architecture`

Track title: Novelty and research-taste architecture

- Status: `blocked`
- Priority: `P2`
- Owner: `neurokg-architecture`
- Target: March 31, 2026

Goal:
Defer new novelty/taste surface design until the hypothesis-quality baseline is
validated on real probes.

Current scope:
- Keep the blocked scope explicit so future sessions do not restart
  architecture work before validation.
- Re-open architecture choices only after the P0 quality exit criteria are met.
- Tie any future novelty design work to concrete validated evidence, not fresh
  repo exploration.

Done when:
- Architecture work is unblocked only by explicit P0 completion.
- Future novelty work starts from grounded evidence rather than fresh
  exploration.
- Deferred scope is documented clearly enough to avoid parallel drift.
