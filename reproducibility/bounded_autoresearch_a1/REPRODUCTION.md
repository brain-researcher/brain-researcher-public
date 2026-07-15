# Reproduction record — bounded_autoresearch_a1

**Re-run: 2026-07-08** · current stack (conda env `brain_researcher`, numpy/pandas/h5py) ·
data staged under the governed A1 root (`a1_governed_root:`).

Three steps were re-run on the current stack against the governed data:
**(1)** rebuild the residualised-cognition target, **(2)** chain that rebuilt target
through the frozen §5.1 Path-B predictive check, and **(3)** re-run a seed subset of
the family-block permutation null. Step 1 reproduces to machine epsilon; step 2
reproduces the published predictive numbers exactly; step 3 reproduces the checked
null draws **exactly**.

## Working directory and environment

Unless a block explicitly says otherwise, every command below runs from the
**repository root**. From anywhere inside the clone:

```bash
cd "$(git rev-parse --show-toplevel)"
```

The public headline path is tested with Python 3.11. Create or activate an
isolated environment before running it; `run_end_to_end.sh` installs its light
dependencies into the active interpreter. The deeper commands require files you
stage under your own HCP data-use terms and intentionally write rebuilt output
outside the checkout.

---

## Run it yourself

This pack ships the runnable scripts (`scripts/`), the row-indexed target and
manifests, and the frozen result artifacts. What is *not* in git is the
approximately 1.0 GB extracted functional-connectivity feature set and any
HCP-controlled row — see the data-access boundary below.

### Data-access boundary

