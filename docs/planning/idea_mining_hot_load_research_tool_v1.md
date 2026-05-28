# Idea Mining Hot-Load Research Tool V1

Date: 2026-03-14

## Goal

Define the next architecture line for idea mining as a live research tool:

`fresh question -> seed resolution -> KG search + external deep research -> evidence-grounded candidate cards`

This is intentionally separate from the frozen replay-harness line.

## Why A New Line Is Needed

The replay baselines show that miner-side discrimination is not converging under
the current seed-driven bounded replay setup. The strongest value now lies in
the harness, not in more replay-only miner tuning.

The runtime, however, already has the beginnings of the desired path:

- deep research in the live web run path
- live KG novelty tool calls
- candidate-card projection

So the right move is not to keep widening replay packs. It is to connect these
existing live pieces into one hot-load path.

## Current Concrete Entry Points

### Live deep research and candidate generation

The live web run path already waits for deep research before candidate
synthesis in
[hypothesis-runner.ts](<repo>/apps/web-ui/src/lib/server/hypothesis-runner.ts#L1033).

The current flow:

- waits for deep research evidence
- builds an evidence pack
- generates candidate cards

### Live KG novelty sampling

The current adapter already calls KG novelty tools on fresh seed IDs in
[hypothesis-research-adapter.ts](<repo>/apps/web-ui/src/lib/server/hypothesis-research-adapter.ts#L2951).

It already hits:

- `kg_find_structural_leverage`
- `kg_sample_ood_hypothesis`
- `kg_detect_contradiction_motifs`

### Optional deep-research enrichment in CLI

The CLI path can already run optional blocking `google_deep_research`, but it
currently happens after cards are generated in
[agent_commands.py](<repo>/src/brain_researcher/cli/commands/agent_commands.py#L797).

That is the wrong side of the pipeline if the goal is evidence-grounded
candidate generation.

## Required Changes

### 1. Free-text query -> seed resolution

Current bottleneck:

- the system can accept fresh query text, and the first
  `free-text -> anchor bundle` resolver now exists
- however, anchor bundles still need downstream evidence to become truly useful

Main insertion point:

- [_resolve_semantic_seed_context()](<repo>/src/brain_researcher/services/neurokg/query_service.py#L6397)

Current concrete improvement:

- novelty-tool resolution now surfaces a traceable `resolved_anchor_bundle`
  instead of only raw `resolved_seed_kg_ids`
- live MCP candidate-card calls can therefore show which anchors were chosen
  for a fresh question

Required behavior:

- continue treating free-text query as a first-class seed source
- keep explicit entity extraction and node resolution visible to callers
- retain a traceable seed-resolution artifact, not just transient IDs

### 2. External literature evidence before or during verify

Current bottleneck:

- `verify_sampled_hypotheses()` mostly verifies against BR-KG-internal
  evidence neighborhoods
- deep research is not yet a first-class verifier input
- recent live MCP runs show that better anchors alone still yield
  `insufficient_evidence`, so this is now the dominant bottleneck

Main insertion points:

- [verify_sampled_hypotheses()](<repo>/src/brain_researcher/services/neurokg/query_service.py#L9921)
- [sample_and_verify_hypotheses()](<repo>/src/brain_researcher/services/neurokg/query_service.py#L10323)
- live deep research helpers in
  [deep_research.py](<repo>/src/brain_researcher/core/literature/deep_research.py)

Required behavior:

- external literature search should provide evidence candidates before final
  verdicting
- the verifier should distinguish:
  - KG-only evidence
  - literature-only evidence
  - joint KG + literature evidence

### 3. Candidate cards should be instantiated from real evidence, not only templates

Current bottleneck:

- direction patterns are still mostly template-fillers
- minimal tests and falsifiers are not grounded in retrieved literature

Main insertion points:

- [hypothesis_candidate_cards.py](<repo>/src/brain_researcher/services/agent/hypothesis_candidate_cards.py#L303)
- [direction_patterns.v1.json](<repo>/configs/hypothesis/direction_patterns.v1.json#L3)

Required behavior:

- preserve `taste_axis`
- replace pure template fill-in with evidence-instantiated:
  - minimal test
  - falsifier
  - supporting publication anchors

## Minimal V1 Build Plan

### Phase A. Hot-load seed resolution

Deliver:

- query-to-seed resolution artifact
- top resolved KG entities
- traceable fallback when no exact seed exists

### Phase B. Literature-augmented verify

Deliver:

- external evidence channel attached before final card synthesis
- verifier summary that reports whether support came from KG, literature, or both

### Phase C. Evidence-grounded cards

Deliver:

- cards with:
  - seed provenance
  - candidate provenance
  - verifier mode
  - literature anchors
  - evidence-instantiated discriminating test

## Non-Goals

This line should not:

- reopen replay-miner tuning as the main success criterion
- imply benchmark admission
- mix candidate-only evidence into benchmark claims
- claim autonomous discovery

## Success Criteria

This hot-load line is successful if:

- a fresh question can be run without prewritten manifest seeds
- the system resolves seeds and shows that resolution trace
- candidate cards cite external evidence anchors, not only KG-local structure
- some cards become meaningfully distinguishable by grounding quality
- the result is useful for human-in-the-loop research triage

## Relationship To The Frozen Line

The replay-harness line remains frozen as the evaluation and audit baseline.

The hot-load research-tool line should reuse:

- candidate-card schema
- routing states
- reviewer rubric
- candidate-lane separation

but it should not be judged by the replay miner's old success criterion of
`broad-vs-strict delta on frozen seed packs` alone.
