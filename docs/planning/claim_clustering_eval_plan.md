# Claim Clustering Eval Plan

Date: 2026-03-13

## Purpose

This note operationalizes the immediate next move after
[claim_canonicalization_adr.md](<repo>/docs/planning/claim_canonicalization_adr.md):

- build a bounded clustering evaluation pack
- tag failure modes explicitly
- decide what is safe enough to carry into `claim_snapshot_v1`

This is not a full-corpus clustering plan.

## Scope

In scope:

- bounded benchmark-oriented claim examples
- already reviewed or intentionally retained bootstrap examples
- explicit support/mixed/conflict seeds
- failure tagging on semantically noisy claim rows

Out of scope:

- full-graph claim clustering
- automatic graph rewrites
- turning clusters into live benchmark metrics immediately

## Input Sets

Primary sources:

- [claim_hypotheses_calibration_v3_lite.jsonl](<repo>/docs/planning/claim_hypotheses_calibration_v3_lite.jsonl)
- [claim_hypotheses_heldout_v3_lite.jsonl](<repo>/docs/planning/claim_hypotheses_heldout_v3_lite.jsonl)
- [pre_gate_b_claim_adjudication_pack_v1.jsonl](<repo>/docs/planning/pre_gate_b_claim_adjudication_pack_v1.jsonl)

Why these inputs:

- they already contain paper-local `claim_id`
- they preserve `paper_id`, `target_id`, `target_type`, `polarity`, and anchor
  evidence
- they already expose some noisy cases through warnings such as
  `title_only_evidence_present` and `claim_evidence_semantic_mismatch_present`

## Proposed Evaluation Slices

### Slice A. Stable single-paper controls

Purpose:

- verify that obvious one-claim examples remain singleton canonical claims

Seed types:

- accepted high-precision fixture claims
- clean accepted bootstrap support rows

Expected outcome:

- `singleton`
- high cluster confidence

### Slice B. Same-target opposing-stance examples

Purpose:

- test whether the clustering layer groups paper-local claims under one
  proposition while preserving paper-level support vs refute stance

Seed examples:

- `bootstrap:attention_mixed`
- `bootstrap:default_mode_network_conflicting`

Expected outcome:

- merge into one `canonical_claim_id` family per proposition
- preserve row-level polarity
- flag any semantic weakness that prevents reliable aggregation

### Slice C. Failure-taxonomy stress cases

Purpose:

- identify rows that look clusterable by target or text but should not be
  trusted as aggregation truth

Seed examples:

- title-only support rows
- rows with `claim_evidence_semantic_mismatch`
- rows with low or zero `method_rigor`
- composite concept rows retained in bootstrap-only benchmark seeds

Expected outcome:

- explicit `failure_tags`
- either `do_not_merge` or `merge_with_warning`

## Required Output Fields

The bounded clustering pack should include at least:

- `source_claim_id`
- `paper_id`
- `target_id`
- `target_type`
- `claim_text`
- `claim_kind`
- `polarity`
- `review_status`
- `evidence_depths`
- `warnings`
- `proposed_canonical_claim_id`
- `proposed_action`
  - `singleton`
  - `merge_same_proposition`
  - `merge_with_warning`
  - `do_not_merge`
- `cluster_confidence`
- `failure_tags`
- `notes`

## Failure Taxonomy To Apply

Minimum tags, inherited from
[claim_canonicalization_adr.md](<repo>/docs/planning/claim_canonicalization_adr.md):

- `target_mismatch`
- `granularity_mismatch`
- `polarity_or_antonym_confusion`
- `population_or_disease_scope_mismatch`
- `intervention_or_context_mismatch`
- `modality_or_method_leakage`
- `title_only_or_insufficient_text`
- `semantic_composite_or_analysis_claim`

## Exit Criterion

This evaluation step is complete only if:

- every row in the bounded pack has an explicit proposed action
- every non-clean row has at least one failure tag or a written reason for why
  it is still mergeable
- at least one mixed/conflicting example has been reviewed in a way that shows
  how canonical claim families should preserve stance disagreement

## Immediate Build Order

1. Assemble a bounded JSONL pack from the three input sources above.
2. Deduplicate by `source_claim_id`.
3. Hand-tag the first-pass failure taxonomy on the bounded set.
4. Review mixed/conflicting rows first.
5. Use the reviewed output as the input contract for `claim_snapshot_v1`.

## Practical Outcome

If this plan succeeds, the next freeze will no longer depend on implicit
paper-local rows. `claim_snapshot_v1` can then carry both:

- paper-local `Claim.id`
- reviewed `canonical_claim_id`

without pretending the live graph has already been rewritten.
