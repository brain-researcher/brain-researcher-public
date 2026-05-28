# MCP Surface Tiering

This document defines the intended user-facing tiers for Brain Researcher MCP
tools. The goal is not to remove low-level tools. The goal is to stop treating
all tools as equally prominent.

## Why

The current MCP surface mixes four different classes of capability:

- everyday read/query tools
- advanced research helpers
- run and artifact inspection tools
- admin and environment diagnostics

That makes tool selection harder for both humans and coding agents. The fix is
to classify each tool along two axes:

- `surface_tier`: `default`, `advanced`, or `ops`
- `capability_family`: a stable family label used for grouping and ranking

The machine-readable catalog keeps the legacy `tier` field for compatibility.
New consumers should prefer `surface_tier`.

## Tier definitions

- `default`
  - Safe, common, and expected in ordinary research workflows.
  - A coding agent should be able to use these without already knowing the
    repo's operational model.
- `advanced`
  - Useful and supported, but more specialized, more expensive, or more
    operationally sharp.
  - These should remain in the main MCP server, but should not dominate default
    discovery.
- `ops`
  - Diagnostics, admin paths, compatibility surfaces, or low-level mutation
    entrypoints.
  - These remain available, but should be hidden or strongly de-emphasized for
    ordinary agent routing.

## Key decisions

### Sherlock stays in the main MCP surface

`sherlock_guide` and `sherlock_slurm` are part of Brain Researcher execution,
not a separate product. They stay in the main MCP server.

They are `advanced`, not `ops`, because Sherlock-backed users legitimately use
them as a primary execution path.

### `kg_neighbors` is a default KG primitive

The natural KG exploration loop is:

- `kg_search_nodes`
- `kg_get_node`
- `kg_neighbors`

`kg_neighbors` belongs in `default`, not `advanced`.

### `run_cancel` is part of run lifecycle, not pure ops

Users need to cancel long-running work when they detect a bad parameter choice
or route selection. `run_cancel` is `advanced`, not `ops`.

### `pipeline_plan_validate` and `pipeline_execute` move together

These two tools are a single lifecycle:

- validate
- then execute

They must share a tier. Under the current codebase policy they remain `ops`,
because `pipeline_execute` is explicitly documented as a manual/admin path.

If Brain Researcher later adopts direct agent-driven pipeline submission, both
tools should move to `advanced` together.

### Alias tools should not shape the surface

`verify_hypothesis_with_kg` is only an alias for `kg_verify_hypothesis`.
Aliases can remain for compatibility, but should not be treated as first-class
surface anchors.

### `kg_hypothesis_workflow` is the public hypothesis-family entrypoint

The KG hypothesis workflow family should be described around
`kg_hypothesis_workflow` as the public tool for sample / verify / combined
candidate flows.

The legacy names `kg_sample_ood_hypothesis`, `kg_verify_sampled_hypotheses`,
and `kg_sample_and_verify_hypotheses` remain compatibility aliases, but they
should not be presented as separate first-class discovery tools.

### Background polling should converge on `run_get`

Background task families can keep specialized `*_start` launch tools when the
sync and async entrypoints remain semantically useful.

But polling should converge on `run_get`. Specialized `*_get` tools can remain
as compatibility aliases, not as first-class discovery tools.

Background `*_start` launch responses should also converge on one shape:
`run_id`, `status`, `run_dir`, `execution_mode`, `execution_trace`, and
`poll_tool`, with `compat_poll_tool` only when a legacy poller still exists.

### `kg_probe` is the public structural-signal entrypoint

The KG probe family should be described around `kg_probe` as the public tool
that surfaces structural signals from the graph.

The legacy names
`kg_find_structural_leverage`,
`kg_detect_contradiction_motifs`,
`kg_find_contradiction_frontiers`,
`kg_mine_assumption_cracks`, and
`kg_find_analogy_transfers`
remain compatibility aliases, but they should not be presented as separate
first-class discovery tools.

## Capability families

- `server_ops`
- `tool_discovery`
- `execution_recipe`
- `tool_execution_admin`
- `pipeline_execution`
- `plan_handoff`
- `run_observability`
- `research_synthesis`
- `artifact_inspection`
- `kg_explore`
- `kg_reasoning`
- `kg_hypothesis`
- `kg_probe`
- `dataset_resolution`
- `google_research`
- `sherlock`

## Current tiering policy

### Default

- `tool_search`
- `tool_get`
- `run_list`
- `run_get`
- `run_request_summary`
- `get_latest_plan`
- `kg_search_nodes`
- `kg_get_node`
- `kg_neighbors`
- `kg_verify_hypothesis`
- `dataset_get_resources`

### Advanced

- `tool_search_structured`
- `tool_resolve`
- `workflow_search`
- `get_execution_recipe`
- `run_bundle_get`
- `run_logs`
- `run_cancel`
- `run_metrics`
- `run_scorecard`
- `run_compare`
- `generate_research_trajectory_and_insights`
- `generate_bug_digest`
- `generate_repo_repair_context`
- `artifact_*`
- `kg_search_datasets`
- `kg_related_datasets`
- `kg_list_dataset_onvoc_links`
- `kg_multihop_qa`
- `kg_probe`
- `kg_hypothesis_workflow`
- `kg_hypothesis_candidate_cards`
- `kg_hypothesis_candidate_cards_start`
- `hypothesis_hot_load_research`
- `hypothesis_run_start`
- `kg_detect_topology_shifts`
- `google_file_search`
- `google_deep_research`
- `google_deep_research_start`
- `sherlock_guide`
- `sherlock_slurm`

### Ops

- `server_info`
- `loop_profile_get`
- `system_self_test`
- `tool_execute`
- `pipeline_plan_validate`
- `pipeline_execute`

## Implementation notes

- The canonical metadata map lives in
  [server.py](<repo>/src/brain_researcher/services/mcp/server.py).
- The machine-readable catalog in
  [mcp_tools.schema.json](<repo>/docs/mcp_tools.schema.json)
  mirrors the same `surface_tier` and `capability_family` labels.
- Keep the published catalog in parity with the live MCP surface; any drift
  between decorated tools and the schema should fail CI.
- Client-side routing should prefer `surface_tier` over the legacy `tier` field.
- Search UIs should group by `capability_family` and rank `default` above
  `advanced`, and `advanced` above `ops`.
