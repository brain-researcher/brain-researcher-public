# Demo Scripts

This directory contains demo and catalog helpers. Not every file here is a
public release entrypoint.

## Supported Release-Facing Scripts

| Script | Purpose | Notes |
| --- | --- | --- |
| `build_demo_runs.py` | Builds normalized demo bundles for the Web UI demo catalog from an index and existing artifacts. | Does not execute analysis pipelines. This is the main release demo materialization script. |
| `prepare_realtime_twophoton_demo.py` | Builds a synthetic realtime two-photon replay and calibration bundle. | Covered by focused unit tests. Outputs are synthetic demo artifacts. |
| `demo_pipeline_routing.py` | Probes pipeline-catalog routing for a small set of canonical queries. | Does not execute tools or call an LLM. Requires Neo4j settings for live catalog lookup. |
| `generate_connectivity_demo.py` | Generates functional-connectivity demo artifacts from a BOLD input. | Use explicit paths for public/reproducible runs; defaults are environment-specific. |

## Exploratory Or Legacy Demos

These scripts are retained for review but are not the supported public demo
surface until they have current docs, inputs, and focused smoke coverage:

- `demo_catalog.py`
- `demo_evidence_based_strength.py`
- `demo_glm_validation.py`
- `fusion_examples.py`
- `run_grandmaster_demos.py`
- `run_rest_demo.py`

## Cleanup Rule

For public release work, prefer `build_demo_runs.py` and documented artifacts.
If an exploratory demo becomes supported, add a current invocation, required
environment variables, expected outputs, and a focused validation path here. If a
demo is removed, update any docs or tests that mention it in the same change.
