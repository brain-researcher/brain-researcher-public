# Candidate Refinement Workflow V1

Date: 2026-03-14

## Purpose

This workflow adapts the useful part of external "proposal -> review ->
refine" systems to Brain Researcher.

Its scope is intentionally narrow:

- refine `candidate-only` idea-mining outputs
- preserve provenance and verifier mode
- route outcomes into review artifacts

It does **not** reopen `novelty_architecture`.

## Input

The workflow takes:

- replayed candidate cards from
  [idea_mining_replay_pack_v1.md](<repo>/docs/planning/idea_mining_replay_pack_v1.md)
- the scoring contract from
  [candidate_card_rubric_v1.md](<repo>/docs/planning/candidate_card_rubric_v1.md)

## Stages

### Stage 1. Generate

Run the bounded replay pack and collect candidate cards with:

- workflow result
- verifier mode
- candidate provenance

### Stage 2. Review

Score each card against the rubric.

Required outputs:

- per-card scores
- reviewer notes
- failure tags when applicable

### Stage 3. Refine

Refine only cards that are:

- plausibly grounded
- but still weak on specificity, routing, or testability

Allowed refinement actions:

- sharpen the hypothesis statement
- sharpen the discriminating test
- clarify route: `promote`, `hold`, `retire`, or `codify`

Disallowed refinement actions:

- invent new evidence
- remove candidate-lane provenance
- collapse benchmark and candidate semantics

### Stage 4. Route

Every refined card must end in one of:

- `promote_for_candidate_review`
- `hold_for_refinement`
- `retire_from_candidate_pack`
- `codify_failure_pattern`

### Stage 5. Codify

If a failure pattern repeats, write it back into the system as:

- a manifest field
- a validation rule
- a workflow gate
- a review heuristic

## Output Artifacts

Machine-readable workflow skeleton:

- [candidate_refinement_workflow_v1.json](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v1_20260314/candidate_refinement_workflow_v1.json)

Placeholder runtime-output skeletons now exist at:

- [candidate_card_review_rows.jsonl](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v1_20260314/candidate_card_review_rows.jsonl)
- [candidate_card_refinement_log.jsonl](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v1_20260314/candidate_card_refinement_log.jsonl)
- [candidate_card_routing_decisions.jsonl](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v1_20260314/candidate_card_routing_decisions.jsonl)
- [candidate_card_codified_failures.jsonl](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v1_20260314/candidate_card_codified_failures.jsonl)
- [idea_mining_outcome_ledger_v1.jsonl](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v1_20260314/idea_mining_outcome_ledger_v1.jsonl)

These are still template-only in `v1`; they freeze the review/refine/routing
contract, but do not yet claim that the replay loop has been executed.

## Human Review Boundary

Human review remains mandatory at:

- final routing from candidate card into review packet
- any attempt to interpret a refined card as benchmark-admissible
- any codification that changes a promotion or exclusion rule

## Success Criterion

The workflow is useful if it reduces ambiguity.

Specifically:

- fewer cards should end in "interesting but unclear"
- more cards should end in a concrete routing state
- recurring weak patterns should become codified failures rather than repeated
  reviewer comments
