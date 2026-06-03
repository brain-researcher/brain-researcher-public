# BR-KG Deep Research Evidence — Spec v1.0 (Engineering)

Last updated: 2026-01-05

## 0. Summary

Define a provider-agnostic Deep Research interface that:
- runs asynchronously by default (start/get),
- produces *citable* outputs (claims + citations),
- persists results for reuse (idempotency + caching),
- supports optional File Search store grounding.

This spec targets “web/search-grounded research” (Gemini + Google Search), not GFS-only RAG.

---

## 1. Goals and Scope

**Goals**
- Provide a stable schema for Deep Research input/output.
- Default to async execution (better UX, telemetry, retries, cancelability).
- Persist results as evidence that can be referenced later by agents/UI.
- Use “claim-level” citations by default; degrade gracefully when needed.

**Non-Goals**
- Ingesting all empirical papers into Neo4j as KG nodes.
- Building a full literature pipeline (that is a separate long-term project).
- Allowing unrestricted domain scraping; domain control is policy-driven.

---

## 2. Trigger Policy (Hard Gate + Two-Level Trigger)

### 2.1 Explicit trigger (strong)
Always run Deep Research when user intent is explicit:
- “latest / recent / today / this year / research / investigate / cite / source / official”
- “最新 / 最近 / 调研 / 给出处 / 官方来源”

### 2.2 Automatic trigger (weak)
Run only when *all* are true:
- system policy allows auto Deep Research, AND
- one of:
  - conflict/uncertainty detected upstream,
  - high-risk correctness (version/spec/policy),
  - best-practice/authority needed,
  - base retrieval quality is low.

### 2.3 Recency policy
- Default `recency_days = 180`.
- If query implies “latest/recent”: force `recency_days = 30`.
- If query implies “foundational/seminal/classic”: set `recency_days = null`.

---

## 3. Provider Interface

### 3.1 Async-first API (preferred)
- `start(request) -> {interaction_id, status}`
- `get(interaction_id) -> {status, result?}`

### 3.2 Sync fast-path (optional)
Allowed only for:
- cache hits,
- low-budget debug requests.

---

## 4. Request Schema (MVP)

```json
{
  "query": "string",
  "intent": "evidence_search|deep_research",
  "recency_days": 180,
  "top_k": 10,
  "exclude_domains": [],
  "language": "en",
  "idempotency_key": "sha256(normalized_query+recency+top_k+filters+config_hash)"
}
```

Notes:
- `idempotency_key` MUST be deterministic to enable caching and reproducibility.
- `exclude_domains` is a governance control (prefer downranking over hard exclude unless spam).

---

## 5. Output Schema (Mid-Structured, Citable)

### 5.1 Envelope
```json
{
  "status": "ok|partial|error",
  "summary": "string",
  "documents": [],
  "claims": [],
  "raw": null,
  "metadata": {
    "provider": "google_deep_research",
    "model": "gemini-2.5-pro",
    "recency_days": 180,
    "created_at": "2026-01-05T00:00:00Z",
    "idempotency_key": "..."
  }
}
```

### 5.2 Documents
```json
{
  "doc_id": "doc_1",
  "title": "string|null",
  "url": "https://...",
  "publisher": "string|null",
  "published_at": "2025-11-01|null",
  "snippets": ["..."]
}
```

### 5.3 Claims (default on; can be disabled for ultra-minimal mode)
```json
{
  "claim_id": "c_1",
  "text": "string",
  "citations": [
    {
      "doc_id": "doc_1",
      "url": "https://...",
      "quote": "short excerpt (<=25 words)"
    }
  ]
}
```

Policy:
- Each claim should have 1–3 citations where possible.
- If claim-level extraction fails, degrade to doc-level citations.

---

## 6. Persistence and Caching

### 6.1 Mandatory (MVP)
- Persist results keyed by `idempotency_key`:
  - Artifact JSON (preferred for auditability), and/or
  - Knowledge-layer cache entry (for fast reuse).

### 6.2 Optional (post-MVP)
- Write back **only stable canonical evidence** to Neo4j (tooling specs/guidelines).
- Avoid writing all empirical papers into KG to prevent bloat/governance complexity.

---

## 7. Domain Weighting (Governance)

Prefer/boost:
- official documentation/specs,
- journals / institutional sources,
- authoritative repositories (where appropriate).

Downrank (not necessarily hard-block):
- personal blogs,
- SEO/low-trust aggregators,
- unversioned reposts.

---

## 8. Definition of Done (DoD)

Deep Research is “done” when:
1) Can be started asynchronously and polled to completion.
2) Output includes citable evidence (at least doc-level URLs; claim-level preferred).
3) Results are persisted and cacheable via `idempotency_key`.
4) Trigger policy prevents “always-run” behavior and enforces budget controls.

---
