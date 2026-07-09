# Pack: bounded_autoresearch_a1 — recorded result

A **real** bounded-autoresearch (A1) result: an HCP-YA component↔behavior
residualised-cognition target plus a family-block exchangeability null. This pack
ships checksum-verifiable public artifacts plus the governed-output checksums
needed to audit a data-gated re-run. The source use-case directory keeps the
build scripts needed for that re-run.

## Contents
- `artifacts/liu_component_behavior_residualised_cognition.csv` — row-indexed
  public copy of the residualised target values. The governed run output had an
  HCP `Subject` column; this public copy removes subject identifiers.
- `artifacts/residualised_target_provenance.json` — inputs + method provenance.
- `artifacts/liu_source_provenance_summary.json` — public-safe Liu/Tian + HCP-YA
  source-data provenance: OSF node/checksums, component reconstruction record,
  target-manifest comparability rules, and redaction boundary.
- `artifacts/family_block_null_summary.json` — exchangeability (family-block) null summary.
- `artifacts/residualised_cheap_check.json`, `residualised_target_summary.json` — checks/summary.
- `manifest.json` — every artifact + its recorded `sha256`.
- `provenance_card.md` — execution envelope + provenance (Appendix F).

## Verify
```bash
python reproducibility/verify.py reproducibility/packs/bounded_autoresearch_a1
```
Exit 0 = the shipped artifacts match the recorded checksums.

## Re-run — REPRODUCED 2026-07-08 (end-to-end)
This pack was **re-run end-to-end on the current stack** (see `REPRODUCTION.md`):
**Step 1** rebuilds the residualised target — same inputs (sha256-proven), OLS
betas / R² / residual_std reproduce to ~1e-15 (machine epsilon; CSV differs only in
last-ULP float formatting). **Step 2** chains that rebuilt target through the frozen
§5.1 Path-B predictive check (152 FC term features, 10 folds, 326 subjects) and
reproduces the published predictive numbers **exactly** — all 117 numeric fields,
max |Δ| = 0.0. **Step 3** re-runs a 30-seed subset of the 1000-permutation
family-block null: all 1830 fields reproduce exactly (max |Δ| = 0.0), and since each
seed is deterministic the published significance (`+1 p = 0.000999`, z = 5.744)
follows by construction. Re-run summary: `REPRODUCTION.md`; permutation records:
`reproduction/rerun_20260708_null_seeds_1_30.jsonl`.

The upstream inputs live under the governed A1 data root and are **not** in this
repo. This pack now exposes the public-safe source route in
`artifacts/liu_source_provenance_summary.json`:

- Liu FC-pyspi assets were staged from OSF node `75je2`
  (`https://osf.io/75je2`) via `scripts/analysis/fc_benchmarking/setup_liu_fc_pyspi.py`;
  the recorded manifest is `liu_fc_pyspi_osf_manifest.json`
  (`sha256:fb19a74beebb826c337d31f0937414813d2a9ff797d219014a8ecc10ce0f0736`).
- HCP-YA behavior rows must be staged by the user under HCP Data Use Terms. Raw
  subject rows, subject identifiers, raw FC files, credentials, and local
  absolute paths are not redistributed.
- The governed residualised-target output checksum remains recorded in
  `artifacts/residualised_target_provenance.json`; the shipped CSV is a
  row-indexed public copy with the same target values and no HCP `Subject`
  identifiers.
- The five Liu/Tian component targets are reconstructed from the paper mapping
  and published demixing matrix, not copied from released subject-level paper
  weights. The target manifest therefore labels the line
  `reconstructed_not_paper_exact`.

To reproduce yourself:
1. Stage the HCP-YA behavior inputs referenced in
   `artifacts/residualised_target_provenance.json` and audit the source route in
   `artifacts/liu_source_provenance_summary.json`.
2. Stage or verify the Liu FC-pyspi OSF derivative/raw assets using the recorded
   OSF manifest route above.
3. Run the source use-case builders: `build_residualised_target.py`
   then `run_residualised_cheap_check.py`.
4. Re-verify shipped bytes with `verify.py`; compare live re-run outputs using
   the tolerances documented in `REPRODUCTION.md`.

Because the pipeline residualises real behavioral data, exact re-runs are expected
to reproduce within tolerance (documented per the reproducibility-audit convention),
not necessarily byte-identical.

Source: `docs/use_cases/bounded_autoresearch_a1_2026-04-30/`.
