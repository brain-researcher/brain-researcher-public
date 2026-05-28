# Code Import Graph Snapshot

Generated: 2026-05-27T18:55:33Z

Package: `brain_researcher`
Source root: `src/brain_researcher`

This is a static import graph over Python source files. It is a
navigation and boundary-checking artifact; it does not imply that
directories have been moved or that runtime services were exercised.

## Top-Level Package Areas

| Area | Python files | Imports out | Imports in |
| --- | ---: | ---: | ---: |
| `(root)` | 1 | 0 | 1 |
| `autoresearch` | 9 | 1 | 5 |
| `behavior` | 10 | 6 | 9 |
| `cli` | 50 | 84 | 0 |
| `config` | 7 | 0 | 112 |
| `core` | 204 | 6 | 330 |
| `infrastructure` | 17 | 0 | 0 |
| `integrations` | 15 | 3 | 2 |
| `legacy` | 23 | 22 | 0 |
| `neurocore` | 1 | 0 | 0 |
| `research` | 20 | 10 | 1 |
| `sdk` | 6 | 1 | 0 |
| `semantics` | 3 | 0 | 9 |
| `services` | 1161 | 433 | 97 |

### Largest Cross-Area Imports

| Source | Target | Imports |
| --- | --- | ---: |
| `services` | `core` | 315 |
| `services` | `config` | 99 |
| `cli` | `services` | 68 |
| `legacy` | `services` | 20 |
| `cli` | `config` | 9 |
| `services` | `behavior` | 9 |
| `cli` | `core` | 6 |
| `services` | `semantics` | 5 |
| `research` | `services` | 4 |
| `behavior` | `services` | 3 |
| `core` | `config` | 3 |
| `core` | `semantics` | 3 |
| `integrations` | `core` | 3 |
| `research` | `autoresearch` | 3 |
| `research` | `core` | 3 |
| `behavior` | `core` | 2 |
| `services` | `autoresearch` | 2 |
| `services` | `integrations` | 2 |
| `autoresearch` | `services` | 1 |
| `behavior` | `semantics` | 1 |

### Cycles

- `autoresearch` -> `behavior` -> `research` -> `services`

## `core/*` Subpackage Areas

| Area | Python files | Imports out | Imports in |
| --- | ---: | ---: | ---: |
| `core/(root)` | 1 | 0 | 0 |
| `core/analysis` | 13 | 1 | 0 |
| `core/analysis_bundle` | 1 | 8 | 0 |
| `core/analysis_manifest` | 1 | 1 | 0 |
| `core/artifact_checksums` | 1 | 0 | 4 |
| `core/artifact_manifest` | 1 | 1 | 0 |
| `core/artifact_validator` | 1 | 1 | 1 |
| `core/contracts` | 36 | 1 | 14 |
| `core/datasets` | 4 | 1 | 0 |
| `core/diagnostics_summary` | 1 | 0 | 0 |
| `core/environment_runner` | 1 | 1 | 0 |
| `core/epistemic_policy` | 1 | 1 | 0 |
| `core/execution_manifest` | 1 | 1 | 1 |
| `core/gates` | 2 | 2 | 0 |
| `core/grounding_references` | 1 | 0 | 2 |
| `core/ingestion` | 98 | 0 | 2 |
| `core/inputs_manifest` | 1 | 1 | 0 |
| `core/kg` | 15 | 0 | 1 |
| `core/literature` | 4 | 2 | 0 |
| `core/memory` | 3 | 0 | 0 |
| `core/multiverse` | 3 | 0 | 0 |
| `core/package_resolver` | 1 | 0 | 1 |
| `core/provenance` | 1 | 0 | 0 |
| `core/quote_grounded` | 1 | 2 | 0 |
| `core/reproducibility` | 1 | 2 | 0 |
| `core/utils` | 10 | 1 | 1 |

### Largest Cross-Area Imports

