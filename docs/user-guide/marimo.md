# Marimo + Claude Code / Codex

This is the recommended notebook workflow for Brain Researcher when you want a
reactive `.py` notebook that external agents can edit directly.

Marimo owns the interactive notebook UI. Brain Researcher provides the
notebook contract: the `br.*` SDK, the notebook templates, the validation
commands, and the agent guidance.

## Preferred path: Pair with an agent

1. Open a notebook with `br notebook open br_quickstart --port 2718`.
2. Install the pairing skill:

```bash
npx skills add marimo-team/marimo-pair
```

3. In marimo, open `Config -> Pair with an agent`.
4. Launch your agent with the live pair prompt from marimo:

```bash
claude "$(uvx marimo@latest pair prompt --url 'http://127.0.0.1:2718/' --claude)"
codex "$(uvx marimo@latest pair prompt --url 'http://127.0.0.1:2718/' --codex)"
```

5. Once paired, also point the agent at [BR Marimo Agent Guide](../marimo/MARIMO_AGENT.md).
6. Ask the agent to edit the notebook `.py` file directly.
7. Validate with `br notebook check br_quickstart` or `marimo check <notebook.py>`.

## MCP `@resource` context

If your paired agent client supports MCP resources, Brain Researcher can expose
concise context cards for:

- `tool://{tool_id}`
- `dataset://{dataset_ref}`
- `workflow://{workflow_id}`

Treat this as client-dependent UX, not a guaranteed universal `@...` feature.
Claude Code is the first validation target for `@resource` mentions. Codex
stays in verify-then-claim mode until the actual client experience is tested.

## `br.chat()` positioning

`br.chat()` remains available, but it is the programmatic and headless path.
Use it for scripts, CI, or environments where no notebook UI is available.

For interactive notebook work, prefer marimo's pairing / sidebar flow over
embedding a custom BR chat surface. Use `br.call()` in notebook cells for
direct MCP endpoints that do not yet have a dedicated helper. Use
`br.execute()` when you intentionally want `tool_execute` semantics for
registry-backed tools.

## Fallback path: CLI + watch

If the pair flow is not available, use the same notebook file from a terminal:

```bash
marimo edit --watch notebooks/templates/br_quickstart.py
```

This fallback is not a pure hot-reload autorun workflow in validated marimo
`0.23.x` runs. External file edits still go through marimo's staged
fix/reconcile flow with `Accept` / `Reject` UI. `watcher_on_save = "autorun"`
only affects execution after a change is accepted.

That fallback still uses the same BR contract:

- import `brain_researcher.sdk as br`
- prefer `br.search()`, `br.recipe()`, `br.execute()`, `br.call()`, and `br.display.*`
- use `br.call()` for direct MCP endpoints that do not have a dedicated helper yet
- use `br.execute()` for registry tools that must run through `tool_execute`
- avoid raw MCP or raw HTTP when the SDK can express the task
- run `marimo check` after meaningful edits

## Tested external-agent commands

For terminal-driven validation, these invocation styles worked against a
scratch copy of `br_quickstart.py`:

```bash
codex exec --dangerously-bypass-approvals-and-sandbox --add-dir /tmp "... modify <notebook.py> and run marimo check ..."
claude -p --dangerously-skip-permissions --add-dir /tmp < prompt.txt
```

Both agents successfully edited Marimo `.py` notebooks and produced files that
passed `marimo check` in local validation. Claude's generated notebook still
emitted a markdown-indentation warning, so treat `marimo check` as a required
final gate rather than assuming the agent output is lint-clean.

## Current caveats

- The pair flow is the preferred UX, but the repo's automated validation still
  relies on external-agent edits against a watched `.py` notebook rather than a
  scripted browser/sidebar round-trip.
- `marimo edit --watch` is a fallback path only. It remains a staged
  fix/reconcile workflow rather than a direct file-watch autorun path.
- If `uvx marimo@latest pair prompt --codex` still reports that `/marimo-pair`
  cannot be found, verify `~/.codex/skills/marimo-pair` exists.
- In this environment, Codex CLI's default sandboxed run hit a local
  bubblewrap/`.git` error. Running Codex with its internal sandbox disabled
  avoided that issue.
- In this environment, Claude Code `-p` with ordinary edit permissions paused
  before running `marimo check`. A fully noninteractive loop needed
  `--dangerously-skip-permissions`.

## Setup helpers

Use these BR commands when onboarding a notebook:

```bash
br notebook agent-setup
br notebook open br_quickstart --port 2718
br notebook check br_quickstart
br notebook open behavior_task_builder --port 2718
```

`br notebook open` sets `BR_MCP_SERVER_COMMAND=brain-researcher-mcp` for you
when no HTTP MCP target is configured. To point the notebook at the hosted MCP
server instead, export:

```bash
export BR_MCP_HTTP_URL=https://brain-researcher.com/mcp
export BR_MCP_AUTH_HEADER="Bearer $BR_MCP_TOKEN"
# or: export BR_MCP_TOKEN=<token>
br notebook open br_quickstart --port 2718
```

`behavior_task_builder` is the one exception to the “hosted MCP over HTTP”
pattern: it spins up a dedicated local stdio BR client inside the marimo
runtime so `out_dir` and `run_data_dir` stay bound to the notebook workspace
filesystem.

## TaskBeacon handoff

Hosted `/hub` can also seed a TaskBeacon repo into the workspace at runtime.
The current narrow contract is:

```text
/hub?taskbeacon_repo=TaskBeacon/T000015-ant
/hub?taskbeacon_repo=TaskBeacon/T000015-ant&taskbeacon_ref=main
```

This launches a fresh hosted Marimo session, clones the requested
`github.com/TaskBeacon/...` repo into:

```text
projects/<project_id>/taskbeacon/<repo_name>
```

and opens that path in the workspace. This is best-effort runtime seeding, not
a remote execution handoff to TaskBeacon itself.

BR also exposes a TaskBeacon MCP-backed control-plane surface:

- `GET /api/taskbeacon/tasks` lists upstream TaskBeacon tasks via
  `taskbeacon-mcp`.
- `POST /api/taskbeacon/download` downloads a TaskBeacon repo into the
  configured BR workspace, preferring `taskbeacon-mcp` and falling back to the
  verified GitHub materializer.
- `POST /api/taskbeacon/localize` requests upstream localization prompt
  messages while BR enforces workspace path safety.
- `POST /api/taskbeacon/run` is fail-closed in the central orchestrator by
  default. QA/sim execution stays BR-owned, but should run inside a hosted
  marimo/runtime workspace or another image that explicitly enables
  `BR_TASKBEACON_ENABLE_ORCHESTRATOR_RUN=1` and includes the PsychoPy/psyflow
  runtime stack. It is not delegated to TaskBeacon MCP.

## Related docs

- [BR Marimo Agent Guide](../marimo/MARIMO_AGENT.md)
- [Studio to Marimo Migration Plan](../planning/studio_to_marimo_migration_20260410.md)
- [Studio Deprecation Inventory](../audits/studio_deprecation_inventory_20260410.md)
