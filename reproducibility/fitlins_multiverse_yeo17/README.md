# Pack: fitlins_multiverse_yeo17 (synthetic schema fixture)

This manifest-backed directory preserves a **historical synthetic bundle
shape** for a FitLins Yeo-17 multiverse. It contains no real BIDS dataset and no
NIfTI statmap bytes. It is useful for inspecting and testing the pack format;
it is not a real scientific result and is not runnable end to end as shipped.

## Choose what you want to do

| Goal | Use this | Result |
|---|---|---|
| Check the committed fixture | `python reproducibility/verify.py reproducibility/fitlins_multiverse_yeo17` | Matches seven shipped files; two unshipped statmap keys keep complete integrity indeterminate (exit 2) |
| Inspect the bundle shape | Open `run/run.json`, `run/analysis_bundle.json`, and `source/specs/` | Shows the historical synthetic records only |
| Run a real FitLins multiverse | Do not start from this fixture's params | Supply a real BIDS dataset, current specs, runtime, and scientific comparison criterion |

For a public-data result with an actual rerun command, use
[`../bounded_autoresearch_a1/`](../bounded_autoresearch_a1/). For a tutorial
that generates claim-card JSON, use
[`../auditable_claim_record/`](../auditable_claim_record/).

Run commands from the **repository root**, the directory containing
`pyproject.toml` and `reproducibility/`. From anywhere inside the clone:

```bash
cd "$(git rev-parse --show-toplevel)"
```

## Verify the fixture

```bash
python reproducibility/verify.py reproducibility/fitlins_multiverse_yeo17
```

The report shows seven `match` rows and two `schema_only` rows as
`indeterminate`. Because those NIfTI bytes were intentionally never included,
the overall result is `integrity_verified: null` and exit code 2 rather than a
complete-integrity success. It also reports `executed: false` and
`scientifically_reproduced: false`: this command checks the available fixture
bytes and does not execute FitLins.

Exit 2 is expected for this partial synthetic fixture. It means verification is
incomplete, not that one of the seven shipped files mismatched. A changed or
missing shipped file instead reports `integrity_verified: false` and exits 1.

## What is shipped

- `run/run.json`: historical synthetic step record naming
  `fitlins.run_multiverse`
- `run/analysis_bundle.json`: `analysis-bundle-v1` fixture whose two statmaps
  are path/checksum examples, not downloadable files
- `source/specs/*.json`: synthetic multiverse spec and manifest fixtures
- `source/fitlins/yeo17_summary.csv`: synthetic summary table
- `manifest.json`: seven checksummed entries plus two `schema_only` paths
- `provenance_card.md`: provenance boundary for this synthetic fixture

## Why the recorded params are not a rerun recipe

`run/run.json` records an older example shape:

```text
dataset_id
output_dir
multiverse_run_id
bids_model
```

The current `fitlins.run_multiverse` model in
[`fitlins_tool.py`](../../src/brain_researcher/services/tools/fitlins_tool.py)
instead requires:

```text
study_id
task
bids_root
multiverse_specs
```

It also accepts optional `derivatives_root`, `output_root`, participant filters,
runtime settings, and `execute`. Its safe default is `execute=false`, which
returns planned commands rather than running FitLins.

An honest real rerun therefore needs all of the following:

1. a real BIDS dataset and executor-visible `bids_root`;
2. a valid `study_id` and task whose events match the model;
3. current multiverse spec files;
4. a working FitLins runtime and writable output location;
5. `execute=true` only after reviewing the planned commands; and
6. real expected outputs or a stated scientific equivalence criterion.

This fixture supplies none of those runtime bindings. Do not pass its historical
params unchanged to a current tool and describe the result as a reproduction.

## Optional MCP handoff

After you provide and validate real inputs,
`get_execution_recipe(tool_id="fitlins.run_multiverse", params=...)` can return
a local/container/cluster recipe when that tool is exposed by the connected MCP.
The recipe is a planning handoff; it does not execute the analysis.

Some hosted deployments may also expose `run_export_pack(run_id=...)`. That
exports a pack from an **already persisted run**. This static fixture has no such
live `run_id`, and a bare local checkout should not be assumed to expose that
deployment-only export surface.
