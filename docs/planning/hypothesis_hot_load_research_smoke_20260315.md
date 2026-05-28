# hypothesis_hot_load_research smoke

Date: 2026-03-15

## Scope

Ran live MCP-side `hypothesis_hot_load_research(...)` on several real free-text queries to evaluate:

- anchor bundle quality
- candidate-card usefulness
- sync latency
- whether `balanced` depth plus external literature changes the verification outcome

## Query results

### 1. `reward learning in fMRI`

- depth: `shallow`
- elapsed: `103.69s`
- cards: `1`
- top anchors:
  - `Effort and Reward Learning Task`
  - `Emotional Learning (EL) and Reward Based Learning (RBL) Tasks`
  - `Emotionally primed probabilistic reward learning task`
  - `A virtual reality-based FMRI study of reward-based spatial learning.`
  - `Dopamine release in human associative striatum in response to reward-prediction errors during reversal learning: Evidence from functional hybrid PET-MR`
- verdicts: `insufficient_evidence=1`
- evidence scopes: `direct=1`
- deep research status: `null`

Assessment:
- anchor resolution is plausible and domain-aligned
- candidate generation works
- verification still bottoms out at weak KG-only evidence in shallow mode

### 2. `fmri-based image decoding`

- depth: `shallow`
- elapsed: `139.16s`
- cards: `1`
- top anchors:
  - `Visual image reconstruction`
  - `Brain-based translation: fMRI decoding of spoken words in bilinguals reveals language-independent semantic representations in anterior temporal lobe.`
  - `From Questions to Neural Insights: Towards Query-Based fMRI Decoding.`
  - `Generic Object Decoding (fMRI on ImageNet)`
  - `Cross-decoding of natural scenes`
- verdicts: `insufficient_evidence=1`
- evidence scopes: `expanded_family=1`
- deep research status: `null`

Assessment:
- anchor bundle is much better than the earlier bad-seed drift
- returned card is still a weak hypothesis lead, not a grounded result
- sync latency is already too high for a simple synchronous MCP call

### 3. `resting-state attention network dynamics`

- depth: `shallow`
- elapsed: `61.10s`
- cards: `1`
- top anchors:
  - `Aberrant Resting-State Functional Connectivity of the Dorsal Attention Network in Tinnitus`
  - `Abnormal Functional Connectivity in Cognitive Control Network, Default Mode Network, and Visual Attention Network in Internet Addiction: A Resting-State fMRI Study`
  - `Brain networks underlying bistable perception`
- verdicts: `insufficient_evidence=1`
- evidence scopes: `none=1`
- deep research status: `null`

Assessment:
- anchor quality is mixed; the query is broad and publication-heavy
- candidate surfaced, but there is effectively no usable KG evidence
- this is a good example of why shallow sync results should be treated as triage, not answers

### 4. `fmri-based image decoding`

- depth: `balanced`
- elapsed: `167.65s`
- cards: `1`
- top anchors:
  - `Visual image reconstruction`
  - `Brain-based translation: fMRI decoding of spoken words in bilinguals reveals language-independent semantic representations in anterior temporal lobe.`
  - `From Questions to Neural Insights: Towards Query-Based fMRI Decoding.`
  - `Generic Object Decoding (fMRI on ImageNet)`
  - `Cross-decoding of natural scenes`
- verdicts: `uncertain=1`
- evidence scopes: `external_literature=1`
- deep research status: `ok`

Assessment:
- this is the key positive signal
- external literature is actually changing verifier output
- the line is no longer stuck at pure `insufficient_evidence` once external evidence is enabled

## Cross-run takeaways

1. Anchor bundle resolution is good enough to proceed.
   The returned anchors for `reward learning in fMRI` and `fmri-based image decoding` are directionally correct and much better than the earlier seed drift.

2. Shallow sync mode is still weak as an end-user answer surface.
   It reliably produces a card, but the result is usually `insufficient_evidence` and should be treated as a hypothesis lead.

3. External literature is the real unlock.
   `balanced` depth changed `fmri-based image decoding` from `insufficient_evidence` to `uncertain` with `evidence_source_scope=external_literature`.

4. Sync latency is the main operational problem.
   Observed wall-clock times:
   - `61s`
   - `104s`
   - `139s`
   - `168s`

## Decision

### `hypothesis_run_get`

Recommended: `yes`

Reason:
- current sync MCP facade is acceptable for manual smoke testing
- it is too slow for production-grade agent use once depth is `balanced` or `deep`
- the web runtime already has the right durability model; MCP still lacks a run handle, polling, and resumability

### Production rollout

Recommended: `not yet` for full hot-load production default

Reason:
- the underlying research path is promising
- the sync UX is too slow
- the strongest value now is `background hot-load research` with persisted artifacts, not long blocking MCP calls

## Recommended next step

Implement a minimal MCP background pair:

1. `hypothesis_run_start`
2. `hypothesis_run_get`

The current `hypothesis_hot_load_research` should remain as the synchronous smoke/dev path, but production-facing agent usage should move to background runs.
