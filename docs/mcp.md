# MCP (Model Context Protocol)

Brain Researcher can run as a **local stdio MCP server**, so external coding agents
(Claude Code / Codex CLI / Gemini CLI) can call deterministic tools for:

- Tool discovery (`tool_search`, `tool_get`)
- External loop profile (`loop_profile_get`)
- Plan handoff retrieval (`get_latest_plan`)
- Sherlock/OAK guidance and Slurm operations (`sherlock_guide`, `sherlock_slurm`)
- Plan validation/execution (`pipeline_plan_validate`, `pipeline_execute`, `run_get`)
- Run status/metrics (`run_list`, `run_logs`, `run_metrics`, `run_cancel`)
- Run request history summary (`run_request_summary`)
- Run observation/compare helpers (`run_bundle_get`, `run_scorecard`, `run_compare`)
- Repo repair context helper (`generate_repo_repair_context`)
- Post-hoc synthesis helpers (`generate_research_trajectory_and_insights`, `generate_bug_digest`)
- Hypothesis-card and hot-load workflows (`kg_hypothesis_candidate_cards`, `hypothesis_hot_load_research`, plus background `_start` variants; poll background runs via `run_get`, with `_get` aliases retained for compatibility)
- Artifact listing/reading (`artifact_list`, `artifact_read_text`, `artifact_get_metadata`, `artifact_read_bytes`)
- KG read-only helpers (`kg_search_nodes`, `kg_get_node`, `kg_neighbors`, `kg_search_datasets`, `kg_related_datasets`, `kg_verify_hypothesis`; fail-fast by default, degraded responses are opt-in)
- KG structural-signal probe (`kg_probe`; compatibility aliases: `kg_find_structural_leverage`, `kg_detect_contradiction_motifs`, `kg_find_contradiction_frontiers`, `kg_mine_assumption_cracks`, `kg_find_analogy_transfers`)
- KG hypothesis workflow (`kg_hypothesis_workflow`; compatibility aliases: `kg_sample_ood_hypothesis`, `kg_verify_sampled_hypotheses`, `kg_sample_and_verify_hypotheses`)
- KG novelty wrappers (`br_kg.sample_ood_hypothesis`, `br_kg.detect_topology_shifts`)
- KG frontier synthesis helper (`br_kg.synthesize_wow_candidate_cards`, used by `workflow_hypothesis_candidate_cards` when `frontier_mode=frontier`)
- Session learning helpers (`research_log_summary`, `session_risk_classify`, `session_lesson_extract`, `session_open_risks_query`, `session_policy_cards_generate`, `session_learning_report_generate`, `session_signal_report_generate`, `session_backfill_to_kg`)
- Dataset resources (`dataset_get_resources`)
- Google tools (`google_file_search`, `google_deep_research_start`, `google_deep_research`; compatibility poller: `google_deep_research_get`)

Note: `google_deep_research_start/get` use the Gemini Interactions API (background tasks, optional file search
stores). `google_deep_research_start` now advertises the same async launch contract as other background MCP tools
(`run_id`, `status`, `run_dir`, `execution_mode`, `execution_trace`, `poll_tool`, optional `compat_poll_tool`),
while retaining Deep Research-specific `interaction_id`/`data` fields for compatibility. `google_deep_research`
is a grounded-generation helper and does not use the official Deep Research agent.
Deep Research tools are **disabled by default** and will return `network_blocked` unless
`BR_MCP_ALLOW_NETWORK=1` is set. They also require `GOOGLE_API_KEY` or `GEMINI_API_KEY`,
otherwise responses return `missing_api_key`.

## Surface tiers

MCP tools are grouped so common research workflows stay easy to discover while
advanced and administrative tools remain available.

- `default`: safe, common read/query tools for ordinary research workflows.
- `advanced`: specialized, higher-cost, or sharper tools that are still
  supported for power users.
- `ops`: diagnostics, admin paths, manual execution surfaces, and low-level
  mutation entrypoints.

Catalog entries expose both `surface_tier` and `capability_family` in
`docs/mcp_tools.schema.json`. The legacy `tier` field is retained for
compatibility; new clients should prefer `surface_tier`.

Important policy anchors:

- `kg_neighbors` is a default KG primitive alongside `kg_search_nodes` and
  `kg_get_node`.
- `run_cancel` is advanced because users need to stop long-running work.
- `pipeline_plan_validate` and `pipeline_execute` stay in ops together while
  direct pipeline execution remains a manual/admin path.
- Alias tools stay available for compatibility, but public discovery should
  focus on canonical entrypoints such as `kg_verify_hypothesis`,
  `kg_hypothesis_workflow`, `kg_probe`, and `run_get`.

## Install (recommended)

Install Brain Researcher so the `brain-researcher-mcp` entrypoint is available:

```bash
pip install -e .
```

Or, for the full stack (recommended for contributors):

```bash
pip install -e ".[all]"
```

## Run the server (stdio)

Recommended:

```bash
brain-researcher-mcp
```

Fallback:

```bash
python -m brain_researcher.services.mcp.server
```

## Run via Docker (stdio)

If you want to run the MCP server in Docker (to avoid local Python env setup),
prefer running the container with your host UID/GID and redirecting cache dirs
to a bind-mounted writable location.

