# Brain Researcher Docs

Brain Researcher is an OSS-preview neuroimaging research assistant with a recipe/handoff-first workflow surface. Use these docs to install the local stack, connect an MCP client, inspect the knowledge graph, and understand which public surfaces are currently verified.

## Start Here

- [Quick start](getting-started/quickstart.md) - local setup and first commands.
- [Installation](getting-started/installation.md) - Python, Docker, and environment setup.
- [MCP setup](mcp.md) - local stdio MCP server and client configuration.
- [CLI reference](api/cli-reference.md) - `brain-researcher` / `br` command surface.
- [Operations](OPERATIONS.md) - service ports, health checks, and runtime notes.

## Product Surfaces

- [Architecture overview](architecture/overview.md) - service layout and core components.
- [Tool universe](api/tool_universe.md) - catalog and metadata conventions.
- [MCP surface tiering](api/mcp_surface_tiering.md) - public, internal, and compatibility MCP tools.
- [KG tool schema](services/neurokg/kg_tool_schema.md) - graph schema for tools, versions, and runs.
- [UI wiring checklist](UI_WIRING_CHECKLIST.md) - Web UI, agent, and BR-KG connectivity expectations.

## Release And Review

- [OSS preview release gate](release/oss_preview_release_gate_2026-05-28.md) - latest public web and docs boundary check.
- [Tracked legacy/script/demo review](review/tracked_legacy_script_demo_review.md) - cleanup ledger for public-surface files.
- [Scientific review stack](review/scientific_review_stack.md) - review workflow and failure-mode framing.

## Support

- [GitHub Issues](https://github.com/zjc062/brain_researcher/issues)
- [Contributing](../CONTRIBUTING.md)
- [Security](../SECURITY.md)
