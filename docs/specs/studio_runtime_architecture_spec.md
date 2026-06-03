# Studio Runtime Architecture Spec

- Status: Draft
- Last updated: 2026-03-29
- Related docs:
  - `docs/specs/br_mcp_mode_profile_spec.md`
  - `docs/specs/self_managed_onboarding_spec.md`

## 1. Purpose

This document defines the runtime architecture for the Brain Researcher hosted
web product when the primary web surface is:

- `Studio = Monaco + agent/chat + results/artifacts`
- backed by `Neurodesk` for execution
- backed by `BR MCP` for domain intelligence

The goal is to make `Studio` a lightweight, branded, web-native control plane
without forcing the product to rebuild all of Jupyter inside Next.js.

This spec also defines how `Workspace` fits into the model:

- `Workspace` is the advanced notebook view over the same project and runtime
- `Workspace` is not a separate product stack with a separate execution world
- `Workspace` remains the canonical notebook-native research surface

This spec records the hosted workspace direction. It defines how a lighter
Brain Researcher-owned `Studio` surface should sit in front of the same runtime
family.

This document is therefore a `vNext hosted Studio` architecture spec, not a
retroactive rewrite of the current hosted MVP definition in the workspace PRD.

## 2. Core Decision

Brain Researcher should split the hosted product into two coordinated surfaces
over one shared backend runtime model:

- `Studio`: the default hosted entry and control-plane surface
- `Workspace`: the canonical notebook-native work surface

The shared substrate is:

- `Neurodesk-backed stateful runtime`
- `BR MCP` as the domain intelligence layer
- shared project storage and artifact model

This means:

- `Studio` should not embed full JupyterLab as its primary UI
- `Studio` should not pretend to be a notebook
- `Workspace` should not require a separate project or runtime universe
- the hosted product should present one logical assistant identity across both
  surfaces, not two competing hosted assistants
- hosted product docs should distinguish between `primary web surface` and
  `advanced notebook surface`

### 2.1 Hosted surface framing

For hosted cloud, Brain Researcher should treat the surfaces as:

- `Studio`: default hosted entry point for lightweight iterative work
- `Workspace`: advanced hosted surface for notebook-native work

This avoids the earlier ambiguity where `hosted cloud` implied that JupyterLab
must always be the first user-facing surface.

Until the higher-level PRDs are updated, this should be read as a proposed
hosted surface split rather than as the already-ratified MVP contract.

## 3. Product Surface Split

### 3.1 Studio

`Studio` is the primary hosted web surface.

It should provide:

- Monaco-based code editing
- one assistant surface
- result and artifact panels
- project-aware execution controls
- session and run visibility
- lightweight file navigation

It should not be responsible for:

- full notebook document semantics
- terminal multiplexing as a first-class UI
- raw JupyterLab extension surface
- reproducing the full Jupyter chrome inside Next.js

### 3.2 Workspace

`Workspace` is the advanced hosted surface for users who need a full research
environment.

It should provide:

- JupyterLab
- notebook documents
- terminals
- file browser
- kernel-native workflows
- notebook-native assistant integrations

It is not the required first interaction path for every hosted user.

### 3.2.1 Hosted assistant identity

Hosted Brain Researcher should expose one logical assistant across `Studio` and
`Workspace`.

Allowed:

- one Brain Researcher assistant rendered in different surface-specific shells
- one shared project-aware assistant policy and MCP/tool posture

Not allowed:

- one generic Studio assistant plus a separate notebook assistant with a
  different identity and different domain logic
- two first-class hosted assistants competing for the same project context

Implementation implication:

- if `Workspace` uses a notebook-native assistant integration, it should be the
  notebook rendering of the same hosted Brain Researcher assistant, not a second
  product brain

### 3.3 BR MCP

`BR MCP` remains the domain intelligence layer for both surfaces.

It is responsible for:

- dataset discovery and resolution
- task and method interpretation
- workflow and tool recommendation
- evidence retrieval
- method guardrails and interpretation support

It is not the primary execution engine for user code.

### 3.4 Neurodesk runtime

`Neurodesk` is the execution substrate for hosted work.

It is responsible for:

- Python environment
- neuroimaging tools and system dependencies
- shell and terminal access
- long-running analysis jobs
- runtime filesystem visibility

### 3.5 Ownership matrix

