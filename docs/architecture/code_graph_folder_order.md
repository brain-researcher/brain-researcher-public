# Code Graph Folder Order

Date: 2026-05-27

This note records a dependency-aware folder order for `src/brain_researcher`.
It is based on static imports of `brain_researcher.*` modules, grouped by the
first package segment under `src/brain_researcher`.

This is a navigation and reorganization guide, not a statement that the source
tree has already been physically moved. A physical directory refactor should
only happen after the cycles below are broken and import compatibility is
validated.

## Method

- Parsed Python files under `src/brain_researcher`.
- Counted internal imports from one top-level package area to another.
- Collapsed strongly connected components before deriving a dependency-first
  order.
- Repeated the same check for `services/*` and `core/*` subpackages.

## Current Top-Level Graph

Top-level package areas by file and import counts:

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

`llmcore` was removed 2026-05-27: `router.py` and `metrics_emitter.py` moved into `services/agent/` (as `router.py` and `llm_metrics_emitter.py`). The whole `llmcore` package is gone; the `llmcore → services: 11` boundary edge is therefore eliminated structurally rather than refactored away.

The remaining top-level cycle is:

```text
autoresearch, behavior, research, services
```

The cycle is driven mostly by reverse imports such as:

- `core -> services`: 0 imports
- `services -> core`: 315 imports
- `services -> behavior`: 9 imports
- `behavior -> services`: 3 imports
- `research -> services`: 4 imports

Because of the remaining cycle, a strict physical folder order is not currently
enforceable without more refactoring. The former `core -> services` edge is now
held at zero by `tests/architecture/core_services_import_baseline.txt`.

## Recommended Navigation Order

Use this order in docs, review checklists, and architecture diagrams:

1. `config`
   Runtime settings, path helpers, and configuration contracts.

2. `assets`, `data`, `infrastructure`
   Static package resources and packaged infrastructure helpers. Runtime data
   should remain outside source code under repo-level `data/`.

3. `semantics`
   Taxonomy and semantic normalization rules.

4. `core`
   Domain contracts, ingestion, analysis, literature, KG primitives, memory,
   and multiverse support.

5. `neurocore`
   Low-level neuroscience primitives. This is currently small and isolated.

6. `integrations`
   Notebook, Jupyter, marimo, and other host integration adapters.

7. `services`
   Runtime service surfaces: agent (including the LLM router and metrics
   emitter), MCP, BR-KG, tools, orchestrator, review, memory, telemetry,
   feedback, and gateways.

8. `research`, `autoresearch`, `behavior`
   Higher-level research loops and behavior task workflows. These currently
   participate in the main cycle and should be isolated behind service or core
   contracts before moving.

9. `sdk`, `cli`
   User-facing entrypoints. These should stay at the top of the dependency
   stack and depend inward on services/contracts.

10. `legacy`
    Historical compatibility surfaces. Keep separate from the active stack.

## Core Subpackage Order

`core/*` has no internal cycles in the static import graph. Use this order:

1. `core/contracts`
2. `core/analysis`
3. `core/data`
4. `core/ingestion`
5. `core/kg`
6. `core/memory`
7. `core/multiverse`
8. root-level `core/*.py`
9. `core/gates`
10. `core/datasets`
11. `core/literature`
12. `core/utils`

Current cross-core imports are sparse. The largest are:

- `core/analysis_bundle -> core/contracts`: 6 imports
- `core/gates -> core/contracts`: 2 imports
- `core/reproducibility -> core/contracts`: 2 imports
- `core/analysis -> core/utils`: 1 import
- `core/datasets -> core/ingestion`: 1 import
- `core/literature -> core/ingestion`: 1 import
- `core/utils -> core/kg`: 1 import

## Services Subpackage Order

`services/*` has a large internal cycle:

```text
agent, mcp, memory, neurokg, orchestrator, review, shared, telemetry, tools
```

The target order after cycle-breaking should be:

1. `services/shared`
2. `services/telemetry`
3. `services/memory`
4. `services/review`
5. `services/neurokg`
6. `services/tools`
7. `services/orchestrator`
8. `services/agent`
9. `services/mcp`
10. `services/communication`
11. `services/feedback`
12. `services/knowledge`
13. `services/llm_gateway`
14. `services/model`
15. `services/virtual_brain`
16. `services/api_gateway`

This is the intended architecture order, not the current topological order.
The current graph cannot produce a clean order because `agent`, `tools`,
`neurokg`, `orchestrator`, and `mcp` import each other.

## Physical Reorganization Plan

Do not move directories yet. Use this sequence first:

1. Keep `core -> services` at zero.
   The direct imports were removed by moving generic cache support into `core`
   and replacing core service lookups with explicit resolver/callback inputs.
   Keep the architecture ratchet active so lower-level core modules do not
   depend on concrete runtime services again.

2. ~~Break `llmcore -> services`.~~ **Done 2026-05-27** by removing the
   `llmcore` package: `router.py` and `metrics_emitter.py` moved into
   `services/agent/`. No new boundary policy is needed because the boundary
   no longer exists. The `services/agent/router.py` location now reflects
   where the maintenance has always lived.

3. Break `behavior/research/autoresearch -> services` where those imports are
   merely execution conveniences.
   Keep reusable domain logic under `core` or `behavior`; keep runtime
   execution under `services`.

4. Break the `services` internal cycle.
   The desired direction is:

   ```text
   shared -> telemetry/memory/review/neurokg -> tools -> orchestrator -> agent -> mcp/api_gateway
   ```

   In dependency terms, higher layers may import lower layers. Lower layers
   should not import higher layers.

5. Add import-boundary tests.
   Once the cycles are broken, add a small static import test that fails if
   lower layers import higher layers again.

6. Only then move or rename directories.
   Use compatibility shims and focused tests for each move. Avoid a single
   repo-wide path rewrite.

## Practical Folder Display Order

For README trees and architecture diagrams, use this repo-level order:

1. `src/brain_researcher/`
2. `apps/`
3. `packages/`
4. `tests/`
5. `scripts/`
6. `configs/`
7. `docs/`
8. `docs/specs/`
9. `benchmarks/`
10. `infrastructure/`
11. `skills/`
12. `data/`
13. `external/`
14. `backups/`
15. `archive/`

This keeps source and entrypoints first, validation next, operational config and
docs after that, and large runtime or historical state at the end.
