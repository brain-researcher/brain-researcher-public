# Pre-Gate-B Claim Adjudication Pack v1

As of March 10, 2026.

This pack is a canonical pre-Gate-B review set derived from `v3-lite`.
It is intended for quote-first manual adjudication before any formal benchmark upgrade.

## Review Rules

- Review quote-level evidence before looking at any verifier output.
- Confirm final verdict, rationale, and whether the example is valid for future held-out use.
- If provenance is not good enough, mark the item `needs_revision` or `rejected` rather than forcing a label.

## Pack Summary

| Rank | hypothesis_id | current slice | expected_verdict | target after adjudication | builder warnings | why now |
|---:|---|---|---|---|---|---|
| 1 | `bootstrap:attention_mixed` | `held_out` | `mixed` | `future_held_out` | `claim_evidence_semantic_mismatch_present`, `method_rigor_zero_present`, `title_only_evidence_present`, `verdict_semantic_prerequisite_unmet` | Only mixed candidate in v3-lite; highest leverage for preserving a non-support class in the formal benchmark. |
| 2 | `bootstrap:default_mode_network_conflicting` | `held_out` | `conflicting` | `future_held_out` | `verdict_semantic_prerequisite_unmet`, `verdict_structural_prerequisite_unmet` | Only conflicting candidate retained after the weak precuneus refute was dropped. |
| 3 | `claim:88f2eb8941c9228d0071651be108fa58` | `calibration` | `supported` | `future_held_out` | `all_method_rigor_zero`, `method_rigor_zero_present`, `title_only_evidence_present` | Only Task seed in v3-lite and the cleanest way to diversify the formal benchmark beyond region/concept anchors. |
| 4 | `claim:b16751b473f09874df8053775fbb35f0` | `calibration` | `supported` | `future_held_out` | `all_method_rigor_zero`, `method_rigor_zero_present`, `title_only_evidence_present` | Clean concept-level support case with exact title claim and auditable concept mapping. |
| 5 | `claim:872fcaaffec17ba363216ac5eb04c317` | `held_out` | `supported` | `future_held_out` | `all_method_rigor_zero`, `method_rigor_zero_present`, `title_only_evidence_present` | Intervention-specific amygdala support case that adds richer supported-region coverage than generic cortical rows. |
| 6 | `claim:7b858b2e0cfe374856830def8df4a681` | `calibration` | `supported` | `future_calibration` | `all_method_rigor_zero`, `method_rigor_zero_present`, `title_only_evidence_present` | Highly auditable exact region/title match for a specific brainstem nucleus; strong formal calibration anchor. |
| 7 | `claim:28fcbcec2470e0c24db5a5fc716143cc` | `calibration` | `supported` | `future_calibration` | `all_method_rigor_zero`, `method_rigor_zero_present`, `title_only_evidence_present` | Clean TPJ region seed with exact mapping and low ambiguity, suitable for a durable calibration slot. |
| 8 | `pmid:40000003` | `held_out` | `insufficient_evidence` | `future_held_out` | `claim_evidence_semantic_mismatch_present`, `unverifiable_snippet_present` | Only insufficient-evidence control; provenance is now repaired, so adjudication can decide whether it remains the negative-control row for Gate B. |

## Builder Warnings

- `claim_evidence_semantic_mismatch_present`: at least one evidence quote is not semantically aligned enough with the benchmark claim text.
- `verdict_structural_prerequisite_unmet`: a `mixed` or `conflicting` row is missing either support or refute evidence.
- `verdict_semantic_prerequisite_unmet`: a `mixed` or `conflicting` row does not retain at least one semantically aligned support and one semantically aligned refute.
- `title_only_evidence_present`: at least one anchor is derived only from the paper title.
- `unverifiable_snippet_present`: at least one anchor is a non-locatable, non-direct, non-statistical snippet and should be treated as extraction debt.
- `method_rigor_zero_present` / `all_method_rigor_zero`: extracted evidence has no method-rigor signal for some or all anchors.

## Item Checklist

For each row in the JSONL pack:

1. Read the `review_material.evidence_anchors` quote(s) and provenance first.
2. Decide whether the expected verdict is still correct without using system outputs.
3. Record `final_verdict`, `rationale`, and `valid_for_heldout` in the adjudication block.
4. If the seed is weak but salvageable, set `status=needs_revision` and describe the repair needed.

## Artifacts

- Canonical pack: `docs/planning/pre_gate_b_claim_adjudication_pack_v1.jsonl`
- Source calibration manifest: `docs/planning/claim_hypotheses_calibration_v3_lite.jsonl`
- Source held-out manifest: `docs/planning/claim_hypotheses_heldout_v3_lite.jsonl`