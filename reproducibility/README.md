# Brain Researcher — Reproducibility Packs

This directory ships **self-verifying reproduction packs** for recorded Brain
Researcher results, so an external reviewer can confirm that the artifacts a
result was built from are exactly the bytes recorded — and, where the data is in
reach, re-run the analysis.

Each pack under `packs/<id>/` carries a `manifest.json` listing every shipped
artifact with its production-time `sha256`, a `provenance_card.md` (the run's
execution envelope + provenance, per `docs/appendices/06_appendix_F_run_bundle_provenance.md`),
and a `README.md` runbook (what it is, how to re-run, how to verify).

## Verify a pack (no Brain Researcher install required)

```bash
python reproducibility/verify.py reproducibility/packs/<id>
```

`verify.py` re-hashes each manifest artifact against the shipped file and prints a
report. Exit code: **0** = reproduced (all shipped checksums match), **1** =
mismatch/missing, **2** = cannot verify. Entries marked `schema_only` (large
provenance-key artifacts whose bytes are not shipped, e.g. NIfTI statmaps in a
synthetic exemplar) are reported `indeterminate`, never a failure. For packs that
ship a runnable `execution_pack/` (emitted by the MCP `run_export_pack` tool),
`verify.py` delegates to `run_pack.py --verify`, which re-executes and diffs
produced-vs-expected checksums.

## Packs

| id | kind | what it demonstrates |
|----|------|----------------------|
| `bounded_autoresearch_a1` | recorded result | A real bounded-autoresearch A1 result (HCP-YA component↔behavior residualised-cognition target + family-block null). Shipped artifacts + real sha256 verify; re-run is data-gated (see the pack README). |
| `fitlins_multiverse_yeo17` | schema exemplar (synthetic) | The run-bundle + multiverse-spec structure for a FitLins Yeo-17 multiverse. A **synthetic** proxy — shipped specs/summary verify by checksum; the statmap NIfTIs are provenance keys only (`schema_only`). Use as the format template, not a real-data result. |

## Reproduce end-to-end

1. `git clone` the public core repo — this `reproducibility/` dir ships with it.
2. Pick a pack; read `packs/<id>/README.md`.
3. `python reproducibility/verify.py reproducibility/packs/<id>` to confirm the shipped bytes.
4. To re-run: create the env (`conda activate brain_researcher` / `pip install -e .`),
   stage any grant-gated data as the pack README documents, then run the recorded
   command (or request a recipe via the MCP `get_execution_recipe` / `run_export_pack`
   using the `tool_id` + `params` in the pack's `run/run.json`).

Provenance/paths in packs are repo-relative and PII-scrubbed (OSS carve redaction).
