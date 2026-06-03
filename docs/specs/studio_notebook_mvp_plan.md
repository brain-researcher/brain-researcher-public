# Studio Notebook MVP Plan

- Status: Draft
- Last updated: 2026-03-29
- Horizon: 2-week MVP
- Related docs:
  - `docs/specs/studio_runtime_architecture_spec.md`
  - `docs/specs/studio_session_gateway_api_spec.md`
  - `docs/specs/studio_execution_gateway_api_spec.md`

## 1. Goal

Convert hosted `Studio` from a Monaco-centered workbench into an
assistant-first surface with:

- left-side `AI chat / session`
- right-side `Notebook panel`
- `Preview / Edit` notebook modes
- notebook persistence as `.ipynb`
- Python execution through the existing Jupyter session model

The target shape is closer to Drylab:

- the notebook is a durable session artifact
- the assistant is the primary interaction surface
- notebook edits happen through cell-level operations, not through a generic IDE
- Monaco becomes a cell editor, not the page-level product shell

## 2. What Already Exists

The repo is not starting from zero.

### 2.1 Frontend assets already in repo

- [`studio-plan-panel-example.tsx`](../../apps/web-ui/src/components/chat/plan/studio-plan-panel-example.tsx)
  already demonstrates the intended `notebook stream + focused right rail`
  interaction pattern.
- [`page.tsx`](../../apps/web-ui/src/app/studio/plan-preview/page.tsx)
  already exposes that preview as a standalone route.
- [`StudioWorkbenchPage.tsx`](../../apps/web-ui/src/components/studio/StudioWorkbenchPage.tsx)
  already owns Studio session/execution wiring, but the main layout is still
  Monaco-first and should be treated as legacy for this effort.
- [`chat-workspace.tsx`](../../apps/web-ui/src/components/chat/chat-workspace.tsx)
  already contains reusable chat primitives such as `ChatComposer` and
  `MessageList`.

### 2.2 Runtime and execution assets already in repo

- [`studio_session_runtime.py`](../../src/brain_researcher/services/orchestrator/studio_session_runtime.py)
  already provides:
  - Studio session attach/create
  - runtime session binding
  - project-aware workspace handoff
  - working-directory and Jupyter metadata storage
- [`studio_execution_runtime.py`](../../src/brain_researcher/services/orchestrator/studio_execution_runtime.py)
  already provides:
  - session-scoped execution records
  - Python execution against a bound Jupyter runtime
  - fallback execution lanes for `neurodesk_module` and `container`
- [`runtime_client.py`](../../src/brain_researcher/integrations/jupyter/runtime_client.py)
  already provides:
  - Jupyter session create/reuse
  - kernel channel execution
  - interrupt support

### 2.3 Web-to-backend plumbing already in repo

- [`studio-sessions.ts`](../../apps/web-ui/src/lib/api/studio-sessions.ts)
- [`studio-executions.ts`](../../apps/web-ui/src/lib/api/studio-executions.ts)
- [`route.ts`](../../apps/web-ui/src/app/api/studio/[...path]/route.ts)

These are sufficient for the current Studio control plane, but not for
notebook document operations.

## 3. Main Gaps

The largest missing piece is not kernel execution. It is the notebook document
model.

### 3.1 Missing backend resource family

The repo currently lacks a dedicated notebook document service for Studio.

This MVP needs a third Studio resource family in addition to:

- session lifecycle
- execution lifecycle

The new family is:

- notebook document lifecycle

### 3.2 Missing notebook source-of-truth contract

The notebook source of truth should be the `.ipynb` file in project storage,
not a database-only representation.

Database/index state can be secondary metadata, but the canonical saved notebook
must remain a standard nbformat notebook.

### 3.3 Missing frontend notebook state layer

The frontend currently has:

- a Monaco workbench
- a notebook-style preview example

It does not yet have:

- a real `NotebookPanel`
- notebook document state
- `Preview / Edit` mode switching
- cell-level controls
- autosave / dirty-state handling
- inline execution output rendering

## 4. Notebook MVP Contract

