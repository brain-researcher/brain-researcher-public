# Pack: bounded_autoresearch_a1 — recorded result

A **real** bounded-autoresearch (A1) result: an HCP-YA component↔behavior
residualised-cognition target plus a family-block exchangeability null. This pack
ships checksum-verifiable public artifacts, the runnable scripts (`scripts/`) and
manifests (`manifests/`), and the governed-output checksums needed to audit a
re-run. The redesign→recovery headline (`ICA_Cognition` fold-mean r ≈ 0.183)
reproduces on **public data alone** — see the "Run it yourself" section of
[`REPRODUCTION.md`](REPRODUCTION.md).

This is a formal reproducibility pack: `manifest.json` and
`provenance_card.md` define its audit boundary. For a tutorial that generates an
auditable claim record but is not a checksum pack, see
[`../auditable_claim_record/`](../auditable_claim_record/).

## Working directory

Every shell command in this README is written for the **repository root**, not
this pack directory. After cloning, `cd brain-researcher-public`. If you are
already anywhere inside the clone, run:

```bash
cd "$(git rev-parse --show-toplevel)"
```

## Quickstart: public-data rerun

No HCP account or MCP server is needed. The release download is approximately
835 MB and occupies about 1.0 GB after extraction; the prediction itself takes
about 8 seconds after the feature files are staged.
For a new clone, create an isolated environment and run:

```bash
git clone https://github.com/brain-researcher/brain-researcher-public.git
cd brain-researcher-public
python3.11 -m venv ~/.venvs/br-a1-repro
source ~/.venvs/br-a1-repro/bin/activate
bash reproducibility/bounded_autoresearch_a1/run_end_to_end.sh
```

`run_end_to_end.sh` installs `numpy`, `pandas`, `h5py`, and `scikit-learn` into
the active environment; downloads and checksum-verifies the public FC features;
runs the frozen predictor; and checks `ICA_Cognition` fold-mean r ≈ 0.183 and
aggregate r ≈ 0.151. Its default result JSON is
`/tmp/a1_e2e_result.json` (override with `BR_A1_E2E_RESULT`).

To run the two analysis steps manually, still from the repository root:

```bash
python -m pip install numpy pandas h5py scikit-learn
python reproducibility/bounded_autoresearch_a1/scripts/fetch_fc_features.py
python reproducibility/bounded_autoresearch_a1/scripts/run_prediction.py
```

Verify the committed pack separately with:

```bash
python reproducibility/verify.py reproducibility/bounded_autoresearch_a1
```

The deeper, HCP-gated steps are in [`REPRODUCTION.md`](REPRODUCTION.md). To
reproduce A1 the way it was produced — a coding agent driving the loop from
language through the MCP — see [`AGENTIC_REPRODUCTION.md`](AGENTIC_REPRODUCTION.md).

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
- `scripts/` — runnable, parameterized scripts: `run_prediction.py` (frozen
  Path-B predictor over the shipped target; reproduces the recovery on public
  data), `predict.py` (the predictor), `build_residualised_target.py` and
  `run_residualised_cheap_check.py` (deeper-provenance steps needing staged HCP).
- `manifests/` — row-indexed `fold_manifest.json` and the component reference
  manifest consumed by `run_prediction.py`.
- `manifest.json` — every artifact + its recorded `sha256`.
- `provenance_card.md` — execution envelope + provenance (Appendix F).

## Verify

From the repository root:

```bash
python reproducibility/verify.py reproducibility/bounded_autoresearch_a1
```
Exit 0 = the shipped artifacts match the recorded checksums.

## Re-run — target and predictive check reproduced 2026-07-08
This pack was **re-run through the predictive check on the current stack** (see
`REPRODUCTION.md`):
**Step 1** rebuilds the residualised target — same inputs (sha256-proven), OLS
betas / R² / residual_std reproduce to ~1e-15 (machine epsilon; CSV differs only in
last-ULP float formatting). **Step 2** chains that rebuilt target through the frozen
§5.1 Path-B predictive check (76 FC terms, 10 folds, 326 subjects) and
reproduces the published predictive numbers **exactly** — all 117 numeric fields,
max |Δ| = 0.0. **Step 3** spot-checks seeds 1–30 of the recorded 1000-permutation
family-block null: all 1830 checked fields reproduce exactly (max |Δ| = 0.0). The
remaining 970 seeds were not re-run, so the published full-null significance
(`+1 p = 0.000999`, z = 5.744) remains a recorded result rather than an independently
reproduced result. Re-run summary: `REPRODUCTION.md`; permutation records:
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
  `reconstructed_not_paper_exact`. The exact 326-subject FC/behavior
  intersection and subject-keyed derived component table are governed inputs;
  their identifiers are not shipped in this public pack.

To reproduce yourself (full recipe + data-access boundary in `REPRODUCTION.md`):

1. **Public headline** — run
   `reproducibility/bounded_autoresearch_a1/run_end_to_end.sh` from the
   repository root. It downloads the Liu FC-pyspi per-term features from the
   GitHub release into the pack's git-ignored `inputs/`, verifies the archive,
   and reproduces `ICA_Cognition` r ≈ 0.183 / aggregate ≈ 0.151 with no HCP
   account.
2. **Deeper provenance** — to rebuild the target and re-run the §5.1 check, stage
   your own HCP-YA behavior **and** supply the governed, subject-keyed
   `liu_component_behavior.csv` for the exact 326-subject FC intersection. The
   public module documents the projection method, but this pack does not ship
   the subject identifiers or a public builder for that exact intersection.
   Follow the input template in `REPRODUCTION.md`. The family-block confirmatory
   null additionally needs HCP Restricted `Family_ID` and its derived
   exchangeability manifest.
3. Re-verify shipped bytes with `verify.py`; compare re-run outputs using the
   tolerances documented in `REPRODUCTION.md`.

Because the pipeline residualises real behavioral data, exact re-runs are expected
to reproduce within tolerance (documented per the reproducibility-audit convention),
not necessarily byte-identical.

Source: `docs/use_cases/bounded_autoresearch_a1_2026-04-30/`.
