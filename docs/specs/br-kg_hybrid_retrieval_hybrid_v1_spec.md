# BR-KG Hybrid Retrieval (`hybrid_v1`) — Spec v1.0 (Engineering)

Last updated: 2026-01-05

## 0. Summary

Define a single, stable retrieval entrypoint that composes:
- Neo4j fulltext recall (term/alias precision)
- Node embeddings (`text_v1`) recall/rerank (natural language bridge)
- GFS evidence boost (traceable snippets; bounded; policy-triggered)

Primary contract: `POST /api/search` with `mode="hybrid_v1"`.

---

## 1. Goals and Scope

**Goals**
- A single query interface that supports:
  - semantic recall,
  - similar-node exploration (via vector endpoints),
  - filter+rank (Neo4j filter then embedding rank),
  - evidence attachment and explainable scoring breakdown (opt-in).
- Keep GFS as **evidence boost**, not the primary recall engine.
- Provide deterministic caching via `idempotency_key`.

**Non-Goals**
- Removing legacy search modes immediately (keep compatibility window).
- Allowing request-side arbitrary tuning in production (weights are internal/debug-only).

---

## 2. Endpoint Contract (MVP)

### 2.1 Request
```json
{
  "mode": "hybrid_v1",
  "query": "string",
  "node_types": ["Task", "TaskDef", "TaskSpec", "Concept", "Tool", "Dataset"],
  "filters": {},
  "limit": 20,
  "include_explain": false
}
```

Optional (internal/debug only):
```json
{
  "weights": {
    "w_fulltext": 0.6,
    "w_vector": 0.4,
    "w_gfs_boost": 0.25
  }
}
```

### 2.2 Response (two-tier)
- Always return `explain_min` (compact).
- Return `explain_full` only when `include_explain=true`.

---

## 3. Pipeline (MVP)

### 3.1 Candidate generation strategy

**Case A: filters present (Filter + Rank)**
1) Neo4j filter produces candidate set capped at:
   - `filtered_cap = 500`
2) Embedding rank within filtered candidates.
3) (Optional) fulltext within filtered set for extra precision.

**Case B: no filters (Union + Rerank)**
1) Fulltext recall: `fulltext_k = 60`
2) Vector recall: `vector_k = 60`
3) Union candidates → rerank.

### 3.2 Base scoring (before evidence)
Normalize scores to 0–1, then:
- `base = 0.60 * norm_fulltext + 0.40 * norm_vector`

### 3.3 GFS evidence boost (bounded)
GFS is *not always on*. It runs when policy triggers (see below), and:
- binds evidence only for the top 20–30 candidates post-rerank,
- attaches up to 2 evidence snippets per result,
- adds:
  - `final = base + 0.25 * norm_gfs_boost`

### 3.4 GFS trigger rules (MVP)
Default: off. Turn on if any:
1) explicit evidence intent (“cite/出处/推荐/according to”)
2) `include_explain=true`
3) weak base retrieval (e.g. `topK < 5` or `max(base_score) < 0.45`)

### 3.5 Confidence and conflicts (integration point)
If `confidence` exists for relevant edges/nodes:
- apply: `final_score = final * (0.5 + 0.5 * confidence)`

Tooling/guideline conflicts may further discount confidence (see TODO#6 spec).

---

## 4. Defaults and Limits (MVP)

| Parameter | Default |
|---|---:|
| `filtered_cap` | 500 |
| `fulltext_k` | 60 |
| `vector_k` | 60 |
| `limit` | 20 |
| `max_nodes_for_evidence_binding` | 20–30 |
| `max_evidence_per_result` | 2 |
| `w_fulltext` | 0.60 |
| `w_vector` | 0.40 |
| `w_gfs_boost` | 0.25 |

---

## 5. Output Schema (MVP)

### 5.1 Result item (default)
```json
{
  "id": "string",
  "type": "string",
  "score": 0.0,
  "confidence": 0.0,
  "evidence_status": "ok|partial|none|unconfigured|error",
  "evidence": [
    { "evidence_id": "ev1", "doc_id": "...", "title": "...", "snippet": "...", "doc_role": "tooling_spec", "polarity": "neutral" }
  ],
  "explain_min": {
    "reason_codes": ["RECALL_FULLTEXT_HIT", "RECALL_VECTOR_HIT"],
    "retrieval_trace_summary": "hybrid(fulltext+vector)->rerank; gfs=off",
    "filters_matched": [],
    "mapsto_path": null,
    "evidence_refs": ["ev1"]
  }
}
```

### 5.2 Explain mode additions (`include_explain=true`)
```json
{
  "explain_full": {
    "score_breakdown": { "fulltext": 0.0, "vector": 0.0, "gfs_boost": 0.0 },
    "retrieval_trace_full": { "fulltext_k": 60, "vector_k": 60, "filtered_cap": 500 },
    "filtered_out_summary": { "after_node_type_filter": 0, "after_structured_filter": 0, "after_rank_cut": 0 },
    "conflict_flags": []
  }
}
```

---

## 6. Caching and Degradation

### 6.1 Cache (recommended)
Cache results by:
`hash(mode + query + node_types + filters + limit + include_explain + index_version)`

TTL: **1 hour** (MVP).

### 6.2 Degradation rules (MVP)
- Vector unavailable → fulltext-only (+ optional GFS).
- Fulltext unavailable → vector-only (+ optional GFS).
- GFS unavailable → return results with `evidence_status!=ok`.

Return `degraded: []` with reason codes when applicable.

---

## 7. DoD (Minimum Acceptance)

- One stable entrypoint (`/api/search`, `mode=hybrid_v1`) supports filters and node_types.
- `include_explain=false` returns compact explain; `include_explain=true` returns breakdown.
- GFS is bounded (1 call) and policy-triggered.
- Cache is deterministic and prevents repeated expensive calls.

---