| Component | Owns | Does not own | Interfaces with |
| --- | --- | --- | --- |
| `wrapper` | auth entry, launch flow, routing, docs/admin entrypoints | code execution, notebook semantics, domain reasoning | `Studio`, `Workspace`, `JupyterHub` |
| `Studio` | Monaco editing, assistant surface, result/artifact views, execution controls | notebook document semantics, full terminal UX, raw MCP credentials | `runtime gateway`, `BR MCP`, artifact index |
| `Workspace` | notebook UI, terminals, file browser, notebook-native kernel workflows | branded wrapper concerns, Studio-specific editing UX | `JupyterHub`, runtime session, `BR MCP` |
| `JupyterHub` | spawn/auth/session attachment for hosted notebook surface | Studio UX, artifact semantics, domain reasoning | `Workspace`, runtime session |
| `runtime_session` | kernel state, shell state, working directory, runtime env | product routing, domain planning, durable artifact metadata | `Studio`, `Workspace`, runtime manager |
| `Neurodesk` | toolchain image and execution substrate | product/session semantics above the runtime | runtime session |
| `BR MCP` | domain reasoning, search, recommendation, evidence | raw user code execution | `Studio`, `Workspace` assistants |
| artifact index | artifact metadata, provenance, lookup | raw bytes execution environment | `Studio`, `Workspace`, project storage |

## 4. Architectural Model

```text
User
  -> Studio web UI
      -> Studio API / session gateway
          -> Runtime manager
              -> Neurodesk-backed runtime session
                  -> Python kernel
                  -> shell/terminal
                  -> project filesystem
                  -> analysis tools
          -> BR MCP
          -> artifact index / metadata store

User
  -> Workspace (JupyterLab)
      -> same project storage
      -> same runtime family
      -> same BR MCP layer
```

The intended hosted model is:

- one project can have one or more runtime sessions over time
- `Studio` talks to a runtime through a Brain Researcher-owned gateway
- `Workspace` opens the same project in a notebook-native shell
- both surfaces consume the same project and assistant contracts

### 4.1 Hosted request flows

The hosted product should separate three flows clearly:

- `Studio assistant -> Studio backend -> BR MCP`
- `Studio execution -> runtime gateway -> runtime session`
- `Workspace assistant -> notebook-local server extension or equivalent hosted proxy -> BR MCP`

The browser must never call BR MCP directly with long-lived credentials.

## 5. Invariants

The following must remain true:

- `Studio` and `Workspace` share the same project identity
- artifacts created from either surface belong to the same project
- `Studio` does not require notebook documents to exist
- `Workspace` can be opened at any time from a `Studio` project
- `BR MCP` remains transport-independent from the surface
- user code execution remains separated from MCP reasoning/tool selection
- each surface has one primary assistant, not a parallel `BR chat` plus
  notebook/chat assistant pair

Hosted implication:

- if both `Studio` and `Workspace` expose an assistant, they must represent the
  same assistant identity and the same underlying BR MCP-backed domain layer,
  not competing assistants with different roles

## 6. Session Model

### 6.1 Session types

The hosted runtime model should distinguish six session concepts:

1. `project`
2. `runtime_profile`
3. `runtime_session`
4. `studio_session`
5. `workspace_session`
6. `assistant_session`

### 6.2 Project

`project` is the durable unit of work.

It owns:

- files
- notebooks
- outputs
- artifact metadata
- run history
- dataset mounts or references

Suggested identifier:

- `project_id`

Required ownership:

- one `project` belongs to one user or one explicitly shared workspace scope
- one `project` may have zero or more `runtime_session` records over time
- MVP should assume one primary interactive runtime per project at a time

Additional required ownership fields:

- `owner_user_id`
- `workspace_mode=hosted`
- `created_at`
- `updated_at`

### 6.3 Runtime profile

`runtime_profile` defines the class of runtime a project may request.

It should capture at least:

- compute shape
- memory class
- GPU availability
- storage class
- runtime image lineage
- policy constraints

Suggested identifier:

- `runtime_profile_id`

Suggested MVP profiles:

- `standard`
- `high_mem`
- `gpu`

### 6.4 Runtime session

`runtime_session` is the stateful execution environment attached to a project.

It should map to a Neurodesk-backed runtime boundary such as:

- a hosted single-user pod for MVP
- a container session
- a kernel + terminal bundle inside a managed session

It owns:

- Python process or kernel state
- shell state
- working directory
- environment variables
- mounted toolchain
- temporary execution state

Suggested identifier:

- `runtime_session_id`

Required ownership:

- one `runtime_session` belongs to exactly one `project`
- one `runtime_session` belongs to exactly one effective hosted user identity
- long-running jobs may outlive the interactive `runtime_session`, but they must
  still point back to the same `project_id`

Required foreign keys:

- `project_id`
- `owner_user_id`
- `runtime_profile_id`

Recommended additional metadata:

- `surface_origin` = `studio` or `workspace`
- `last_activity_at`
- `idle_timeout_at`
- `image_ref`
- `mount_set_id` or equivalent

### 6.5 Studio session

`studio_session` is a web interaction session for the Studio UI.

It is lighter than the runtime and may be recreated without losing project
state.

It owns:

- open buffers
- assistant conversation state
- selected artifacts
- UI layout state
- current execution focus

Suggested identifier:

- `studio_session_id`

Required ownership:

- one `studio_session` belongs to exactly one `project`
- one `studio_session` may attach to zero or one `runtime_session` at a time

Required foreign keys:

- `project_id`
- `runtime_session_id?`

### 6.6 Workspace session

`workspace_session` is a notebook-native attachment to the same project.

It may attach to:

- the same runtime session
- a new runtime session in the same project

Suggested identifier:

- `workspace_session_id`

Required ownership:

- one `workspace_session` belongs to exactly one `project`
- one `workspace_session` may attach to zero or one `runtime_session` at a time

Required foreign keys:

- `project_id`
- `runtime_session_id?`

### 6.7 Assistant session

`assistant_session` is the conversation and planning state owned by the product
assistant layer rather than by a single browser tab.

Suggested identifier:

- `assistant_session_id`

Required foreign keys:

- `project_id`
- `runtime_session_id?`

MVP note:

- cross-surface assistant continuity is desirable but not guaranteed in MVP
- if continuity is not implemented, the product must state that clearly rather
  than implying seamless chat carry-over between Studio and Workspace

### 6.8 Session state machine

Recommended `runtime_session` states:

- `provisioning`
- `ready`
- `busy`
- `idle`
- `degraded`
- `stopping`
- `stopped`
- `failed`
- `expired`

Recommended behaviors:

- `Studio` can attach only to `ready`, `busy`, or `idle`
- `Workspace` launch may trigger provisioning if no attachable runtime exists
- `expired` sessions preserve project state but lose in-memory kernel state

### 6.9 Runtime lease and keepalive

Interactive runtime sessions should be leased resources, not permanent user
containers.

The platform should track at least:

- `leased_at`
- `last_activity_at`
- `idle_timeout_at`
- `expires_at`

Required behaviors:

- idle runtime sessions may be culled without deleting project storage
- user-visible surfaces should receive a clear distinction between
  `runtime_stopped` and `project_deleted`
- `Open in Workspace` may revive a project by provisioning a fresh runtime when
  the prior runtime has expired

### 6.10 Attachment policy

The product should not assume that `Studio` and `Workspace` can always attach to
the same live interactive runtime safely.

MVP policy:

- the system should prefer reattaching to the same runtime when it is idle or
  safely reusable
- the system may provision a new runtime for the same project when concurrent
  interactive attachment would create state or UX ambiguity
- `same project` is a stronger guarantee than `same live in-memory kernel`

### 6.11 Runtime attach policy

The product should define an explicit attach policy rather than leaving runtime
selection implicit.

MVP policy:

- prefer one active attachable runtime per `project_id`
- if a compatible runtime exists for the same `project_id` and
  `runtime_profile_id`, reuse it
- otherwise provision a new runtime session

This avoids ambiguity during `Open in Workspace` and reverse handoff.

Later extensions may allow multiple named runtime sessions per project, but MVP
should not make the user choose among many runtime instances.

## 7. Execution Model

### 7.1 Execution principle

`Studio` should execute code against a stateful Neurodesk runtime, not through
stateless one-shot subprocess calls by default.

This is required to preserve:

- imported modules
- in-memory variables
- iterative analysis flow
- long-lived working context

### 7.2 Execution lanes

`Studio` should support four execution lanes.

#### Lane A: Python snippet execution

Use case:

- run selected code from Monaco
- run a generated analysis fragment
- inspect variables or load data

Execution target:

- project-bound Python kernel inside the runtime session

Output shape:

- stdout/stderr
- structured display payloads
- figures
- tables
- errors and tracebacks

#### Lane B: Command execution

