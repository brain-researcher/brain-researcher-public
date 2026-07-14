# Brain Researcher — Reproducibility Packs

This directory ships **self-verifying reproduction packs** for recorded Brain
Researcher results. A reviewer can confirm that the shipped artifacts are the
exact bytes named by a manifest and, when the required data and runnable scripts
are available, re-run the analysis.

Each pack under `packs/<id>/` carries a `manifest.json`, a
`provenance_card.md`, and a pack-specific `README.md`. Optional directories such
as `run/`, `source/`, `artifacts/`, `reproduction/`, or `execution_pack/` depend
on the pack type.

## Which directory should I use?

| Goal | Start here | What it is |
|---|---|---|
| Check a recorded result or schema snapshot | `reproducibility/packs/<id>/` | A manifest-backed pack accepted by `reproducibility/verify.py`. |
| Re-run the public A1 result | [`packs/bounded_autoresearch_a1/`](packs/bounded_autoresearch_a1/) | A real recorded-result pack with public-data scripts plus deeper HCP-gated steps. |
| Inspect the FitLins pack format | [`packs/fitlins_multiverse_yeo17/`](packs/fitlins_multiverse_yeo17/) | A synthetic schema exemplar. It is verifiable but is not a shipped real-data rerun. |
| Learn how an auditable claim record is generated | [`../examples/auditable_claim_record/`](../examples/auditable_claim_record/) | A runnable tutorial that emits claim-card JSON. It is an example, **not** a manifest-backed pack. |

The two top-level folders are therefore intentionally different:
`reproducibility/` contains immutable, checksummed audit packages, while
`examples/` contains teaching and integration examples. The auditable-claim
example has no `manifest.json`, so passing it to `verify.py` returns exit code 2.

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
python reproducibility/verify.py reproducibility/packs/bounded_autoresearch_a1
python reproducibility/verify.py reproducibility/packs/fitlins_multiverse_yeo17
```

`verify.py` uses only the Python standard library. It re-hashes each manifest
artifact and prints a JSON report. Exit code **0** means all shipped,
checksum-bearing files match; **1** means a mismatch or missing file; **2** means
the path is not a verifiable pack. `schema_only` entries are reported
`indeterminate` because their bytes are intentionally not shipped.

Checksum verification proves the integrity of the committed snapshot. It does
**not** execute an analysis. If a pack actually contains
`execution_pack/run_pack.py` and `execution_pack/expected_artifacts.json`,
`verify.py` instead delegates to that runnable pack and compares produced output
against expected checksums.

## Current packs and their rerun boundary

| id | kind | What you can do from this clone |
|---|---|---|
| `bounded_autoresearch_a1` | real recorded result | Verify the snapshot and reproduce the public-data headline with its shipped script. Deeper reconstruction additionally needs governed derived inputs and subject bindings that are not shipped. |
| `fitlins_multiverse_yeo17` | synthetic schema exemplar | Verify the shipped specs and summary. There is no real BIDS dataset, statmap payload, or ready-to-run execution pack in this directory. |

For the public A1 rerun, first activate an isolated environment, then run this
from the repository root:

```bash
python3.11 -m venv ~/.venvs/br-a1-repro
source ~/.venvs/br-a1-repro/bin/activate
bash reproducibility/packs/bounded_autoresearch_a1/run_end_to_end.sh
```

The script installs its light Python dependencies into the active environment,
downloads the public FC feature archive, verifies its checksum, runs the frozen
predictor, and checks the expected result. It does not use MCP or HCP-controlled
data. See the [pack README](packs/bounded_autoresearch_a1/README.md) for download
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