This repo ships a small wrapper script:

```bash
scripts/ops/mcp_docker_stdio.sh
```

It runs `docker run --rm -i` (no TTY) so Claude/Codex can speak MCP over stdio,
and mounts:

- `<repo>/artifacts` -> `/app/artifacts`
- `<repo>/data` -> `/app/data`
- `<repo>/tmp` -> `/app/tmp`

You can override paths and image name via env vars (see the script header).

## Neo4j configuration (KG tools)

KG tools (`kg_search_nodes`, `kg_get_node`, `kg_neighbors`, …) connect to the local
Neo4j instance and require these environment variables:

- `NEO4J_URI` (default: `bolt://localhost:7687`)
- `NEO4J_USER` (default: `neo4j`)
- `NEO4J_PASSWORD` (required; no safe default)
- `NEO4J_DATABASE` (optional)

If you keep credentials in a repo `.env`, make sure you export them before starting
the MCP server:

```bash
set -a
source .env
set +a
brain-researcher-mcp
```

`session_learning_report_generate` is read-only and aggregates recent BR session
snapshots into top task surfaces, repeated blockers, validation patterns, policy
card candidates, KG lesson candidates, stale/running sessions, and recommended
next actions. The output is digest/regex-derived, so treat it as guidance for
AGENTS.md, skills, KG, or MCP changes rather than causal evidence.

`session_signal_report_generate` is also read-only. It mines post-snapshot
activity, trace-only invariant terms, validation-parser false negatives, and
unresolved next-action themes so silent-fail candidates can be reviewed before
they become durable policy.

`session_backfill_to_kg` is a session-learning write surface only when called with
`dry_run=false`; by default it returns normalized AgentSession/TaskSurface/OpenRisk
rows and query examples without writing. The apply path uses the same Neo4j env vars
above and sets up session-learning constraints/indexes before writing.

## Environment / policy knobs

- `BR_MCP_ALLOWED_ROOTS` (comma-separated): allowed filesystem roots for `work_dir` / `output_dir`
  - default: `<repo>/artifacts,<repo>/data,<repo>/tmp`
- `BR_MCP_RUN_ROOT`: where runs are stored
  - default: `<repo>/data/runs/mcp_runs`
- `BR_MCP_RUN_ROOT_ALIASES`: optional comma-separated legacy run roots to read from
  - typical compatibility value: `<repo>/artifacts/mcp_runs`
- `BR_MCP_ALLOW_NETWORK`: allow running tools that may use network (`0/1`)
  - default: `0`
- `BR_MCP_ALLOW_DANGEROUS`: allow running tools marked `dangerous` (`0/1`)
  - default: `0`
- `BR_MCP_ENABLE_TOOL_EXECUTE`: enable `tool_execute` (advanced; allowlisted)
  - default: `0`
- `BR_MCP_TOOL_EXECUTE_ALLOWLIST`: comma-separated tool ids/prefixes allowed for `tool_execute` (supports `*`)
  - default: empty
- `BR_MCP_TOOL_TIMEOUT_S`: per-tool execution timeout in seconds for MCP runtime wrappers
  - default: unset (no MCP wrapper timeout)
- `BR_MCP_TIMEOUT_CANCEL_GRACE_S`: grace window after timeout `terminate()` before force kill
  - default: `1.0`
- `BR_MCP_TIMEOUT_KILL_GRACE_S`: grace window after SIGKILL fallback on POSIX
  - default: `0.5`
- `BR_MCP_LOG_LEVEL`: `DEBUG|INFO|WARNING|ERROR`
  - default: `INFO`
- `BR_MCP_MAX_BINARY_BYTES`: max bytes returned by `artifact_read_bytes`
  - default: `5000000`
- `BR_MCP_SESSION_BOOTSTRAP_MAX_BODY_BYTES`: maximum JSON request body size (bytes) accepted by HTTP session bootstrap middleware
  - default: `16384`
- `BR_MCP_SESSION_BOOTSTRAP_PRIME_TIMEOUT_SECONDS`: timeout (seconds) for bootstrap GET preflight used to seed `mcp-session-id`
  - default: `1.5`

## Tool timeout semantics

When `BR_MCP_TOOL_TIMEOUT_S` is set, the MCP server executes tool calls in an isolated worker process.

- On timeout, MCP attempts graceful stop first, then hard kill fallback.
- On POSIX, MCP signals the worker **process group** (SIGTERM then SIGKILL) to avoid orphan child processes.
- `tool_execute` and pipeline logs include timeout outcome metadata:
  - `result.metadata.timeout_outcome = "timed_out_stopped"` when worker termination succeeded.
  - `result.metadata.timeout_outcome = "timed_out_background"` if the worker could not be confirmed stopped.
- Timeout errors remain `tool_timeout_after_<seconds>s`; run records include an auditable suffix (`execution_stopped` or `execution_continues_in_background`).

## Recommended execution flow for heavy tools

For tools that may be slow, remote, or policy-sensitive, use this order:

1. `tool_search` to discover the candidate tool.
2. `tool_get` to inspect the callable contract.
3. `tool_execute(..., preview=true)` to generate a non-executing preview.
4. `tool_execute(...)` to execute only after the preview looks correct.