Use case:

- run CLI tools
- inspect files
- call Neurodesk-packaged utilities
- trigger environment-aware scripts

Execution target:

- managed command channel inside the same runtime session

Output shape:

- streamed terminal output
- exit code
- generated files and logs

Boundary:

- Studio lane B is for bounded command execution with logs
- full interactive terminal UX remains Workspace-only

#### Lane C: Long-running job execution

Use case:

- heavy neuroimaging pipelines
- long analyses
- batch execution

Execution target:

- background process, job runner, or scheduler-bound execution from the runtime

Output shape:

- run record
- logs
- status transitions
- generated artifacts

This lane must not block the Studio request lifecycle.

#### Lane D: Notebook materialization

Use case:

- convert Studio work into reproducible notebook assets
- prepare handoff into Workspace

Execution target:

- project filesystem

Output shape:

- `.ipynb` or source-backed notebook materialization
- linked artifacts
- optional generated markdown narrative

### 7.3 Role of BR MCP in execution

`BR MCP` should guide and enrich execution, but it should not be the default
transport for raw code execution.

Recommended split:

- `BR MCP`: reasoning, planning, search, recommendation, interpretation
- runtime gateway: code, shell, and job execution

### 7.4 MCP profile mapping

Hosted Studio should use a dedicated MCP profile distinct from the hosted
notebook profile.

Recommended profile name:

- `hosted_studio_v1`

Intended characteristics:

- safe for browser-originated assistant use
- broader than `hosted_notebook_v1` where Studio needs artifact-aware planning
- still excludes low-level admin and mutation-heavy operational tools

Hosted Workspace should continue using a notebook-oriented profile such as:

- `hosted_notebook_v1`

### 7.5 Code execution API shape

Suggested logical request model:

```text
execute_code(
  request_id,
  project_id,
  runtime_session_id,
  runtime_profile_id?,
  source_surface="studio",
  language="python",
  source,
  cwd,
  context_files[],
  idempotency_key?,
  persist_outputs=true
)
```

Suggested logical response model:

```text
execution_result(
  execution_id,
  request_id,
  status,
  stdout,
  stderr,
  displays[],
  artifact_ids[],
  error,
  started_at,
  completed_at,
  runtime_session_id
)
```

### 7.6 Execution controls

The hosted execution layer should support:

- start
- stream output
- cancel
- interrupt
- restart runtime session
- retry with a new runtime session

MVP does not need every control exposed in the initial UI, but the backend
contract should anticipate them.

### 7.7 Failure model

Execution failures should be normalized at the gateway layer.

Recommended failure classes:

- `user_code_error`
- `dependency_error`
- `tool_missing`
- `runtime_unavailable`
- `runtime_expired`
- `timeout`
- `cancelled`
- `policy_denied`

Each failure should preserve enough structured metadata to support:

- UI display
- retry behavior
- artifact linking
- research logging and telemetry

### 7.8 Kernel policy

The hosted product should default to one primary Python execution context per
active runtime session.

Possible later extensions:

- multiple named kernels per project
- R kernels
- notebook-specific kernels

MVP should avoid exposing multi-kernel complexity in Studio.

## 8. Artifact Model

### 8.1 Core decision

Artifacts are first-class product objects.

They are not only files on disk. They are indexed outputs tied to:

- project
- runtime session
- execution
- assistant run or user action

### 8.2 Artifact classes

The hosted product should support at least these artifact classes:

- `file`
- `notebook`
- `plot`
- `table`
- `log`
- `report`
- `dataset_reference`
- `execution_result`
- `run_bundle`

### 8.3 Required artifact metadata

Each artifact should minimally carry:

- `artifact_id`
- `project_id`
- `runtime_session_id?`
- `artifact_type`
- `path` or backing storage reference
- `created_by`
- `created_at`
- `source_execution_id` if applicable
- `source_surface` = `studio` or `workspace`
- `mime_type` when relevant
- `previewable` boolean
- `display_name`
- `size_bytes?`
- `checksum?`
- `status` = `materializing` | `ready` | `failed`

### 8.4 Artifact persistence

Artifacts should persist in project storage, not only in session memory.

Recommended split:

- canonical bytes in project filesystem or object storage
- canonical metadata in artifact index

### 8.5 Artifact visibility

Artifacts produced in Studio must be visible in Workspace.

Artifacts produced in Workspace must be visible in Studio.

