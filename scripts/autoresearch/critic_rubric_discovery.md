Autoresearch discovery critic rubric

Judge only from the scorer/runtime artifact, not from any prior agent reasoning.

Judgment gate:
- Fail if branch-quality evidence is too weak to support a scientific claim.
- Fail if the strongest branch still looks dominated by a confound or format mismatch.
- Require at least one alternative interpretation when the result is not cleanly dissociated.

Completeness gate:
- Fail if mandatory KG injections are incomplete.
- Fail if branch coverage changed without maintaining score_B semantics.
- Fail if biological motion still uses the legacy `biomo_type` harness instead of the intact-vs-scrambled materializer.

Promotion rule:
- Proceed only when judgment and completeness both pass.
- Otherwise prefer `needs_diagnosis` for failure-axis problems and `needs_exploration` for missing follow-up evidence.
