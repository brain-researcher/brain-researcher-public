# BR-KG Node Embeddings (text_v1) — Spec v1.0 (Engineering)

Last updated: 2026-01-05

## 0. Summary

Standardize “node embeddings” as a first-class capability for:
- **A) Semantic recall** (bridge natural language ↔ KG terminology)
- **B) Similar nodes** (explore/expand from a selected node)
- **D) Filter + rank** (Neo4j structural filter, then embedding-based rerank)

Primary design choice: **Neo4j is SSOT** and hosts the canonical embedding vectors + vector index.

---

## 1. Goals and Scope

**Goals**
- Provide a stable embedding space `text_v1` for P0 node types.
- Ensure embeddings are reproducible (model/template/index versioning).
- Support query-time filters and “similar nodes” exploration.
- Keep rebuild/admin operations protected from agent invocation.

**Non-Goals**
- Replacing fulltext/BM25 recall (embeddings supplement recall and ranking).
- Mixing NiCLIP embeddings into the default search space (NiCLIP is a separate space for linking/specialized tasks).
- Publication embeddings as a P0 requirement (GFS/Deep Research cover literature retrieval first).

---

## 2. Coverage (Phased)

**P0 node types**
- `Task`, `TaskDef`, `TaskSpec`
- `Concept` / `Construct` (e.g., `CognitiveConstruct`)
- `Tool`, `ToolFamily` (if present in the KG)

**P1**
- `Dataset`

**P2 (optional)**
- `Region` / `BrainRegion` (only if product needs region search/similarity)

**Defer**
- `Publication` (use GFS/Deep Research first)

---

## 3. Embedding Spaces

### 3.1 `text_v1` (default)
Used by hybrid retrieval for recall/rerank.

Required metadata per embedding:
- `index_version` (e.g., `kg_text_v1`)
- `model` (e.g., `text-embedding-XXX`)
- `dimension` (e.g., 1536; must match Neo4j vector index config)
- `template_version` (e.g., `node_text_v1`)
- `updated_at` (UTC ISO-8601)

### 3.2 `niclip_v1` (optional)
Separate space for cross-source alignment / brain-text tasks; not default for search.

---

## 4. Text Template (Versioned)

**Base template (`node_text_v1`)**
- `name/label`
- `aliases/synonyms`
- `short_description` (or selected description fields)

**Node-type additions (MVP)**
- Task/TaskSpec: `task_family`, contrast keywords, modality keywords
- Tool: key phrases (confounds/smoothing/ICA-AROMA/etc.)
- Dataset: title + tasks + modalities + key stats (n_subjects, source)

All templates MUST be versioned (`template_version`) to enable re-embedding and rollback.

---

## 5. Storage and Indexing (Neo4j SSOT)

### 5.1 Node properties (recommended)
Store the vector under a stable property key (examples):
- `embedding_text_v1: List[float]` (or Neo4j vector type)
- `embedding_text_v1_model`, `embedding_text_v1_dim`, `embedding_text_v1_updated_at`

### 5.2 Vector index
Create Neo4j vector indices for the relevant labels (can be one combined index or per-label indices).

Index config MUST match:
- `dimension` for `text_v1`
- similarity function (cosine recommended for normalized embeddings)

---

## 6. Update Strategy

**Default**
- Incremental updates after ingestion (update only changed nodes).
- Periodic full calibration (weekly/monthly) for drift cleanup and missed nodes.

Version tracking:
- `index_version` and `template_version` MUST be returned in API responses.

---

## 7. Interfaces

### 7.1 HTTP (preferred)
- `POST /api/vector/search`
- `GET /api/vector/similar/<node_type>/<node_id>`
- `GET /api/vector/stats`

### 7.2 Internal API
- `query_service.vector_search(...)` and `query_service.similar_nodes(...)`

### 7.3 Access control
- Agent: search/similar/stats only.
- Rebuild/reindex: admin/pipeline only.

---

## 8. DoD (Minimum Acceptance)

For a query like:
> “movement artifacts resting-state fMRI recommended confounds fmriprep”

The vector search layer returns:
- topK results (>=10),
- supports `node_types` filter,
- includes metadata: `index_version/model/dimension/template_version/updated_at`.

---
