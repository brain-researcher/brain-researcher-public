# Canonical Observation (`observation.json`)

This repo standardizes run-level “what happened” data under a single canonical
document: `observation.json` (schema `observation-v1`).

## Source of truth

- **Source-of-truth for UI/export:** `observation.json`
- **Back-compat / raw traces:** `provenance.json`
- **Optional manifest:** `analysis.json` (best-effort; may be absent)

The Web UI Evidence Rail first tries `/api/jobs/{job_id}/observation` and only
falls back to legacy endpoints when the observation document is unavailable.

## Where it is generated

On terminal job completion (succeeded/failed/timeout/cancelled), the orchestrator
writes `observation.json` into the run directory.

Server endpoint:
- `GET /api/jobs/{job_id}/observation` serves `observation.json` if present, or
  synthesizes it best-effort and persists it.

## What it contains (v1)

`observation.json` is a wrapper that can embed legacy payloads while providing
stable top-level identifiers and file references:

- `schema_version`: `"observation-v1"`
- `job_id`, `run_id`, `state`, timestamps
- `files`: relative references (when available) to:
  - `observation_json` (self)
  - `provenance_json`
  - `analysis_json`
- `run_card`: canonical “RunCard-like” summary used by the UI
- `provenance`: best-effort embedded copy of `provenance.json` (when present)
- `artifacts`: artifact list (with per-artifact checksum fields filled best-effort)
- `steps`: UI-friendly step summaries (derived from provenance child runs)
- `diagnostics_summary`: run-level stable summary of warnings/errors/recovery

## Relationship to `provenance.json`

`provenance.json` is the low-level execution trace written by the recorder. It
may include:

- run timestamps / command / environment
- child step summaries (`child_runs`)

`observation.json` may embed the provenance payload and will also derive
UI-friendly `steps` from it. The long-term direction is that clients should not
need to parse raw provenance directly.

## Relationship to `analysis.json`

`analysis.json` is an optional manifest emitted by the orchestrator on success.
It is not a UI dependency. When present, `observation.json.files.analysis_json`
points to it.

## Artifact checksums (policy)

Per-artifact SHA256 checksums are populated best-effort during observation
generation.

- Output fields:
  - `checksum` (when computed): `"sha256:<hex>"`
  - `checksum_status`: `"ok" | "missing" | "skipped" | "error"`
  - `checksum_reason`: filled when status is not `ok`
- Default size cap (to keep finalize latency bounded):
  - `BR_ARTIFACT_SHA256_MAX_MB` (default: `128`)

MCP file metadata hashing uses the same policy and returns `sha256_status` /
`sha256_reason` for traceability.

## Deprecation strategy (future)

- New clients should only depend on `/observation`.
- Legacy endpoints (`/runcard`, `/provenance`, `/steps`, `/artifacts`) remain for
  compatibility but should not be required by the UI once observation coverage
  is sufficient.

## Tool Checklist: `kg_multihop_qa`

For `kg_multihop_qa`, record these run metrics to keep traversal behavior
observable and synthesis-safe:

- `seed_count`
- `hops_used`
- `nodes_traversed` (mapped from `data.summary.n_nodes_traversed`)
- `paths_returned`
- `query_time_s`

Contract details: `docs/specs/kg_multihop_qa_spec.md`.
