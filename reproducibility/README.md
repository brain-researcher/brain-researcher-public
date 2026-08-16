# Brain Researcher — Reproducibility

This directory is the single home for Brain Researcher reproducibility
materials. Manifest-backed packs and runnable teaching examples are stored
together here by example name.

Each manifest-backed pack carries a v2 `manifest.json`, an
`environment.lock.json`, a `provenance_card.md`, and a pack-specific `README.md`.
Optional directories such as `run/`, `source/`, `artifacts/`, `reproduction/`,
or `execution_pack/` depend on the pack type.

## Which directory should I use?

| Goal | Start here | What it is |
|---|---|---|
| Check a recorded result or schema snapshot | `reproducibility/<id>/` with a `manifest.json` | A manifest-backed pack accepted by `reproducibility/verify.py`. |
| Inspect the HCP workflow-search trajectory | [`hcp_workflow_search/`](hcp_workflow_search/) | An `integrity_verified` derived-artifact replay of Figure 5; it does not rerun governed HCP analyses. |
| Inspect the TRIBE speech--tools trajectory | [`tribe_speech_tools/`](tribe_speech_tools/) | An `integrity_verified` derived-data replay of Figure 6; it does not rerun audio or model inference. |
| Re-run the public A1 result | [`bounded_autoresearch_a1/`](bounded_autoresearch_a1/) | A `public_runnable` real recorded-result pack with public-data scripts plus deeper HCP-gated steps. |
| Inspect the FitLins pack format | [`fitlins_multiverse_yeo17/`](fitlins_multiverse_yeo17/) | An `inspectable` synthetic schema exemplar with partial integrity; it is not a shipped real-data rerun. |
| Run the auditable-claim NiMARE light path | [`auditable_claim_record/`](auditable_claim_record/) | A `public_runnable` tutorial path that emits fresh claim-card JSON. It is **not** a manifest-backed pack. |
| Inspect the historical NeuroLang snapshot | [`auditable_claim_record/`](auditable_claim_record/#reference-path-neurolang-engine-behind-the-committed-card) | Committed JSON that is `inspectable` only; the historical NeuroLang environment is not currently reconstructable from this repository. |

The directory type is determined by its contents, not by another navigation
level: a directory with `manifest.json` is a verifiable pack; the
auditable-claim tutorial has no manifest, so passing it to `verify.py` returns
exit code 2.

## Working directory convention

Unless a command block explicitly says otherwise, run it from the **repository
root**, the directory containing `pyproject.toml` and `reproducibility/`.

For a new clone:

```bash
git clone https://github.com/brain-researcher/brain-researcher-public.git
cd brain-researcher-public
```

If you are already anywhere inside the clone, return to the repository root
with:

```bash
cd "$(git rev-parse --show-toplevel)"
```

In the commands below, `python` means the Python interpreter from your currently
active conda environment or virtual environment.

## Verify a pack (no Brain Researcher install required)

From the repository root:

```bash
python reproducibility/verify.py reproducibility/bounded_autoresearch_a1
python reproducibility/verify.py reproducibility/fitlins_multiverse_yeo17
python reproducibility/verify.py reproducibility/hcp_workflow_search
python reproducibility/verify.py reproducibility/tribe_speech_tools
```

`verify.py` uses only the Python standard library. It re-hashes each manifest
artifact and prints three separate status fields. For a v2 manifest it first
validates the required source, environment, tool, input, seed, tolerance, and
five-level attestation metadata; an invalid v2 contract fails closed with exit
code 1 before hashes are accepted.

- `integrity_verified`: `true` only when every manifest entry is available and
  matches its checksum; `false` for a mismatch or missing file; `null` if any
  entry cannot be checked;
- `executed`: whether a runnable execution pack records a completed analysis;
- `scientifically_reproduced`: whether that execution pack records a completed
  scientific reproduction with matching produced artifacts.

Exit code **0** means the requested verification completed successfully; **1**
means a mismatch or failed execution; **2** means verification is incomplete or
unavailable. Therefore, a manifest with any `schema_only`, oversized, or
unreadable entry reports `integrity_verified: null` and exits 2. The deprecated
`reproduced` field remains as an alias for `scientifically_reproduced`; it is
never set by manifest hashing alone.

A complete checksum-verification result proves the integrity of the committed
snapshot. It does **not** execute an analysis. If a pack actually contains
`execution_pack/run_pack.py` and `execution_pack/expected_artifacts.json`,
`verify.py` instead delegates to that runnable pack. A scientific-reproduction
success then requires the runner to record completed execution, matching
produced artifacts, and a successful scientific comparison.

The cumulative status vocabulary is `inspectable` → `integrity_verified` →
`public_runnable` → `governed_rerun` → `fully_reproduced`. See
[`docs/reproducibility_packs.md`](../docs/reproducibility_packs.md#reproduction-status-vocabulary)
for the exact boundary and the meaning of `partial`.

## Current packs and their rerun boundary

| id | maturity | current level | What you can do from this clone |
|---|---|---|---|
| `bounded_autoresearch_a1` | `stable` | `public_runnable` | Verify the snapshot and reproduce the public-data headline with its shipped script. The governed rerun is partial; deeper reconstruction additionally needs governed derived inputs and subject bindings that are not shipped. `fully_reproduced` is not claimed. |
| `fitlins_multiverse_yeo17` | `historical` | `inspectable` | Check eight shipped files; two unshipped statmap keys keep integrity partial, so execution and scientific reproduction are not claimed. There is no real BIDS dataset or runnable historical environment. |
| `hcp_workflow_search` | `stable` | `integrity_verified` | Validate the 116-candidate search ledger, frozen matched comparisons, cohort counts, and redraw Figure 5 from public-safe derived tables. Restricted HCP inputs, participant-level predictions, and a governed rerun are not shipped or claimed. |
| `tribe_speech_tools` | `stable` | `integrity_verified` | Validate the 15-pair screen, recurring and new-collection geometry tables, and redraw Figure 6. Raw audio, feature tensors, model checkpoints, and underlying inference are not shipped or rerun. |

These status rows describe the frozen packs themselves. Separately, this
repository now ships the governed HCP producing drivers under
[`src/brain_researcher/research/predictive/`](../src/brain_researcher/research/predictive/)
and the TRIBE feature-to-result evaluator chain under
[`src/brain_researcher/research/discovery/programs/`](../src/brain_researcher/research/discovery/programs/).
The HCP drivers remain data- and authorization-gated, and the TRIBE chain does
not ship raw audio, checkpoints, or feature extraction. Neither code surface
changes the evidence level recorded by these derived-data packs.

For the public A1 rerun, first activate an isolated environment, then run this
from the repository root:

```bash
python3.11 -m venv ~/.venvs/br-a1-repro
source ~/.venvs/br-a1-repro/bin/activate
bash reproducibility/bounded_autoresearch_a1/run_end_to_end.sh
```

The script installs its light Python dependencies into the active environment,
downloads the public FC feature archive, verifies its checksum, runs the frozen
predictor, and checks the expected result. It does not use MCP or HCP-controlled
data. See the [pack README](bounded_autoresearch_a1/README.md) for download
size, outputs, and the separately data-gated steps.

## MCP recipes are optional

MCP is not required to verify any pack or to run the public A1 script.

- `get_execution_recipe(tool_id=..., params=...)` returns a local/container/
  cluster recipe. It is a planning and handoff call; it does **not** execute the
  analysis. Use it only when a pack supplies params compatible with the current
  tool contract. The historical synthetic params in
  `fitlins_multiverse_yeo17/run/run.json` do not meet that bar; see that pack's
  README.
- When the connected hosted/deployed MCP exposes it,
  `run_export_pack(run_id=...)` exports an `execution_pack/` from an **existing
  persisted Brain Researcher run**. It takes a `run_id`, not a `tool_id` plus
  params, and is an authoring/export path rather than a prerequisite for using
  the static packs in this repository. Do not assume a bare local checkout
  exposes this deployment-only surface.

Pack paths and provenance are repository-relative and PII-scrubbed for the
public release.
