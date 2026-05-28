# Idea Mining Status Memo

Date: 2026-03-13

## Scope

This memo uses "idea mining" to mean the current novelty and research-taste
path that powers:

- Hypothesis Explorer candidate generation and candidate cards
- KG novelty tool calls such as structural leverage, contradiction motifs, OOD
  hypothesis sampling, and topology shifts
- sampled-hypothesis verification and sample-and-verify flows

It does **not** mean that a new novelty architecture track is already open.
That track remains explicitly blocked in roadmap until the hypothesis-quality
baseline is formally validated.

## 1. Completed Capabilities

### Backend novelty/query surface is implemented

The BR-KG query layer already exposes the main idea-mining primitives:

- `synthesize_wow_candidate_cards()` in
  [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L8866)
- `sample_ood_hypothesis()` in
  [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L9027)
- `verify_sampled_hypotheses()` in
  [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L9878)
- `sample_and_verify_hypotheses()` in
  [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L10280)

These are wrapped as tools in
[kg_novelty_tools.py](<repo>/src/brain_researcher/services/tools/kg_novelty_tools.py),
including structural leverage, contradiction motifs/frontiers, analogy
transfers, OOD hypothesis sampling, verify-sampled, and sample-and-verify.

### Hypothesis Explorer runtime is wired end to end

The web runtime already builds and persists idea-mining artifacts:

