# Autoresearch script governance

This directory is an inventory of several research lines, not one executable
workflow. The status matrix below covers every tracked Python and shell script
under `scripts/autoresearch/`.

Status meanings:

- **runnable**: supported public entrypoint with a documented reproducibility
  path and focused tests.
- **governed**: finite utility with explicit input/output arguments and a
  fail-closed CLI contract. It may still require governed or private data and is
  not a public end-to-end example.
- **worker**: operator-controlled process that launches jobs, mutates an external
  workspace, or runs until a bound is reached. It requires an explicit runtime
  and is not supported as a public example.
- **historical**: point-in-time campaign, figure, adapter, or patch material.
  Retained for provenance only; do not execute it as current guidance.

Only **runnable** means that a public user should start there. **Governed** does
not mean that the required inputs are distributed, and script completion never
establishes scientific validity by itself.

These script-level labels refine the repository-wide documentation statuses:

- **active**: the single runnable tutorial and governed utilities with shipped
  inputs or an explicitly documented staging path.
- **experimental**: governed utilities and workers that remain research or
  operator surfaces rather than supported public tutorials.
- **historical**: the historical rows below, retained only for provenance.
- **private-input-required**: any governed utility or worker whose named HCP,
  TRIBE, FC, model, or external-workspace input is not distributed here.

## Root scripts

| Script | Status | Execution boundary |
|---|---|---|
| [`launch_bounded_supervisor_tmux.sh`](launch_bounded_supervisor_tmux.sh) | **worker** | Creates a detached tmux supervisor and restart scripts; operator-owned runtime only. |
| [`make_figure12_data_only_validation.py`](make_figure12_data_only_validation.py) | **historical** | Re-renders a dated manuscript figure from campaign-specific artifact roots. |
| [`migrate_research_roots.py`](migrate_research_roots.py) | **governed** | Requires `--data-root` and prints a migration plan by default; filesystem mutation requires explicit `--apply`. |
| [`run_auditable_claim_demo.py`](run_auditable_claim_demo.py) | **runnable** | Canonical implementation helper for the auditable-claim tutorial; requires a staged NiMARE corpus. |

## Discovery scripts

