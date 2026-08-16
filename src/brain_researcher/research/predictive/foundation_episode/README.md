# HCP predictive producing code

This directory and its sibling `predictive` modules ship the canonical
historical HCP predictive implementation. They are governed code surfaces, not
public end-to-end HCP reruns or scientific-result claims.

## Canonical entrypoints

| Stage | Library implementation | Governed CLI |
|---|---|---|
| MVE-100 discovery | `foundation_episode/` | `scripts/autoresearch/foundation_exploration/run_mve24.py` |
| 12-slot recovery | `foundation_episode/recovery.py` | `scripts/autoresearch/foundation_exploration/run_mve100_recovery12.py` |
| Nested 100 replay | `hcp_nested100_replay.py` | `scripts/autoresearch/foundation_exploration/run_hcp_nested100_replay.py` |
| Liu matched comparator | `hcp_liu_matched_comparator.py` | `scripts/autoresearch/foundation_exploration/run_hcp_liu_matched_comparator.py` |
| R2 calibration equivalence | `hcp_calibration_equivalence_r2.py` | `scripts/autoresearch/foundation_exploration/run_hcp_calibration_equivalence_r2.py` |
| R3 cross-component transfer | `hcp_cross_component_transfer_r3.py` | `scripts/autoresearch/foundation_exploration/run_hcp_cross_component_transfer_r3.py` |
| R3 transfer inference | `hcp_cross_component_transfer_inference.py` | `scripts/autoresearch/foundation_exploration/run_hcp_cross_component_transfer_inference.py` |
| Cognition paired inference | `hcp_cognition_r2_paired_inference.py` | `scripts/autoresearch/foundation_exploration/run_hcp_cognition_r2_paired_inference.py` |

`run_mve24.py` is the historical MVE-100 command name. No duplicate
`run_mve100.py` wrapper is shipped.

## External governed boundary

Every data root, source bundle, authorization path, output directory, worker
count, and runtime path is supplied at invocation time. The repository does
not distribute HCP assets, participant or family identifiers, target tables,
prediction vectors, execution receipts, or previously generated governed
artifacts.

MVE-100 uses score-blind `preflight` followed by a separate human-authorized
`launch`. Recovery has the same separation. R2, R3, and both inference drivers
first write inactive authorization templates; their launch paths require a
completed authorization and retain their historical claim boundaries. Command
completion is operational evidence only: it does not grant confirmation,
independent replication, external validation, or scientific acceptance.

## Runtime and protocol controls

MVE and recovery accept an explicit Codex binary and runtime configuration.
MVE writes that runtime to its controller contract and forwards the same values
to the supervised child process. R2 exposes repeat workers and optional repeat
seeds; R3 exposes worker count; the inference drivers expose draws plus
permutation and bootstrap seeds. Input roots and output directories are always
explicit CLI arguments.

Defaults preserve the historical folds, grids, estimands, and seed schedules.
Changing a statistical seed changes the resulting protocol and cannot be
described as an exact historical reproduction. Changing a Codex binary, model,
reasoning setting, version, or timeout likewise produces a separately recorded
runtime. Worker overrides alter resource scheduling, not the estimand.

## Public test boundary

Focused tests use a synthetic governed-form fixture only for the real transfer
inference `prepare` and `validate-authorization` path. It contains no governed
HCP values or prediction vectors and does not execute inference. The frozen
`reproducibility/hcp_workflow_search` pack remains a derived-artifact replay;
it is not upgraded to a producing-code pack and does not claim a governed
rerun.
