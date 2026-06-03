# Brain Researcher Docs

Brain Researcher is an OSS-preview neuroimaging research assistant with a recipe/handoff-first workflow surface. Use these docs to connect an MCP client, inspect the knowledge graph, and understand which public surfaces are currently verified.

## Start Here

- [MCP setup](mcp.md) - local stdio MCP server and client configuration.
- [Operations](OPERATIONS.md) - service ports, health checks, and runtime notes.

## Product Surfaces

- [Architecture overview](architecture/overview.md) - service layout and core components.
- [MCP tool catalog](mcp_tools.schema.json) - machine-readable tool contracts.
- [MCP surface tiers](mcp.md#surface-tiers) - public, internal, and compatibility MCP tools.
- [KG tool schema](services/br-kg/kg_tool_schema.md) - graph schema for tools, versions, and runs.
- [UI wiring checklist](UI_WIRING_CHECKLIST.md) - Web UI, agent, and BR-KG connectivity expectations.
- [GABRIEL pipeline](services/br-kg/gabriel_full_pipeline.md) - runtime notes for the GABRIEL BR-KG flow.
- [GABRIEL quickstart](services/br-kg/gabriel_sample_quickstart.md) - small sample workflow notes.

## Release And Review

- [OSS preview release gate](release/oss_preview_release_gate_2026-05-28.md) - latest public web and docs boundary check.
- [Public KG dump](release/public_kg_dump.md) - export and release notes for the public graph dump.
- [Tracked legacy/script/demo review](review/tracked_legacy_script_demo_review.md) - cleanup ledger for public-surface files.
- [Scientific review stack](review/scientific_review_stack.md) - review workflow and failure-mode framing.

## Support

- [GitHub Issues](https://github.com/zjc062/brain_researcher/issues)
- [Contributing](../CONTRIBUTING.md)
- [Security](../SECURITY.md)
