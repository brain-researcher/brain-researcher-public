---
name: brain-researcher-session-handoff
description: Shared session handoff discipline for Brain Researcher coding and research agents. Use when Codex or Claude Code starts, tracks, or closes Brain Researcher repo work that should be recoverable later through BR logging and a concise final handoff.
---

# Brain Researcher Session Handoff

## Overview

Use this skill to make a Brain Researcher work session resumable without
turning the log into a chat transcript dump. The core pattern is:

1. Start BR logging once at the beginning of real work.
2. Reuse one stable `session_id` and the correct `source_client`.
3. Do the work and validate the changed surface.
4. Close exactly one final `write_session_snapshot`.
5. Summarize the logged session in the user-facing handoff; do not paste raw
   MCP JSON unless the user asks for it.

## When To Use

Use this skill for Brain Researcher repo work that leaves state another agent
may need to resume, especially:

- prod/runtime rollout or deploy handoff
- web, Studio, demo, or artifact-viewer changes
- repo cleanup or release-readiness triage
- scientific workflow runs or analysis reports
- code, API, schema, protocol, or contract changes

For very small read-only answers, use judgment. If no durable state is created
and there is no practical resume value, a BR snapshot is usually unnecessary.

## MCP Preflight

Before relying on BR logging, inspect the actual exposed MCP tools in the
current client. Prefer the repo guidance if it is stricter than this skill.

Required tools for the normal path:

- `log_research_event`
- `write_session_snapshot`

Useful inventory tools when exposed:

- `server_info`
- `memory_search`

Useful post-close learning tools when exposed:

- `session_risk_classify`
- `session_lesson_extract`
- `session_open_risks_query`
- `session_policy_cards_generate`
- `session_learning_report_generate`
- `session_backfill_to_kg` with `dry_run=true` unless the user asked for KG
  writes and Neo4j env vars are configured

Client prompt artifacts:

- `agents/openai.yaml` for Codex/OpenAI skill launch metadata.
- `agents/claude_code.md` for a compact Claude Code instruction block. Keep
  this in the skill directory; do not duplicate the policy into `CLAUDE.md`.

If the BR MCP server or logging tools are unavailable:

- say they are unavailable
- continue with a local concise handoff
- do not imply that BR logging or snapshot persistence happened

## Session Identity

Pick one stable `session_id` for the continuous task and reuse it through the
session. A good value is short, descriptive, and date-scoped, for example:

```text
br-web-demo-routing-20260526
br-cleanup-release-readiness-20260526
br-session-handoff-skill-p1-20260526
```

Set:

- `source="agent"`
- `source_client="codex"` for Codex API/chat agent sessions
- `source_client="codex_cli"` for Codex CLI sessions when that distinction is
  known
- `source_client="claude_code"` for Claude Code sessions

If the client exposes a native thread, chat, or session id, pass it as
`client_session_id`. Otherwise, rely on the stable `session_id`.

## Start Logging

At the start of real work, call:

```text
log_research_event(
  kind="start",
  content="<one sentence goal>",
  session_id="<stable session id>",
  source="agent",
  source_client="<codex|codex_cli|claude_code>",
  tags=[...],
  context={...}
)
```

Do not log every turn. Mid-session `kind="note"` entries are optional and should
be reserved for rationale or state that cannot be inferred from tool traces.

## Final Snapshot

Before the final user-facing handoff, call exactly one:

```text
write_session_snapshot(
  session_id="<same stable session id>",
  goal="<requested goal>",
  done=[...],
  open=[...],
  next_command="<next concrete command, or empty string if none>",
  source="agent",
  source_client="<same source_client>",
  tags=[...],
  context={...}
)
```

The snapshot should capture:

- what changed
- what validation actually ran
- what remains open, including blockers and risk labels
- the next concrete command when work is intentionally left open

Do not close multiple snapshots for one continuous task. If a BR tool response
returns an agent directive with a session id, reuse that session id.

If the closeout directive includes `review_session_snapshot_hygiene`, treat it
as advisory feedback. The snapshot was persisted; use the warnings to improve a
future closeout, propose a policy card, or decide whether a follow-up is needed.