### 4.1 Notebook resource

```text
studio_notebook(
  id,
  project_id,
  session_id?,
  path,
  title,
  kernel_name,
  format,
  metadata,
  created_at,
  updated_at,
  last_saved_at,
  revision
)
```

Suggested persisted path:

- `projects/{project_id}/notebooks/studio/{session_id}.ipynb`

### 4.2 Cell model

```text
cell(
  id,
  type,
  source,
  metadata,
  outputs,
  execution_count,
  status
)
```

MVP cell types:

- `code`
- `markdown`

Rules:

- every cell must have a stable UUID
- the UUID should map to nbformat cell `id`
- assistant ops target `cell_id`, not raw array index

### 4.3 Preview/Edit semantics

Notebook mode should be notebook-wide in MVP.

`Preview` mode:

- render markdown
- show code read-only
- show saved outputs
- hide raw editing affordances

`Edit` mode:

- show raw markdown and code editors per cell
- preserve outputs under cells when helpful
- use Monaco or another code editor only at the cell level

### 4.4 Assistant notebook ops

User-facing ops:

- `append`
- `edit`
- `ai_edit`
- `edit_and_move`

Internal patch primitives:

- `insert_cell`
- `update_cell`
- `delete_cell`
- `move_cell`
- `replace_cell`
- `apply_outputs`

`edit_and_move` behavior:

- replace a bad cell with a corrected version appended at a new destination
- preserve top-to-bottom rerun correctness
- avoid requiring notebook drag/drop in MVP

## 5. Recommended API Additions

Recommended new surface:

- `GET /api/studio/sessions/{session_id}/notebook`
- `POST /api/studio/sessions/{session_id}/notebook/open-or-create`
- `PATCH /api/studio/sessions/{session_id}/notebook`
- `POST /api/studio/sessions/{session_id}/notebook/ops`
- `POST /api/studio/sessions/{session_id}/notebook/cells/{cell_id}/execute`

Responsibilities:

- notebook API owns notebook JSON load/save and patch application
- execution API owns runtime execution
- cell execution endpoint bridges notebook cell source to the existing Jupyter
  execution runtime

## 6. Frontend Plan

### 6.1 Target composition

Replace the current `/studio` composition with:

- left: assistant thread + composer + session summary
- right: notebook panel + toolbar + inspector

Notebook toolbar should own:

- mode toggle: `Preview` / `Edit`
- save state
- run current cell
- notebook path/title

Global runtime controls should move out of the primary canvas and into:

- a compact top bar
- an overflow sheet
- or a dev-only panel

The current page-level stdout/stderr panels should be removed. Execution output
belongs inline under notebook cells.

### 6.2 Recommended component split

Keep route:

- [`page.tsx`](../../apps/web-ui/src/app/studio/page.tsx)

Replace its implementation with a new shell:

- `apps/web-ui/src/components/studio/StudioNotebookShell.tsx`

New assistant pane:

- `apps/web-ui/src/components/studio/assistant/StudioAssistantPane.tsx`

New notebook pane:

- `apps/web-ui/src/components/studio/notebook/StudioNotebookPanel.tsx`
- `apps/web-ui/src/components/studio/notebook/StudioNotebookToolbar.tsx`
- `apps/web-ui/src/components/studio/notebook/StudioNotebookCell.tsx`
- `apps/web-ui/src/components/studio/notebook/StudioNotebookOutput.tsx`
- `apps/web-ui/src/components/studio/notebook/StudioNotebookInspector.tsx`

New notebook state hook:

- `apps/web-ui/src/components/studio/notebook/useStudioNotebookState.ts`

### 6.3 Reuse guidance

Reuse:

- chat primitives from [`chat-workspace.tsx`](../../apps/web-ui/src/components/chat/chat-workspace.tsx)
- notebook stream patterns from
  [`studio-plan-panel-example.tsx`](../../apps/web-ui/src/components/chat/plan/studio-plan-panel-example.tsx)

Do not reuse as the primary surface:

- the current Monaco-first `StudioWorkbenchPage`
- the whole `ChatWorkspace` container

## 7. Backend Plan

### 7.1 New backend deliverables

Add:

- `src/brain_researcher/services/orchestrator/studio_notebook_runtime.py`
- `src/brain_researcher/services/orchestrator/endpoints/studio_notebook.py`

Extend:

- [`studio_session_runtime.py`](../../src/brain_researcher/services/orchestrator/studio_session_runtime.py)
- [`studio_execution_runtime.py`](../../src/brain_researcher/services/orchestrator/studio_execution_runtime.py)
- orchestrator route registration in `main_enhanced.py`

### 7.2 Execution boundary

Notebook execution flow should be:

1. persist pending notebook edits
2. resolve target cell source and notebook working directory
3. execute code on the bound Jupyter session
4. translate runtime outputs into nbformat-compatible cell outputs
5. persist updated notebook JSON

Outputs should be stored back into notebook JSON, not only into separate
execution records.

## 8. Two-Week Delivery Plan

### Week 1

Days 1-2: Notebook runtime contract

- define notebook JSON response shape
- implement session-to-notebook path resolution
- implement create/load/save `.ipynb`
- add notebook API endpoints

Acceptance:

- given a `studio_session`, the backend can create or fetch a `.ipynb`
- the UI can fetch notebook JSON without executing anything

Days 3-4: Assistant-first Studio shell

- freeze [`StudioWorkbenchPage.tsx`](../../apps/web-ui/src/components/studio/StudioWorkbenchPage.tsx) as legacy
- add `StudioNotebookShell`
- lay out left assistant / right notebook panel
- reuse static notebook stream patterns from the preview example

Acceptance:

- `/studio` visually matches the assistant-first shape
- notebook panel is driven by real notebook state, not only mock data

Day 5: Preview/Edit modes

- add notebook-wide `Preview / Edit` switch
- render markdown in preview
- show code and markdown editing in edit mode
- add initial dirty-state tracking

Acceptance:

- user can toggle preview/edit
- notebook updates save through the backend

### Week 2

Days 6-7: Cell operations

- implement `append`
- implement `edit`
- implement `ai_edit` as assistant-proposed replacement payload
- implement `edit_and_move`

Acceptance:

- assistant actions mutate notebook cells through stable API operations
- notebook validity and cell ordering are preserved

Days 8-9: Execution binding

- execute selected code cell through the existing Jupyter runtime
- update notebook outputs from execution results
- show running/succeeded/failed state on the cell
- support rerun after edit

Acceptance:

- Python cell execution round-trips from UI to backend to Jupyter kernel
- output persists into `.ipynb`

Day 10: Autosave, handoff, tests

- autosave after notebook mutations
- carry notebook path into `Open in Workspace`
- add focused route and runtime tests
- add targeted Studio UI coverage

Acceptance:

- notebook survives refresh and reconnect
- workspace handoff opens the same notebook document

## 9. Acceptance Criteria

The MVP is complete when:

- `/studio` opens into an assistant-first layout
- a session notebook can be created or opened automatically
- notebook state persists as `.ipynb`
- the notebook can switch between `Preview` and `Edit`
- assistant actions can append and revise cells
- Python code cells execute against the bound Jupyter runtime
- outputs persist into the notebook and render inline
- the notebook path is preserved on `Open in Workspace`

## 10. Risks

- overreaching into full notebook editor behavior too early
- mixing notebook document semantics with generic code execution semantics
- underestimating output rendering and notebook persistence edge cases
- allowing the current Monaco workbench shape to dictate the new product model

Risk controls:

- keep MVP to `code + markdown`
- keep notebook mode notebook-wide
- defer drag/drop reorder and notebook history
- treat `Workspace` as the place for full notebook-native power features
- keep Jupyter runtime reuse and avoid inventing a second execution substrate

## 11. Immediate Next Step

Create the new `/studio` shell first, even if the notebook panel initially
renders notebook state from a mocked `.ipynb` payload. This de-risks the product
shape before deeper persistence and runtime integration work.