Current default execution behavior is intentionally strict:

- `tool_execute` does **not** remap tool IDs unless `allow_remap=true`.
- `tool_execute` does **not** forward failed local execution to the agent unless `allow_fallback=true`.
- `preview=true` is non-executing and disables remap/fallback.
- KG read tools fail fast on timeout by default; degraded success must be requested explicitly with `allow_degraded=true`.

Every `tool_execute` response now includes:

- `requested_tool_id`
- `resolved_tool_id`
- `remap_applied`
- `execution_mode`
- `execution_trace`

## Recommended external coding-agent flow

For Codex / Claude Code / Gemini CLI style clients, prefer this loop:

1. `loop_profile_get("external_coding_v1")`
2. keep one `session_id` per continuous coding session; if the client has a native thread/chat id, also pass it as `client_session_id`
3. pass `source_client` when known, for example `codex`, `claude_code`, or `cursor`
4. `log_research_event(session_id=..., client_session_id=..., source_client=..., kind="start", content=...)` once real work starts
5. `plan_preflight(...)` for read-only dataset facts, blockers, and explore/plan candidate tools
6. `plan_create(...)` to get a human-facing `display` summary plus a minimal `execution` envelope
7. show `display.markdown` to the user, then pass only `execution` forward after approval
8. `tool_search(phases=["execute"])` / `tool_get` to inspect the execute-phase surface
9. `get_execution_recipe(...)` for stateless local execution plans
10. `pipeline_plan_validate(...)` only for manual/admin multi-step pipeline paths
11. execute outside MCP or via the appropriate hosted MCP path
12. rely on BR server-side telemetry for most mid-session signals such as tool calls, non-success returns, retries, and timing
13. when a BR tool response includes `_agent_directive.research_logging`, treat it as a versioned action contract and follow `actions[]` rather than inferring behavior from ad hoc fields
14. use `log_research_event(..., kind="note", ...)` only as optional enrichment for rationale the server cannot infer, such as goal changes or subjective tradeoffs
15. `run_bundle_get(run_id)` to fetch normalized run observations
16. `run_scorecard(run_id)` to inspect quality signals
17. `run_compare(baseline_run_id, candidate_run_id)` for keep/discard decisions
18. `generate_repo_repair_context(...)` when the agent needs a durable repair-oriented view of recent motifs, absorbed fixes, HARNESS coverage, and golden principles
19. `write_session_snapshot(session_id=..., goal=..., done=[...], open=[...], next_command=..., client_session_id=..., source_client=...)` before the final user-facing answer
20. `generate_research_trajectory_and_insights(...)` when the user asks for a durable session summary
18. `generate_bug_digest(...)` when the user asks for a root-cause/fix-status summary

This keeps MCP as the deterministic harness and leaves repo mutation to the
external coding agent.

### MCP resources for paired notebook agents

When a client supports MCP resources, BR can expose concise context attachments
for paired notebook editing via:

- `tool://{tool_id}`
- `dataset://{dataset_ref}`
- `workflow://{workflow_id}`

Treat the `@resource` UX as client-dependent. Validate Claude Code first, then
verify Codex before documenting it as supported.

### Research logging directive contract

BR tool responses may include `_agent_directive.research_logging` with this shape:

```json
{
  "protocol": "br.research_logging.directive.v1",
  "state": {
    "session_id": "codex:chat-1",
    "client_session_id": "chat-1",
    "source_client": "codex",
    "snapshot_required_on_close": true,
    "session_closed": false,
    "post_close_actions_available": false,
    "note_policy": "optional_enrichment_only",
    "server_mid_session_telemetry": true
  },
  "actions": [
    {"type": "bind_session", "required": false, "payload": {...}},
    {"type": "write_snapshot_on_close", "required": true, "payload": {...}},
    {"type": "log_optional_note", "required": false, "payload": {...}},
    {"type": "observe_server_auto_event", "required": false, "payload": {...}}
  ]
}
```

Client expectations:

- `bind_session`: update the local active research session binding and reuse that `session_id` on later explicit research logging calls.
- `write_snapshot_on_close`: before the final user-facing response, call `write_session_snapshot(...)` for that session unless the workflow is intentionally aborted.
- `prompt_post_session_actions`: after a successful `write_session_snapshot(...)`, optionally prompt the user to run follow-up tools such as `generate_research_trajectory_and_insights(...)` for a durable session summary.
- `review_session_snapshot_hygiene`: advisory only; the snapshot has already been persisted, but the closeout contains classifier-derived warnings such as missing `source_client`, vague open items, missing validation evidence, or prod/runtime work without rollout/health evidence.
- `log_optional_note`: only emit a mid-session `note` if the agent has rationale the server cannot infer from tool/error/retry traces.
- `observe_server_auto_event`: informative only; no follow-up call is required.

### Minimal client-side directive handlers

These snippets are for thin wrappers or bridges around Codex CLI, Claude Code,
or Cursor. They are not patches to the vendor clients themselves. The pattern
is:

1. after each BR MCP tool call, inspect `_agent_directive.research_logging`
2. apply `bind_session` locally
3. remember whether `write_snapshot_on_close` is required
4. before the final user-facing answer, call `write_session_snapshot(...)`

#### Codex wrapper example

```python
research_state = {
    "session_id": None,
    "snapshot_required": False,
    "client_session_id": codex_chat_id,
    "source_client": "codex",
    "run_id": None,
}


def handle_br_directive(result: dict, state: dict) -> None:
    directive = (
        result.get("_agent_directive", {}).get("research_logging")
        if isinstance(result, dict)
        else None
    )
    if not isinstance(directive, dict):
        return
    if directive.get("protocol") != "br.research_logging.directive.v1":
        return

    state_block = directive.get("state") or {}
    if state_block.get("session_id"):
        state["session_id"] = state_block["session_id"]

    for action in directive.get("actions", []):
        action_type = action.get("type")
        payload = action.get("payload") or {}
        if action_type == "bind_session" and payload.get("session_id"):
            state["session_id"] = payload["session_id"]
        elif action_type == "write_snapshot_on_close":
            state["snapshot_required"] = bool(action.get("required", False))
            if payload.get("session_id"):
                state["session_id"] = payload["session_id"]


def maybe_write_snapshot(mcp_client, state: dict, goal: str, done: list[str], open_items: list[str], next_command: str) -> None:
    if not state.get("snapshot_required") or not state.get("session_id"):
        return
    mcp_client.call_tool(
        "write_session_snapshot",
        {
            "session_id": state["session_id"],
            "client_session_id": state["client_session_id"],
            "source_client": state["source_client"],
            "run_id": state.get("run_id"),
            "goal": goal,
            "done": done,
            "open": open_items,
            "next_command": next_command,
        },
    )
    state["snapshot_required"] = False
```

Call `handle_br_directive(...)` after every BR tool call. Call
`maybe_write_snapshot(...)` immediately before the final Codex answer for that
continuous coding session.

#### Claude Code wrapper example

```python
research_state = {
    "session_id": None,
    "snapshot_required": False,
    "client_session_id": claude_thread_id,
    "source_client": "claude_code",
    "run_id": None,
}


def apply_br_research_logging(result: dict, state: dict) -> None:
    directive = (
        result.get("_agent_directive", {}).get("research_logging")
        if isinstance(result, dict)
        else None
    )
    if not isinstance(directive, dict):
        return
    if directive.get("protocol") != "br.research_logging.directive.v1":
        return

    for action in directive.get("actions", []):
        action_type = action.get("type")
        payload = action.get("payload") or {}
        if action_type == "bind_session" and payload.get("session_id"):
            state["session_id"] = payload["session_id"]
        elif action_type == "write_snapshot_on_close":
            state["snapshot_required"] = bool(action.get("required", False))
            state["session_id"] = payload.get("session_id") or state["session_id"]


def closeout_research_session(mcp_client, state: dict, summary: dict) -> None:
    if not state.get("snapshot_required") or not state.get("session_id"):
        return
    mcp_client.call_tool(
        "write_session_snapshot",
        {
            "session_id": state["session_id"],
            "client_session_id": state["client_session_id"],
            "source_client": state["source_client"],
            "run_id": state.get("run_id"),
            "goal": summary["goal"],
            "done": summary["done"],
            "open": summary["open"],
            "next_command": summary["next_command"],
        },
    )
    state["snapshot_required"] = False
```

Use Claude Code's native thread/chat id as `client_session_id` when available.
If Claude Code does not expose one, mint a stable id once per continuous session
and reuse it for every BR call in that session.

#### Cursor bridge example

```ts
type ResearchState = {
  sessionId?: string;
  snapshotRequired: boolean;
  clientSessionId: string;
  sourceClient: "cursor";
  runId?: string;
};

function applyResearchDirective(result: any, state: ResearchState): void {
  const directive = result?._agent_directive?.research_logging;
  if (!directive || directive.protocol !== "br.research_logging.directive.v1") {
    return;
  }

  for (const action of directive.actions ?? []) {
    const payload = action.payload ?? {};
    if (action.type === "bind_session" && payload.session_id) {
      state.sessionId = payload.session_id;
    } else if (action.type === "write_snapshot_on_close") {
      state.snapshotRequired = Boolean(action.required);
      state.sessionId = payload.session_id ?? state.sessionId;
    }
  }
}

async function maybeWriteSnapshot(
  mcpClient: { callTool(args: { name: string; arguments: Record<string, unknown> }): Promise<unknown> },
  state: ResearchState,
  summary: { goal: string; done: string[]; open: string[]; nextCommand: string },
): Promise<void> {
  if (!state.snapshotRequired || !state.sessionId) {
    return;
  }
  await mcpClient.callTool({
    name: "write_session_snapshot",
    arguments: {
      session_id: state.sessionId,
      client_session_id: state.clientSessionId,
      source_client: state.sourceClient,
      run_id: state.runId,
      goal: summary.goal,
      done: summary.done,
      open: summary.open,
      next_command: summary.nextCommand,
    },
  });
  state.snapshotRequired = false;
}
```