| Input | Access | Needed for |
|---|---|---|
| Liu FC-pyspi per-term features (`--terms-dir`) | **Public** — approximately 835 MB GitHub release archive and 1.0 GB after extraction, fetched by `reproducibility/bounded_autoresearch_a1/scripts/fetch_fc_features.py` (repackaged from OSF [75je2](https://osf.io/75je2); `tar.gz sha256 ac3d0f369ea99e0f7587a2bb144664a3a2ea490e7ebfafac1ecf22bf14e811f5`) | the prediction (all steps) |
| Residualised target CSV | **Shipped** (`reproducibility/bounded_autoresearch_a1/artifacts/liu_component_behavior_residualised_cognition.csv`, row-indexed, de-identified) | the prediction (recovery) |
| Subject-keyed `liu_component_behavior.csv` for the exact 326-subject FC intersection | **Governed derived input, not shipped** — the public projection module records the method, but the subject IDs and a builder for this exact intersection are not public | rebuilding the target (step 1) and the §5.1 cheap check |
| HCP-YA behavior export | **HCP Open Access** (click-through Data Use Terms) | IQ/covariate columns for rebuilding the target (step 1) and the §5.1 cheap check |
| HCP-YA `Family_ID` | **HCP Restricted** (application) | the family-block confirmatory null (step 3) |

### The headline result reproduces on public data alone (no HCP account)

After cloning and activating an isolated environment, run this one command
(public FC features → frozen evaluator → built-in result check):

```bash
python3.11 -m venv ~/.venvs/br-a1-repro
source ~/.venvs/br-a1-repro/bin/activate
bash reproducibility/bounded_autoresearch_a1/run_end_to_end.sh
```

Or run the two underlying steps from the repository root:

```bash
python -m pip install numpy pandas h5py scikit-learn
python reproducibility/bounded_autoresearch_a1/scripts/fetch_fc_features.py
python reproducibility/bounded_autoresearch_a1/scripts/run_prediction.py
```

`fetch_fc_features.py` downloads the approximately 835 MB archive from the GitHub release
(`a1-fc-features-v1`; verified against `tar.gz sha256 ac3d0f36…`) into `inputs/`
(git-ignored). `run_prediction.py` then reads that directory plus the shipped
`artifacts/` target CSV and `manifests/` — no flags needed, no HCP account. This
is the redesign→recovery half of the self-evolving loop, reproducible with zero
controlled data. (To use your own copy of the features, pass
`--terms-dir <dir>` / `$A1_TERMS_DIR`.)

### Deeper provenance (needs your own HCP-YA export)

HCP behavior alone is **not enough** to rerun the first two audited steps. You
must also have the subject-keyed `liu_component_behavior.csv` for the exact
326-subject FC/behavior intersection. The public projection module documents
the mathematical reconstruction, but the pack intentionally omits those subject
identifiers and does not ship a command that recreates that exact intersection.
For users who already have both governed inputs, the command template is below.
The family-block null additionally needs a governed workspace and a
`Family_ID`-derived exchangeability manifest. Set paths explicitly so the
commands do not overwrite the published pack:

```bash
export A1_HCP_DIR=/absolute/path/to/staged-hcp
export A1_REBUILD_DIR=/tmp/a1_rebuilt

# step 1 — rebuild the (subject-keyed) target from HCP Open Access behavior
python reproducibility/bounded_autoresearch_a1/scripts/build_residualised_target.py \
  --behavior-dir "$A1_HCP_DIR" \
  --component-csv liu_component_behavior.csv --hcp-csv HCP_YA_subjects.csv \
  --out-dir "$A1_REBUILD_DIR"
# step 2 — §5.1 within-fold cheap check (needs the subject-keyed target + HCP covariates)
python reproducibility/bounded_autoresearch_a1/scripts/run_residualised_cheap_check.py \
  --resid-csv "$A1_REBUILD_DIR/liu_component_behavior_residualised_cognition.csv" \
  --hcp-csv "$A1_HCP_DIR/HCP_YA_subjects.csv" \
  --output-json "$A1_REBUILD_DIR/residualised_cheap_check.json"
```

Step 2 also requires the public FC features fetched by the headline path. It
writes `$A1_REBUILD_DIR/residualised_cheap_check.json`, outside the committed
pack.
The exact numbers those steps must reproduce are recorded below.

---

## Step 1 — rebuild the residualised target

### Command
```bash
export A1_HCP_DIR=/absolute/path/to/staged-hcp
export A1_REBUILD_DIR=/tmp/a1_rebuilt
python reproducibility/bounded_autoresearch_a1/scripts/build_residualised_target.py \
  --behavior-dir "$A1_HCP_DIR" \
  --component-csv liu_component_behavior.csv \
  --hcp-csv HCP_YA_subjects.csv \
  --out-dir "$A1_REBUILD_DIR"
```
Fits `ICA_Cognition ~ 1 + PMAT24_A_CR + ListSort_Unadj + ReadEng_Unadj` on the 326
HCP-YA Liu-intersection subjects and residualises the cognition target.

## Inputs — identical to the recorded run (sha256-proven)
| input | sha256 |
|---|---|
| liu_component_behavior.csv | `1fbade58d6e2820fdfda5029d5a77f9c34f726d42afb5b39c24f1ab237b0e1a4` |
| HCP_YA_subjects_2026_03_31_18_06_54.csv | `1fdcee3a066c45daa8325f0207ca3b8db9176ca56edcf6afc316380daad3a11e` |

Both match the recorded run's `source_files` checksums exactly → same data.

The public-safe source route for these inputs is now recorded in
`artifacts/liu_source_provenance_summary.json`. In brief:

- The Liu FC-pyspi assets were obtained from the upstream OSF project
  `https://osf.io/75je2`. The recorded OSF
  manifest has `sha256:fb19a74beebb826c337d31f0937414813d2a9ff797d219014a8ecc10ce0f0736`,
  vendor commit `6617f0f6ba7e00c94a7ce59032b92e1f268eb27f`, 1308 raw files,
  and 23 derivative files.
- The component behavior table was reconstructed with
  `brain_researcher.research.predictive.liu_component_projection` from the HCP
  behavior export, the Liu/Tian Supplementary Table 4 mapping, and the published
  demixing matrix
  `https://raw.githubusercontent.com/yetianmed/subcortex/master/Behavior/ica.mat`
  (`sha256:e1b9646d8bb7386aaae262be27aa2a2a0bf0b88155f01946832eb26e828b3345`).
- The target manifest labels this line `reconstructed_not_paper_exact`: it is a
  reconstructed benchmark target, not a direct redistribution of paper-exact
  subject-level component weights.

The public module is a Python API, not a complete CLI for this pack, and the
de-identified pack cannot recover the exact 326-subject intersection by itself.
Consequently, Step 1 is independently rerunnable only by a user who already has
an equivalent governed subject binding and derived component table.

The public pack deliberately omits raw HCP rows, raw FC files, subject IDs,
credentials, and absolute local paths. Those omissions are privacy/data-use
requirements, not missing provenance.

## Result — REPRODUCED (tolerance-equivalent)
| quantity | recorded | re-run | Δ |
|---|---|---|---|
| n_subjects | 326 | 326 | exact |
| r2_explained_by_iq | 0.549225645315 | 0.549225645315 | exact |
| residual_std | 0.6755793349896194 | 0.6755793349896193 | 1.11e-16 |
| max \|OLS β diff\| | — | — | 1.78e-15 |

The governed output CSV is **not byte-identical** to the 2026-07-08 re-run
(recorded `sha256:f62365e25793b199…`, re-run `sha256:440fa49dae21c202…`) — it
differs only in the float formatting of the last unit-in-the-last-place. All
estimated quantities reproduce to ~1e-15 (IEEE-754 machine epsilon; BLAS
thread-order non-associativity in the OLS solve).

For public release, the shipped
`artifacts/liu_component_behavior_residualised_cognition.csv` is a row-indexed
copy of the target values with the HCP `Subject` column removed. Its checksum is
therefore the public redacted artifact checksum, not the governed run output
checksum. The governed checksum remains recorded in
`artifacts/residualised_target_provenance.json`.

**Verdict: reproduced within numerical tolerance.** For numerical pipelines this
is the honest bar — bit-for-bit equivalence modulo floating-point non-determinism,
not byte-identical output. `manifest.json` sha256 still gates artifact
INTEGRITY (the shipped bytes are the recorded bytes); this record documents a live
re-run REPRODUCING the science.

Step-1 provenance fields are recorded in
`artifacts/residualised_target_provenance.json`; the 2026-07-08 deltas are
summarized above.

---

## Step 2 — §5.1 predictive check, chained from the rebuilt target (EXACT)

### Command
```bash
export A1_HCP_DIR=/absolute/path/to/staged-hcp
export A1_REBUILD_DIR=/tmp/a1_rebuilt
python reproducibility/bounded_autoresearch_a1/scripts/run_residualised_cheap_check.py \
  --resid-csv "$A1_REBUILD_DIR/liu_component_behavior_residualised_cognition.csv" \
  --hcp-csv "$A1_HCP_DIR/HCP_YA_subjects.csv" \
  --output-json "$A1_REBUILD_DIR/residualised_cheap_check.json"
```
Takes the **freshly-rebuilt** target from step 1 and re-fits the frozen Path-B FC
predictor over the 10-fold manifest, then within-fold-residualises against
{Age, Gender, Handedness, BMI, Acquisition(one-hot), PMAT24, ListSort, ReadEng}.
Predictor inputs: `liu_fc_pyspi_osf/.../schaefer100x7_resave_clean_terms` (76 term
matrices plus 76 metadata sidecars; 4950 edges per matrix), 326 subjects, 5 ICA
components.

### Result — EXACT reproduction
| quantity | recorded | re-run | Δ |
|---|---|---|---|
| aggregate_raw_mean_r | 0.150847 | 0.150847 | 0 |
| aggregate_deconf_mean_r | 0.090627 | 0.090627 | 0 |
| ICA_Cognition raw_r | 0.183158 | 0.183158 | 0 |
| ICA_Cognition deconf_r | 0.141650 | 0.141650 | 0 |
| ICA_Cognition fraction_retained | 0.773377 | 0.773377 | 0 |

**All 117 numeric fields** compared (per-component × per-fold raw/deconf r, deltas,
retained fractions, and both aggregates): **max |Δ| = 0.0, zero mismatches.** The
field-wise values are recorded in `artifacts/residualised_cheap_check.json`.

**Verdict: the §5.1 predictive result reproduces exactly** (bit-for-bit on the
rounded outputs), chained from the machine-epsilon-equivalent step-1 target. The two
steps together are an end-to-end re-run of the A1 result — target construction
through predictive check — on the current stack against the original governed data.

---

## Step 3 — family-block permutation null (seed subset, EXACT)

This is a record of the governed rerun, **not a command that works from a bare
public clone**. It requires HCP Restricted `Family_ID`, the frozen governed
workspace, and its derived exchangeability manifest. Those inputs cannot be
redistributed. After constructing equivalent inputs under your own agreement,
the command shape is:

### Command
```bash
export A1_WORKSPACE=/absolute/path/to/intelligence_residualised_cognition
export A1_EXCHANGEABILITY_MANIFEST=/absolute/path/to/hcp_exchangeability_manifest.json
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
python scripts/autoresearch/fc/liu_confirmatory_permutation.py \
  --workspace "$A1_WORKSPACE" --null-mode family_block \
  --exchangeability-manifest "$A1_EXCHANGEABILITY_MANIFEST" \
  --n-perm 1000 --start-seed 1 --max-new 30
```
The published null is **1000** Family_ID-block permutations: within each fixed
training fold, whole family blocks are shuffled among same-size blocks (test labels
never permuted), each permutation seeded by
`np.random.default_rng(seed·1e6 + fold_id)`. Every permutation is thus a
**deterministic function of its seed**. Re-running seeds 1..30 and matching them
bit-for-bit validates deterministic replay for that subset; it does not validate the
970 seeds that were not re-run.

### Result — EXACT reproduction
| check | recorded | re-run | Δ |
|---|---|---|---|
| observed mean-fold r | 0.150847 | 0.150847 | 0 (60 fields, max \|Δ\|=0) |
| permutation seeds 1..30 | — | — | **1830 fields, max \|Δ\| = 0.0** |

All 1830 numeric fields across seeds 1..30 (per-seed aggregate + per-component
pooled/fold-mean + per-fold r) reproduce exactly; zero mismatches. Evidence:
`reproduction/rerun_20260708_null_seeds_1_30.jsonl` (the 30 fresh permutation
records) plus the field-wise verdict summarized here.

The published full-null summary is `+1 p = 0.000999` (0/1000 permutations ≥
observed), permutation z = 5.744, null mean −0.00205 / sd 0.0266. Those values
remain the **recorded result**: this rerun checked seeds 1..30 only and therefore did
not independently reproduce the full 1000-permutation significance calculation.
Re-running all 1000 seeds is ~30 min single-thread.

---

**Overall verdict:** against the original governed data, the target reproduced to
machine epsilon and the §5.1 predictive check reproduced exactly. Seeds 1..30 of the
family-block null also matched exactly, validating that subset's replay path. The
complete 1000-permutation null and its significance were not re-run here.