| Script | Status | Execution boundary |
|---|---|---|
| [`discovery/build_hcp_language_covariate_sidecar.py`](discovery/build_hcp_language_covariate_sidecar.py) | **governed** | Requires an explicit manifest and output directory; writes covariate and balance diagnostics. |
| [`discovery/build_hcp_language_exchangeability_manifest.py`](discovery/build_hcp_language_exchangeability_manifest.py) | **governed** | Requires explicit embedding rows and output path; records descriptive exchangeability metadata only. |
| [`discovery/build_hcp_language_heldout_manifest.py`](discovery/build_hcp_language_heldout_manifest.py) | **governed** | Requires base/used manifests and output path; creates a deterministic held-out manifest. |
| [`discovery/build_hcp_language_layer_family_confirmatory_manifest.py`](discovery/build_hcp_language_layer_family_confirmatory_manifest.py) | **governed** | Requires both manifests, word-list root, and output; builds the locked paired design. |
| [`discovery/extract_tribe_layer_features.py`](discovery/extract_tribe_layer_features.py) | **governed** | Finite GPU utility with required manifest, cache, and output paths; exits nonzero if no item or feature matrix succeeds. |
| [`discovery/generate_nanobanana_tribe_schematic.py`](discovery/generate_nanobanana_tribe_schematic.py) | **historical** | Dated external image-generation helper, not an evidence or public reproduction path. |
| [`discovery/make_tribe_branch_outcome_landscape.py`](discovery/make_tribe_branch_outcome_landscape.py) | **historical** | Campaign-specific deterministic figure renderer with private artifact defaults. |
| [`discovery/make_tribe_discovery_paper_plate_v2.py`](discovery/make_tribe_discovery_paper_plate_v2.py) | **historical** | Dated paper-plate renderer over the discovery campaign ledger. |
| [`discovery/make_tribe_discovery_story_plate.py`](discovery/make_tribe_discovery_story_plate.py) | **historical** | Dated multi-panel story renderer over local figure tables. |
| [`discovery/make_tribe_h1_to_h1prime_figures.py`](discovery/make_tribe_h1_to_h1prime_figures.py) | **historical** | Fixed H1-to-H1-prime report figures with embedded campaign assumptions. |
| [`discovery/make_tribe_neural_bridge_figures.py`](discovery/make_tribe_neural_bridge_figures.py) | **historical** | Campaign figure renderer; does not provide observed neural evidence. |
| [`discovery/make_tribe_predicted_response_surface_figures.py`](discovery/make_tribe_predicted_response_surface_figures.py) | **historical** | Renders dated predicted-response artifacts, not observed fMRI. |
| [`discovery/make_tribe_remaining_figures.py`](discovery/make_tribe_remaining_figures.py) | **historical** | Remaining campaign-specific figure batch. |
| [`discovery/make_tribe_representation_figures.py`](discovery/make_tribe_representation_figures.py) | **historical** | Dated representation-depth figure helper over local evidence tables. |
| [`discovery/manifest_synthesizer.py`](discovery/manifest_synthesizer.py) | **historical** | Embedded campaign module with no standalone public CLI. |
| [`discovery/materialize_biomo_runtime.py`](discovery/materialize_biomo_runtime.py) | **governed** | Requires explicit source MAT, output root, and manifest path; materializes a finite stimulus set. |
| [`discovery/materialize_hcp_ready_runtime.py`](discovery/materialize_hcp_ready_runtime.py) | **historical** | VM-era indexer with site-specific project and protocol defaults. |
| [`discovery/materialize_patch.py`](discovery/materialize_patch.py) | **historical** | In-place patch for a fixed external TRIBE workspace. |
| [`discovery/oscillation_convergence_patch.py`](discovery/oscillation_convergence_patch.py) | **historical** | In-place policy patch for a dated external controller. |
| [`discovery/overlay_nanobanana_tribe_schematic_labels.py`](discovery/overlay_nanobanana_tribe_schematic_labels.py) | **historical** | Dated post-processing step over a generated schematic. |
| [`discovery/proposal_promoter_patch.py`](discovery/proposal_promoter_patch.py) | **historical** | In-place patch for a dated external proposal controller. |
| [`discovery/render_tribe_latex_report.py`](discovery/render_tribe_latex_report.py) | **historical** | Renders a campaign report from local artifact defaults; not a general report CLI. |
| [`discovery/run_action_executor.sh`](discovery/run_action_executor.sh) | **worker** | Polls decisions and launches bounded GPU work in an external discovery project. |
| [`discovery/run_biological_motion_redesign_branch.py`](discovery/run_biological_motion_redesign_branch.py) | **governed** | Finite branch runner with explicit manifest/output and bounded permutation arguments. |
| [`discovery/run_biomo_motion_aware_redesign.py`](discovery/run_biomo_motion_aware_redesign.py) | **historical** | Dated follow-up analysis with campaign-specific input/output defaults. |
| [`discovery/run_live_watchdog.sh`](discovery/run_live_watchdog.sh) | **worker** | Bounded decision-producing loop over an external discovery project; it is not the action executor. |
| [`discovery/score_smoothing_patch.py`](discovery/score_smoothing_patch.py) | **historical** | In-place score-policy patch for a fixed worker checkout. |
| [`discovery/state_evolution_patch.py`](discovery/state_evolution_patch.py) | **historical** | In-place state-evolution patch for a dated controller. |
| [`discovery/validate_embedding_contrast_covariate_adjusted.py`](discovery/validate_embedding_contrast_covariate_adjusted.py) | **governed** | Requires explicit prediction, covariate, contrast, and output inputs; writes a bounded sensitivity analysis. |
| [`discovery/validate_embedding_contrast_permutation.py`](discovery/validate_embedding_contrast_permutation.py) | **governed** | Requires explicit prediction/contrast/output inputs and uses exact or seeded bounded permutations. |
| [`discovery/validate_embedding_permutation.py`](discovery/validate_embedding_permutation.py) | **governed** | Requires an explicit closed-loop root and output directory for the locked validation set. |
| [`discovery/validate_hcp_language_barch2013_group_alignment.py`](discovery/validate_hcp_language_barch2013_group_alignment.py) | **governed** | Requires named prediction directories and output; missing group/ROI evidence is recorded as blocked, not success. |
| [`discovery/validate_layer_feature_contrast_permutation.py`](discovery/validate_layer_feature_contrast_permutation.py) | **governed** | Requires explicit rows, feature layers, and output; performs bounded max-stat correction. |
| [`discovery/validate_layer_feature_family_confirmatory.py`](discovery/validate_layer_feature_family_confirmatory.py) | **governed** | Requires explicit feature rows and output for the locked within-pair test. |
| [`discovery/validate_predicted_fmri_fold_stability.py`](discovery/validate_predicted_fmri_fold_stability.py) | **governed** | Requires explicit prediction folds and output; reports predicted-response evidence only. |
| [`discovery/zero_score_refute_patch.py`](discovery/zero_score_refute_patch.py) | **historical** | In-place kill-policy patch for a fixed external controller. |

## Foundation exploration scripts

