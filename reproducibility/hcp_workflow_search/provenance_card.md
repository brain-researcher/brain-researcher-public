# Provenance card: HCP workflow-search derived-artifact replay

## What this pack is

This pack records a public-safe, paper-facing snapshot of an HCP workflow
search and its downstream matched comparisons. Its scripts validate and redraw
Figure 5 from derived aggregate tables.

The pack is not a fresh HCP analysis and does not recreate the search, model
fits, resampling, or participant-level prediction vectors.

## Recorded result envelope

- Search: 20 initial plus 96 expanded candidate evaluations, for a parent
  denominator of 116. Of these, 104 yielded scores and 12 were incomplete.
  Transport recovery did not change that parent denominator. The initial maximum
  was `r = .372637...`; 27 of 84 scored expanded candidates exceeded it, and
  the expanded maximum was `r = .487109...`.
- Selection: `C1_raw` was selected by a recorded researcher decision rather
  than automatic champion selection. The matched comparison was frozen before
  it was evaluated.
- Cognition: 10 favorable repeats out of 10; median `delta r = .098272...`;
  conditional one-sided `p = .006`.
- Transfer: 37 favorable repeats out of 40 across four no-retuning outcomes;
  47 out of 50 including Cognition. Weak-FWER support is not established.
- Absolute utility: the selected workflow has positive median `R2` only for
  Cognition and Tobacco Use.
- Aggregate cohort ledger: eligible HCP cohort `N = 326`; discovery/search
  subset 245 rows / 244 families; matched comparison 244 rows / 243 families;
  separate internal holdout 81 rows. No identifiers are included.

## Source and code closure

The derived tables were exported from persisted, governed study artifacts and
then redacted to aggregate scores and repeat-level score differences. The
public pack does not include the original artifact files or a location for them.

The canonical producing code for the following four stages is now publicly
shipped elsewhere in this repository:

- MVE100 expansion
- 12-slot recovery
- R2 Cognition paired inference
- R3 transfer

The public source and governed CLI map is in the
[HCP predictive producing-code guide](../../src/brain_researcher/research/predictive/foundation_episode/README.md).
The implementations were recovered from historical private work before their
public release, but they are deliberately not part of this checksum-bound replay
pack. The stage-level code provenance is distinct from this public aggregate
replay. The pack is classified as an `integrity_verified` derived-artifact
snapshot because it does not ship governed HCP inputs, participant-level
predictions, original run artifacts, or execution authorization, and it does
not execute those stages.

## Excluded material

- HCP participant and family identifiers
- Raw imaging/behavioral inputs and restricted study bindings
- Out-of-fold prediction vectors and fitted-model internals
- Private receipts, credentials, and machine-specific paths

The files in this directory are all repository-relative and public-safe by
construction. The `scripts/replay_and_validate.py` check confirms the intended
derived-table scope, but a passing check does not establish a new scientific
analysis.
