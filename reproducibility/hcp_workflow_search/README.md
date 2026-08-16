# HCP workflow search: derived-artifact replay

This pack lets a reader inspect and redraw the HCP workflow-search result in
Figure 5 from public-safe derived tables. It preserves the published accounting
for the search and matched comparisons, but it does **not** rerun the original
HCP analyses.

The scope is deliberately narrow: this is a replay of recorded aggregate
artifacts, not a substitute for the governed HCP workflow.

## Run the replay

Run commands from the root of a clone of this repository:

```bash
python reproducibility/hcp_workflow_search/scripts/replay_and_validate.py
```

The command uses only the Python standard library. It validates the supplied
tables and writes `figures/figure5_hcp_workflow_search.svg`. To avoid changing
the committed SVG while checking a clone, supply a temporary output path:

```bash
python reproducibility/hcp_workflow_search/scripts/replay_and_validate.py \
  --output /tmp/figure5_hcp_workflow_search.svg
```

For an integrity check of the committed pack, use the repository-wide verifier:

```bash
python reproducibility/verify.py reproducibility/hcp_workflow_search
```

That verifier checks the committed files. It does not execute an HCP analysis.

## What the replay checks

- The open search contains 20 initial and 96 expanded candidates: 116 total.
  It records 104 scored candidates and 12 incomplete transport slots. The
  transport recovery did not increase or replace the 116-candidate parent
  denominator. The initial maximum was `r = .373`; 27 of the 84 scored expanded
  candidates exceeded it, and the expanded maximum was `r = .487`.
- The selected `C1_raw` workflow was not an automatic discovery champion. It
  was frozen before the matched comparison against the nested Liu reference.
- The recorded Cognition comparison is 10/10 in the favorable direction, with
  median `delta r = .098272...` and conditional one-sided `p = .006`.
- Across the four no-retuning transfer outcomes, the frozen workflow is higher
  in 37/40 repeat-level comparisons, or 47/50 across all five outcomes.
- Median selected `R2` is positive only for Cognition and Tobacco Use. The
  transfer comparison is descriptive and its weak-FWER result is unsupported.

The conditional p-value belongs to the frozen Cognition sensitivity only. It
does not turn the transfer panel into a multiplicity-confirmed generalization.

## Aggregate cohort ledger

The candidate count is not the HCP sample size. To make the denominator visible
without releasing identifiers, this pack records the aggregate ledger used by
the paper:

| Stage | Rows | Families |
|---|---:|---:|
| Eligible HCP cohort | 326 | not reported in this pack |
| Discovery/search subset | 245 | 244 |
| Matched comparison | 244 | 243 |
| Separate internal holdout | 81 | not reported in this pack |

These are aggregate counts only. They do not identify any HCP participant or
family.

## Contents and privacy boundary

| Path | Content | Public-safety boundary |
|---|---|---|
| `data/search_candidates.csv` | Candidate order, search phase, completion state, and aggregate cross-validated score | No candidate receipts, participant records, or prediction vectors |
| `data/matched_outcomes.csv` | Five outcome-level medians and directional counts | Aggregate metrics only |
| `data/paired_repeat_deltas.csv` | Fifty repeat-level `delta r` values | No out-of-fold prediction vectors |
| `data/study_summary.json` | Freeze, denominator, claim-boundary, and producer-closure metadata | No absolute paths or private run receipts |
| `CAPTION.md` | Figure 5 main-text caption | Describes the same derived-artifact boundary |
| `scripts/replay_and_validate.py` | The single replay and validation command | Standard library only |
| `scripts/render_figure5.py` | Figure 5 SVG source | Reads only the derived tables above |

No participant IDs, family IDs, raw HCP behavior or imaging data, out-of-fold
predictions, private receipts, credentials, or absolute local paths are shipped.

## Reproducibility boundary

Historical producing code for the following stages was recovered in private
history. It is not shipped in this public pack and is not publicly resolvable.

| Stage | Public provenance status |
|---|---|
| MVE100 expansion | Recovered in private history; not shipped or publicly resolvable |
| 12-slot recovery | Recovered in private history; not shipped or publicly resolvable |
| R2 Cognition paired inference | Recovered in private history; not shipped or publicly resolvable |
| R3 transfer | Recovered in private history; not shipped or publicly resolvable |

This public package deliberately does not carry those governed HCP execution
inputs or claim an independent scientific reproduction. It provides an
auditable replay of the derived tables used for paper-facing Figure 5. A future
governed rerun would stage the permitted HCP inputs, use the recovered
historical code, and compare newly produced artifacts with this recorded
snapshot before changing any scientific claim.

See `provenance_card.md` and `manifest.json` for the machine-readable boundary.
