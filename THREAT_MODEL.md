# Threat model

Attack surface for the Brain Researcher MCP server and the OSS contract layer at `contracts/tools/`. This document complements `SECURITY.md` (which covers vulnerability reporting) by enumerating the surfaces an integrator should harden before exposing the server beyond a trusted local network.

## Trust boundaries

The MCP server is designed to run **inside** a trusted process tree (an agent, a CLI, or a developer's own session). It is **not** designed to be exposed directly to untrusted callers over a network. The threat model assumes:

- The caller of any `@mcp.tool` is at least as trusted as the host process.
- Filesystem reads are scoped by `ALLOWED_ROOTS` (see `server_info.data.allowed_roots`).
- `enable_tool_execute` is `false` by default; `tool_execute` / `pipeline_execute` only run when explicitly enabled.

## Surfaces

| Surface | Threat | Mitigation |
|---|---|---|
| Untrusted prompts passed into agent loops that then call MCP tools | Prompt injection causing the agent to invoke tools with malicious args | Tool args are typed via the published `contracts/tools/*.json` schemas; reject calls that don't match. Stable-tier tools enumerate allowed parameter ranges in `input_schema`. |
| Untrusted file paths in tool args (`run_id`, `autoresearch_dir`, `logs_dir`, `local_workspace`) | Caller tricks the server into reading outside `ALLOWED_ROOTS` | `_run_roots_for_read()` and `ALLOWED_ROOTS` constrain reads. `scientific_report_generate.local_workspace` is explicitly documented as a handoff pointer; the server does not assume it can read that path. |
| Untrusted MCP tool args | Caller invokes a deprecated or experimental tool expecting stable behavior | `server_info` returns `stability_tier_map` and `deprecated_tools`; integrators MUST refuse to call anything not in `stable_tools` if they require API-stability guarantees. |
| Untrusted external HTTP responses (literature retrieval, KG calls) | Malformed responses trigger parse errors or resource exhaustion | `services/shared/retry_timeout.py` enforces retry/timeout budgets; `cli/utils/http_client.py` (`br.http`) caps payload sizes and times out by default. |
| Tool execution side-channel | `tool_execute` / `pipeline_execute` running attacker-supplied commands | Disabled by default (`ENABLE_TOOL_EXECUTE=false`). When enabled, only the names in `TOOL_EXECUTE_ALLOWLIST` are dispatchable. |
| Log leakage of caller-provided paths or credentials | Logs persist host filesystem layout or API keys | `services/shared/log_scrubber.py` (`br.redaction`) scrubs known credential patterns from log output. **Known gap**: it does not currently redact absolute `/home/<user>/` paths; the `disclose_paths` gate on `server_info` is the public-mode escape hatch. See `REDACTION_POLICY.md`. |
| Network egress from KG/LLM helpers | Outbound traffic to attacker-controlled endpoints | Configured via `BR_MODEL_API_BASE` env var; `allow_network` flag on `server_info` reports whether net access is enabled. |
| Contract drift | Server upgrade silently changes a stable-tier tool's shape | `toolset_hash` in `server_info` changes when any stable-tier schema changes; `contracts/VERSION` bumps for breaking changes. Adapters refuse to dispatch on version mismatch. |

## Out of scope for v0.1.0

- Multi-tenant isolation. The server assumes one tenant per process.
- Network-level authentication. Use a fronting proxy if you need AuthN/AuthZ.
- Sandboxed code execution. Tool execution runs in the host process; use container isolation upstream.
- Supply-chain attestation of the LLM endpoints reachable via LiteLLM.

## Reporting

See `SECURITY.md` for the disclosure process. Threat-model gaps that are *not* vulnerabilities (e.g. "the scrubber doesn't cover paths") should be filed as issues, not vulnerability reports, unless they enable a concrete exploit.
