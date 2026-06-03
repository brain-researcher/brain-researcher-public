# BR-KG GFS Auto Retrieval — Spec v1.0 (Engineering)

Last updated: 2026-01-05

## 0. Summary

Define when and how the system automatically calls Google File Search (GFS) to attach traceable, bounded evidence to:
- user-facing answers (agent)
- `/api/search` results (BR-KG evidence layer)
- optional tool discovery enrichment (ToolRetriever)

This spec focuses on *query-only* usage (no automatic store/file mutation).

---

## 1. Goals and Scope

**Goals**
- Add a default “auto GFS” policy with hard cost/latency bounds (1 call per request).
- Make evidence *traceable* (doc_id/title/snippet) and reusable by downstream explainability.
- Support three call sites:
  - **A)** General chat agent (answer grounding)
  - **C)** BR-KG Search Orchestrator (`/api/search` evidence binding)
  - **B)** ToolRetriever (optional; best-effort)

**Non-Goals**
- Auto-upload/auto-delete/auto-create stores (mutating ops remain explicit/admin-only).
- Replacing KG recall (fulltext/aliases remain primary for symbolic recall).
- Deep research / Google Search grounding (covered by a separate spec).

---

## 2. Configuration (Defaults)

**Store**
- Default store comes from `.env`: `FILE_SEARCH_STORE` (SSOT).

**Query budget defaults (MVP)**
- `top_k_docs`: **10** (default; must be overridable per-request)
- `max_snippets_per_doc`: **2**
- `snippet_max_chars`: **300**
- `max_gfs_calls_per_request`: **1**

**Safety**
- Only query operations are allowed under auto-policy.

---

## 3. Trigger Policy

### 3.1 Explicit trigger (strong)
Always run GFS when the user explicitly requests evidence/authority, e.g.:
- “cite / citation / evidence / source / official / guideline / best practice / recommended”
- “给出处 / 引用 / 证据 / 官方文档 / 标准 / 指南 / 最佳实践”

### 3.2 Automatic trigger (weak)
Run GFS only when at least one of the following is true:
- **Uncertainty / conflict** detected upstream (see TODO#6 conflict flags).
- **High-risk correctness**: versions, specs, policies, API behavior likely to change.
- **Authority needed**: “best practice / recommended / guideline” intent.
- **Retrieval is weak**:
  - KG results are empty or very small (`<3`) and the query is not an exact ID lookup.
  - Orchestrator evidence coverage is poor (e.g. many top candidates have `evidence_status != ok`).

### 3.3 Do-not-trigger (hard exclusions)
Do *not* auto-run GFS when:
- Query is a pure ID lookup (dataset/node IDs) and the user did not ask for recommendations/evidence.
- User explicitly requests *no literature/no GFS*.

---

## 4. Execution (Query-only)

### 4.1 Call shape
Auto GFS performs:
1) Build `query_used` (raw query; optional light rewrite only if needed).
2) Perform **exactly one** GFS query against `FILE_SEARCH_STORE`.
3) Normalize/shape hits into `evidence[]` items with bounded payload size.

### 4.2 Evidence shaping rules (MVP)
- Group by `doc_id` when available.
- For each document keep at most `max_snippets_per_doc` snippets.
- Truncate snippet to `snippet_max_chars`.
- Return doc identifiers and minimal metadata needed for traceability.

---

## 5. Output Contracts

### 5.1 GFS meta envelope
Returned on calls that run GFS:

```json
{
  "gfs": {
    "status": "ok|partial|none|unconfigured|quota_exhausted|error",
    "stores_hit": ["fileSearchStores/..."],
    "query_used": "string",
    "n_docs_hit": 10
  }
}
```

### 5.2 Evidence item schema (MVP)
Evidence items MUST be traceable and compact:

```json
{
  "evidence_id": "ev_...",
  "doc_id": "fileSearchStores/.../files/...",
  "title": "string|null",
  "year": 2023,
  "doc_role": "tooling_spec|guideline|empirical|foundation|null",
  "snippet": "string",
  "polarity": "positive|negative|neutral",
  "score": 0.82
}
```

Notes:
- `polarity` is used by conflict detection (TODO#6); defaults to `neutral`.
- `doc_role` classification is governed by `docs/specs/br-kg_search_evidence_architecture_spec.md`.

---

## 6. Definition of Done (DoD)

Auto GFS is considered “done” when:
1) **Stability**: the same query run 3 times returns consistent `gfs.status` (except external errors).
2) **Traceability**: each attached snippet can be traced to `(doc_id, title)`.
3) **Usefulness**: for method/parameter questions, top results include at least one `evidence_status=ok` when the store contains relevant docs.
4) **Cost control**: at most 1 GFS call/request and bounded payload size (e.g. <200KB).

---

## 7. Example (Acceptance)

Input:
> “fMRIPrep 默认 confounds 策略是什么？如何处理 motion outliers？6mm smoothing 有没有推荐依据？”

Expected behavior:
- Triggers GFS (explicit “recommended/依据” intent).
- Returns results with `evidence[]` (0–2 per candidate) and `gfs` meta.
- In orchestrator mode with score breakdown enabled, confidence fields may include
  `contradiction_density` and `uncertainty_density` from `conf_v2`.

---
