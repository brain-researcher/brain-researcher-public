# Studio Execution Gateway API Spec

- Status: Draft
- Last updated: 2026-03-29
- Related docs:
  - `docs/specs/studio_runtime_architecture_spec.md`
  - `docs/specs/studio_session_gateway_api_spec.md`

## 1. Purpose

This document defines the minimal Studio execution gateway contract.

The gateway is the Studio-side control plane for code and command execution
requests. It does not run code yet; it accepts requests, records execution
state, and returns stubbed responses that preserve the shape of the future
runtime-backed API.

## 2. Scope

In scope:

- code execution requests
- command execution requests
- session-scoped execution listing
- execution inspection
- lightweight lifecycle actions

Out of scope:

- actual kernel/process execution
- artifact generation internals
- long-running job scheduling
- BR MCP tool calls
- notebook materialization internals

## 3. Base Path

Recommended base path:

- `/api/studio/sessions/{session_id}/executions`

## 4. Resource Model

### 4.1 Studio execution object

Minimum response shape:

```text
studio_execution(
  id,
  session_id,
  project_id,
  owner_user_id,
  kind,
  runtime_backend,
  runtime_profile_id,
  status,
  language?,
  code?,
  command?,
  working_directory?,
  env,
  timeout_seconds?,
  metadata,
  request_summary,
  result?,
  created_at,
  updated_at,
  accepted_at?,
  completed_at?
)
```

### 4.2 Result object

Stub result shape:

```text
execution_result(
  stubbed,
  exit_code?,
  stdout,
  stderr,
  artifacts,
  summary?
)
```

## 5. Endpoints

### 5.1 Create execution

`POST /api/studio/sessions/{session_id}/executions`

Request:

```json
{
  "kind": "code",
  "language": "python",
  "code": "print('hello')",
  "runtime_backend": "stub",
  "runtime_profile_id": "standard",
  "working_directory": "notebooks",
  "env": {
    "PYTHONUNBUFFERED": "1"
  },
  "timeout_seconds": 60,
  "dry_run": true,
  "metadata": {
    "source": "studio"
  }
}
```

Behavior:

- validate that the session exists and belongs to the authenticated user
- accept `kind=code` requests with `code`
- accept `kind=command` requests with `command`
- return a stubbed execution record immediately

Response:

```json
{
  "execution": {
    "id": "exec_...",
    "session_id": "studio_...",
    "project_id": "proj_motor_demo",
    "owner_user_id": "user_123",
    "kind": "code",
    "runtime_backend": "stub",
    "runtime_profile_id": "standard",
    "status": "accepted",
    "language": "python",
    "code": "print('hello')",
    "command": [],
    "working_directory": "notebooks",
    "env": {
      "PYTHONUNBUFFERED": "1"
    },
    "timeout_seconds": 60,
    "metadata": {
      "source": "studio"
    },
    "request_summary": "Stub execution accepted; no runtime backend is attached yet.",
    "result": {
      "stubbed": true,
      "exit_code": null,
      "stdout": "",
      "stderr": "",
      "artifacts": [],
      "summary": "Execution gateway stub"
    },
    "created_at": "2026-03-29T00:00:00Z",
    "updated_at": "2026-03-29T00:00:00Z",
    "accepted_at": "2026-03-29T00:00:00Z",
    "completed_at": null
  }
}
```

### 5.2 List executions

`GET /api/studio/sessions/{session_id}/executions`

Query params:

- `kind`
- `status`
- `limit`
- `offset`

### 5.3 Get execution

`GET /api/studio/sessions/{session_id}/executions/{execution_id}`

### 5.4 Perform action

`POST /api/studio/sessions/{session_id}/executions/{execution_id}/actions/{action}`

MVP actions:

- `touch`
- `cancel`

## 6. Error Model

Standard errors should use:

```json
{
  "detail": "..."
}
```