This is required for the product to feel like one system rather than two
separate apps.

### 8.6 Artifact promotion

The product should support promotion flows such as:

- execution output -> saved report
- generated code -> notebook
- notebook output -> pinned artifact
- plot/table -> reusable result card

### 8.7 Artifact provenance

Artifacts should preserve enough provenance to answer:

- which execution produced this
- which runtime session produced this
- whether it originated in Studio or Workspace
- which source files or notebooks were involved

MVP may store provenance lightly, but the metadata model should reserve space
for it.

## 9. Open in Workspace Contract

### 9.1 Core decision

`Open in Workspace` is not a blind redirect.

It is a product contract that preserves user state across surfaces whenever
possible.

### 9.2 Minimum contract

When a user chooses `Open in Workspace`, the system must preserve:

- `project_id`
- current file or target path
- runtime attachment intent
- selected artifact or code context

### 9.3 Preferred contract

Preferred payload:

```text
open_in_workspace(
  project_id,
  runtime_session_id?,
  runtime_profile_id?,
  target_path?,
  notebook_path?,
  open_artifact_id?,
  initial_focus?,
  materialize_notebook_if_needed=false
)
```

### 9.4 Semantics

#### Case A: existing attachable runtime

If a compatible runtime session already exists:

- Workspace should attach to that project/runtime pair
- in-memory state may be preserved if the runtime substrate allows it
- the system should prefer the currently selected Studio runtime session
- MVP should default to reusing the attachable active runtime unless the user
  explicitly requests a clean workspace

#### Case B: no active runtime

If no attachable runtime exists:

- provision a new runtime for the same project
- mount the same project storage
- open the requested path or artifact

#### Case C: code buffer without notebook

If the user is in Studio with code that is not yet a notebook:

- the user may open Workspace in script view, or
- the system may materialize a notebook before handoff

MVP should prefer explicit user intent over silent notebook generation.

#### Case D: incompatible runtime profile

If the current Studio runtime session is not compatible with the requested
Workspace surface or requested task:

- provision a new runtime session for the same project
- preserve project storage and handoff target
- clearly expose that in-memory runtime state was not carried over

### 9.5 Workspace launch response

`Open in Workspace` should resolve through a Brain Researcher-owned launch
contract rather than requiring the browser to construct raw hub URLs.

Preferred logical response:

```text
workspace_launch(
  workspace_launch_id,
  project_id,
  workspace_session_id?,
  runtime_session_id?,
  workspace_url,
  launch_token?,
  launch_token_expires_at?
)
```

Required behaviors:

- the launch response is generated server-side
- any launch token is scoped to one user, one project, and one launch flow
- the browser does not need cluster-internal routing knowledge

### 9.6 Handoff targets

Supported `Open in Workspace` targets should include:

- open project root
- open file
- open notebook
- open generated notebook from current code buffer
- open artifact-producing working directory

### 9.7 Reverse handoff

The reverse flow should also exist:

- `Return to Studio`
- `Open this artifact in Studio`
- `Continue this project in Studio`

This prevents Workspace from becoming a one-way escape hatch.

### 9.8 URL and routing implications

`Open in Workspace` should resolve to a durable project-aware route, not only a
raw hub URL.

Recommended logical contract:

- Studio creates a project-aware handoff token or route payload
- Workspace resolves that payload into a target file, notebook, or artifact

This allows the frontend routing model to evolve without breaking the product
contract.

## 10. Failure Modes and Recovery

The hosted product should explicitly handle at least these failure classes:

- runtime provisioning failure
- kernel startup failure
- kernel interruption or death mid-execution
- command execution timeout
- artifact bytes persisted but artifact indexing failed
- `Open in Workspace` launch prepared but workspace attach failed
- project exists but the referenced runtime session has expired

Recovery expectations:

- users should keep project state even when runtime state is lost
- failed execution should still produce an `execution_result` record with error
  metadata when possible
- artifact indexing failure should be repairable from persisted storage
- `Open in Workspace` failure should return the user to Studio with a clear
  retry path

## 11. Storage and Filesystem Model

### 11.1 Project filesystem

Each project should have a canonical filesystem root visible to both surfaces.

Suggested shape:

- `/projects/<project_id>/`

For hosted MVP, this should be treated as a logical project root, not
necessarily an absolute top-level filesystem path.

Recommended hosted mapping:

- `<user-home>/projects/<project_id>/`

Example:

- `/home/jovyan/work/projects/<project_id>/`

Subdirectories may include:

- `notebooks/`
- `scripts/`
- `outputs/`
- `reports/`
- `logs/`
- `data-links/`

### 11.2 Runtime working directory

The runtime should default to the project root or an explicit project work
subdirectory.

Studio and Workspace must agree on path semantics.

### 11.3 Dataset handling

Datasets should generally be mounted or referenced, not copied into project
storage by default.

The artifact layer may store:

- dataset references
- mount metadata
- derived outputs

## 12. Security and Policy Boundaries

### 12.1 Surface boundary

`Studio` browser code should not receive unrestricted runtime credentials.

Execution should go through a Brain Researcher-owned gateway.

### 12.2 Runtime boundary

Runtime sessions should remain isolated at least per user and preferably per
project/runtime attachment.

### 12.3 MCP boundary

`BR MCP` credentials and execution credentials should remain distinct.

Do not overload MCP tokens as general-purpose runtime execution credentials.

### 12.4 Workspace handoff credentials

`Open in Workspace` may require short-lived credentials or handoff tokens.

Those tokens should:

- be scoped to project and user
- be time-limited
- not act as general-purpose runtime execution tokens

### 12.5 Command and execution policy

The platform should distinguish between:

- interactive code execution policy
- command execution policy
- long-running job submission policy

The MVP does not need a perfect policy engine, but it should preserve a clear
boundary so that command and job capabilities can be tightened independently of
Python snippet execution.

## 13. Observability Requirements

The hosted product should emit telemetry at the boundaries that matter for
Studio and Workspace convergence.

Minimum required events:

- runtime provision started/completed/failed
- execution started/completed/failed/cancelled
- artifact created/promoted/failed
- `Open in Workspace` invoked/succeeded/failed
- reverse handoff invoked/succeeded/failed

Minimum required dimensions:

- `project_id`
- `runtime_session_id`
- `source_surface`
- `runtime_profile_id`
- `execution_lane`
- `execution_id?`
- `artifact_id?`

## 14. MVP Requirements

This section describes the MVP for the `Studio runtime architecture`, not the
earlier hosted workspace MVP defined in the JupyterHub workspace PRD.

The MVP version of this architecture must support:

- Monaco-based code editing in Studio
- one primary assistant in Studio
- stateful Python execution against a Neurodesk-backed runtime
- shell command execution against the same runtime
- persisted project storage
- artifact indexing for at least files, plots, logs, and execution results
- `Open in Workspace` from Studio into the same project
- server-side workspace launch contract
- runtime lease and idle expiry handling

The MVP does not need:

- full notebook rendering inside Studio
- multi-kernel Studio execution
- perfect in-memory handoff from Studio to Workspace
- collaborative editing
- browser-side direct terminal websocket handling

## 15. Non-Goals

This architecture does not attempt to:

- replace JupyterLab entirely
- make Studio a notebook clone
- collapse Studio and Workspace into one UI shell
- expose every Neurodesk capability directly in the web client
- provide arbitrary package-management UX in Studio
- expose unrestricted shell or admin powers directly to the browser
- guarantee concurrent live-kernel coherence across Studio and Workspace in MVP

## 16. Open Questions

The following questions remain intentionally open after this spec:

- whether the runtime gateway should proxy a Jupyter kernel protocol directly or
  expose a Brain Researcher-owned execution abstraction above it
- whether notebook materialization should default to `.ipynb`, source-backed
  notebooks, or support both from the start
- whether long-running execution should stay inside the runtime session or be
  promoted immediately into a separate job runner
- whether Workspace should always reuse the active Studio runtime when
  technically possible, or whether certain actions should prefer a fresh
  notebook-native runtime

## 17. Recommended Implementation Order

1. Define project and runtime session APIs
2. Build Monaco-based code execution in Studio against a stateful runtime
3. Define workspace launch contract and attachment policy
4. Add artifact indexing and result panels
5. Add shell execution lane
6. Add notebook materialization and reverse handoff

## 18. Decision Summary

The canonical hosted Brain Researcher model should be:

- `Studio` as the lightweight branded control plane
- `Workspace` as the advanced notebook surface
- one shared project model
- one shared artifact model
- Neurodesk-backed stateful runtime execution
- BR MCP as the shared domain intelligence layer

The key architectural principle is:

> Studio is not a notebook. Studio is a branded control plane over a real
> neuroimaging runtime.
