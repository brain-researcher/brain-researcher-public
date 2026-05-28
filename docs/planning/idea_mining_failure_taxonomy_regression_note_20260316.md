# Idea Mining Failure Taxonomy Regression Note

Date: 2026-03-16

## Scope

This note codifies the recurring end-to-end failure mode now observed in live
`idea mining` query runs:

`semantic collapse -> topology attractor -> template degeneration -> late verifier`

It is a bounded harness/regression note, not:

- a new architecture proposal
- a benchmark admission request
- a claim that automated novelty discovery is working

## Why This Note Exists

The repo already has the high-level line conclusion that replay-only miner
tuning is a `NO-GO FOR NOW` and that the replay harness should stay frozen in
[idea_mining_line_conclusion_20260314.md](<repo>/docs/planning/idea_mining_line_conclusion_20260314.md).

What was still missing was a harder, reusable failure taxonomy that can be
attached to:

- future regression probes
- candidate-card routing
- fail-closed runtime gates
- benchmark/harness design discussions

This note fills that gap.

## Artifacts

Machine-readable pack:

- [idea_mining_failure_regression_manifest_v1.json](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_failure_taxonomy_20260316/idea_mining_failure_regression_manifest_v1.json)
- [idea_mining_failure_taxonomy_v1.json](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_failure_taxonomy_20260316/idea_mining_failure_taxonomy_v1.json)
- [idea_mining_failure_regression_probes_v1.jsonl](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_failure_taxonomy_20260316/idea_mining_failure_regression_probes_v1.jsonl)
- [idea_mining_failure_regression_summary_v1.json](<repo>/data/neurokg/raw/gabriel/eval/idea_mining_failure_taxonomy_20260316/idea_mining_failure_regression_summary_v1.json)

Builder and evaluator:

- [build_idea_mining_failure_taxonomy_pack.py](<repo>/scripts/tools/etl/build_idea_mining_failure_taxonomy_pack.py)
- [evaluate_idea_mining_failure_probes.py](<repo>/scripts/tools/etl/evaluate_idea_mining_failure_probes.py)

## Source Signals

This taxonomy is grounded in the current runtime and planning state, not in a
new speculative theory.

Primary repo signals:

- replay-line freeze and downstream-bottleneck diagnosis in
  [idea_mining_line_conclusion_20260314.md](<repo>/docs/planning/idea_mining_line_conclusion_20260314.md)
- hot-load path requirements in
  [idea_mining_hot_load_research_tool_v1.md](<repo>/docs/planning/idea_mining_hot_load_research_tool_v1.md)
- live smoke behavior in
  [hypothesis_hot_load_research_smoke_20260315.md](<repo>/docs/planning/hypothesis_hot_load_research_smoke_20260315.md)
- offline failure-motif routing contract in
  [candidate_card_rubric_v1.md](<repo>/docs/planning/candidate_card_rubric_v1.md)

Primary code surfaces:

