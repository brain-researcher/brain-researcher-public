# Idea Mining Line Conclusion

Date: 2026-03-14

## Decision

This line should now be split into:

- `KEEP`: the replay harness, candidate-card projection, review/refine/routing
  ledger, and strict/broad verifier surface
- `NO-GO FOR NOW`: miner-side novelty discrimination as a headline capability

This is a line conclusion, not a new architecture proposal.

## Frozen Baselines

The following three runs should be treated as frozen baselines of record:

- [idea_mining_replay_pack_v1_first_pass_20260314.md](<repo>/docs/planning/idea_mining_replay_pack_v1_first_pass_20260314.md)
- [idea_mining_replay_pack_v2_first_pass_20260314.md](<repo>/docs/planning/idea_mining_replay_pack_v2_first_pass_20260314.md)
- [idea_mining_replay_pack_v2_tightened_20260314.md](<repo>/docs/planning/idea_mining_replay_pack_v2_tightened_20260314.md)

## What The Data Actually Says

Across `v1`, `v2`, and tightened `v2`, candidate volume moved but discrimination
did not:

- `v1`: `12` successful runs, `16` cards, `0` meaningful broad-vs-strict delta
- `v2`: `16` successful runs, `26` cards, `0` meaningful broad-vs-strict delta
- tightened `v2`: `16` successful runs, `24` cards, `0` meaningful broad-vs-strict delta

The strongest negative control result is stable across both `v2` runs:

- `concept:reward_learning` yields `0` cards in both `broad` and `strict`

The query-side tightening was directionally correct, but not decisive:

- candidate cards dropped `26 -> 24`
- `SEARCH_EXPANDED` rows dropped `23 -> 19`
- weak dataset-style bridges were reduced
- no meaningful routing split emerged

Subsequent live MCP runs reinforce the same diagnosis:

- manual anchor bundles can now stabilize the query neighborhood
- free-text resolution has been improved into a traceable `anchor bundle`
  rather than a single opaque seed
- the live query `fmri-based image decoding` now resolves to plausible anchors
  such as `Visual image reconstruction`, `Generic Object Decoding (fMRI on
  ImageNet)`, and `Cross-decoding of natural scenes`
- despite that improvement, returned cards still remain
  `insufficient_evidence`

This means the bottleneck has moved downstream. The main failure is no longer
`seed resolution is too noisy`, but rather:

- `verify` still depends too heavily on sparse BR-KG-internal evidence
- publication linkage remains thin enough that plausible candidates still
  collapse into `insufficient_evidence`
- improving upstream seed selection alone is now a diminishing-return path

## What We Can Claim

The current line successfully provides:

- a live novelty/query runtime
- candidate-card projection from workflow outputs
- broad-vs-strict verifier controls
- replayable seed packs and fixed-baseline runs
- reviewer-style scoring and routing artifacts
- refinement taxonomy for repeated failure motifs

This supports the claim that Brain Researcher now has a bounded,
audit-friendly `structured hypothesis triage` capability.

## What We Should Not Claim

The current line does **not** support the claim that Brain Researcher has a
robust `automated novelty detection` or `automated hypothesis discovery`
capability.

The current evidence is insufficient for that stronger claim because:

- miner output remains uniformly weakly grounded
- broad-vs-strict verification does not separate candidates in practice
- routing does not split into promote/retire in a meaningful way
- the positive control remains zero-card

## Runtime Interpretation

The repo now contains two distinct things that should not be conflated.

### 1. Live Runtime

The product/runtime path is partially live:

- Hypothesis Explorer can accept fresh queries
- deep research is already part of the web runtime
- KG novelty tools can resolve fresh seed neighborhoods and generate cards

### 2. Replay Harness

The line that was actively tuned in this round is a bounded replay harness:

- fixed seed packs
- fixed workflow
- frozen baseline notes
- review/refine/routing ledgers

The replay harness is the piece that should be frozen now.

## Keep / Freeze / Reopen

### Keep

Keep the following as platform capabilities:

- candidate-card generation
- reviewer rubric and refinement workflow
- strict/broad verifier surface
- replay packs and outcome ledgers
- failure-taxonomy codification

The current four-layer regression taxonomy for recurring live failures is now
captured in
[idea_mining_failure_taxonomy_regression_note_20260316.md](<repo>/docs/planning/idea_mining_failure_taxonomy_regression_note_20260316.md).

### Freeze

Freeze the following as no-go for this line:

- more replay-only miner tuning as the primary path
- more replay-pack revisions whose main goal is to squeeze discrimination out of
  the same KG-only verifier surface
- further seed-pack churn as the main explanation for weak candidate outcomes
- stronger claims about novelty discrimination
- paper wording that implies benchmark-grade automated discovery

### Reopen Only Under A New Line

If idea mining is reopened, it should reopen as a different line:

`hot-load research tool`

rather than as:

`another replay miner revision`

## Recommended Reframing

For paper and internal positioning, this line should be described as:

- `structured hypothesis triage`
- `AI-augmented research ideation infrastructure`
- `human-in-the-loop candidate generation and sorting`

It should not be described as:

- `fully automated novelty detection`
- `autonomous scientific discovery`

## Next Line

The next architecture line, if opened, should target:

`fresh question -> query/seed resolution -> KG search + external deep research -> evidence-grounded candidate cards`

That line is captured separately in
[idea_mining_hot_load_research_tool_v1.md](<repo>/docs/planning/idea_mining_hot_load_research_tool_v1.md).

## Immediate P0 For The New Line

The first required move on the new line is not another replay pack. It is:

`external literature search attached inside verify`

The concrete rationale is:

- current hot-load query resolution is now good enough to produce interpretable
  anchor bundles
- current candidate cards are still blocked by evidence sparsity, not by
  inability to form anchors
- the verifier will not become meaningfully more discriminative until external
  literature evidence is allowed to compete with or supplement KG-internal
  evidence

The practical order should therefore be:

1. freeze `v1`, `v2`, and tightened `v2` as baselines of record
2. keep the improved anchor-bundle resolver as part of the hot-load path
3. attach external literature evidence to `verify`
4. only then reassess whether `insufficient_evidence` verdicts begin to split

## Live Smoke Addendum

- `smoke_tool = kg_verify_sampled_hypotheses`
- `query = "fmri-based image decoding"`
- `with_deep_research = true`
- `timestamp_utc = 2026-03-15T06:29:40Z`
- `seed_kg_ids = ["ds:openneuro:ds000255"]`
- `n_tested = 1`
- `verdict_counts = {"uncertain": 1}`
- `evidence_source_scope_counts = {"hybrid_kg_literature": 1}`
- `n_external_literature_uncertain = 3`
- `any_hypothesis_left_insufficient_evidence = no`
- `line_conclusion_effect = hot_load_line_positive_signal`

This is the first live signal that external research inside `verify` can change verifier outcomes; keep the replay line frozen and reopen only the hot-load line.
