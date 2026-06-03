# Self-Managed Onboarding Spec

- Status: Draft
- Last updated: 2026-03-28
- Related docs:
  - `docs/specs/br_mcp_mode_profile_spec.md`
  - `docs/mcp.md`

## 1. Purpose

This document defines the canonical onboarding paths for self-managed Brain
Researcher users in:

- local Docker
- HPC

The goal is to make self-managed users first-class product users even when they
do not use the hosted JupyterHub workspace.

## 2. Core Definition

Self-managed Brain Researcher users do **not** start in JupyterHub.

They start in:

- a repo checkout
- a terminal and editor
- a coding agent
- a local or cluster runtime

Their primary assistant is a coding agent, and their domain layer is BR MCP.

Canonical self-managed product shape:

- `coding agent + BR MCP + local/HPC runtime`

## 3. Supported Self-Managed Modes

| Mode | Primary shell | Primary assistant | Default transport | Runtime |
| --- | --- | --- | --- | --- |
| Local Docker | local repo + terminal + editor | `Claude Code`, `Codex`, `Opencode` | stdio or Docker stdio | local filesystem, local Docker, optional local Neurodesk |
| HPC | login node + repo + terminal | `Claude Code`, `Codex`, `Opencode` | stdio | Neurodesk/CVMFS, scheduler, cluster runtime |

## 4. First-Class Clients

For v1, the self-managed onboarding docs should explicitly support:

- `Claude Code`
- `Codex`
- `Opencode`

Other MCP-capable coding agents may work, but do not need first-class launch
docs on day one.

## 5. Shared Onboarding Invariants

Every self-managed onboarding path should do the same five things:

1. establish a repo or project workspace
2. connect the coding agent to BR MCP
3. verify MCP with a minimal health call such as `server_info`
4. make the runtime usable for neuroimaging work
5. provide one starter prompt or starter task

If a path cannot satisfy those five steps clearly, it is not production-ready.

## 6. Local Docker Path

### 6.1 Intended user

Local Docker is for contributors, power users, and researchers who want a
self-managed local workflow without the hosted JupyterHub shell.

### 6.2 Canonical shape

- repo checkout
- coding agent
- BR MCP over stdio or Docker stdio
- local runtime for code, files, and notebooks

### 6.3 Prerequisites

Minimum:

- Brain Researcher repo checkout
- coding agent installed
- Docker available if using the Docker stdio wrapper

Optional but recommended:

- local Python environment for `brain-researcher-mcp`
- local Neo4j if KG tools are needed

### 6.4 Recommended connection options

Preferred:

- repo-local `brain-researcher-mcp` over stdio

Fallback:

- `scripts/ops/mcp_docker_stdio.sh`

The local Docker onboarding doc should point to `docs/mcp.md` for exact command
snippets instead of duplicating all client JSON examples.

### 6.5 Canonical first-run flow

1. open the repo locally
2. connect the coding agent to BR MCP
3. call `server_info`
4. call `tool_search` or `dataset_get_resources`
5. run one starter task from the coding agent

### 6.6 Starter task examples

- find the resources for a known dataset
- ask for a GLM workflow recipe
- inspect which tool handles a task

## 7. HPC Path

### 7.1 Intended user

HPC is for users who already work from a cluster login node, shared filesystem,
and scheduler-backed environment.

### 7.2 Canonical shape

- login node or interactive dev environment
- repo checkout
- coding agent
- BR MCP over stdio
- heavy execution via Neurodesk / Slurm recipes

### 7.3 Prerequisites

Minimum:

- repo checkout on cluster-facing filesystem
- coding agent available on the login node or trusted dev node
- environment capable of launching `brain-researcher-mcp`

Recommended:

- Neurodesk/CVMFS availability
- Slurm access
- validated module environment

### 7.4 Canonical first-run flow

1. open repo on the login node
2. connect the coding agent to BR MCP over stdio
3. call `server_info`
4. call `sherlock_guide` or execution-recipe helpers
5. generate the workflow or scheduler recipe before any heavy run

### 7.5 Execution rule

The coding agent should use BR MCP to generate guidance, recipes, and
diagnostics, but the actual heavy execution should route through:

- Neurodesk modules
- Slurm
- cluster-native runtime mechanisms

The login-node coding session is the control plane, not the data plane.

## 8. MCP Profiles

Self-managed onboarding should align with these MCP profiles:

- Local Docker -> `external_coding_v1`
- HPC -> `hpc_coding_v1`

These names and semantics are defined in:

- `docs/specs/br_mcp_mode_profile_spec.md`

## 9. Auth and Transport Defaults

### 9.1 Local Docker

- default transport: stdio
- fallback transport: Docker stdio
- default auth: none across local stdio process boundaries

### 9.2 HPC

- default transport: stdio
- default auth: none for repo-local login-node stdio
- token or JWT only when using a shared remote MCP service

## 10. Minimum Success Checks

Every self-managed onboarding guide must include a minimal success checklist:

- coding agent can call BR MCP
- `server_info` succeeds
- one tool-discovery call succeeds
- one domain-relevant task succeeds
- the user knows what runtime will execute heavy work

## 11. Explicit Non-Goals

The self-managed onboarding path is not trying to:

- recreate the hosted JupyterHub UI locally
- require Notebook Intelligence outside the hosted mode
- push local or HPC users through the hosted HTTP shell
- hide the difference between local control-plane work and heavy execution

## 12. Follow-on Docs

This spec should be followed by:

1. client-specific quickstarts for `Claude Code`, `Codex`, and `Opencode`
2. a local Docker quickstart
3. an HPC quickstart
4. concrete example prompts for self-managed workflows
