# Brain Researcher — Reproducibility

This directory is the single home for Brain Researcher reproducibility
materials. Manifest-backed packs and runnable teaching examples are stored
together here by example name.

Each manifest-backed pack carries a `manifest.json`, a
`provenance_card.md`, and a pack-specific `README.md`. Optional directories such
as `run/`, `source/`, `artifacts/`, `reproduction/`, or `execution_pack/` depend
on the pack type.

## Which directory should I use?

| Goal | Start here | What it is |
|---|---|---|
| Check a recorded result or schema snapshot | `reproducibility/<id>/` with a `manifest.json` | A manifest-backed pack accepted by `reproducibility/verify.py`. |
| Re-run the public A1 result | [`bounded_autoresearch_a1/`](bounded_autoresearch_a1/) | A real recorded-result pack with public-data scripts plus deeper HCP-gated steps. |
| Inspect the FitLins pack format | [`fitlins_multiverse_yeo17/`](fitlins_multiverse_yeo17/) | A synthetic schema exemplar. It is verifiable but is not a shipped real-data rerun. |
| Learn how an auditable claim record is generated | [`auditable_claim_record/`](auditable_claim_record/) | A runnable tutorial that emits claim-card JSON. It is **not** a manifest-backed pack. |

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
```

`verify.py` uses only the Python standard library. It re-hashes each manifest
artifact and prints three separate status fields:

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

## Current packs and their rerun boundary

| id | kind | What you can do from this clone |
|---|---|---|
| `bounded_autoresearch_a1` | real recorded result | Verify the snapshot and reproduce the public-data headline with its shipped script. Deeper reconstruction additionally needs governed derived inputs and subject bindings that are not shipped. |
| `fitlins_multiverse_yeo17` | synthetic schema exemplar | Check seven shipped specs/summary files; two unshipped statmap keys remain indeterminate, so complete integrity and scientific reproduction are not claimed. There is no real BIDS dataset or execution pack. |

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

MCP is not required to verify either pack or to run the public A1 script.

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
