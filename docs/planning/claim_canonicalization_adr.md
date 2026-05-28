# Claim Canonicalization ADR

Date: 2026-03-13

Status: `accepted-for-v1-planning`

## Decision Summary

For `Workstream B`, `Claim.id` remains a paper-local ingest identifier.
Cross-paper claim aggregation will use a separate canonicalization layer rather
than rewriting live `Claim.id` values in place.

The first canonicalization surface will be a snapshot/evaluation artifact, not a
new source of graph truth.

## Context

The current repo already has a functioning claim-first runtime path, but it is
still vulnerable to paper-local fragmentation.

This risk is explicit in the execution plan:

- [neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md#L62)
- [neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md#L63)
- [neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md#L156)

It is also explicit in the roadmap:

- [roadmap.md](<repo>/docs/planning/roadmap.md#L73)

The current bounded benchmark deliberately excluded cross-paper claim
canonicalization:

- [claim_benchmark_charter.md](<repo>/docs/planning/claim_benchmark_charter.md#L56)

That was the right decision for the early claim-spine phase, but it cannot
remain implicit if later support/conflict aggregation or idea mining is meant to
operate at a reusable claim level.

### Current identity behavior

Today, live `Claim` objects are stable enough for ingest and query, but they are
not a canonical cross-paper claim identity.

Loader fallback identity:

- [gabriel_loader.py](<repo>/src/brain_researcher/services/neurokg/etl/loaders/gabriel_loader.py#L2077)

Generator fallback identity:

- [gabriel_generator.py](<repo>/src/brain_researcher/services/neurokg/etl/gabriel_generator.py#L2170)
- [gabriel_generator.py](<repo>/src/brain_researcher/services/neurokg/etl/gabriel_generator.py#L3131)

These two fallbacks are not identical:

- loader fallback hashes `(paper_id, target_id, claim_text)`
- generator fallback hashes `(paper_id, target_id, claim_text, measurement_index)`

This mismatch is survivable for current ingest because explicit IDs often pass
through and because both are still paper-local. It is not a safe basis for
cross-paper canonicalization.

### Query/runtime dependency

Current query paths treat `Claim` nodes as direct evidence anchors:

- [kg_verify_hypothesis_spec.md](<repo>/docs/specs/kg_verify_hypothesis_spec.md)
- [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L4525)
- [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L5232)

That means retroactively rewriting `Claim.id` in the live graph now would be a
high-risk change. It would cut across:

- `EvidenceSpan.claim_id`
- `REPORTS_CLAIM`
- `SUPPORTS`
- `GENERATED`
- held-out benchmark anchors that already point to existing `claim:*` IDs

## Decision

### 1. `Claim.id` remains paper-local in v1

`Claim.id` is frozen as an ingest/runtime identifier, not a canonical
cross-paper proposition ID.

Meaning:

- it must remain stable for existing live graph objects
- it must remain valid as the local anchor for `EvidenceSpan` and provenance
- it must not be reinterpreted as semantic claim identity across papers

Operational rule:

- no in-place live rewrite of existing `Claim.id` values in this phase

### 2. Add a separate canonical claim layer

Cross-paper aggregation will use a new canonicalization layer with a distinct
identifier, referred to in this ADR as `canonical_claim_id`.

This layer is conceptually above paper-local `Claim` nodes:

- many paper-local `Claim` rows may map to one `canonical_claim_id`
- paper-local `polarity` remains on the source `Claim`
- support/conflict aggregation is computed over multiple paper-local claims that
  map to the same canonical claim

Operational rule:

- the canonical layer is additive
- it does not replace paper-local `Claim` nodes

### 3. Canonicalization is snapshot-first, not graph-rewrite-first

The first implementation target is a snapshot/evaluation artifact used to test
clustering and adjudicate failure modes.

It is not, initially:

- a new live `CanonicalClaim` node type
- a mass backfill over all existing claim nodes
- a hard dependency for current verifier behavior

This keeps the first canonicalization phase compatible with:

- current benchmark paths
- current candidate-lane replay
- existing held-out anchors that reference paper-local `claim:*` IDs

### 4. Canonicalization keys are target-anchored and stance-aware

The canonical layer must not collapse claims by text alone.

Minimum canonicalization inputs for a candidate cluster:

- `target_id`
- `target_type`
- normalized proposition text or proposition signature
- normalized `claim_kind`
- relation/assumption context when present

`polarity` must not be baked into the canonical proposition ID itself.

Reason:

- support and refute findings about the same proposition must be able to
  aggregate into one canonical claim family
- polarity belongs to evidence stance, not proposition identity

### 5. Canonicalization scope for v1 is bounded

The first canonicalization pass should operate on a bounded, reviewed set, not
the whole graph.

In-scope rows for the first pass:

- benchmark-admitted claims from the bounded benchmark path
- reviewed candidate examples that were intentionally retained for conflict or
  coverage analysis

Out of scope for the first pass:

- raw unreviewed candidate-only backlog
- full-corpus claim clustering
- automatic use of canonical clusters as benchmark metrics without review

### 6. Failure taxonomy is mandatory before aggregate support/conflict is trusted

No cluster may be treated as reliable aggregation truth unless the failure mode
is visible.

The first-pass taxonomy must at least support:

- `target_mismatch`
- `granularity_mismatch`
- `polarity_or_antonym_confusion`
- `population_or_disease_scope_mismatch`
- `intervention_or_context_mismatch`
- `modality_or_method_leakage`
- `title_only_or_insufficient_text`
- `semantic_composite_or_analysis_claim`

Operational rule:

- aggregate support/conflict reporting must remain provisional until clustered
  examples are tagged against this taxonomy

## Consequences

### Positive consequences

- current live claim/evidence IDs remain stable
- benchmark artifacts that already reference paper-local claims do not break
- cross-paper aggregation can be prototyped without rewriting the live graph
- idea-mining work gains an explicit bridge from paper-local evidence to
  reusable claim families

### Costs

- there will be two identity layers for a while:
  - paper-local `Claim.id`
  - snapshot-level `canonical_claim_id`
- some reports will need to show both local and canonical IDs together
- implementation cannot stop at writing this ADR; it still needs:
  - clustering evaluation
  - failure taxonomy adjudication
  - a frozen `claim_snapshot_v1`

## Rejected Alternatives

### A. Rewrite live `Claim.id` to canonical IDs now

Rejected because:

- current query and evidence structures already depend on paper-local claim IDs
- loader/generator fallback identity is not yet unified
- held-out benchmark artifacts already anchor to existing paper-local IDs

### B. Treat `target_id` equality as claim equality

Rejected because:

- multiple different propositions can share the same target
- this would collapse unrelated findings into one pseudo-claim

### C. Cluster by raw text alone

Rejected because:

- text-only similarity will over-merge across targets, disease scopes, and
  methodological phrases
- it is too brittle for claim-level scientific aggregation

### D. Canonicalize the entire candidate lane first

Rejected because:

- the candidate lane is intentionally broader and noisier
- the first objective is to make claim aggregation explicit and testable on a
  bounded slice, not to cluster all weak evidence immediately

## V1 Artifact Contract

The first canonicalization snapshot should carry at least:

- `source_claim_id`
- `paper_id`
- `target_id`
- `target_type`
- `claim_text`
- `claim_kind`
- `polarity`
- `quality_profile`
- `candidate_lane_present`
- `benchmark_eligibility`
- `canonical_claim_id`
- `cluster_confidence`
- `failure_tags`
- `adjudication_status`

Operational rule:

- `claim_snapshot_v1` must preserve a reversible mapping from every
  `canonical_claim_id` back to its source paper-local claims

## Immediate Implementation Follow-Ups

1. Build a bounded clustering evaluation pack from the current reviewed
   benchmark-oriented claim set.
2. Run a first-pass clustering evaluation and tag failures using the taxonomy
   above.
3. Freeze `claim_snapshot_v1` only after the cluster mapping and failure tags
   are reviewable.

## Status Reading

This ADR is enough to satisfy the Week 9 requirement that claim aggregation
strategy be explicit.

It is not enough to satisfy the Week 10 requirement that cross-paper claim
clustering and failure modes be prototyped and adjudicated.
