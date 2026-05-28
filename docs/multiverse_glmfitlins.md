# GLM Multiverse Design (glmfitlins)

Draft plan for extending the current `openneuro_glmfitlins` workflow so each
dataset/task can run a **family of BIDS Statistical Models** rather than a
single spec. The goal is to surface how results change across reasonable GLM
choices while reusing the existing FitLins execution and reporting stack.

## Goals and scope (Phase 1)
- Input: an OpenNeuro dataset (preprocessed) and one seed BIDS Stats Model.
- Output: 10–50 variant Stats Models (`*-mvXX_specs.json`) that are valid under
  the BIDS Stats Model schema and runnable by FitLins.
- Keep pre-processing fixed; vary only the statistical model layer.
- Rule-based, reviewable transforms first; leave hooks for a literature/agent
  layer in later phases.

## Where it fits in the existing flow
Current steps (simplified):
1) Download + summarize dataset (subjects, events, contrasts)
2) Optional fMRIPrep on HPC
3) Modify events / confounds (dataset-specific rules)
4) Create a single Stats Model spec (`3_create_spec_file.sh`)
5) Run FitLins for that spec (`4_run_fitlins.sh`)
6) Build group report (`run_grouprepo.sh`)

Multiverse extension inserts a new **Step 4a** between 4 and 5:
- 4a) Generate multiverse specs around the seed; write `*-mvXX_specs.json`

Then Step 5 becomes “run FitLins for every `mvXX` spec”, and Step 6 adds a
multiverse summary alongside the per-model reports.

## New components to add
- `scripts/prep_report_py/multiverse_specs.py`
  - CLI: `python .../multiverse_specs.py --openneuro_study dsXXXX --task taskname --max_models 20 [--include-seed]`
  - Loads the seed spec, applies transform rules, validates (schema + design
    rank), writes `mvXX` specs to `statsmodel_specs/<study>/`.
  - Supports dataset-specific functions (e.g., `ds003425_learning_multiverse`) with a global fallback rule set.

- `scripts/4_run_fitlins_multiverse.sh`
  - Discovers all `*-mv*_specs.json` for the study/task.
  - For each, derives `task_suffix=mvXX` and calls existing `4_run_fitlins.sh`
    (passes through smoothing/estimator flags).

- (Optional) `scripts/run_multiverse_grouprepo.sh`
  - Calls `run_grouprepo.sh` per `mvXX` output.
  - Builds a summary table/CSV and stubs overlap metrics across models.

## Naming and conventions
- Seed remains `<study>-<task>[_suffix]_specs.json`.
- Multiverse variants live in the same folder as `*-mvXX_specs.json` (zero
  padded). Reserve `mv00` for the seed in manifests even if not regenerated.
- Manifests: CSV with columns `[model_id, hrf, confounds, filter, censoring,
  contrasts, notes]` emitted by `multiverse_specs.py`.

## Variation axes for Phase 1 (examples)
- Event modeling: collapse vs. split trial types; parametric modulator vs.
  binning; impulse vs. epoch.
- HRF basis: canonical; canonical+derivatives; FIR with fixed window/bin.
- Confounds: 6 vs. 24 motion; aCompCor (0/5/10 components); optional global
  signal flag where appropriate.
- Filtering / autocorrelation: high-pass 100/128/200s; AR(1) vs. prewhiten
  flag when supported by runner.
- Censoring: scrubbing at FD>0.5 mm vs. none.
- Group/inference: one-sample vs. mixed-effects; voxel FDR vs. cluster-FWE/TFCE
  toggle where runner permits.

Generation strategy: start with one-axis-at-a-time variants around the seed,
optionally add a sparse set of multi-axis combinations to cap total models.

## Validation expectations
- Every generated spec must pass the BIDS Stats Model JSON schema.
- Lightweight design check: build design matrix header to ensure full rank and
  sensible regressor counts (e.g., <50% of timepoints) before writing.

## Future hooks (Phase 2+)
- Literature/registry priors: mine existing `statsmodel_specs` and methods text
  to weight axis options by observed frequency for similar tasks.
- Agent layer: propose variants with rationales, then map onto the whitelisted
  transform functions to keep outputs valid and bounded.
- Multiverse report: voxelwise overlap/Jaccard, ROI effect-size dispersion,
  stability maps (fraction of models significant per voxel/ROI).

## Open questions to settle when implementing
- Default cap for `--max_models` (20? 40?) and whether to include the seed by
  default.
- How to parameterize FIR (fixed window/bin vs. task-specific heuristics).
- Whether to store multiverse manifests under `reports/` or alongside specs.
- Minimum information needed to rerun: should we also emit a `models.jsonl`
  manifest with CLI flags and software versions for provenance?

## Suggested next steps
1) Land this document and link it near the model-spec/run steps in README.
2) Add the `multiverse_specs.py` CLI skeleton with a small global rule set and a
   dataset-specific example.
3) Add `4_run_fitlins_multiverse.sh` wrapper; smoke-test on one dataset/task.
4) Draft a minimal multiverse summary (CSV manifest + TODOs for overlap maps).
