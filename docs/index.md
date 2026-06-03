# Brain Researcher Docs

Brain Researcher is an OSS-preview neuroimaging research assistant with a recipe/handoff-first workflow surface. Use these docs to connect an MCP client, inspect the knowledge graph, and understand which public surfaces are currently verified.

## Start Here

- [MCP setup](mcp.md) - local stdio MCP server and client configuration.
- [Operations](OPERATIONS.md) - service ports, health checks, and runtime notes.

## Product Surfaces

- [Runtime stack](specs/brain_researcher_runtime_stack.md) - service layout and runtime boundaries.
- [MCP tool catalog](mcp_tools.schema.json) - machine-readable tool contracts.
- [MCP surface tiers](mcp.md#surface-tiers) - public, internal, and compatibility MCP tools.
- [KG tool schema](services/br-kg/kg_tool_schema.md) - graph schema for tools, versions, and runs.
- [UI wiring checklist](UI_WIRING_CHECKLIST.md) - Web UI, agent, and BR-KG connectivity expectations.
- [GABRIEL pipeline](services/br-kg/gabriel_full_pipeline.md) - runtime notes for the GABRIEL BR-KG flow.
- [GABRIEL quickstart](services/br-kg/gabriel_sample_quickstart.md) - small sample workflow notes.

## Release And Review

- [Call for contributors](CALL_FOR_CONTRIBUTORS_EXPANDED.md) - review workflow and contribution areas.
- [Collaborator review items](CALL_FOR_COLLABATORS_REVIEW_ITEMS.md) - reviewer-facing item inventory.
- [BR-KG plot probe](use_cases/br_kg_plot_probe_20260502/SUMMARY.md) - bounded public summary and retained figures.
- [Bounded autoresearch case report](use_cases/bounded_autoresearch_a1_2026-04-30/BOUNDED_AUTORESEARCH_CASE_REPORT.md) - public markdown report.

## Support

- [GitHub Issues](https://github.com/zjc062/brain_researcher/issues)
- [Contributing](../CONTRIBUTING.md)
- [Security](../SECURITY.md)