| Script | Status | Execution boundary |
|---|---|---|
| [`foundation_exploration/run_mve24.py`](foundation_exploration/run_mve24.py) | **governed** | Historical filename for the MVE100 search driver; requires explicit HCP inputs, a pinned controller runtime, an output bundle, and human authorization before launch. |
| [`foundation_exploration/run_mve100_recovery12.py`](foundation_exploration/run_mve100_recovery12.py) | **governed** | Replays the fixed 12-slot recovery protocol from an explicit failed source bundle; launch requires a separate authorization artifact. |
| [`foundation_exploration/run_hcp_nested100_replay.py`](foundation_exploration/run_hcp_nested100_replay.py) | **governed** | Runs the fixed retrospective Nested-100 replay from explicit governed HCP inputs and writes to a caller-selected output directory. |
| [`foundation_exploration/run_hcp_liu_matched_comparator.py`](foundation_exploration/run_hcp_liu_matched_comparator.py) | **governed** | Prepares or runs the frozen Liu matched comparator from explicit governed inputs; it does not add a separate authorization artifact. |
| [`foundation_exploration/run_hcp_calibration_equivalence_r2.py`](foundation_exploration/run_hcp_calibration_equivalence_r2.py) | **governed** | Prepares or launches the frozen ten-repeat R2 comparison from explicit upstream artifacts; launch requires human authorization. |
| [`foundation_exploration/run_hcp_cross_component_transfer_r3.py`](foundation_exploration/run_hcp_cross_component_transfer_r3.py) | **governed** | Prepares, validates authorization for, or launches the frozen four-outcome R3 transfer analysis over governed HCP artifacts. |
| [`foundation_exploration/run_hcp_cognition_r2_paired_inference.py`](foundation_exploration/run_hcp_cognition_r2_paired_inference.py) | **governed** | Runs the frozen conditional paired inference over persisted R2 predictions only after its explicit authorization and interpretation acknowledgements. |
| [`foundation_exploration/run_hcp_cross_component_transfer_inference.py`](foundation_exploration/run_hcp_cross_component_transfer_inference.py) | **governed** | Runs the frozen weak-FWER transfer inference over persisted R3 predictions only after its explicit authorization and interpretation acknowledgements. |

## Functional-connectivity scripts

| Script | Status | Execution boundary |
|---|---|---|
| [`fc/build_hcp_exchangeability_manifest.py`](fc/build_hcp_exchangeability_manifest.py) | **historical** | Dated HCP family audit with private project defaults. |
| [`fc/launch_live_watchdog_tmux.sh`](fc/launch_live_watchdog_tmux.sh) | **worker** | Starts the FC watchdog in a detached local tmux session. |
| [`fc/liu_confirmatory_permutation.py`](fc/liu_confirmatory_permutation.py) | **governed** | Requires an explicit frozen workspace; runs a resumable, bounded permutation analysis. |
| [`fc/liu_define_post_selection_family.py`](fc/liu_define_post_selection_family.py) | **historical** | Campaign-specific candidate-family definition with private defaults. |
| [`fc/liu_max_over_pipelines_permutation.py`](fc/liu_max_over_pipelines_permutation.py) | **historical** | Dated post-selection campaign runner with private workspace defaults. |
| [`fc/liu_merge_max_over_pipelines_shards.py`](fc/liu_merge_max_over_pipelines_shards.py) | **governed** | Requires explicit shard directories, output, and expected permutation count; exits 2 when incomplete. |
| [`fc/liu_post_selection_inventory.py`](fc/liu_post_selection_inventory.py) | **historical** | Dated inventory over a private predictive project. |
| [`fc/make_liu_paper_plate_figures.py`](fc/make_liu_paper_plate_figures.py) | **historical** | Campaign-specific paper-plate renderer with local artifact defaults. |
| [`fc/run_contract_closure_batch.sh`](fc/run_contract_closure_batch.sh) | **worker** | Appends experiment rows and launches missing controls in an explicit FC project. |
| [`fc/run_live_watchdog.sh`](fc/run_live_watchdog.sh) | **worker** | Bounded controller loop that may launch analyses in an external FC project. |
| [`fc/score_component_line.py`](fc/score_component_line.py) | **governed** | Side-effect-bounded scorer with required ledger and manifest paths. |
| [`fc/score_explicit.py`](fc/score_explicit.py) | **governed** | Standalone scorer with required ledger and optional explicit output. |

Supporting Markdown rubrics and the Nano Banana prompt are non-executable
research records and therefore are not script rows.

## Working directory and execution

Resolve repository-relative paths from the repository root:

```bash
cd "$(git rev-parse --show-toplevel)"
python scripts/autoresearch/run_auditable_claim_demo.py --help
```

The supported reproduction path is
[Auditable claim record](../../reproducibility/auditable_claim_record/README.md).
The bounded A1 pack is documented separately at
[Bounded autoresearch A1](../../reproducibility/bounded_autoresearch_a1/README.md).

For a **governed** utility, run `--help`, supply every required path explicitly,
and keep generated outputs outside the checkout unless its owning workflow says
otherwise. For a **worker**, inspect the script and export every project/runtime
variable before launch. Never infer that the public clone ships the private HCP,
TRIBE, FC, model, or worker assets named by these historical campaigns.
