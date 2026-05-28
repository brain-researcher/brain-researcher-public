# Migration notes

Per-release migration guidance for downstream consumers of the OSS contract surface (`contracts/tools/`, `br.*` namespace, MCP tool names).

## v0.1.0 (2026-05-27, first OSS release)

Initial release. No prior contract to migrate from. If you were depending on the internal pre-OSS shape:

- `brain_researcher.llmcore.router` → `brain_researcher.services.agent.router`. The `llmcore` package no longer exists; see commit history on `refactor/llmcore-into-agent`.
- Tool naming policy: prefer `slurm_*` over `sherlock_*`. The `sherlock_guide` / `sherlock_slurm` entries remain as deprecated aliases for one release cycle and will be removed in the release following v0.1.0.

Future entries land here whenever `contracts/VERSION` bumps.
