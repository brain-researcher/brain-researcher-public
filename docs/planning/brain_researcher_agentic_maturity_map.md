# Brain Researcher Agentic Maturity Map

Date: 2026-03-14

## Purpose

This note adapts the "8-layer agentic engineering" framing to the current
Brain Researcher system.

It is not a vanity scorecard. It is meant to answer:

- which parts of the repo are still tool-centric rather than harness-centric
- where `idea mining` currently sits
- what can be borrowed from external refinement workflows without reopening
  `novelty_architecture`

## Interpretation Rule

The source 8-layer model is useful as a diagnostic vocabulary, but not as a
strict linear maturity ladder.

For Brain Researcher, the useful reading is:

- `L1-L3`: session productivity and local context control
- `L4-L5`: accumulated workflow rules plus tool-connected execution
- `L6`: harnessed self-check loops with replay, validation, and regression
- `L7`: durable long-horizon execution and recoverability
- `L8`: stable multi-agent collaboration on top of `L6/L7`, not instead of them

## Current Track Map

### Repo Development Flow

Current level:

- `L5`, with `L6` fragments

Why:

- rules, manifests, CLI entrypoints, and tool surfaces are already codified
- many code paths now include tests and fail-closed checks
- but the repo is still uneven in replayability and post-change validation

### Evidence / Claim / Task-Panel Engineering

Current level:

- `L6`

Why:

- builders, apply scripts, reroute packs, split manifests, post-apply dry-runs,
  and regression tests are already present
- this line no longer behaves like prompt-level experimentation

### Idea Mining Runtime

Current level:

- `L5`, moving toward `L6`

Why:

- novelty tools, Hypothesis Explorer runtime, candidate cards, strict/broad
  verifier controls, and candidate provenance are implemented
- but idea quality is still not governed by a stable replay harness or a fixed
  reviewer rubric

### Long-Horizon Execution

Current level:

- `L7 partial`

Why:

- packets, manifests, run summaries, and candidate-lane provenance exist
- but there is not yet a unified effect log, resumability contract, or durable
  step-recovery surface across the whole stack

### Multi-Agent Collaboration

Current level:

- experimental pre-`L8`

Why:

- subagents are already useful for bounded parallel work
- but the repo should not treat multi-agent orchestration as the next milestone
  until `L6` harnesses are stronger

## What We Should Learn From Auto-Research-Refine

Useful parts:

- explicit `generate -> review -> refine -> log` loops
- reviewer-style scoring criteria instead of vague taste judgments
- persistent artifacts per iteration
- writing lessons back into rules, manifests, and gating logic

Useful only with adaptation:

- refinement must stay inside `candidate-only` / analyst-assisted space
- "research" must mean claim-first KG grounding, not generic literature prose
- "review" must produce routing signals such as `promote`, `hold`, `retire`,
  or `codify`, not only higher-scoring text

Parts we should not copy:

- self-reinforcing proposal loops that blur candidate and benchmark evidence
- any framing that implies `novelty_architecture` is already unblocked
- optimization for polished narrative over audited evidence paths

## Program Decision

The right near-term move is:

- do not start a new architecture track
- do not chase `L7/L8` branding
- push `idea mining` from `L5` tooling into `L6` harness engineering

That means:

- fixed seeds
- fixed replay packs
- a candidate-card rubric
- a bounded refinement workflow
- explicit routing and codification outputs

## New Program Artifacts

This maturity map is paired with:

- [idea_mining_seed_set_v1.md](<repo>/docs/planning/idea_mining_seed_set_v1.md)
- [candidate_card_rubric_v1.md](<repo>/docs/planning/candidate_card_rubric_v1.md)
- [idea_mining_replay_pack_v1.md](<repo>/docs/planning/idea_mining_replay_pack_v1.md)
- [candidate_refinement_workflow_v1.md](<repo>/docs/planning/candidate_refinement_workflow_v1.md)
- [brain_researcher_agentic_maturity_map.json](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v1_20260314/brain_researcher_agentic_maturity_map.json)

## Immediate Next Move

The next milestone is not "more agents."

The next milestone is:

- run the replay pack over a fixed seed set
- score the resulting cards with the rubric
- route them through the bounded refinement workflow
- keep all outputs inside candidate-lane review artifacts
