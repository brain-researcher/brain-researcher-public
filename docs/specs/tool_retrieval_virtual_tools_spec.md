# Tool Retrieval Virtual-Tools Spec

## Summary

This spec defines the next retrieval architecture for Brain Researcher tool
selection.

The goal is to stop treating retrieval as direct ranking over a large flat list
of tools. Instead, retrieval should:

- expose a small default set of family-level "virtual tools"
- route queries into the most relevant families first
- score tools and workflows inside a single shared corpus
- keep naming, discoverability, and executability as separate concerns

This design follows the same product lesson described in GitHub Copilot's
"smarter with fewer tools" writeup: smaller default decision surfaces improve
latency, tool-use reliability, and model reasoning quality.

## Problem

Today retrieval quality is shaped by multiple overlapping systems:

- [registry.py](<repo>/src/brain_researcher/services/tools/registry.py)
  ranks `ToolSpec` entries with one heuristic scorer
- [server.py](<repo>/src/brain_researcher/services/mcp/server.py)
  reranks MCP tool cards with a second scorer and mixes workflows late
- [tool_retriever.py](<repo>/src/brain_researcher/services/agent/tool_retriever.py)
  uses BR-KG structured search with a third retrieval path

That creates three problems:

- the same query can rank differently across MCP, planner, and chat
- workflow/tool mixing is late and brittle
- `exposed_only`, `agent_visible`, and actual executability are entangled

## Goals

- Use one retrieval contract across MCP, planner, and chat
- Make family-level routing the default retrieval surface
- Keep canonical runtime tool IDs as the only public tool IDs
- Score tools and workflows in one shared candidate universe
- Separate policy into three axes:
  - `discoverable`
  - `agent_visible`
  - `executable`
- Support both lexical and embedding-guided routing
- Improve benchmark stability for broad natural-language queries

## Non-Goals

- Replace all heuristics with a learned retriever immediately
- Remove all compatibility aliases in the same change
- Change execution recipes or runtime resolution semantics
- Replace BR-KG structured search for all use cases on day one

## Retrieval Model

Retrieval becomes a two-stage process:

1. Stage 1: route to family cards
- Query is scored against a small set of family-level entries
- Return top `k_family` family cards

2. Stage 2: expand and rank members
- Expand tools and workflows from the selected families
- Score all expanded entries in one shared scorer
- Return top `k_candidates`

This is the default path for natural-language queries.

There is one exception:

- explicit canonical tool references like `fsl_bet` or `ants_registration`
  bypass family routing and resolve directly into the shared candidate universe

## Retrieval Index

The retrieval index is the shared corpus for MCP, planner, and chat.

Each row is one of:

- `family_card`
- `tool`
- `workflow`

Each row has retrieval metadata plus policy metadata.

### Python shape

```python
from dataclasses import dataclass, field
from typing import Any, Literal

EntryType = Literal["family_card", "tool", "workflow"]

@dataclass(slots=True)
class RetrievalIndexRow:
    entry_id: str
    entry_type: EntryType
    canonical_id: str
    family_id: str | None
    title: str
    summary: str
    search_text: str
    aliases: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    modalities: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    software: str | None = None
    module_name: str | None = None
    command_name: str | None = None
    implementation_level: str | None = None
    requires_runtime: bool | None = None
    surface_tier: str | None = None
    discoverable: bool = True
    agent_visible: bool = True
    executable: bool = True
    is_default_entry: bool = True
    embedding_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### Field semantics

- `entry_id`
  - stable retrieval row ID
  - examples: `family:registration`, `tool:fsl_bet`,
    `workflow:workflow_seed_based_connectivity`
- `canonical_id`
  - public ID emitted to planner/MCP/UI
  - must follow [canonical_runtime_tool_ids.md](<repo>/docs/specs/canonical_runtime_tool_ids.md)
- `family_id`
  - required for `tool` and `workflow`
  - equals the owning virtual-tool family
- `search_text`
  - preassembled normalized text used by lexical scoring
  - should include title, summary, aliases, tags, software, module, command, and
    domain phrases
- `discoverable`
  - eligible for search/discovery results
- `agent_visible`
  - eligible for default agent tool exposure
- `executable`
  - can be executed in at least one supported runtime, subject to runtime
    availability

### Sources of truth

- family definitions: [tool_families.yaml](<repo>/configs/catalog/tool_families.yaml)
- exposed policy: [exposed_tools.yaml](<repo>/configs/catalog/exposed_tools.yaml)
- canonical tool IDs: [canonical_runtime_tool_ids.md](<repo>/docs/specs/canonical_runtime_tool_ids.md)
- runtime metadata: Neurodesk package/module profiles and execution recipe config

### Index construction rules

- tools and workflows live in the same index
- workflow rows are not appended after retrieval; they are indexed up front
- aliases are stored only as retrieval hints, never as output IDs
- family membership is explicit, not inferred at query time
- search policy is applied by filtering rows, not by maintaining separate
  retrieval codepaths

## Family-Card Schema

Family cards are Brain Researcher virtual tools.

They are the default retrieval surface for broad natural-language queries.

### Canonical schema

```yaml
id: registration
type: family_card
title: Registration
summary: Linear and nonlinear alignment of structural or functional images.
when_to_use:
  - Align subject images into common space
  - Register anatomy to functional or template space
  - Run affine or nonlinear registration
canonical_entrypoints:
  - ants_registration
  - fsl_flirt
  - fsl_fnirt
related_workflows:
  - workflow_structural_preproc
tags:
  - registration
  - alignment
  - affine
  - nonlinear
modalities:
  - fmri
  - smri
  - dmri