## Post-Close Learning Loop

After `write_session_snapshot`, optionally run the session-learning tools when
the user is asking what agents did, what failed, or what should become durable
policy:

1. Use `session_risk_classify` or `session_lesson_extract` on the current
   session.
2. Use `session_policy_cards_generate` or `session_learning_report_generate`
   across recent sessions before proposing `AGENTS.md` or skill changes.
3. Use `session_backfill_to_kg` first as a dry run. Only write to KG when the
   user explicitly wants it and the Neo4j environment is configured.

## User-Facing Handoff

In the final answer:

- summarize what changed and name changed paths
- summarize validation that actually ran
- mention open items or risk labels if any remain
- mention the BR `session_id` and `run_id` if useful
- do not paste raw JSON from `log_research_event` or `write_session_snapshot`
- for periodic learning reports, summarize top task surfaces, repeated blockers,
  successful patterns, policy candidates, KG lesson candidates, and
  stale/running sessions

Use explicit status language:

- `implemented` for behavior present in code and validated as such
- `partial` for incomplete or partially verified behavior
- `spec-only` for docs, recipes, or contracts that do not execute anything
- `handoff-only` for instructions that prepare another actor to execute

## Surface Mini-Checklists

### Prod Rollout

Capture:

- commit SHA or image tag
- rollout target and environment
- rollout status: local-only, dry-run, staged, deployed, rolled back, or blocked
- health checks actually run
- API and browser smoke checks actually run
- auth, data, runtime, migration, or infra blockers

Useful risk labels:

- `prod-auth-data-runtime`
- `partial-validation`
- `logging-metadata-gap`

Do not claim hosted execution when only a recipe, local verification, dry run,
or handoff was completed.

### Web Or Demo UI

Capture:

- changed routes, components, API endpoints, and demo config files
- whether API payload shape was checked
- whether rendered browser state was checked
- whether evidence is curated demo evidence, live analysis evidence, or degraded
  backend evidence
- mode boundaries, especially chat versus grounded requests versus handoff-only
  surfaces

Useful validation:

- focused unit test
- route/API test
- browser smoke or Playwright check when visual behavior matters
- screenshot or manual browser note when no automated visual test exists

### Repo Cleanup

Capture:

- exact path inventory before cleanup
- unrelated dirty worktree surfaces kept separate
- generated artifacts versus source files
- files intentionally left on disk but removed from git tracking, if applicable
- templates and examples preserved

Useful validation:

- `git status --short`
- `git diff --check`
- `git ls-files`
- `git check-ignore`

Useful risk labels:

- `uncommitted-local`
- `unrelated-dirty-worktree`
- `generated-artifact`
- `pre-existing-debt`

### Scientific Workflow

Capture:

- hypothesis or scientific question
- confirmatory test and gate/outcome state
- exploratory follow-up and how it was labeled
- null-result diagnosis when effects are weak or non-significant
- datasets, run ids, artifacts, and blocked assets
- self-critique or review pass performed before final reporting

Useful risk labels:

- `scientific-method-gap`
- `partial-validation`
- `prod-auth-data-runtime`
- `logging-metadata-gap`

Separate run completion from scientific validity and manuscript/report
readiness.

### Code Or Contract Change

Capture:

- changed files and ownership surface
- behavior or contract shape changed
- focused tests added or updated
- schema, API, planner, or protocol validation performed
- repo-wide checks skipped or blocked by unrelated pre-existing debt

Useful validation:

- focused unit or integration test
- contract/schema validation
- typecheck or lint for the touched package
- reproduction command for the original failure, when applicable

Use `implemented`, `partial`, or `spec-only` precisely. For planning and
handoff surfaces, state whether they execute anything or only prepare a
validated recipe.

## Anti-Patterns

Avoid:

- generating a new `session_id` for every turn
- omitting `source_client`
- using `source="codex"` instead of `source="agent"`
- writing multiple final snapshots for one continuous task
- pasting raw MCP JSON into the final answer
- claiming a rollout, analysis, or contract executed when only a plan or
  handoff was created
- hiding open blockers behind a generic "completed" summary
