# BR-KG `kg_multihop_qa` Tool Spec

Status: active
Scope: pipeline/tool invocation contract for `kg_multihop_qa`

## Purpose

`kg_multihop_qa` returns deterministic graph-traversal artifacts for downstream
synthesis. It is not a free-form answer generator.

## Inputs

- `question` (`str`, required): natural-language query to resolve against KG links.
- `max_hops` (`int`, optional, default `3`): traversal depth cap.
- `mode` (`str`, optional, default `breadth_first`): traversal mode.
- `max_results` (`int`, optional, default `50`): path cap.
- `allowed_edge_types` (`list[str] | null`, optional): relationship allowlist.
- `return_subgraph` (`bool`, optional, default `true`): include supporting subgraph.

## Structured Success Output

Top-level envelope:

- `status`: `"success"`
- `data.outputs`: traversal outputs
- `data.summary`: traversal metrics

`data.outputs` fields:

- `answer` (`str`): deterministic synthesis-ready answer text.
- `seed_entities` (`list[object]`)
- `paths` (`list[object]`)
- `subgraph` (`object`, optional): present when `return_subgraph=true`.
  - `nodes` (`list[object]`)
  - `edges` (`list[object]`)
- `provenance` (`object`)
- `confidence` (`float`, range `[0,1]`)
- `warnings` (`list[str]`)
- `summary` (`object`) (mirrors `data.summary`)

`data.summary` fields:

- `question` (`str`)
- `max_hops` (`int`)
- `hops_used` (`int`)
- `n_nodes_traversed` (`int`)
- `n_edges_traversed` (`int`)
- `query_time_s` (`float`)
- `reasoning_method` (`str`)

## Error Semantics

Top-level envelope on failure:

- `status`: `"error"`
- `error`: error message
- `metadata.error_category`: one of `validation|network|data|configuration|unknown`
- `metadata.error_type`: exception class name
- `metadata.tool_name`: `kg_multihop_qa`
- `metadata.args`: input args passed to the tool

Behavioral notes:

- Schema/input failures surface as `validation` errors.
- Downstream synthesis should gate on `status=="success"` and treat error payloads
  as non-answer states.

## MCP Wrapper Behavior

When `kg_multihop_qa` is called through the MCP server, the outer envelope adds
MCP-specific execution semantics on top of the tool contract above.

Default behavior is fail-fast:

- Timeouts return `ok=false` with `error="kg_query_timeout"`.
- Degraded traversal summaries are also blocked by default and surfaced as
  `ok=false` with `error="kg_query_degraded"` unless the degraded state was
  specifically caused by timeout.
- The MCP response includes `execution_trace` so clients can distinguish
  `kg_timeout` from `kg_degraded_blocked`.

Opt-in best-effort behavior is enabled with `allow_degraded=true`:

- The MCP response returns `ok=true`.
- The traversal payload stays under `result`.
- Top-level fields include `warnings`, `completion_state="degraded"`,
  `degraded_reason`, and `execution_trace`.

Client guidance:

- If you need strict reproducibility, accept only `ok=true` and
  `completion_state!="degraded"`.
- If you explicitly want a best-effort traversal, pass `allow_degraded=true` and
  treat degraded responses as partial evidence rather than full success.

## Observability Checklist (Per Invocation)

- `seed_count`: number of KG seed nodes used to start traversal.
- `hops_used`: `data.summary.hops_used`
- `nodes_traversed`: map from `data.summary.n_nodes_traversed`
- `paths_returned`: number of traversal paths returned for synthesis
- `query_time_s`: `data.summary.query_time_s`
