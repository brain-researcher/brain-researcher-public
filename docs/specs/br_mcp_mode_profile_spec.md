# BR MCP Mode and Profile Spec

- Status: Draft
- Last updated: 2026-03-28
- Related docs:
  - `docs/mcp.md`
  - `docs/mcp.md#surface-tiers`

## 1. Purpose

This document defines how Brain Researcher MCP should be used across the three
first-class deployment modes:

- hosted cloud
- local Docker
- HPC

The goal is to keep one shared Brain Researcher MCP intelligence surface while
allowing different transports, auth paths, assistant shells, and tool profiles
per deployment mode.

## 2. Core Decision

Brain Researcher does **not** require one universal assistant UI across all
environments.

Instead, it requires:

- one shared BR MCP tool surface
- one primary assistant per deployment mode
- one explicit MCP profile per deployment mode

The shared abstraction is the MCP intelligence contract, not the frontend shell.

## 3. Deployment Mode Matrix

| Mode | Primary shell | Primary assistant | Default transport | Execution substrate | Notes |
| --- | --- | --- | --- | --- | --- |
| Hosted cloud | JupyterHub + JupyterLab | notebook assistant | streamable HTTP | hosted Neurodesk-backed workspace | managed product path |
| Local Docker | repo + editor + terminal | coding agent (`Claude Code`, `Codex`, `Opencode`) | stdio or Docker stdio | local Docker / local runtime | self-managed local path |
| HPC | login node + repo + terminal | coding agent (`Claude Code`, `Codex`, `Opencode`) | stdio by default | Neurodesk/CVMFS + Slurm / cluster runtime | self-managed cluster path |

## 4. Shared Invariants

The following are invariant across all three modes:

- the canonical domain layer is `BR MCP`
- tool discovery starts from the same public tool surface
- tool contracts should remain transport-independent
- research logging semantics remain consistent
- tool tiering stays consistent with `docs/mcp.md#surface-tiers`

What may differ by mode:

- transport
- auth model
- exposed tool profile
- filesystem roots
- runtime substrate
- operational deployment shape

## 5. Same Surface vs Same Server

The phrase "same MCP server" is too loose and should be avoided in product and
platform docs.

More accurate wording:

- same **BR MCP tool surface**
- same **MCP contract family**
- same **server implementation lineage**
- not necessarily the same **operational instance**
- not necessarily the same **auth path**
- not necessarily the same **allowlist/profile**

Examples:

- hosted cloud may use a deployed multi-tenant HTTP MCP service
- local Docker may use a repo-local stdio MCP process
- HPC may use a login-node stdio MCP process or a thin local wrapper

These are different operational shapes over the same MCP contract family.

## 6. Mode Definitions

### 6.1 Hosted cloud

Hosted cloud is the flagship managed product mode.

Canonical shape:

- `JupyterHub + JupyterLab + notebook assistant + BR MCP over HTTP`

Required characteristics:

- notebook assistant is the only primary assistant
- browser does not hold raw BR MCP bearer credentials
- a local Jupyter server extension proxies requests to BR MCP
- BR MCP is called over in-cluster or otherwise internal HTTP

Default transport:

- `streamable HTTP`

Default auth:

- service-to-service credential or workspace-scoped token
- browser talks only to the local Jupyter server extension

Execution boundary:

- BR MCP plans, retrieves, explains, and recommends
- notebook kernel and Neurodesk-backed workspace execute the actual code

### 6.2 Local Docker

Local Docker is the primary self-managed local mode.

Canonical shape:

- `coding agent + BR MCP over stdio / Docker stdio`

Required characteristics:

- coding agent is the only primary assistant
- no JupyterHub required
- no branded wrapper required
- repo-local or Docker-wrapped MCP is the default path

Default transport:

- `stdio`

Secondary transport:

- `Docker stdio` wrapper for users who do not want a local Python install

Default auth:

- none for local stdio process boundaries
- if a local HTTP bridge is used later, require explicit token or local trust boundary

Execution boundary:

- coding agent edits files, notebooks, and configs
- BR MCP provides deterministic tool access and domain intelligence
- heavy execution may still happen via local Docker, local Neurodesk, or other runtime helpers

### 6.3 HPC

HPC is the primary self-managed cluster mode.

Canonical shape:

- `coding agent + BR MCP over stdio`

Required characteristics:

- coding agent runs on login node, dev node, or a trusted interactive environment
- repo checkout and scheduler access remain in the user's control
- heavy execution routes to Neurodesk / Slurm recipes