| Source | Target | Imports |
| --- | --- | ---: |
| `core/analysis_bundle` | `core/contracts` | 6 |
| `core/gates` | `core/contracts` | 2 |
| `core/reproducibility` | `core/contracts` | 2 |
| `core/analysis` | `core/utils` | 1 |
| `core/analysis_bundle` | `core/artifact_checksums` | 1 |
| `core/analysis_bundle` | `core/execution_manifest` | 1 |
| `core/analysis_manifest` | `core/artifact_checksums` | 1 |
| `core/artifact_manifest` | `core/artifact_checksums` | 1 |
| `core/artifact_validator` | `core/contracts` | 1 |
| `core/contracts` | `core/artifact_validator` | 1 |
| `core/datasets` | `core/ingestion` | 1 |
| `core/environment_runner` | `core/package_resolver` | 1 |
| `core/epistemic_policy` | `core/contracts` | 1 |
| `core/execution_manifest` | `core/contracts` | 1 |
| `core/inputs_manifest` | `core/artifact_checksums` | 1 |
| `core/literature` | `core/grounding_references` | 1 |
| `core/literature` | `core/ingestion` | 1 |
| `core/quote_grounded` | `core/contracts` | 1 |
| `core/quote_grounded` | `core/grounding_references` | 1 |
| `core/utils` | `core/kg` | 1 |

### Cycles

- `core/artifact_validator` -> `core/contracts`

## `services/*` Subpackage Areas

| Area | Python files | Imports out | Imports in |
| --- | ---: | ---: | ---: |
| `services/agent` | 263 | 159 | 132 |
| `services/api_gateway` | 1 | 0 | 0 |
| `services/communication` | 10 | 1 | 0 |
| `services/feedback` | 5 | 0 | 6 |
| `services/knowledge` | 11 | 9 | 0 |
| `services/llm_gateway` | 2 | 2 | 0 |
| `services/mcp` | 8 | 92 | 17 |
| `services/memory` | 5 | 1 | 10 |
| `services/model` | 1 | 2 | 0 |
| `services/neurokg` | 316 | 27 | 86 |
| `services/orchestrator` | 152 | 110 | 28 |
| `services/review` | 42 | 17 | 28 |
| `services/shared` | 15 | 1 | 61 |
| `services/telemetry` | 14 | 1 | 7 |
| `services/tools` | 311 | 80 | 129 |
| `services/virtual_brain` | 5 | 2 | 0 |

### Largest Cross-Area Imports

| Source | Target | Imports |
| --- | --- | ---: |
| `services/agent` | `services/tools` | 88 |
| `services/orchestrator` | `services/agent` | 66 |
| `services/tools` | `services/agent` | 32 |
| `services/tools` | `services/neurokg` | 28 |
| `services/agent` | `services/shared` | 26 |
| `services/orchestrator` | `services/shared` | 23 |
| `services/mcp` | `services/agent` | 22 |
| `services/mcp` | `services/review` | 21 |
| `services/mcp` | `services/tools` | 20 |
| `services/agent` | `services/neurokg` | 19 |
| `services/mcp` | `services/neurokg` | 19 |
| `services/agent` | `services/orchestrator` | 13 |
| `services/neurokg` | `services/tools` | 12 |
| `services/tools` | `services/orchestrator` | 11 |
| `services/review` | `services/neurokg` | 9 |
| `services/agent` | `services/mcp` | 7 |
| `services/knowledge` | `services/neurokg` | 7 |
| `services/neurokg` | `services/agent` | 7 |
| `services/orchestrator` | `services/tools` | 7 |
| `services/mcp` | `services/shared` | 6 |

### Cycles

- `services/agent` -> `services/mcp` -> `services/memory` -> `services/neurokg` -> `services/orchestrator` -> `services/review` -> `services/shared` -> `services/telemetry` -> `services/tools`

## Boundary Checks

### `core` -> `services`

Current imports: 0

### `llmcore` -> `services`

Current imports: 0
