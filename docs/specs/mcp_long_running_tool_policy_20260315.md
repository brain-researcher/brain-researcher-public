# MCP Long-Running Tool Policy

## Why

Many Brain Researcher tools are minute-scale, not second-scale. The main failure mode is not total elapsed time by itself. It is long periods with no visible progress and no recoverable handle.

That means the default policy should be:

- Keep running while progress is still advancing.
- Mark runs as stalled when heartbeat silence exceeds a threshold.
- Prefer background execution plus polling over forcing users to wait on a single blocking call.
- Treat manual cancel as a fallback control, not the primary control surface.

## Contract

All persisted MCP runs should expose a progress snapshot through `run_get`-style polling:

- `current_stage`
- `message`
- `progress_pct`
- `last_progress_at`
- `silence_seconds`
- `elapsed_seconds`
- `stalled`
- `timing_policy`

The current default timing policy is:

- `heartbeat_interval_seconds = 30`
- `stall_timeout_seconds = 120`
- `soft_timeout_seconds = 300`
- `hard_timeout_seconds = 1800`

These values are metadata and health signals first. They do not imply automatic hard-kill semantics for every tool.

## Product Behavior

For minute-scale tools:

1. If a sync path is still needed, it should be treated as a smoke/debug entrypoint.
2. The production path should expose `run_start` + `run_get`.
3. UI and agents should prefer polling `progress` instead of waiting silently.
4. A run is suspicious when `stalled = true`, not merely because `elapsed_seconds` is large.

## Current Coverage

This policy is now wired into the MCP filesystem-backed run contract used by:

- `pipeline_execute` via `run_get`
- `hypothesis_run_start` / `hypothesis_run_get`
- `google_deep_research_start` with `run_get` or `google_deep_research_get(run_id)`
- `tool_execute` persisted run records

`hypothesis_run_start` and pipeline execution also emit heartbeats while background work is active, so polling clients can distinguish:

- active progress
- long-but-healthy execution
- stalled execution
- terminal failure

## Next Extensions

The next safe extensions are:

- add dedicated cancel semantics for higher-level background facades
- add UI/agent wording that surfaces `stalled` explicitly
- wrap any other minute-scale sync MCP tool behind the same `run_start` / `run_get` pattern before making it a default production path
