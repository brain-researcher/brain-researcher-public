# Contract tiers

Brain Researcher tools live on two orthogonal axes. This document explains both and the policy attached to each tier.

## Axis 1 — `surface_tier`

Agent-facing complexity. Set in `_MCP_SURFACE_METADATA_BY_NAME` in `src/brain_researcher/services/mcp/server.py`.

| Value | Who uses it | Examples |
|---|---|---|
| `ops` | Admin/ops surface, not the default agent path | `server_info`, `system_self_test`, `pipeline_plan_validate`, `scientific_report_generate` |
| `default` | Everyday agent calls | `tool_search`, `tool_get`, `plan_preflight`, `kg_search_nodes` |
| `advanced` | Power-user / cross-tool composition | `get_execution_recipe`, `grounding_*`, `memory_*`, `run_*` |

`tool_search` exposes the tier so an agent UI can filter by it.

## Axis 2 — `stability`

OSS-facing API-stability promise. Set at the contract layer via `STABLE_TIER` in `scripts/oss/extract_tool_contracts.py` (per-tool JSON exists under `contracts/tools/`).

| Value | Policy |
|---|---|
| `stable` | Breaking schema changes require a `contracts/VERSION` bump **and** a one-release deprecation window. `toolset_hash` in `server_info` changes when the schema changes; adapter-kit consumers refuse to dispatch on version mismatch. |
| `experimental` | No stability promise. May change shape between releases. Listed in `server_info` with explicit `"stability": "experimental"` so adapter-kit consumers can choose to skip them. |
| `deprecated` | Replaced by another tool. `server_info.deprecated_tools` lists the rename. Removed after one release cycle. |
| `internal` | Not in `server_info` / `tool_search` for the public; admin-only. |

## Current stable tier (contract_version 2026-05-27)

| Tool | Capability family | Why stable |
|---|---|---|
| `server_info` | server_ops | Adapter-kit needs it to discover everything else. |
| `tool_search` | tool_discovery | The dynamic resolver for domain-specific intents. |
| `plan_preflight` | planning | Closed-loop gate: dataset facts + candidate tools. |
| `pipeline_plan_validate` | pipeline_execution | Schema + path/policy validation. |
| `pipeline_plan_review` | pipeline_execution | Domain critique (tool ordering, modality compatibility). |
| `get_execution_recipe` | execution_recipe | Produces runnable recipes for the caller. |
| `grounding_resolve` | grounding | Anchor resolution. |
| `grounding_gate_evidence_basis` | grounding | Downgrades weak/unresolved claims before reporting. |
| `scientific_report_generate` | scientific_report | Final-report gate; depends on the above. |
| `run_scorecard` | run_observability | Normalized scorecard for a persisted run. |

## How a tool moves between tiers

- `experimental` → `stable`: add to `STABLE_TIER`, rerun the extractor, bump `contracts/VERSION`, announce in `CHANGELOG.md`.
- `stable` → `deprecated`: add to `DEPRECATED_ALIASES` pointing at the replacement, keep emitting the schema, announce in `CHANGELOG.md`. The deprecated entry persists for one release.
- `deprecated` → removed: remove the `@mcp.tool` decorator and the metadata entry; the next extractor run drops it from `contracts/tools/`. Bump `contracts/VERSION` and note the removal in `CHANGELOG.md`.

## Why two axes

The agent-complexity tier answers "should the agent UI surface this by default?" The stability tier answers "can a downstream package depend on this not breaking?" They cross-cut: a tool can be `surface_tier=ops` (admin-only) and still be `stable` (e.g. `server_info`); another can be `surface_tier=default` (everyday use) but `experimental` (active iteration).