For Cursor, prefer a stable editor-side chat/thread id as `client_session_id`.
If the bridge only sees workspace-local state, generate one once per chat tab and
reuse it until the tab is closed or intentionally reset.

For repo-local harness instructions, put provider-specific variants here:

- `AGENTS.md` for Codex or other agents that read repo-level `AGENTS.md`
- `CLAUDE.md` for Claude Code
- `docs/mcp.md` for the shared, vendor-neutral MCP loop and tool semantics

## Surface policy

- `kg_probe` is the primary public entrypoint for KG structural-signal search.
- `kg_hypothesis_workflow` is the primary public entrypoint for KG
  sample/verify workflows.
- Poll background `kg_hypothesis_candidate_cards_start` and
  `hypothesis_run_start` runs via `run_get`; the specialized `_get` tools are
  compatibility-only.
- Poll `google_deep_research_start` background runs via `run_get`; keep
  `google_deep_research_get` only as a compatibility poller.
- Background `*_start` tools should expose one common async launch contract:
  `run_id`, `status`, `run_dir`, `execution_mode`, `execution_trace`, and
  `poll_tool`, plus `compat_poll_tool` only when a legacy poller still exists.
- `verify_hypothesis_with_kg` is compatibility-only; new clients should use
  `kg_verify_hypothesis`.
- The published MCP catalog should stay in lockstep with the live surface.
  Treat schema/catalog drift as a CI failure, not a manual cleanup task.

Execution-recipe metadata now distinguishes local recipes from hosted tools:

- `execution_recipe_available=true` means a portable local recipe exists.
- `hosted_via_br_mcp_service=true` means the tool is intended to run through the
  deployed Brain Researcher MCP service and does not advertise a portable local
  recipe.
- For hosted tools, prefer calling the tool through the deployed Brain
  Researcher MCP service instead of `tool_execute`.

When `get_execution_recipe(...)` returns a portable recipe, the response also
includes a structured `run_pack` for callers that want a ready-to-run local
handoff. `local_run` is a compact backwards-compatible alias that points to
`run_pack`; pass `include_legacy_local_run=true` only when a legacy client needs
the duplicated payload.

- `run_pack.runtime.target`: the intended local runtime (`python`,
  `neurodesk`, `container`, or `slurm`).
- `run_pack.workspace`: suggested directory name for materializing the recipe.
- `run_pack.write_files`: files that should be written from `recipe.files`.
- `run_pack.commands`: ordered commands to run after materializing the files.
- `run_pack.environment.required`: structured environment requirements with
  descriptions and example values.
- `run_pack.prerequisites.setup_once`: one-time local setup guidance for the
  chosen runtime.
- `run_pack.shell_snippet`: copy-paste shell block for users who want the
  shortest path.
- `run_pack.materialize_python`: Python snippet that writes `recipe.files` to
  disk and prints the local commands to run.

Typical client flow for local execution:

1. Call `get_execution_recipe(...)`.
2. Write `response["recipe"]["files"]` into `response["run_pack"]["workspace"]`.
3. Apply any required exports from `response["run_pack"]["environment"]`.
4. Run `response["run_pack"]["commands"]` in that directory.

## Post-hoc run and candidate summaries

Two MCP tools are intended for "总结一下" / "what happened here?" style requests:

- `generate_research_trajectory_and_insights`
- `generate_bug_digest`

Both tools require exactly one anchor:

- `run_id` for one MCP run
- `candidate_id` for one autoresearch candidate

Both tools can optionally ingest coding-agent logs via `agent_log_paths`. In v1
this is best-effort local text ingestion only (`.jsonl`, `.ndjson`, `.log`,
`.md`); if no agent logs are supplied, the tools still work from BR evidence
alone.

Persistence behavior:

- run-anchored summaries are written under `artifacts/summaries/` inside the run
  directory so they appear through `artifact_list`
- candidate-anchored summaries are written under
  `data/autoresearch/candidates/<candidate_id>/summaries/`

Summary generation is template-first with optional LLM enrichment. Set
`BR_MCP_SUMMARY_LLM_ENABLED=1` to allow best-effort LLM synthesis; otherwise the
tools return deterministic `template_fallback` output.

## Repo repair context

`generate_repo_repair_context` builds a durable repair-oriented artifact from:

- recent persisted failure motifs under `data/autoresearch/failure_motifs/`
- absorbed-upstream candidates and validation reports
- HARNESS coverage derived from benchmark slice configs
- machine-readable golden principles from
  `configs/codegen/autoresearch_golden_principles.yaml`

The tool returns structured JSON plus a markdown rendering and, by default,
persists:

- `data/autoresearch/repo_repair_context/repo_repair_context_latest.json`
- `data/autoresearch/repo_repair_context/repo_repair_context_latest.md`

This is intended for coding agents that need a compact repo-repair snapshot
before patching: hot surfaces, high-frequency motifs, what HARNESS already
covers, and which invariants should not be violated.

### `tool_execute` preview-first example

Preview request:

```json
{
  "tool_id": "extract_timeseries",
  "params": {"fmri_path": "sub-01_bold.nii.gz", "atlas": "harvard_oxford"},
  "preview": true
}
```

Preview response (shape):