- free-text anchor resolution in
  [kg_novelty_tools.py#L90](<repo>/src/brain_researcher/services/tools/kg_novelty_tools.py#L90),
  [kg_novelty_tools.py#L138](<repo>/src/brain_researcher/services/tools/kg_novelty_tools.py#L138),
  [kg_novelty_tools.py#L226](<repo>/src/brain_researcher/services/tools/kg_novelty_tools.py#L226)
- semantic seed expansion and leverage ranking in
  [query_service.py#L6687](<repo>/src/brain_researcher/services/neurokg/query_service.py#L6687),
  [query_service.py#L8085](<repo>/src/brain_researcher/services/neurokg/query_service.py#L8085),
  [query_service.py#L8320](<repo>/src/brain_researcher/services/neurokg/query_service.py#L8320)
- deterministic hypothesis draft construction in
  [query_service.py#L7185](<repo>/src/brain_researcher/services/neurokg/query_service.py#L7185),
  [query_service.py#L7259](<repo>/src/brain_researcher/services/neurokg/query_service.py#L7259)
- sampled-hypothesis verification and late literature fallback in
  [query_service.py#L4785](<repo>/src/brain_researcher/services/neurokg/query_service.py#L4785),
  [query_service.py#L5605](<repo>/src/brain_researcher/services/neurokg/query_service.py#L5605),
  [query_service.py#L9980](<repo>/src/brain_researcher/services/neurokg/query_service.py#L9980),
  [query_service.py#L10211](<repo>/src/brain_researcher/services/neurokg/query_service.py#L10211)

## The Four-Layer Failure Taxonomy

### `SC-1` Semantic Collapse

Definition:

- a structured scientific question is reduced too early to a lexical
  `anchor bundle` or a flat `seed_kg_ids` list
- explicit role structure such as phenomenon, task, population, comparator,
  region, and measurement target is not preserved

Current trigger surface:

- free-text query variants are produced by lexical normalization, alias hits,
  and a small set of hand-written special queries rather than a query-role
  parser
- the novelty path can also fall back to raw `search_nodes(query_text)` seed
  resolution for some entry points

Current code evidence:

- [kg_novelty_tools.py#L138](<repo>/src/brain_researcher/services/tools/kg_novelty_tools.py#L138)
- [kg_novelty_tools.py#L186](<repo>/src/brain_researcher/services/tools/kg_novelty_tools.py#L186)
- [query_service.py#L8597](<repo>/src/brain_researcher/services/neurokg/query_service.py#L8597)

Operational symptom:

- anchors can look locally plausible while still dropping the parts of the query
  that matter most
- examples:
  - losing `younger vs older adults`
  - losing `default mode network suppression`
  - losing `across visual cortex regions`

Harness interpretation:

- this is the first failure in the chain
- if `SC-1` happens, later stages are very unlikely to recover the original
  scientific question

Required regression assertion:

- if a query contains explicit comparator/population/region language, either:
  - at least one returned card retains those roles in its statement
  - or the runtime returns `0` cards

### `TA-1` Topology Attractor

Definition:

- once the query has collapsed into a seed bag, candidate ranking is pulled
  toward high-connectivity, semantically generic, graph-convenient nodes

Current trigger surface:

- `find_structural_leverage(...)` ranks candidates using novelty proxy, bridge,
  diversity, specificity, coherence, and feasibility
- `principle_v0` reranks only these same leverage features; it does not add a
  real query-fidelity term

Current code evidence:

- [query_service.py#L8085](<repo>/src/brain_researcher/services/neurokg/query_service.py#L8085)
- [query_service.py#L8320](<repo>/src/brain_researcher/services/neurokg/query_service.py#L8320)
- [principle_controller.py#L413](<repo>/src/brain_researcher/services/agent/principle_controller.py#L413)

Operational symptom:

- top candidates drift toward:
  - psychometric battery tasks
  - generic task families
  - dataset nodes
  - publication-heavy but question-misaligned anchors

Harness interpretation:

- this is not random noise
- it is a systematic attractor induced by the current objective function

Required regression assertion:

- for mechanism-specific queries, generic `Task` / `TaskFamily` / `Dataset`
  nodes should not dominate the top candidate set unless the query explicitly
  asks about transfer or cross-task generalization

### `TD-1` Template Degeneration

Definition:

- once a generic task-like candidate survives ranking, hypothesis generation
  collapses into a narrow template family rather than producing a
  question-conditioned statement

Current trigger surface:

- `_infer_ood_claim_type(...)` maps `Task`, `TaskFamily`, and `Dataset`
  candidates to `transfer`
- `_build_ood_candidate_draft(...)` then instantiates a standard transfer
  statement

Current code evidence:

- [query_service.py#L7185](<repo>/src/brain_researcher/services/neurokg/query_service.py#L7185)
- [query_service.py#L7201](<repo>/src/brain_researcher/services/neurokg/query_service.py#L7201)
- [query_service.py#L7323](<repo>/src/brain_researcher/services/neurokg/query_service.py#L7323)

Operational symptom:

- different query domains collapse into near-identical cards:
  - `A may transfer to B`
  - `shared latent mechanism`
  - `cross-condition generalization`

Harness interpretation:

- this is a degenerate template family, not genuine cross-domain novelty
- repeated appearance across unrelated queries should be treated as one codified
  failure motif, not as multiple independent weak cards

Required regression assertion:

- if the original query does not imply transfer/generalization, transfer-style
  statements should be fail-closed before card return

### `LV-1` Late Verifier

Definition:

- verification happens only after a misaligned hypothesis has already been
  drafted, and the verifier mostly audits or vetoes rather than shaping the
  hypothesis upstream

Current trigger surface:

- verification hint building compresses context to a preferred pair or small
  hint bundle
- verifier defaults remain `high_recall` and `broad` for early-stage ideation
- external literature is attached only when KG support/conflict is still empty

Current code evidence:

- [query_service.py#L4785](<repo>/src/brain_researcher/services/neurokg/query_service.py#L4785)
- [query_service.py#L5605](<repo>/src/brain_researcher/services/neurokg/query_service.py#L5605)
- [query_service.py#L9980](<repo>/src/brain_researcher/services/neurokg/query_service.py#L9980)
- [query_service.py#L10146](<repo>/src/brain_researcher/services/neurokg/query_service.py#L10146)
- [kg_verify_hypothesis_spec.md#L61](<repo>/docs/specs/kg_verify_hypothesis_spec.md#L61)

Operational symptom:

- support counts can become large on a generic candidate without rescuing the
  actual scientific semantics of the original query
- external literature can improve verdict status late, but it does not undo an
  already mis-specified hypothesis

Harness interpretation:

- evidence quantity is not enough
- late verifier rescue should never be mistaken for aligned candidate generation

Required regression assertion:

- if literature changes the verdict but the card still omits the core query
  roles, the card remains a failure of aligned idea generation

## Failure Cascade Rule

The current recurring live failure should be read as a cascade, not as four
independent bugs:

1. `SC-1` drops query structure
2. `TA-1` amplifies graph-convenient generic nodes
3. `TD-1` converts those nodes into a repeated transfer template
4. `LV-1` audits the already-degenerated hypothesis too late

This matters for prioritization.

The correct reading is:

- `LV-1` alone is not the root cause
- `TA-1` alone is not the root cause
- the dominant root is the upstream loss of question structure plus the absence
  of a fail-closed query-alignment gate

## Freeze-Now Regression Probes

### `IMR-01` DMN Aging Probe

Query:

- `Does default mode network suppression during working memory tasks differ between younger and older adults?`

Why this probe matters:

- it is a classic neuroimaging question with clear role structure:
  - phenomenon: `default mode network suppression`
  - task context: `working memory`
  - comparator: `younger vs older adults`

Expected failure pattern under the current system:

- `SC-1`: comparator and DMN-specific semantics are likely to disappear during
  anchor resolution
- `TA-1`: candidate set drifts toward generic memory-task or psychometric nodes
- `TD-1`: returned cards can collapse into cross-task transfer templates
- `LV-1`: grounded evidence counts may look nontrivial without restoring
  alignment to the original query

Harness fail condition:

- returned cards do not explicitly retain both:
  - `default mode network` or a precise DMN-equivalent label
  - `younger` / `older` or an explicit age-comparison framing

Preferred runtime behavior:

- return `0` cards with a transparent insufficiency message rather than
  returning misaligned transfer cards

### `IMR-02` Visual Decoding Region Probe

Query:

- `Can fMRI-based neural decoding accurately reconstruct visual image representations across different visual cortex regions?`

Why this probe matters:

- it distinguishes improved anchor resolution from genuine end-to-end idea
  quality
- the current runtime already shows directionally better anchors for this area in
  [hypothesis_hot_load_research_smoke_20260315.md](<repo>/docs/planning/hypothesis_hot_load_research_smoke_20260315.md)

Expected failure pattern under the current system:

- `SC-1`: the query can resolve to plausible decoding anchors while still losing
  `across different visual cortex regions`
- `TA-1`: task-like or publication-heavy neighbors still dominate candidate
  ranking
- `TD-1`: output can still collapse into generic task-transfer language
- `LV-1`: deep research may upgrade verdict status late without fixing card
  alignment

Harness fail condition:

- returned cards do not explicitly retain:
  - `visual image` or `visual representation`
  - `visual cortex`, ROI, or cross-region framing

Preferred runtime behavior:

- if only generic task-transfer statements are available, return `0` cards

## Harness Routing Policy

When this taxonomy is used inside the bounded candidate-card harness, routing
should follow these rules:

- `SC-1` only:
  - `hold_for_refinement`
- `SC-1 + TA-1`:
  - `retire_from_candidate_pack`
- `TA-1 + TD-1`:
  - `codify_failure_pattern`
- `LV-1` without upstream `SC-1` / `TA-1` / `TD-1`:
  - `hold_for_refinement`
- `LV-1` after upstream collapse:
  - do not treat as an evidence-only issue; route to `codify_failure_pattern`

## Immediate Codification Targets

This taxonomy should be written back into the harness as explicit checks, not
just reviewer prose.

Minimum useful fields for future regression manifests:

- `query_role_terms_required`
- `query_role_terms_optional`
- `forbidden_template_families`
- `allow_zero_card`
- `expected_anchor_families`
- `forbidden_candidate_families`

Minimum useful runtime gates:

- a query-role coverage gate after anchor resolution
- a candidate-family gate before OOD draft generation
- a transfer-template rejection gate for non-transfer queries
- a fail-closed return policy where `0` cards is preferred over noisy cards

## Non-Goal

This note does not claim that the two probes above are benchmark-ready today.

Its narrower job is:

- freeze a reusable failure taxonomy
- convert recurring weak-card complaints into named regression classes
- provide a shared language for harness design, routing, and future gate work
