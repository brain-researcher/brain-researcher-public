# Pack: fitlins_multiverse_yeo17 — schema exemplar (SYNTHETIC)

This pack shows the run-bundle and multiverse-spec **structure** for a FitLins
Yeo-17 analysis. It is a small, synthetic, checksum-verifiable format example.
It is **not** a real-data result and is **not runnable end to end as shipped**.

Use this pack when you want to inspect the expected file layout. Use
[`../bounded_autoresearch_a1/`](../bounded_autoresearch_a1/) when you want a
public-data result with an actual rerun command. The worked claim-record tutorial
under [`../../../examples/auditable_claim_record/`](../../../examples/auditable_claim_record/)
is a third, different surface: it generates claim-card JSON and is not a
manifest-backed pack.

## Working directory

Run the command below from the **repository root**. From anywhere inside the
clone:

```bash
cd "$(git rev-parse --show-toplevel)"
```

## What is shipped

- `run/run.json` — a historical synthetic step record naming
  `fitlins.run_multiverse` and example params.
- `run/analysis_bundle.json` — an `analysis-bundle-v1` record with a file
  manifest. Statmap entries are provenance keys only; their NIfTI bytes are not
  shipped.
- `source/specs/*.json` — synthetic multiverse specifications and manifest.
- `source/fitlins/yeo17_summary.csv` — a small synthetic summary table.
- `manifest.json` — checksums for shipped files; missing statmap payloads are
  marked `schema_only`.

## Verify the shipped snapshot

From the repository root:

```bash
python reproducibility/verify.py reproducibility/packs/fitlins_multiverse_yeo17
```

Exit code 0 means the seven shipped files match their checksums. The two
`schema_only` statmap entries appear as `indeterminate`; that is expected because
the NIfTI payloads are not part of this synthetic pack. This command checks the
snapshot and does not run FitLins.

## Why there is no rerun command

An end-to-end FitLins rerun would need all of the following, none of which is
fully bound by this pack:

1. a real BIDS dataset and its local `bids_root`;
2. a valid `study_id` and task whose conditions match the model;
3. current multiverse spec paths;
4. a FitLins runtime and an output directory; and
5. real expected statmaps or a scientific equivalence criterion.

The params in `run/run.json` use an older synthetic shape
(`dataset_id`, `output_dir`, `multiverse_run_id`, and `bids_model`). The public
`fitlins.run_multiverse` contract shipped in this repository revision instead
requires `study_id`, `task`, `bids_root`, and `multiverse_specs`. Do **not** pass
the recorded params unchanged to `get_execution_recipe` and describe the result
as a reproduction.

After you supply and validate the real inputs, MCP
`get_execution_recipe(tool_id="fitlins.run_multiverse", params=...)` can return
a local Python recipe. That call produces a recipe only; it does not execute the
analysis. When a connected hosted/deployed MCP exposes
`run_export_pack(run_id=...)`, that tool applies only after a real run has
already been persisted; it is not a way to run this static schema exemplar and
should not be assumed available in a bare local checkout.