```json
{
  "ok": true,
  "requested_tool_id": "extract_timeseries",
  "resolved_tool_id": "extract_timeseries",
  "remap_applied": false,
  "allow_remap": false,
  "allow_fallback": false,
  "execution_mode": "preview_only",
  "execution_trace": ["preflight_passed", "preview_only"],
  "result": {
    "status": "success",
    "metadata": {
      "execution_mode": "preview_only"
    }
  }
}
```

Direct execution request:

```json
{
  "tool_id": "extract_timeseries",
  "params": {"fmri_path": "sub-01_bold.nii.gz", "atlas": "harvard_oxford"},
  "work_dir": "/tmp/br-work",
  "output_dir": "/tmp/br-out"
}
```

Direct execution response now reports the actual path taken:

```json
{
  "ok": true,
  "requested_tool_id": "extract_timeseries",
  "resolved_tool_id": "extract_timeseries",
  "remap_applied": false,
  "allow_remap": false,
  "allow_fallback": false,
  "execution_mode": "direct",
  "execution_trace": ["preflight_passed", "direct_lookup", "local_execution"]
}
```

If you want MCP to try a remapped tool ID or forward a failed local run to the
agent, you must opt in explicitly with `allow_remap=true` and/or
`allow_fallback=true`.

### KG timeout behavior

Default KG behavior is fail-fast. On timeout, KG tools return an error and make
the blocked degraded path explicit:

```json
{
  "ok": false,
  "error": "kg_query_timeout",
  "degraded_result_available": true,
  "degraded_reason": "mcp_timeout",
  "execution_trace": ["kg_query_started", "kg_timeout", "kg_degraded_blocked"]
}
```

Best-effort KG behavior is opt-in. When `allow_degraded=true`, the same timeout
returns a degraded success payload:

```json
{
  "ok": true,
  "items": [],
  "warnings": ["kg_search_nodes timed out after 15.0s; returning a degraded result."],
  "completion_state": "degraded",
  "degraded_reason": "mcp_timeout",
  "execution_trace": ["kg_query_started", "degraded_returned"]
}
```

For `kg_multihop_qa`, the degraded opt-in response uses the same policy but
returns the traversal under `result` instead of `items`.

## HTTP transport notes

When running with `BR_MCP_TRANSPORT=streamable-http`:

- RPC endpoint is typically `/mcp` (not `/`).
- MCP clients should include `Accept: application/json, text/event-stream` for streamable HTTP requests.
- A bare `curl https://${PUBLIC_HOSTNAME}/mcp` is expected to return `406 Not Acceptable`; that does not mean the server is down.

### Example: Cursor (HTTP)

For hosted HTTP MCP in Cursor, paste the full bearer token directly into the
JSON. Do not rely on env placeholder expansion for the `Authorization` header.

```json
{
  "mcpServers": {
    "brain-researcher": {
      "type": "http",
      "url": "https://${PUBLIC_HOSTNAME}/mcp",
      "headers": {
        "Authorization": "Bearer brk_<kid>.<secret>",
        "Accept": "application/json, text/event-stream"
      }
    }
  }
}
```

For Claude Code and other env-friendly clients, exporting `BR_MCP_TOKEN` in the
shell and using `Authorization: Bearer ${BR_MCP_TOKEN}` remains fine.

#### Cursor HTTP adapter snippet for research logging

If you have a thin Cursor-side bridge that already sends JSON-RPC `tools/call`
requests, handle BR's research logging directive in that bridge rather than in
the prompt:

```ts
const researchState = {
  sessionId: undefined as string | undefined,
  snapshotRequired: false,
  clientSessionId: cursorChatId,
  sourceClient: "cursor" as const,
};

async function callBrTool(name: string, args: Record<string, unknown>) {
  const response = await fetch("https://${PUBLIC_HOSTNAME}/mcp", {
    method: "POST",
    headers: {
      Authorization: "Bearer brk_<kid>.<secret>",
      Accept: "application/json, text/event-stream",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: crypto.randomUUID(),
      method: "tools/call",
      params: { name, arguments: args },
    }),
  });
  const body = await response.json();
  const result = body.result ?? {};
  applyResearchDirective(result, researchState);
  return result;
}

async function finalizeResearchSession(summary: {
  goal: string;
  done: string[];
  open: string[];
  nextCommand: string;
}) {
  if (!researchState.snapshotRequired || !researchState.sessionId) {
    return;
  }
  await callBrTool("write_session_snapshot", {
    session_id: researchState.sessionId,
    client_session_id: researchState.clientSessionId,
    source_client: researchState.sourceClient,
    goal: summary.goal,
    done: summary.done,
    open: summary.open,
    next_command: summary.nextCommand,
  });
  researchState.snapshotRequired = false;
}
```

### Manual protocol smoke against prod

```bash
curl https://${PUBLIC_HOSTNAME}/mcp \
  -H "Authorization: Bearer $BR_MCP_TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  --data '{
    "jsonrpc": "2.0",
    "id": "init-1",
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-03-26",
      "capabilities": {},
      "clientInfo": { "name": "manual-probe", "version": "1.0" }
    }
  }'
```

### Local HTTP startup + smoke

Start local MCP HTTP mode:

```bash
scripts/mcp/start_http_local.sh
```

