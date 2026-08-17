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

## Short glossary

- `C1_raw`: the fixed prediction pipeline selected for follow-up. `raw` means
  its predictions were not calibration-adjusted; it does not mean raw HCP data.
- Matched Liu reference: the Liu-style comparator run with the same target,
  preprocessing, participants, splits, and scoring, making the comparison
  like-for-like. It is not an independent sample or a complete reproduction of
  the original Liu study.
- Transport recovery: a limited retry for the 12 incomplete execution slots,
  not a new candidate search. It cannot add or replace candidates in the
  original 116-candidate denominator.
- `r`, `delta r`, and `R2`: `r` is the held-out prediction--target correlation;
  `delta r` is selected minus reference `r` for the same repeat, so a positive
  value favors the selected workflow. `R2` asks whether predictions outperform
  predicting the held-out mean; it can be negative and is not a pairwise metric.
- Conditional `p`: the permutation p-value for the frozen Cognition comparison,
  conditional on the recorded selection, fits, and repeated splits.
- Weak-FWER: the transfer-panel family-wise correction under its conditional
  global-null setup. It was not supported here, so the transfer panel remains
  descriptive.

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

The canonical producing code for the following stages is publicly shipped
elsewhere in this repository. It is intentionally not included in this
checksum-bound replay pack. The public source and governed CLI map is in the
[HCP predictive producing-code guide](../../src/brain_researcher/research/predictive/foundation_episode/README.md).

| Stage | Public provenance status |
|---|---|
| MVE100 expansion | Public code, outside this replay pack |
| 12-slot recovery | Public code, outside this replay pack |
| R2 Cognition paired inference | Public code, outside this replay pack |
| R3 transfer | Public code, outside this replay pack |

The implementations were recovered from historical private work before their
public release. Public source code alone does not make the original analysis
publicly runnable: this pack deliberately excludes governed HCP inputs,
participant-level predictions, original run artifacts, and execution
authorization. It provides an auditable replay of the derived tables used for
paper-facing Figure 5, not an independent scientific reproduction. A future
governed rerun would stage permitted HCP inputs, use the public code under its
recorded authorization controls, and compare newly produced artifacts with
this recorded snapshot before changing any scientific claim.

See `provenance_card.md` and `manifest.json` for the machine-readable boundary.