discoverable: true
agent_visible: true
default_expand_limit: 8
```

### Required fields

- `id`
- `type=family_card`
- `title`
- `summary`
- `canonical_entrypoints`
- `tags`
- `discoverable`
- `agent_visible`

### Optional fields

- `when_to_use`
- `related_workflows`
- `modalities`
- `categories`
- `default_expand_limit`
- `negative_hints`
  - phrases that should de-prioritize the family

### Family-card behavior

- A family card is never directly executable
- A family card may be returned as a discovery result
- A family card may be expanded into tools/workflows
- A family card should be explainable in UI and traces

### Initial family set

The first implementation should use the existing curated families, not dynamic
clustering.

Recommended top-level families:

- `brain_extraction`
- `registration`
- `segmentation`
- `surface_reconstruction`
- `connectivity`
- `task_glm`
- `decoding`
- `quality_control`
- `visualization`
- `dataset_ops`
- `workflow_orchestration`

## Single Scorer API

All retrieval surfaces should call the same scorer.

That means MCP `tool_search`, planner retrieval, and chat retrieval should stop
owning separate ranking logic.

### API shape

```python
from dataclasses import dataclass, field
from typing import Literal

RetrievalMode = Literal["family", "expanded", "direct"]

@dataclass(slots=True)
class RetrievalRequest:
    query: str
    mode: RetrievalMode = "family"
    limit: int = 20
    offset: int = 0
    modalities: list[str] = field(default_factory=list)
    kind_filters: list[str] = field(default_factory=list)
    family_ids: list[str] = field(default_factory=list)
    discoverable_only: bool = True
    agent_visible_only: bool = False
    executable_only: bool = False
    include_workflows: bool = True
    include_families: bool = True
    explicit_tool_ids: list[str] = field(default_factory=list)

@dataclass(slots=True)
class RetrievalMatch:
    entry_id: str
    canonical_id: str
    entry_type: str
    family_id: str | None
    score: float
    matched_terms: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

@dataclass(slots=True)
class RetrievalResponse:
    query: str
    mode: RetrievalMode
    total_matches: int
    matches: list[RetrievalMatch]
    selected_family_ids: list[str] = field(default_factory=list)
```

### Public methods

```python
class UnifiedToolRetriever(Protocol):
    def search(self, request: RetrievalRequest) -> RetrievalResponse: ...
    def route_families(self, request: RetrievalRequest) -> RetrievalResponse: ...
    def expand_families(self, request: RetrievalRequest) -> RetrievalResponse: ...
```

### Scoring contract

The scorer should compute one score for all row types.

Base signals:

- exact canonical ID match
- alias match
- normalized phrase match
- token coverage
- family/tag/category overlap
- modality overlap
- software/module/command overlap
- embedding similarity

Policy is not part of score math.
Policy is a filter applied before ranking.

### Explainability

Every match should carry sparse reasons such as:

- `exact_canonical_match`
- `family_tag_match`
- `command_name_match`
- `high_token_coverage`
- `embedding_family_hit`

This replaces the current opaque mix of per-layer heuristics.

## Retrieval Policies

This spec formalizes three separate policy axes:

- `discoverable`
  - whether an entry is searchable
- `agent_visible`
  - whether an entry is shown in the default agent surface
- `executable`
  - whether the entry can be executed in principle

Examples:

- a family card:
  - `discoverable=true`
  - `agent_visible=true`
  - `executable=false`
- a long-tail tool:
  - `discoverable=true`
  - `agent_visible=false`
  - `executable=true`
- a compatibility alias:
  - not indexed as its own row
  - only used inside `aliases`

## Query Flows

### Natural-language discovery query

Query: `brain age prediction`

1. score query against family cards
2. pick top families, for example `brain_age`, `decoding`, `workflow_orchestration`
3. expand those families into tools and workflows
4. rescore on the unified candidate set
5. return top matches

### Explicit tool reference

Query: `use fsl_bet for skull stripping`

1. detect explicit canonical tool reference
2. pull `tool:fsl_bet` directly into candidate set
3. optionally expand its family for alternates
4. return direct tool match first

## Migration Plan

### Phase 1

- Build retrieval index rows for `tool`, `workflow`, and `family_card`
- Keep current MCP and planner APIs unchanged
- Add a new internal unified retriever module

### Phase 2

- Switch MCP `tool_search` to the unified retriever
- Stop MCP-side workflow append-and-rerank

### Phase 3

- Switch planner/chat retrieval to the same unified retriever
- Reduce direct dependence on separate `query_service.search_tools_structured()`
  for ordinary tool retrieval

### Phase 4

- Add embedding-guided family routing
- Then consider larger alias cleanup

## Benchmark Contract

The benchmark suite should evolve from "top-1 tool" only into a layered
coverage contract.

### Required metrics

- `family_top1_hit`
- `family_top3_hit`
- `tool_top1_hit`
- `tool_top3_hit`
- `workflow_top3_hit` where appropriate

### Query classes

- exact tool phrasing
- broad natural-language phrasing
- method phrasing
- workflow phrasing
- explicit canonical tool IDs

### Must-have regression cases

Based on current weak queries:

- `brain age prediction`
- `searchlight decoding`

These should remain red until the unified retriever turns them green.

## Acceptance Criteria

- MCP, planner, and chat share one retrieval implementation
- workflow rows are retrieved from the same corpus as tools
- family cards are the default discovery surface for broad queries
- canonical runtime names remain the only public tool IDs
- policy filtering is explicit and separate from ranking
- the current broad-query benchmark failures turn green without adding more
  one-off special cases
