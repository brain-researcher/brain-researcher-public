# Studio Session Gateway API Spec

- Status: Draft
- Last updated: 2026-03-29
- Related docs:
  - `docs/specs/studio_runtime_architecture_spec.md`
  - `docs/specs/br_mcp_mode_profile_spec.md`

## 1. Purpose

This document defines the API contract for the hosted `Studio session gateway`.

The gateway is the Brain Researcher-owned control-plane API that lets the web
UI:

- create or attach a Studio session
- inspect current Studio session state
- perform lightweight lifecycle actions
- build an `Open in Workspace` handoff payload

This API does not define raw code execution. Execution belongs in a separate
execution gateway contract.

## 2. Scope

In scope:

- Studio session lifecycle
- runtime attachment metadata
- assistant session attachment metadata
- project-scoped session listing
- workspace handoff construction

Out of scope:

- Python/kernel execution
- shell/command execution
- artifact indexing internals
- BR MCP tool calls
- notebook materialization internals

## 3. Base Path

Recommended base path:

- `/api/studio/sessions`

## 4. Auth Model

The Studio session gateway is a hosted authenticated API.

Requirements:

- caller must resolve to an authenticated Brain Researcher user
- browser must not receive raw runtime or MCP credentials
- the gateway owns session creation and handoff construction

## 5. Resource Model

### 5.1 Studio session object

Minimum response shape:

```text
studio_session(
  id,
  project_id,
  owner_user_id,
  display_name,
  runtime_profile_id,
  runtime_session_id,
  assistant_session_id,
  status,
  metadata,
  created_at,
  updated_at,
  last_activity_at
)
```

### 5.2 Handoff object

Minimum response shape:

```text
workspace_handoff(
  project_id,
  runtime_session_id?,
  runtime_profile_id,
  launch_mode,
  workspace_url,
  target_path?,
  notebook_path?,
  open_artifact_id?,
  initial_focus?,
  materialize_notebook_if_needed
)
```

## 6. Endpoints

### 6.1 Create or attach Studio session

`POST /api/studio/sessions`

Request:

```json
{
  "project_id": "proj_motor_demo",
  "display_name": "Motor Demo",
  "runtime_profile_id": "standard",
  "attach_if_exists": true,
  "metadata": {
    "source": "studio"
  }
}
```

Behavior:

- if an attachable session exists for the same user, project, and runtime
  profile, return it when `attach_if_exists=true`
- otherwise create a new Studio session record

Response:

```json
{
  "session": {
    "id": "studio_...",
    "project_id": "proj_motor_demo",
    "owner_user_id": "user_123",
    "display_name": "Motor Demo",
    "runtime_profile_id": "standard",
    "runtime_session_id": "rt_...",
    "assistant_session_id": "ast_...",
    "status": "ready",
    "metadata": {
      "source": "studio"
    },
    "created_at": "2026-03-29T00:00:00Z",
    "updated_at": "2026-03-29T00:00:00Z",
    "last_activity_at": "2026-03-29T00:00:00Z"
  }
}
```

### 6.2 List Studio sessions

`GET /api/studio/sessions`

Query params:

- `project_id`
- `runtime_profile_id`
- `status`
- `limit`
- `offset`

Response:

```json
{
  "items": [
    {
      "id": "studio_..."
    }
  ]
}
```

### 6.3 Get Studio session

`GET /api/studio/sessions/{session_id}`

Returns the session if owned by the authenticated user.

### 6.4 Perform lifecycle action

`POST /api/studio/sessions/{session_id}/actions/{action}`

MVP actions:

- `touch`
- `close`

Request:

```json
{
  "reason": "user_closed_panel"
}
```

Response:

```json
{
  "session": {
    "id": "studio_..."
  },
  "action": "close"
}
```

### 6.5 Build Workspace handoff

`POST /api/studio/sessions/{session_id}/workspace-handoff`

Request:

```json
{
  "runtime_profile_id": "standard",
  "target_path": "scripts/demo.py",
  "notebook_path": null,
  "open_artifact_id": null,
  "initial_focus": "editor",
  "materialize_notebook_if_needed": false,
  "open_clean_workspace": false
}
```

Behavior:

- default to reusing the active attachable runtime
- if `open_clean_workspace=true`, return a `launch_mode` that tells the caller a
  fresh runtime should be provisioned
- construct a project-aware workspace URL and preserved handoff metadata

Response:

```json
{
  "handoff": {
    "project_id": "proj_motor_demo",
    "runtime_session_id": "rt_...",
    "runtime_profile_id": "standard",
    "launch_mode": "reuse_active_runtime",
    "workspace_url": "https://hub.${PUBLIC_HOSTNAME}/lab/tree/scripts/demo.py",
    "target_path": "scripts/demo.py",
    "notebook_path": null,
    "open_artifact_id": null,
    "initial_focus": "editor",
    "materialize_notebook_if_needed": false
  }
}
```

## 7. Error Model

Standardized errors should use:

```json
{
  "detail": "..."
}
```

Expected statuses:

- `400` invalid request payload
- `401/403` unauthenticated or unauthorized
- `404` session not found
- `409` conflicting lifecycle request
- `503` session runtime unavailable

## 8. MVP Notes

The MVP implementation may use an in-memory or lightweight state-backed runtime
facade for Studio session records before real Neurodesk runtime provisioning is
fully wired in.

What must remain stable even in MVP:

- endpoint paths
- IDs and ownership model
- attach-vs-create behavior
- workspace handoff response shape

## 9. Implementation Notes

The session gateway should live alongside existing orchestrator session APIs,
but remain separate from the older remote monitor/session wrapper surface.

Recommended implementation pieces:

- `studio_session_runtime.py`
- `endpoints/studio_sessions.py`
- `app.state.studio_session_runtime`

## 10. Open Questions

- whether `workspace_url` should remain a direct URL or evolve into a signed
  launch route owned by the wrapper
- whether `assistant_session_id` should always be reused across Studio tabs for
  the same project
- whether `close` should stop only the Studio session record or also request
  runtime shutdown when it is the last attachment
