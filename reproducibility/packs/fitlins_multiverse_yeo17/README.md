# Pack: fitlins_multiverse_yeo17 — schema exemplar (SYNTHETIC)

The run-bundle + multiverse-spec **structure** for a FitLins Yeo-17 multiverse
analysis. This is a **synthetic proxy** (small, CI-guarded) that models the pack
format — NOT a real-data result. Use it as the template for what a workflow
reproduction pack looks like.

## Contents
- `run/run.json` — the recorded step: tool `fitlins.run_multiverse` + params.
- `run/analysis_bundle.json` — analysis-bundle-v1 with a `file_manifest` (statmap
  entries are **provenance keys only** — the NIfTI bytes are not shipped).
- `source/specs/*.json` — the multiverse specification + manifest.
- `source/fitlins/yeo17_summary.csv` — a small summary table (shipped + verifiable).
- `manifest.json` — shipped files with real sha256; statmaps marked `schema_only`.

## Verify
```bash
python reproducibility/verify.py reproducibility/packs/fitlins_multiverse_yeo17
```
Exit 0 = shipped specs/summary match their checksums; the `schema_only` statmaps
are reported `indeterminate` (bytes not shipped) — expected for a schema exemplar.

## Re-run
Reconstruct via the recorded `tool_id` + params in `run/run.json` against a real
BIDS dataset (see `docs/runbooks/workflow_fitlins_multiverse_yeo17.md`). A real run
would produce the statmaps whose provenance keys are recorded here.

Source: `tests/fixtures/review/fitlins_multiverse_binding_golden/`.
