Autoresearch FC critic rubric

Judge only from the scorer/runtime artifact, not from any prior agent reasoning.

Judgment gate:
- Fail if the claimed effect remains below a meaningful weak-target floor.
- Fail if the result cannot distinguish term failure from measure or pipeline failure.
- Fail if the selected continuation ignores an obvious stronger alternative already in the ledger.

Completeness gate:
- Fail if required label-shuffle nulls are missing.
- Fail if required replicate runs are missing.
- Fail if a null or borderline result has no exploratory follow-up arm.

Promotion rule:
- Proceed only when judgment and completeness both pass.
- Otherwise prefer `needs_diagnosis` for interpretability failures and `needs_exploration` for missing follow-up evidence.