`start_http_local.sh` defaults `BR_MCP_AUTO_AUTH_TOKEN=1`, which reuses the
resolved `BR_MCP_TOKEN` as `BR_MCP_AUTH_TOKEN` when no explicit
`BR_MCP_AUTH_TOKEN` is set. This gives a local break-glass bearer token for smoke
testing. Set `BR_MCP_AUTO_AUTH_TOKEN=0` to disable this behavior.

For local smoke reliability, the script also defaults `BR_MCP_STATELESS_HTTP=1`
unless you explicitly override it.

Resolve auth token (env -> repo `.env` -> `~/.bashrc`):

```bash
scripts/mcp/resolve_br_mcp_token.sh
```

Run a protocol smoke (`initialize` -> `tools/list` -> `tools/call server_info`):

```bash
scripts/mcp/smoke_http.sh
```

The smoke script defaults to `http://127.0.0.1:7000/mcp` and honors:

- `BR_MCP_HTTP_URL` (full URL override)
- `BR_MCP_HOST`, `BR_MCP_PORT`, `BR_MCP_MOUNT_PATH` (URL parts)
- `BR_MCP_TOKEN` (if set, bypasses resolver fallback)

## Example: Claude Code (stdio)

```bash
claude mcp add-json brain-researcher '{
  "type":"stdio",
  "command":"brain-researcher-mcp",
  "env":{
    "BR_MCP_ALLOWED_ROOTS":"./artifacts,./data,./tmp",
    "BR_MCP_ALLOW_NETWORK":"0"
  }
}'
```

### Claude Code instruction snippet for directive handling

If you want a copy-paste instruction block for Claude Code, keep it short and
mechanical:

```text
When a Brain Researcher MCP tool response includes
_agent_directive.research_logging:

1. verify protocol == br.research_logging.directive.v1
2. read actions[]
3. if an action.type == bind_session, reuse that session_id on later explicit
   log_research_event(...) or write_session_snapshot(...) calls
4. if an action.type == write_snapshot_on_close, call write_session_snapshot(...)
   before the final user-facing answer for that session
5. ignore observe_server_auto_event except for awareness/debugging
6. use log_research_event(kind="note") only for rationale the server cannot
   infer from tool/error/retry traces
```

This works best when paired with the repo-local rules already present in
[`CLAUDE.md`](../CLAUDE.md).

### Claude Code + Docker wrapper (stdio)

```bash
claude mcp add-json brain-researcher-docker '{
  "type":"stdio",
  "command":"scripts/ops/mcp_docker_stdio.sh",
  "env":{
    "BR_MCP_ALLOW_NETWORK":"0"
  }
}'
```

## Example: Claude Code (HTTP)

Template config lives at:

- `configs/claude/mcp.http.template.json.tmpl`

### Repo-local run (`--mcp-config`) without persisting token

```bash
BR_MCP_TOKEN="$(scripts/mcp/resolve_br_mcp_token.sh)"
MCP_CFG="$(mktemp /tmp/brain-researcher-http-mcp.XXXXXX.json)"
python - "${BR_MCP_TOKEN}" "${MCP_CFG}" <<'PY'
import json
import sys

token = sys.argv[1]
out_path = sys.argv[2]
cfg = json.load(open("configs/claude/mcp.http.template.json.tmpl", encoding="utf-8"))
cfg["mcpServers"]["brain-researcher-http"]["headers"]["Authorization"] = f"Bearer {token}"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
PY

claude -p \
  --strict-mcp-config \
  --mcp-config "${MCP_CFG}" \
  --permission-mode bypassPermissions \
  "Use brain-researcher-http MCP and call server_info."
```

### User-global registration (`claude mcp add-json`)

```bash
TOKEN="$(scripts/mcp/resolve_br_mcp_token.sh)"
claude mcp add-json brain-researcher-http "{
  \"type\":\"http\",
  \"url\":\"http://127.0.0.1:7000/mcp\",
  \"headers\":{
    \"Authorization\":\"Bearer ${TOKEN}\",
    \"Accept\":\"application/json, text/event-stream\"
  }
}"
```

If the token rotates, rerun the command above to refresh the stored header value.

## Example: Codex CLI (stdio)

```bash
codex mcp add brain-researcher -- brain-researcher-mcp
```

### Codex repo-local harness snippet

If you want a copy-paste block for repo-local Codex instructions, use this in
`AGENTS.md` or an equivalent Codex harness file:

```text
When a Brain Researcher MCP tool response includes
_agent_directive.research_logging:

- require protocol == br.research_logging.directive.v1
- follow actions[] rather than inferring ad hoc fields
- on bind_session: store and reuse that session_id for later explicit research
  logging calls
- on write_snapshot_on_close: before the final user-facing answer, call
  write_session_snapshot(session_id=..., goal=..., done=[...], open=[...],
  next_command=...)
- on log_optional_note: only emit a note if the rationale is not visible from
  normal BR tool/error/retry traces
- on observe_server_auto_event: no follow-up call is required
```

This is intentionally narrower than a full repo policy. It only teaches Codex
how to honor the BR directive contract at response time.

### Codex CLI + Docker wrapper (stdio)