- KG compare and novelty-taste gathering in
  [hypothesis-research-adapter.ts](<repo>/apps/web-ui/src/lib/server/hypothesis-research-adapter.ts#L3120)
- run-stage orchestration and artifact persistence in
  [hypothesis-runner.ts](<repo>/apps/web-ui/src/lib/server/hypothesis-runner.ts#L803)
- candidate-card assembly in
  [hypothesis_candidate_cards.py](<repo>/src/brain_researcher/services/agent/hypothesis_candidate_cards.py)

The UI already renders the output in Hypothesis Explorer:

- page shell in
  [HypothesisExplorerPage.tsx](<repo>/apps/web-ui/src/components/hypothesis/HypothesisExplorerPage.tsx#L157)
- artifact display of `Prior Art Match`, `Novelty Gap`, `Structural Leverage`,
  `Contradiction Motifs`, `OOD Hypotheses`, and `Topology Shifts` in
  [HypothesisArtifactPanel.tsx](<repo>/apps/web-ui/src/components/hypothesis/HypothesisArtifactPanel.tsx#L475)

### Verifier-side candidate separation is now in place

The verifier path now supports strict/broad candidate-lane behavior:

- candidate-lane mode normalization and filtering in
  [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L4196)
  and
  [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L5066)
- MCP exposure in
  [server.py](<repo>/src/brain_researcher/services/mcp/server.py#L8715),
  [server.py](<repo>/src/brain_researcher/services/mcp/server.py#L9080),
  and
  [server.py](<repo>/src/brain_researcher/services/mcp/server.py#L9141)

Broad-mode evidence items now also expose nested candidate provenance via
`candidate_lane`, built in
[query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L4212)
and attached in
[query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L5253).

### Test coverage exists on the core path

There is meaningful automated coverage for the currently implemented path:

- novelty tool unit tests in
  [test_kg_novelty_tools.py](<repo>/tests/unit/tools/test_kg_novelty_tools.py)
- Hypothesis Runner novelty integration in
  [hypothesis-runner.novelty.test.ts](<repo>/apps/web-ui/src/lib/server/__tests__/hypothesis-runner.novelty.test.ts)
- realdata smoke placeholder for workflow candidate cards in
  [test_workflow_hypothesis_candidate_cards_smoke.py](<repo>/tests/integration/realdata/test_workflow_hypothesis_candidate_cards_smoke.py)
- strict/broad verifier behavior in
  [test_query_service.py](<repo>/tests/unit/neurokg/test_query_service.py#L1203)
  and
  [test_query_service_novelty.py](<repo>/tests/unit/neurokg/test_query_service_novelty.py#L1473)

## 2. Current Blockers

### The architecture track is formally blocked

The current roadmap is explicit:

- `novelty_architecture` status is `blocked` in
  [roadmap.md](<repo>/docs/planning/roadmap.md#L172)
- the stated goal is to defer new novelty/taste surface design until the
  hypothesis-quality baseline is validated on real probes

This means the repo already contains a runtime novelty surface, but new
architecture work is not yet considered open-ended design space.

### Evidence-quality gates still govern whether novelty work is "real"

The evidence-coverage plan still treats novelty as downstream of evidence
quality and verifier behavior:

- Week 9 requires claim-first evidence controls to affect runtime novelty
  behavior in
  [neurokg_evidence_coverage_expansion_plan.md](<repo>/docs/planning/neurokg_evidence_coverage_expansion_plan.md#L93)
- Week 10 requires a freeze between benchmark-graph and candidate-only evidence
  in the same plan

In other words, idea mining is not blocked because tools are missing. It is
blocked because the repo still wants novelty behavior tied to validated
evidence quality, promotion policy, and benchmark/candidate separation.

### Downstream readiness artifacts are still part of the gate

The graph/claim execution plan still expects a later readiness review before
idea-mining use is considered formally ready:

- joint readiness review for claim-centric reasoning and later idea-mining use
  in
  [neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md#L65)

### Runtime still degrades by design

The current runtime is intentionally fail-open in sparse or unavailable KG
conditions:

- novelty tools provide fallback leverage and OOD outputs when KG access is
  unavailable in
  [kg_novelty_tools.py](<repo>/src/brain_researcher/services/tools/kg_novelty_tools.py)
- `runKgCompare()` softens no-seed and timeout failures into warnings/fallbacks
  in
  [hypothesis-research-adapter.ts](<repo>/apps/web-ui/src/lib/server/hypothesis-research-adapter.ts#L3132)
  and
  [hypothesis-runner.ts](<repo>/apps/web-ui/src/lib/server/hypothesis-runner.ts#L803)

That is good product behavior for v1, but it also means the system is still
optimized for graceful ideation, not for fully benchmarked architecture claims.

## 3. What Counts as V1 Usable

The current implementation is v1-usable for:

- assisted hypothesis exploration in Hypothesis Explorer
- generating candidate cards from KG compare plus evidence context
- using KG novelty tools to surface leverage nodes, contradiction motifs, OOD
  hypotheses, and topology-shift hints
- sampled-hypothesis verification in `broad` vs `strict` mode
- coverage-first ideation on top of benchmark plus candidate evidence layers

The current implementation is **not** yet v1-usable for:

- declaring the novelty architecture solved
- treating novelty/taste outputs as benchmark-grade without human review
- opening a new architecture-design phase independent of evidence-quality
  validation
- using degraded or fallback novelty output as equivalent to grounded KG-backed
  output

Practical interpretation:

- Use it now for analyst-assisted idea generation, candidate surfacing, and
  exploratory verification.
- Do not use it yet as proof that the future novelty architecture is settled.

### Hot-Load Verify Update

The hot-load line now has a positive verify-stage signal after external
literature was attached inside `verify`.

- live smoke tool: `kg_verify_sampled_hypotheses`
- query: `fmri-based image decoding`
- timestamp: `2026-03-15T06:29:40Z`
- tested hypotheses: `1`
- verdict counts: `uncertain = 1`
- evidence source scope: `hybrid_kg_literature = 1`
- external literature uncertain evidence rows: `3`

This changes the status of the hot-load line from "plumbing only" to
"verification can now move beyond pure insufficient-evidence in at least one
live query," but it does not reopen the frozen replay-miner line.

## 4. Conditions to Unblock `novelty_architecture`

The repo already states the high-level condition: explicit P0 completion on the
hypothesis-quality baseline. Concretely, that means at least:

1. Claim-first evidence behavior has to beat or materially out-audit
   mention-fallback on the bounded benchmark.
   Source:
   [neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md#L60)
   and
   [neurokg_evidence_coverage_expansion_plan.md](<repo>/docs/planning/neurokg_evidence_coverage_expansion_plan.md#L93)

2. Benchmark-vs-candidate evidence boundaries have to be frozen explicitly.
   Source:
   [neurokg_evidence_coverage_expansion_plan.md](<repo>/docs/planning/neurokg_evidence_coverage_expansion_plan.md#L98)

3. Claim aggregation / canonicalization strategy has to be explicit and
   testable.
   Source:
   [neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md#L62)

4. Versioned snapshots and formal readiness review have to exist before later
   idea-mining use is treated as greenlit.
   Source:
   [neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md#L64)
   and
   [neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md#L65)

## 5. Proceed One by One

The right order is to treat the unblock as four sequential steps, not one large
"novelty architecture" project.

### Step 1. Close the verifier-grounding gap for novelty

Goal:
prove that richer claim-first evidence and benchmark/candidate separation
change novelty-runtime behavior in a measurable way.

Already present:

- bootstrap comparison evidence in
  [claim_first_vs_mention_report_v3_lite.md](<repo>/docs/planning/claim_first_vs_mention_report_v3_lite.md)
- strict/broad candidate-lane verifier behavior in
  [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L4640)
  and
  [test_query_service_novelty.py](<repo>/tests/unit/neurokg/test_query_service_novelty.py#L1473)

Still missing:

- `claim_first_vs_mention_report_v3.md`
- an explicit pass/fail note that novelty-path behavior is materially better
  under claim-first grounding than under mention fallback

Now available:

- [novelty_claim_first_gap_report.md](<repo>/docs/planning/novelty_claim_first_gap_report.md)
  as the synthesis artifact that links bootstrap claim-first evidence to the
  current novelty strict/broad runtime behavior

Exit criterion:

- the novelty workflow has a reportable broad-vs-strict and claim-first-vs-
  mention-fallback delta on a bounded benchmark slice
- the result is strong enough to clear the Week 9 fail condition in
  [neurokg_evidence_coverage_expansion_plan.md](<repo>/docs/planning/neurokg_evidence_coverage_expansion_plan.md#L93)

Immediate next move:

- decide whether `claim_first_vs_mention_report_v3_lite.md` can be promoted
  into a full `v3` report or needs another bounded rerun

### Step 2. Freeze benchmark vs candidate evidence policy

Goal:
turn the current runtime separation into a documented promotion boundary.

Already present:

- candidate-only lane exists as a live runtime concept
- strict/broad verifier controls exist in
  [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L4640)
- candidate provenance now exists in broad-mode evidence payloads in
  [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L4212)

Still missing:

- no additional Step 2 artifact inside this step

Now available:

- [promotion_policy_v1.md](<repo>/docs/planning/promotion_policy_v1.md)
  as the frozen benchmark-vs-candidate policy boundary
  and the explicit Week 10 freeze decision referenced by
  [neurokg_evidence_coverage_expansion_plan.md](<repo>/docs/planning/neurokg_evidence_coverage_expansion_plan.md#L94)
- [evidence_snapshot_alpha.md](<repo>/docs/planning/evidence_snapshot_alpha.md)
  as the first concrete snapshot cut taken against that policy

Exit criterion:

- candidate-only vs benchmark inclusion rules are frozen in a document
- the benchmark graph and candidate graph can be described without ambiguity

Immediate next move:

- move to Step 3 and draft the claim canonicalization ADR

### Step 3. Make claim aggregation explicit

Goal:
move from paper-local novelty hints to claim-level reusable idea-mining
structure.

Already present:

- claim-centric verification and sampled-hypothesis paths already exist in
  [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L9878)
  and
  [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L10280)

Still missing:

- clustering strategy and failure taxonomy required by
  [neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md#L62)
  and
  [neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md#L63)

Now available:

- [claim_canonicalization_adr.md](<repo>/docs/planning/claim_canonicalization_adr.md)
  as the explicit decision that paper-local `Claim.id` stays stable and
  cross-paper aggregation moves into a separate canonical layer
- [claim_clustering_eval_plan.md](<repo>/docs/planning/claim_clustering_eval_plan.md)
  as the bounded execution plan for the first clustering plus failure-taxonomy
  pass
- [claim_clustering_eval_pack_20260313.md](<repo>/docs/planning/claim_clustering_eval_pack_20260313.md)
  as the first real bounded pack and review note, backed by
  [claim_clustering_eval_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_clustering_eval/bounded_v1_20260313/claim_clustering_eval_summary.json)
  with:
  `rows_total = 12`,
  `same_target_opposing_stance = 2`,
  `failure_taxonomy_stress = 9`,
  `stable_single_paper_control = 1`

Exit criterion:

- claim aggregation strategy is explicit, testable, and no longer implicit in
  paper-local rows

Immediate next move:

- review the `same_target_opposing_stance` slice first, then adjudicate the
  `failure_taxonomy_stress` slice from
  [claim_clustering_eval_pack_20260313.md](<repo>/docs/planning/claim_clustering_eval_pack_20260313.md)
  before cutting `claim_snapshot_v1`

### Step 4. Freeze snapshots and run readiness review

Goal:
formally change novelty work from a usable runtime into an unblocked
architecture track.

Still missing:

- benchmark-scale expansion beyond the current bounded packet

Now available:

- [claim_snapshot_v1_20260314.md](<repo>/docs/planning/claim_snapshot_v1_20260314.md)
  as the bounded reviewed freeze note
- [claim_snapshot_v1.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v1/bounded_v1_20260314/claim_snapshot_v1.jsonl)
  as the first concrete reviewed claim snapshot artifact
  with:
  `snapshot_rows_total = 5`,
  `snapshot_canonical_clusters_total = 4`,
  `snapshot_conflict_clusters = 1`
- [readiness_packet_20260314.md](<repo>/docs/planning/readiness_packet_20260314.md)
  as the current Step 4 packet index
- [graph_snapshot_v1_1_20260314.md](<repo>/docs/planning/graph_snapshot_v1_1_20260314.md)
  and
  [graph_snapshot_v1_1_manifest.json](<repo>/data/neurokg/raw/graph_snapshot_v1_1/bound_20260314/graph_snapshot_v1_1_manifest.json)
  as the explicit graph-side snapshot binding
- [readiness_review.md](<repo>/docs/planning/readiness_review.md)
  with current verdict:
  `graph = pass`,
  `claim = pass (bounded)`,
  `joint Step 4 = pass (bounded closeout)`
- [go_no_go_memo.md](<repo>/docs/planning/go_no_go_memo.md)
  with current decision:
  `GO` for bounded Step 4 closeout,
  `NO-GO` for reopening `novelty_architecture`
- [task_charter.md](<repo>/docs/planning/task_charter.md)
  as the frozen task-definition layer
- [train_dev_test_split_proposal.md](<repo>/docs/planning/train_dev_test_split_proposal.md)
  as the frozen split-policy layer
- [claim_snapshot_v4_split_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_split_manifest_20260314.md)
  and
  [claim_snapshot_v4_split_manifest.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_split_manifest.json)
  as the first real bounded downstream split materialization

Exit criterion:

- the Week 11 and Week 12 gates in
  [neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md#L64)
  and
  [neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md#L65)
  are satisfied explicitly

Immediate next move:

- keep the current bounded packet frozen and expand reviewed snapshot scale
  before starting any new novelty-architecture design
- the first real expansion pack now exists in
  [claim_snapshot_v1_expansion_pack_20260314.md](<repo>/docs/planning/claim_snapshot_v1_expansion_pack_20260314.md),
  but the reviewed cut is now tighter than that first projection:
  [claim_snapshot_v2_20260314.md](<repo>/docs/planning/claim_snapshot_v2_20260314.md)
  shows `11` reviewed families and only `2` target-type buckets
- the reviewed gap pack now exists in
  [claim_snapshot_warning_conflict_gap_pack_20260314.md](<repo>/docs/planning/claim_snapshot_warning_conflict_gap_pack_20260314.md),
  which restores the `Task` bucket in projection but still leaves a family-count gap
- [claim_snapshot_v3_20260314.md](<repo>/docs/planning/claim_snapshot_v3_20260314.md)
  now records the first reviewed cut that consumes both the bridge gap pack and
  the substantive breadth pack; the real reviewed state is now:
  `21` canonical families,
  `16` warning/conflict families,
  `3` target-type buckets,
  and only `3` families short of the split threshold
- [claim_snapshot_terminal_shortfall_pack_20260314.md](<repo>/docs/planning/claim_snapshot_terminal_shortfall_pack_20260314.md)
  now records the compact `+3` terminal candidate set chosen from the remaining
  reviewed pool
- [claim_snapshot_v4_20260314.md](<repo>/docs/planning/claim_snapshot_v4_20260314.md)
  now records the first reviewed cut that actually reaches the bounded split
  threshold: `24` canonical families, `19` warning/conflict families, `3`
  target-type buckets
- [claim_snapshot_v4_split_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_split_manifest_20260314.md)
  now records the first real bounded downstream split:
  `14` train families,
  `5` dev families,
  `5` test families,
  with `0` family-cross-split violations and `0` paper leakage violations

### Step 5. Lift Idea Mining Into an L6 Harness Program

Goal:
turn the current idea-mining runtime from a usable tool surface into a bounded,
replayable, reviewer-scored program.

Already present:

- live novelty tools and candidate-card runtime already exist
- strict/broad verifier behavior and candidate provenance are already wired
- bounded downstream claim packets already exist and can serve as grounding
  references

Still missing:

- a completed replay run over a fixed seed set
- reviewer scores and refinement logs written back from that replay
- a first routing ledger that records `promote`, `hold`, `retire`, or `codify`
  decisions on candidate cards

Now available:

- [brain_researcher_agentic_maturity_map.md](<repo>/docs/planning/brain_researcher_agentic_maturity_map.md)
  as the current maturity diagnosis and program decision to push idea mining
  from `L5` tooling toward `L6` harness engineering
- [idea_mining_seed_set_v1.md](<repo>/docs/planning/idea_mining_seed_set_v1.md)
  and
  [idea_mining_seed_set_v1.jsonl](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v1_20260314/idea_mining_seed_set_v1.jsonl)
  as the frozen bounded seed inventory
- [candidate_card_rubric_v1.md](<repo>/docs/planning/candidate_card_rubric_v1.md)
  and
  [candidate_card_rubric_v1.json](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v1_20260314/candidate_card_rubric_v1.json)
  as the first reviewer-style scoring contract
- [idea_mining_replay_pack_v1.md](<repo>/docs/planning/idea_mining_replay_pack_v1.md),
  [idea_mining_replay_pack_v1_manifest.json](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v1_20260314/idea_mining_replay_pack_v1_manifest.json),
  and
  [idea_mining_replay_pack_v1_examples.jsonl](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v1_20260314/idea_mining_replay_pack_v1_examples.jsonl)
  as the executable bounded replay/control pack
- [candidate_refinement_workflow_v1.md](<repo>/docs/planning/candidate_refinement_workflow_v1.md)
  and
  [candidate_refinement_workflow_v1.json](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v1_20260314/candidate_refinement_workflow_v1.json)
  as the first bounded refinement/codification workflow
- [idea_mining_replay_pack_v1_first_pass_20260314.md](<repo>/docs/planning/idea_mining_replay_pack_v1_first_pass_20260314.md)
  and
  [idea_mining_replay_pack_v1_run_summary.json](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v1_20260314/idea_mining_replay_pack_v1_run_summary.json)
  as the first real bounded replay run, which currently yields:
  `12/12` successful runs,
  `16` candidate cards,
  `0` broad-vs-strict delta pairs,
  and `16` `hold_for_refinement` routes
- [idea_mining_refinement_pack_v1_20260314.md](<repo>/docs/planning/idea_mining_refinement_pack_v1_20260314.md)
  and
  [idea_mining_refinement_pack_v1_summary.json](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_refinement_v1_20260314/idea_mining_refinement_pack_v1_summary.json)
  as the first replay-followup triage cut, which currently reduces the `16`
  held cards into `10` unique refinement units:
  `3` `search_expanded_bridge`,
  `2` `mapping_bridge`,
  `1` `family_hop_bridge`,
  `4` `pair_incomplete_replay`
- [idea_mining_seed_set_v2_20260314.md](<repo>/docs/planning/idea_mining_seed_set_v2_20260314.md)
  and
  [idea_mining_replay_pack_v2_manifest.json](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v2_20260314/idea_mining_replay_pack_v2_manifest.json)
  as the first candidate-sensitive revision pack, with:
  `8` total seeds,
  `5` candidate-sensitive probes,
  `16` run specs,
  and `concept:reward_learning` replacing the weaker `concept:working_memory`
  control
- [idea_mining_replay_pack_v2_first_pass_20260314.md](<repo>/docs/planning/idea_mining_replay_pack_v2_first_pass_20260314.md)
  and
  [idea_mining_replay_pack_v2_20260314_run_summary.json](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v2_20260314/idea_mining_replay_pack_v2_20260314_run_summary.json)
  as the first candidate-sensitive replay result, which currently yields:
  `16/16` successful runs,
  `26` candidate cards,
  `0` meaningful broad-vs-strict deltas,
  `26` `hold_for_refinement` routes,
  and `0` cards from the `concept:reward_learning` positive control
- [idea_mining_replay_pack_v2_tightened_20260314.md](<repo>/docs/planning/idea_mining_replay_pack_v2_tightened_20260314.md)
  and
  [idea_mining_replay_pack_v2_20260314_run_summary.json](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_program_v2_tightened_20260314/idea_mining_replay_pack_v2_20260314_run_summary.json)
  as the first replay after query-side `SEARCH_EXPANDED` tightening, which
  reduces candidate volume from `26` to `24` and search-expanded rows from `23`
  to `19`, but still yields `0` meaningful broad-vs-strict deltas

Exit criterion:

- the fixed replay pack has been executed on the frozen seed set
- resulting candidate cards have been scored with the rubric
- the refinement loop has produced logged routing decisions without mixing
  candidate-only output into benchmark admission
- a revised seed pack exists that responds to first-pass failure modes rather
  than rerunning the control pack unchanged

Immediate next move:

- keep `v1` frozen as the replay-control baseline
- keep `v2` frozen as the first candidate-sensitive replay result
- keep the tightened `v2` replay frozen as the first query-side reduction pass
- translate surviving `BELONGS_TO_FAMILY` bridges into exact anchors before
  adding more seeds
- inspect the zero-card `concept:reward_learning` control failure before
  interpreting seed choice as the only bottleneck

### Step 5A. Freeze The Replay-Miner Line And Reframe It Correctly

Goal:
close the current replay-miner line without overclaiming what it achieved.

Now available:

- [idea_mining_line_conclusion_20260314.md](<repo>/docs/planning/idea_mining_line_conclusion_20260314.md)
  as the formal keep/no-go split:
  `KEEP` the harness and candidate triage system,
  `NO-GO FOR NOW` on miner-side novelty discrimination as a headline claim

Practical reading:

- the replay harness is now a platform capability
- the current line should be framed as `structured hypothesis triage`
- it should not be framed as `automated novelty detection`

### Step 5B. Open A Separate Hot-Load Research-Tool Line

Goal:
turn the live runtime into:
`fresh question -> KG search + external deep research -> evidence-grounded candidate cards`

Now available:

- [idea_mining_hot_load_research_tool_v1.md](<repo>/docs/planning/idea_mining_hot_load_research_tool_v1.md)
  as the first concrete architecture note for the new line, with explicit
  insertion points in:
  [hypothesis-runner.ts](<repo>/apps/web-ui/src/lib/server/hypothesis-runner.ts#L1033),
  [hypothesis-research-adapter.ts](<repo>/apps/web-ui/src/lib/server/hypothesis-research-adapter.ts#L2951),
  [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L6397),
  [query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L9921),
  and
  [hypothesis_candidate_cards.py](<repo>/src/brain_researcher/services/agent/hypothesis_candidate_cards.py#L303)
- query-first MCP candidate-card calls now also expose a
  `resolved_anchor_bundle`, so free-text questions no longer have to be treated
  as a single opaque seed string before the live workflow runs

Current read:

- anchor selection is no longer the dominant failure mode
- the current dominant bottleneck is still verifier evidence sparsity
- therefore the first P0 for the hot-load line is external literature evidence
  inside `verify`, not another replay or seed-pack revision

### Recommended Order Right Now

1. Keep the current bounded readiness packet frozen.
2. Treat the five new idea-mining program artifacts as the current plan of record.
3. Keep `idea_mining_replay_pack_v1` frozen as the control harness.
4. Use the first-pass replay outputs to maintain the refinement pack and outcome ledger.
5. Compare frozen `v2` against the frozen `v1` control before interpreting strict/broad behavior.
6. Use the `v1` refinement buckets plus the `v2` zero-card control failure to decide the next candidate-miner change.
7. Review the bounded clustering eval pack and freeze the first failure-tag
   adjudication.
8. Use the frozen bounded packet to guide the next expansion pass rather than
   reopening architecture work early.

## Bottom Line

Status summary:

- Runtime idea-mining path: **implemented and usable**
- Hypothesis Explorer novelty surface: **implemented and usable**
- Strict/broad evidence-aware verifier behavior: **implemented**
- `claim_snapshot_v1`: **now materialized on a bounded reviewed slice**
- `claim_snapshot_v1_expansion_pack`: **now materialized as the first fresh
  non-title expansion pass**
- `claim_snapshot_v2`: **now materialized as the first reviewed post-expansion cut**
- reviewed warning/conflict gap pack: **now materialized for the next bounded pass**
- `claim_snapshot_v3`: **now materialized as the first bridge-reviewed breadth cut**
- `claim_snapshot_v4`: **now materialized as the first threshold-meeting bounded cut**
- `claim_snapshot_v4` split manifest: **now materialized as the first bounded downstream split**
- `claim_snapshot_v4` downstream B1 task manifest: **now materialized as the first runnable claim-side downstream task**
- `claim_snapshot_v4` B2 task manifest: **now materialized as a conflict-expanded reviewed-seed inclusion/exclusion task**
- `claim_snapshot_v4` B2 split manifest: **now materialized as a bounded split whose `dev` and `test` both contain conflict rows**
- Step 4 readiness packet: **assembled on a bounded reviewed slice**
- `idea_mining_replay_pack_v1`: **now executed as a frozen control replay**
- `idea_mining_refinement_pack_v1`: **now materialized as the first replay-followup triage cut**
- `idea_mining_seed_set_v2`: **now materialized as the first candidate-sensitive replay revision**
- `idea_mining_replay_pack_v2`: **now executed as the first candidate-sensitive probe replay**
- Formal novelty architecture track: **still blocked / current decision = no-go**

The right operational stance today is:

- treat idea mining as an evidence-grounded v1 runtime
- keep using it for assisted exploration and candidate generation
- keep `v1` frozen as the control harness and `v2` frozen as the first probe result
- do not reopen novelty architecture design until the quality gates and
  readiness artifacts above are explicitly closed
- the immediate operational target is no longer family-count expansion or split
  materialization, but freezing the replay-miner line, keeping the improved
  anchor-bundle hot-load path, and attaching external literature evidence to
  `verify` before making any stronger claim about live ideation quality
