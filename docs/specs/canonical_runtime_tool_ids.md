# Canonical Runtime Tool IDs

- Canonical tool ID = lowercase `snake_case` runtime name.
- Canonical tool ID should align with the primary Neurodesk module command or wrapper command.
- Use `package_command` when the bare command name would be ambiguous, for example `fsl_bet` and `ants_registration`.
- Neurodesk-facing structural tools should follow the same rule, for example `cat12_segment`.
- Public tool IDs must not contain dots, hyphens, CamelCase, `.run`, or embedded version strings.
- Version and descriptor information belong in runtime metadata such as `niwrap_id`, module name, and recommended module version, not in the public tool ID.
- Legacy planner/catalog aliases may be accepted only at ingress compatibility boundaries and must normalize to the canonical tool ID immediately.
- Planner output, allowlists, QC fallback rules, MCP responses, and execution traces must emit canonical tool IDs only.
- Adapter-private descriptors such as `fsl.bet.run` or `fsl.6.0.7.bet.run` are implementation details and must not be used as public-facing tool IDs.
- Examples: `fsl_bet`, `ants_registration`, `cat12_segment`, `searchlight_analysis`.