```bash
codex mcp add brain-researcher-docker -- scripts/ops/mcp_docker_stdio.sh
```

## Tool examples (tested)

The canonical machine-readable tool catalog lives at `docs/mcp_tools.schema.json`.
Examples in that file may include a `tested: true` marker, which means the
example input/output pair is validated in `tests/unit/mcp/test_local_mcp_server.py`.
Catalog entries now carry `surface_tier` and `capability_family` metadata in
addition to the legacy `tier` field. See the surface tiers section above for
the current grouping policy.

### Sherlock/OAK helpers

These are read-mostly local helpers for Stanford Sherlock workflows:

- `sherlock_guide`: one entrypoint for topic guidance (`action=guide`) and command rendering (`action=command`)
- `sherlock_slurm`: one entrypoint for `sbatch` generation, script validation/patching, job inspection, log reads, and failure diagnosis

These tools do not submit jobs in v1; they generate text and inspect local Slurm state only.

### run_cancel

Input:

```json
{"run_id": "doc_cancel", "reason": "user_request"}
```

Output:

```json
{"ok": true, "run_id": "doc_cancel", "status": "cancelled"}
```

### run_metrics

Input:

```json
{"run_id": "doc_metrics"}
```

Output:

```json
{
  "ok": true,
  "metrics": {
    "run_id": "doc_metrics",
    "status": "succeeded",
    "started_at": "2025-12-20T00:00:00Z",
    "finished_at": "2025-12-20T00:00:10Z",
    "duration_s": 10.0,
    "totals": {
      "steps": 1,
      "succeeded": 1,
      "failed": 0,
      "skipped": 0,
      "execution_time_s_sum": 1.5,
      "tokens_sum": 15,
      "cost_usd_sum": 0.02
    },
    "steps": [
      {
        "step_id": "s1",
        "tool_id": "extract_timeseries",
        "status": "succeeded",
        "started_at": "2025-12-20T00:00:00Z",
        "finished_at": "2025-12-20T00:00:10Z",
        "duration_s": 10.0,
        "execution_time_s": 1.5,
        "tokens": 15,
        "cost_usd": 0.02,
        "error": null
      }
    ]
  }
}
```

### run_request_summary

Use this to summarize what kinds of MCP requests have been executed recently.
It aggregates persisted MCP run artifacts under the configured run roots and
reports top request types, route counts, status counts, and a few example runs.

Input:

```json
{"top_k": 5, "since_days": 30}
```

Output:

```json
{
  "ok": true,
  "top_k": 5,
  "since_days": 30,
  "total_runs": 12,
  "runs_without_request_type": 0,
  "roots_scanned": ["/path/to/data/runs/mcp_runs"],
  "route_counts": [
    {"route": "pipeline_execute", "count": 9},
    {"route": "tool_execute", "count": 3}
  ],
  "status_counts": [
    {"status": "succeeded", "count": 8},
    {"status": "failed", "count": 4}
  ],
  "request_type_counts": [
    {
      "request_type": "workflow_visual_decoding",
      "count": 4,
      "routes": ["pipeline_execute"],
      "examples": [
        {
          "run_id": "br_20260313_020159_95572bfffc",
          "route": "pipeline_execute",
          "status": "failed",
          "created_at": "2026-03-13T02:02:00Z",
          "param_keys": ["features", "labels"]
        }
      ]
    }
  ]
}
```

### artifact_read_bytes (range)

Input:

```json
{"run_id": "doc_range", "relpath": "artifacts/blob.bin", "start": 1, "end": 4}
```

Output:

```json
{
  "ok": true,
  "encoding": "base64",
  "offset": 1,
  "truncated": false,
  "bytes": "YmNk",
  "range": {"start": 1, "end": 4}
}
```

### kg_neighbors

Input:

```json
{"kg_id": "node_a", "relation_types": ["RELATED_TO"], "direction": "out", "limit": 5}
```

Output:

```json
{
  "ok": true,
  "items": [
    {
      "kg_id": "node_b",
      "label": "Motor cortex",
      "node_type": "BrainRegion",
      "score": 1.0,
      "relation": "RELATED_TO",
      "direction": "out",
      "properties": {"id": "node_b"}
    }
  ]
}
```

### kg_verify_hypothesis

Input:

```json
{
  "hypothesis": "DLPFC is highly involved in n-back task",
  "entity_hints": ["DLPFC", "n-back"],
  "strictness": "high_recall",
  "include_subgraph": true
}
```

Output (shape):

```json
{
  "ok": true,
  "result": {
    "verdict": "supported",
    "confidence": 0.76,
    "summary": {
      "n_supporting": 2,
      "n_conflicting": 0,
      "n_neutral": 1
    },
    "supporting_evidence": [],
    "conflicting_evidence": [],
    "neutral_evidence": [],
    "top_paths": [],
    "subgraph": {"nodes": [], "edges": []},
    "warnings": []
  }
}
```

### kg_search_nodes / kg_get_node ID behavior

`kg_search_nodes` returns both a stable id (`kg_id`, if available) and an
`element_id` (Neo4j element id). `kg_get_node` accepts either — so round‑trip
`search → get` works even when nodes only have element ids.