Default transport:

- `stdio`

Optional later transport:

- local HTTP wrapper if a site needs longer-lived MCP sessions

Default auth:

- none for login-node local stdio
- token or JWT only when crossing to a hosted/shared MCP service

Execution boundary:

- BR MCP provides recipes, guidance, and observability helpers
- cluster jobs run via Neurodesk modules, Slurm, or related runtime integrations

## 7. Recommended Tool Profiles

This spec defines three recommended MCP tool profiles.

### 7.1 `hosted_notebook_v1`

Intended for hosted JupyterLab notebook assistants.

Goals:

- keep the surface safe, focused, and notebook-relevant
- avoid admin and operational sharp edges
- bias toward read-heavy domain intelligence

Include:

- `tool_search`
- `tool_get`
- `dataset_get_resources`
- core KG read tools
- selected execution recipe helpers
- selected run observability helpers

De-emphasize or exclude:

- low-level ops tools
- manual/admin execution paths
- filesystem-heavy repo mutation helpers

### 7.2 `external_coding_v1`

Intended for local coding agents using BR MCP over stdio.

Goals:

- give coding agents broad research and execution-intelligence access
- keep repo mutation outside MCP
- preserve deterministic tool boundaries

Include:

- default and advanced read-heavy tools
- execution recipes
- run observability tools
- repo repair context helpers

De-emphasize:

- admin-only ops flows
- direct mutation-oriented manual paths unless explicitly enabled

### 7.3 `hpc_coding_v1`

Intended for coding agents operating in HPC environments.

Goals:

- preserve the breadth of `external_coding_v1`
- add scheduler and Neurodesk-aware helpers that are first-class on clusters

Include:

- everything in `external_coding_v1`
- `sherlock_guide`
- `sherlock_slurm`
- runtime and execution recipe helpers relevant to Slurm / Neurodesk

## 8. Transport Policy

### 8.1 Default transport by mode

- hosted cloud -> `streamable HTTP`
- local Docker -> `stdio`
- HPC -> `stdio`

### 8.2 Optional transports

- local Docker -> `Docker stdio`
- local Docker -> local HTTP only if a clear need emerges
- HPC -> local or cluster HTTP only when site operations justify it

### 8.3 Anti-pattern

Do not force self-managed local or HPC users through the hosted HTTP MCP path
when a local stdio process is available and sufficient.

## 9. Auth Policy

### 9.1 Hosted cloud

- auth is mandatory
- credentials stay server-side when possible
- notebook/browser surfaces should not directly hold raw MCP secrets

### 9.2 Local Docker

- stdio MCP needs no network auth
- Docker stdio wrapper inherits the same property
- any future local HTTP mode should default to explicit token protection

### 9.3 HPC

- login-node stdio MCP needs no network auth
- any shared service or cross-node HTTP path should use explicit token or JWT auth

## 10. Execution Policy

### 10.1 Hosted cloud

- interactive notebook work stays in the hosted workspace
- BR MCP should not become a hidden general-purpose remote job runner for ordinary notebook turns

### 10.2 Local Docker

- file edits, notebook edits, and shell operations stay with the coding agent
- BR MCP provides intelligence and deterministic tool access

### 10.3 HPC

- BR MCP provides heavy-workflow guidance and recipe generation
- actual heavy execution goes through Neurodesk / Slurm recipes
- scheduler-facing helpers are legitimate first-class tools in this mode

## 11. Recommended Client Guidance

### 11.1 Hosted cloud

- notebook assistant is canonical
- no separate BR chat pane

### 11.2 Local Docker

Document these as first-class clients:

- `Claude Code`
- `Codex`
- `Opencode`

### 11.3 HPC

Document the same agent family as primary, with examples centered on:

- repo checkout on login node
- stdio MCP
- Neurodesk module checks
- Slurm recipe generation and submission guidance

## 12. Documentation Consequences

The docs should consistently say:

- hosted cloud -> notebook assistant + HTTP MCP
- local Docker -> coding agent + stdio MCP
- HPC -> coding agent + stdio MCP + Neurodesk / Slurm execution path

The docs should not say:

- one universal assistant UI across every environment
- one operational MCP server instance for every deployment mode

## 13. Follow-on Artifacts

This spec should be followed by:

1. a `self-managed onboarding spec`: `docs/specs/self_managed_onboarding_spec.md`
2. a `hosted notebook tool-profile spec`
3. concrete allowlist/profile plumbing in the MCP server and docs
