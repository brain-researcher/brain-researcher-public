# Candidate Card Rubric V1

Date: 2026-03-14

## Purpose

This rubric scores `idea mining` candidate cards as review artifacts.

It is not a benchmark leaderboard metric.

Its job is to help route a card into one of:

- `promote_for_candidate_review`
- `hold_for_refinement`
- `retire_from_candidate_pack`
- `codify_failure_pattern`

## Scoring Scale

Each dimension is scored on `0-3`.

- `0`: missing or unusable
- `1`: weak, vague, or degraded
- `2`: usable but incomplete
- `3`: strong and review-ready

## Dimensions

### 1. Evidence Grounding

Question:

- does the card point to a real claim/evidence neighborhood rather than only a
  surface-level semantic association

High score requires:

- exact or near-exact KG anchors
- verifier output present
- no dependence on fallback-only reasoning

### 2. Candidate-Lane Separation

Question:

- is it clear whether the card relies on `broad` candidate-lane evidence, and
  can that be distinguished from benchmark-facing evidence

High score requires:

- explicit `candidate_lane_mode`
- explicit provenance
- no ambiguity about benchmark eligibility

### 3. Novelty Specificity

Question:

- is the hypothesis specific enough to be reviewable, or is it generic

High score requires:

- a concrete candidate relation or mechanism
- bounded target scope
- no generic "interesting connection" language

### 4. Discriminating Testability

Question:

- does the card suggest a minimal test or falsifier that would actually reduce
  uncertainty

High score requires:

- a discriminating test
- a falsifier
- a meaningful decision boundary between success and failure

### 5. Routing Clarity

Question:

- after reading the card, is the next action obvious

High score requires one of:

- route to candidate review
- hold for refinement
- retire
- codify a repeated failure pattern

### 6. Provenance Integrity

Question:

- are the seed, verifier mode, and supporting workflow artifacts visible enough
  that the card can be replayed

High score requires:

- replayable seed id
- workflow source
- verifier mode
- candidate provenance block if applicable

## Routing Rules

### Promote For Candidate Review

Use when:

- total score `>= 14`
- `Evidence Grounding >= 2`
- `Routing Clarity >= 2`
- no fallback-only failure

### Hold For Refinement

Use when:

- total score `9-13`
- the card has a plausible mechanism but weak grounding or poor routing

### Retire From Candidate Pack

Use when:

- total score `<= 8`
- or the card is broad, generic, and not discriminating

### Codify Failure Pattern

Use when:

- a weak card also expresses a recurring failure motif
- for example:
  - title-only drift
  - generic concept inflation
  - benchmark/candidate ambiguity
  - fallback-overconfident synthesis

## Artifact Contract

Machine-readable rubric:

- [candidate_card_rubric_v1.json](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v1_20260314/candidate_card_rubric_v1.json)

The JSON artifact freezes:

- dimensions
- weights
- routing thresholds
- fail-closed exclusions

## Non-Goal

This rubric does not decide benchmark admission.

It only governs candidate-card review quality inside the bounded idea-mining
workflow.
