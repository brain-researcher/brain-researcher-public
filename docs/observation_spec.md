## Observation bundle (run-level source of truth)

- **Canonical file**: `observation.json` (`observation-v1`).
- **Location**: written into each `run_dir` by the orchestrator worker finalize path.
- **Content**: RunCard-like core (job metadata, datasets, tools, parameters), `provenance` (best-effort), `artifacts` (with checksum + status), `steps` (with preflight/exec/postcheck + violations), `diagnostics_summary`, `violations`, and file refs (`analysis.json`, `provenance.json`, `trace.jsonl` when present).

### Relationship to other files
- `provenance.json`: best-effort tool/step lineage; now also carries phase metadata and mask/violations. Observation embeds a copy but observation is the source used by UI.
- `analysis.json`: lightweight manifest of artifacts with checksums. Generated via the shared `analysis_manifest.py` helper; observation references it via `files.analysis_json`.
- `trace.jsonl`: per-step trace (`trace-v1`) for training/analytics; observation references it via `files.trace_jsonl`.

### Consumption guidance
- UI (evidence rail) and exports should read from `observation.json` first; fall back to provenance/analysis only if explicitly needed.
- Agents/CLI should not reconstruct run state from scattered files—prefer observation + trace.

### Open follow-ups
- Enforce checksum required/skip semantics across all artifact emitters.
- Map gate warnings to a `DEGRADED` run flag and expose in diagnostics_summary.
- Publish a machine-readable schema doc alongside `observation.schema.json`.

