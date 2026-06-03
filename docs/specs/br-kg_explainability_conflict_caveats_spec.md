# BR-KG Explainability + Conflict + Caveats — Spec v1.0 (Engineering)

Last updated: 2026-01-05

## 0. Summary

Define an explainability layer that:
- always returns a compact `explain_min`,
- returns full breakdown only with `include_explain=true`,
- flags contradictions/uncertainty deterministically (no LLM-only “explanations”),
- attaches domain caveats from a small, reviewable NeuroMethods KB.

This spec is designed to plug into `/api/search?mode=hybrid_v1`.

---

## 1. Goals and Scope

**Goals**
- Provide user-visible “why” for results without bloating default payloads.
- Detect P0 contradictions:
  - MAPS_TO ambiguity,
  - evidence semantic conflict (explicit positive vs explicit negative),
  - tooling/guideline conflicts that affect confidence.
- Maintain a small caveats KB with triggers and optional citations.

**Non-Goals**
- Chain-of-thought style reasoning.
- A numeric uncertainty model across all relationship types.
- Writing conflict records back into KG in v1 (query-output flags only).

---

## 2. Explainability Contracts

### 2.1 `explain_min` (default)
- Compact, bounded, and suitable for UI default rendering.
- MUST reference evidence via `evidence_id` to avoid duplicated document payloads.

```json
{
  "reason_codes": [],
  "retrieval_trace_summary": "string",
  "filters_matched": [],
  "mapsto_path": null,
  "evidence_refs": ["ev1", "ev2"]
}
```

### 2.2 `explain_full` (`include_explain=true`)
Adds detailed trace/breakdowns:

```json
{
  "score_breakdown": {},
  "retrieval_trace_full": {},
  "filtered_out_summary": {},
  "conflict_flags": [],
  "mapsto_path": null
}
```

---

## 3. Dataset Explain Strategy (P0)

Use D2 as primary and D3 as optional:
- **D2 (default)**: show which structured filters matched + recall sources (fulltext/vector) + whether GFS ran.
- **D3 (optional)**: if graph can produce a canonical mapping path, include it.

Max limits:
- `max_paths = 1`
- `max_evidence_per_result = 2`

---

## 4. `MAPS_TO` Path Representation (Two-Tier)

**Decision**
- SSOT is a structured path in `explain_full`.
- `explain_min` provides a light template string + node ids.

### 4.1 `explain_min.mapsto_path`
```json
{
  "template": "TaskSpec(confounds_aroma) -> MAPS_TO -> TaskDef(ICA-AROMA)",
  "node_ids": ["spec:confounds_aroma", "taskdef:ica_aroma"]
}
```

### 4.2 `explain_full.mapsto_path`
```json
{
  "nodes": [{"id": "...", "type": "...", "label": "..."}],
  "edges": [{"type": "MAPS_TO", "source": "...", "target": "...", "confidence": 0.82}]
}
```

---

## 5. Conflict Detection (P0)

### 5.1 MAPS_TO ambiguity
**Rule**
- Let `delta = top1_confidence - top2_confidence`.
- If `delta <= 0.05`, mark `mapsto_ambiguous`.

**Implementation**
- Use top2 for ambiguity decision.
- Include top3 as explain candidates:
  - `details.candidates[]` includes at most 3 targets.

### 5.2 Evidence polarity (explicit markers)
**Negative markers** (must be explicit):
- `deprecated`, `removed`, `do not use`, `obsolete`, `not recommended`, `avoid`, `should not`

**Positive markers**:
- `recommended`, `default`, `standard`, `we use`, `we applied`

**Rules**
- `evidence_semantic_conflict`: same result has both positive and negative evidence.
- `evidence_negative_only`: negative evidence present with no positive evidence (strong warning; not a “conflict”).

### 5.3 Tooling/guideline confidence discount (severity buckets)
Apply only for tooling/guideline scope conflicts:
- `low`: ×0.9
- `medium`: ×0.7
- `high`: ×0.5

Severity heuristics (P0):
- `high`: contains `deprecated|removed|DO NOT USE|obsolete`
- `medium`: contains `not recommended|avoid|should not`
- `low`: version/default changed, no explicit prohibition

Conflict flags are returned in output (do not write back into KG in v1).

---

## 6. NeuroMethods KB (Caveats)

### 6.1 Storage (SSOT)
- Repo file (YAML/JSON) is SSOT (reviewable).
- Ingestion job writes to Neo4j for query-time joins (optional but recommended).

### 6.2 Minimum schema (YAML)
```yaml
- id: bold_reverse_inference
  title: "Avoid reverse inference from BOLD activation"
  severity: high
  needs_citation: true
  citations: []
  triggers:
    query_keywords: ["reverse inference", "BOLD", "activation implies"]
    node_labels: ["Concept", "TaskSpec"]
  actionable_fix: "Frame claims as associations; cite meta-analytic evidence and report uncertainty."
```

### 6.3 Trigger policy
Use A+B mixed triggers:
- query keyword trigger (fast)
- node type/label trigger (contextual)

De-dup:
- merge by `caveat.id`
- sort by severity (high→low)

---

## 7. DoD (Minimum Acceptance)

- Default search responses include `explain_min` without payload bloat.
- `include_explain=true` returns `score_breakdown`, `filtered_out_summary`, and `conflict_flags`.
- MAPS_TO ambiguity uses `delta<=0.05` and emits top3 candidates.
- Evidence conflict requires explicit negative markers (no implicit sentiment).
- Tooling/guideline conflicts discount confidence by severity buckets (0.9/0.7/0.5).
- Caveats KB is reviewable in repo and triggers via query+node context; can mark `needs_citation=true`.

---
