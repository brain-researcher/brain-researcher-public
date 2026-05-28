# Studio to Marimo Migration Plan

## Context

Brain Researcher is replacing the hosted Studio notebook surface with Marimo.
The current migration branch is `sdk/marimo-p0` and the shipped Marimo base
work is already on the branch:

- `0c4dd646` `Add Marimo notebook SDK and CLI`
- `5f0fac3a` `Add Marimo sidebar agent guidance`
- `60e981b0` `Add Marimo onboarding docs and helpers`
- `1f2c51e2` `Fix marimo notebook open exec path`
- `de427654` `Refine Marimo pairing guidance`

This document is the canonical plan for the migration. It replaces earlier
ad hoc plan drafts from chat threads.

## Product Decisions

- Marimo owns the interactive notebook UI.
- Marimo's `Pair with an agent` / external-agent path is the primary UX.
- Brain Researcher owns the notebook contract:
  - `brain_researcher.sdk`
  - templates
  - prompts / agent guidance
  - validation entrypoints
- `br.chat()` stays as a programmatic and headless API for scripts, CI, and
  non-UI environments. It is not the primary interactive notebook UX.
- `marimo edit --watch` is a fallback path only.
  In validated local runs on marimo `0.23.x`, watch mode remains a staged
  fix/reconcile flow and is not a clean direct file-watch autorun mode.

## Current State

### Done

- Marimo dependency is pinned to a validated range in `pyproject.toml`:
  `marimo>=0.23,<0.24`
- Marimo runtime config is present:
  - `[tool.marimo.runtime]`
  - `watcher_on_save = "autorun"`
- BR Marimo SDK exists under `src/brain_researcher/sdk/`
- Notebook CLI exists:
  - `br notebook open`
  - `br notebook list`
  - `br notebook agent-setup`
  - `br notebook check`
- Quickstart template exists:
  - `notebooks/templates/br_quickstart.py`
- BR agent guidance exists:
  - `docs/marimo/MARIMO_AGENT.md`
- User-facing Marimo guide exists:
  - `docs/user-guide/marimo.md`
- Pairing guidance has been validated locally for Claude Code and Codex
- `br.chat()` has been validated as a codegen path for Marimo `.py` notebooks

### Validated Constraints

- Pair mode works and is the clean live-edit path.
- `watcher_on_save = "autorun"` only changes post-accept execution behavior.
- `edit --watch` still surfaces staged fix / reconcile UI for external file
  edits.
- Global `autosave = "off"` is not part of the primary path and did not
  resolve staged watch behavior in local validation.

## Canonical TODO List

### Marimo P1: MCP `@resource` Agent Context

- Add BR MCP resources for concise agent-side context attachment:
  - `tool://{tool_id}`
  - `dataset://{dataset_ref}`
  - `workflow://{workflow_id}`
- Keep payloads concise and agent-oriented rather than returning full raw
  registry or KG dumps.
- Implement in this order:
  1. resource contracts
  2. FastMCP resource/template API check
  3. resource handlers shaped to the FastMCP template API
  4. focused tests
  5. Marimo + MCP docs
  6. live Claude Code validation
  7. live Codex validation
- Claim policy:
  - Claude Code `@resource` flow is only marked supported after live validation.
  - Codex `@resource` flow is verify-then-claim. Do not document it as a
    supported UX until the actual client-side experience is confirmed.

### Marimo P2: External-Agent Validation and Positioning

- Validate a full paired UI round-trip for Claude Code against the live
  notebook, including notebook edit persistence and post-edit execution.
- Validate a full paired UI round-trip for Codex against the live notebook,
  including notebook edit persistence and post-edit execution.
- Keep `br notebook check` and `marimo check` as the required validation gate
  for agent-edited notebooks.
- Keep product messaging explicit that `br.chat()` is headless/programmatic
  rather than the default interactive notebook path.

### Studio Deprecation: Separate Audited Phase

- Keep Studio deprecation separate from Marimo onboarding work.
- Use the audited inventory in
  `docs/audits/studio_deprecation_inventory_20260410.md`.
- Define replacement behavior before removing any Studio routes or files.
- Remove Studio in small phases:
  1. frontend routes and components
  2. frontend API clients and proxy
  3. orchestrator runtimes and endpoints
  4. residual data, fixtures, and docs

## Out of Scope for This Plan

- Building a custom BR chat sidebar inside Marimo
- Treating `edit --watch` as the main collaboration mode
- Mixing Studio deletion into the same code change set as Marimo onboarding

## Release Guidance

- Keep the current Marimo pin tight until a newer release is revalidated.
- Treat pair/sidebar mode as the supported primary UX.
- Document `edit --watch` only as a fallback with staged accept/reject
  semantics.
