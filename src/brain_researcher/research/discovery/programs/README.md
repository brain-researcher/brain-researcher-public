# Public TRIBE speech-tools producing chain

This directory contains the parameterized public implementation of the TRIBE
speech-tools scientific evaluator chain. The frozen derived-table replay stays
at reproducibility/tribe_speech_tools and is intentionally unchanged.

## Runnable public surface

The public evaluator accepts a caller manifest plus six locked-layer NumPy
feature matrices for reference and evaluation. It writes an attempt record,
runtime state, evaluation artifact, and terminal-evidence artifact to four
caller-named output files.

The v2 command is:

    PYTHONPATH=src python -m \
      brain_researcher.research.discovery.programs.tribe_speech_tools_new_source_asr_covariate_validation_v2.execution \
      evaluate \
      --manifest manifest.json \
      --reference-matrix-map reference-matrices.json \
      --evaluation-matrix-map evaluation-matrices.json \
      --evaluation-artifact evaluation.json \
      --state-artifact state.json \
      --terminal-artifact terminal.json \
      --attempt-artifact attempt.json

Run the same command with verify in place of evaluate to reconstruct the
evaluation and validate the attempt, state, evaluation, and terminal artifacts.
The recurring-v1 module provides the corresponding command at
tribe_speech_tools_acoustic_matched_validation_v1.execution.

All roots, model locations, checkpoint locations, runtime command, runtime
seed, feature maps, and output files are explicit manifest, CLI, or adapter
inputs. The public CLI consumes precomputed matrices only. A caller can use
the library API with an injected feature adapter, but the public code does not
start the configured command.

## Controlled-history v2 inference

For a controlled v2 replay, first run `evaluate` with one source packet,
exactly eight historical-exposure sidecars, and the two feature manifests that
name the supplied matrices:

    PYTHONPATH=src python -m \
      brain_researcher.research.discovery.programs.tribe_speech_tools_new_source_asr_covariate_validation_v2.execution \
      evaluate \
      --manifest manifest.json \
      --reference-matrix-map reference-matrices.json \
      --evaluation-matrix-map evaluation-matrices.json \
      --reference-feature-manifest reference-layer-feature-manifest.json \
      --evaluation-feature-manifest evaluation-layer-feature-manifest.json \
      --evaluation-artifact evaluation.json \
      --state-artifact state.json \
      --terminal-artifact terminal.json \
      --attempt-artifact attempt.json \
      --source-packet source-packet.json \
      --historical-exposure-sidecar history-01.json \
      --historical-exposure-sidecar history-02.json \
      --historical-exposure-sidecar history-03.json \
      --historical-exposure-sidecar history-04.json \
      --historical-exposure-sidecar history-05.json \
      --historical-exposure-sidecar history-06.json \
      --historical-exposure-sidecar history-07.json \
      --historical-exposure-sidecar history-08.json

Then run that exact command again with `verify-controlled-history` in place of
`evaluate`. `verify-controlled-history` verifies the artifacts written by the
first command; it does not create them when the output paths are empty.

The driver first reconstructs the score-blind validator binding, then replaces
its protected row and collection labels with manifest-provided opaque
row-#### and collection-## keys. It retains condition, collection partition,
segment count, selected-panel membership, locked layers, seeds, draw count,
permutation type, and Holm order. In non-fixture inference, the contract
requires the frozen 99,999 draws, PCG64, the locked seeds, and the H1/H2/H3/H5
family order. Each matrix map must resolve to precisely the six matrix paths
declared by its corresponding feature manifest; an arbitrary matrix of the
right shape is rejected. Terminal replay rejects artifacts that re-emit a
controlled-history token or an absolute path.

## Evidence boundary

synthetic_fixture is an executable engineering check from synthetic matrices to
artifacts. It is not a raw-input scientific rerun and it is not scientific
evidence. The public evaluator chain is runnable; a raw-audio/model controlled
rerun remains externally governed and is not claimed by this repository.

The frozen pack remains a derived-data replay, not a producing-chain runtime.
It validates shipped summaries and figures only. It does not invoke the code
in this directory.

## Mechanical publicization map

| Public file | Mechanically retained | Deliberate public boundary |
| --- | --- | --- |
| tribe_speech_tools_acoustic_matched_validation_v1/evaluator.py | Locked layers; D, S, C, G, AUC; four-conjunct decision; bundle and feature-manifest validation; immutable result write and deterministic result read/replay | Protected row/source identities become caller row_key and collection_key; storage paths are not persisted in result artifacts; runtime assets are explicit configuration |
| tribe_speech_tools_acoustic_matched_validation_v1/execution_contract.py and execution.py | Attempt, state, evaluation, terminal stages and terminal evaluator replay | Registration and launch services become an explicit manifest plus optional feature adapter; configured command is never started |
| tribe_speech_tools_new_source_asr_covariate_validation_v2/contracts.py | Candidate-pool counts, score-blind constraints, selection validation, acoustic balance, frozen reference binding, seeds, draws, and Holm configuration | Historical rows, source tokens, PCM identities, and collection labels are caller-supplied and are rekeyed before public evaluation output |
| tribe_speech_tools_new_source_asr_covariate_validation_v2/score_blind_selector.py | Minimax acoustic-balance objective, parent constraint, segment diversity, deterministic tie break | Candidate acquisition is injected |
| tribe_speech_tools_new_source_asr_covariate_validation_v2/evaluator.py | D/S/C/AUC geometry; H1, H2, H3, H5; balanced-label and blocked permutations; Holm decisions | Inputs are matrices and logical rows supplied by the public contract |
| tribe_speech_tools_new_source_asr_covariate_validation_v2/execution_contract.py and execution.py | Attempt consumption, runtime state, evaluation artifact, terminal bundle, and exact terminal replay | Protected registration context becomes explicit manifest, source packet, sidecars, and injected binding |
| source_intake.py, source_materializer.py, intake_tooling.py, producer_evidence.py, canonical_input_materializer.py | Typed candidate, score-blind, historical-exposure, blinded-QC, provenance, and canonical-input stages | Remote catalog access, media decoding, raw-media copying, and model assets are caller adapters or external dependencies |

No protected audio, feature arrays, checkpoints, source catalog values, or
historical identities are shipped in this source tree.
