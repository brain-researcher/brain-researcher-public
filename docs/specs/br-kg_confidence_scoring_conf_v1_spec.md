# BR-KG Confidence Scoring (`conf_v1_k10`) — Spec v1.0 (Engineering)

Last updated: 2026-01-05

## 0. Summary

Standardize numeric `confidence` (0–1) for P0 BR-KG relationships so that:
- queries can rank/filter reliably,
- explainability can show *why* an edge/result is trusted,
- confidence is governance-friendly (versioned, recomputable).

Key decisions:
- `confidence` = “credible existence” of an edge (not effect size).
- P0 edges are written back to Neo4j (versioned); others can be query-time.
- Support uniqueness uses `pmid/doi` first, `dataset_key` fallback; avoid double counting.
- Runtime query scoring for hypothesis/search conflict handling is extended in `conf_v2`
  (see `docs/specs/br-kg_confidence_scoring_conf_v2_spec.md`).

---

## 1. Goals and Scope

**Goals**
- Define a minimal, consistent relationship property set for confidence.
- Provide a computable confidence model: `prov_base_conf × support × diversity × match_score?`.
- Enable safe query usage (do not zero-out results; avoid brittle filters).

**Non-Goals**
- Modeling `strength` universally (only fill strength when upstream provides an effect size).
- Full probabilistic uncertainty/contradiction modeling (handled by TODO#6 flags + selective discounting).

---

## 2. Definitions

### 2.1 `confidence` vs `strength`
- `confidence`: probability-like score that the relationship **exists/holds** (0–1).
- `strength`: association magnitude / effect size (optional; source-specific).

---

## 3. P0 Relationship Coverage

P0 edges (must have numeric confidence + versioning):
- Task ↔ Concept:
  - `MEASURES`, `RELATED`, `INVOLVES_CONSTRUCT` (and equivalents)
- Dataset → Task/Concept:
  - `HAS_TASK`, `USES_TASK`, `USES_PARADIGM` (and equivalents)
- Cross-source alignment:
  - `MAPS_TO` (TaskSpec↔TaskDef, TaskSpec↔Task, Concept↔Construct, etc.)
- TaskSpec → Task bridge:
  - may be represented as `MAPS_TO` in current pipelines; treated as P0 for governance.

P1 (later):
- Publication-derived relationships (pmid/doi extraction + robust dedup needed first).

---

## 4. Relationship Property Schema (Minimum)

P0 relationships MUST carry:

```json
{
  "confidence": 0.0,
  "confidence_version": "conf_v1_k10",
  "computed_at": "2026-01-05T12:34:56Z",

  "support_count_raw": 0,
  "support_count_unique": 0,
  "source_diversity": 0,
  "evidence_type_diversity": 0,

  "prov_source": "cogatlas|openneuro|pubmed|neurosynth|niclip|manual|gfs|...",
  "prov_method": "exact_id|string_match|fuzzy_match|embedding_match|rule|manual|...",
  "evidence_type": "ontology_link|dataset_metadata|mention_snippet|coordinate|rule|manual|..."
}
```

Optional (recommended for explain/debug):
- `confidence_components` (support/diversity/prior/match contributions)
- `match_score` (for MAPS_TO and other matching edges; preserve raw matcher output)

---

## 5. Unique Support Keys (`support_unique_key`)

### 5.1 Rule (MVP)
For each evidence item, compute `support_keys(evidence) -> set[str]`:
1) If `pmid` present → `pmid:<pmid>`
2) Else if `doi` present → `doi:<normalized_doi>`
3) Else if `dataset_key` present → `dataset:<dataset_key>`
4) Else fallback → `src:<prov_source>|id:<source_item_id>`

**No double counting rule**
- If an item has both PMID and DOI, only emit the `pmid:` key.
- DOI may be stored as an alternate id but does not increase `support_count_unique`.

### 5.2 Stored counts
- `support_count_raw`: raw evidence rows/chunks/mentions.
- `support_count_unique`: `len(unique_support_keys)` (used for scoring by default).

---

## 6. Provenance Prior (`prov_base_conf`)

### 6.1 Prior definition
`prov_base_conf = clamp(method_conf × source_conf, 0, 1)`

### 6.2 Method priors (v1)
| prov_method | method_conf |
|---|---:|
| `exact_id` | 1.00 |
| `curated_manual` | 0.95 |
| `rule_high_precision` | 0.90 |
| `string_match` | 0.75 |
| `fuzzy_match` | 0.65 |
| `embedding_match` | 0.60 |
| `llm_extracted` | 0.45 |

### 6.3 Source priors (v1)
| source_class | source_conf |
|---|---:|
| `official_spec` / `major_ontology` | 0.95 |
| `peer_reviewed` | 0.90 |
| `aggregator_db` | 0.80 |
| `scraped_web` | 0.65 |

Mapping `prov_source -> source_class` is policy/configurable.

---

## 7. Confidence Model (`conf_v1_k10`)

### 7.1 Core form (multiplicative; explainable)
```
confidence = clamp(
  prov_base_conf * support_factor * diversity_factor * match_factor,
  0, 1
)
```

### 7.2 Support factor (K=10)
```
support_factor = 1 - exp(-support_count_unique / 10)
```

### 7.3 Diversity factor (MVP normalization)
Compute normalized diversity (saturate at 3 distinct types):
```
source_div_norm = min(1.0, source_diversity / 3)
etype_div_norm  = min(1.0, evidence_type_diversity / 3)
diversity_factor = min(1.0, 0.6 + 0.2 * source_div_norm + 0.2 * etype_div_norm)
```

### 7.4 Match factor
- For MAPS_TO and matching-derived edges: `match_factor = match_score` (0–1).
- For non-matching edges: `match_factor = 1.0`.

---

## 8. Writeback Strategy (Governance)

**Decision**
- Write back computed `confidence` for **P0 edges** into Neo4j.
- Track recomputation via:
  - `confidence_version` (e.g., `conf_v1_k10`)
  - `computed_at`
  - (optional) `confidence_components`

Non-P0 edges:
- may compute confidence at query-time until promoted to P0.

---

## 9. Query Usage (MVP)

### 9.1 Ranking (MVP default)
Apply a “soft” confidence multiplier to avoid dropping low-confidence results:
```
final_score = retrieval_score * (0.5 + 0.5 * confidence)
```

### 9.2 Filtering (optional)
- Support `min_confidence` parameter but default to no hard filter.

### 9.3 Conflicts
- Tooling/guideline conflicts MAY discount confidence (see TODO#6).
- Other conflicts are surfaced as flags first (no automatic discount in v1).

---

## 10. DoD (Minimum Acceptance)

- P0 edges in Neo4j have `confidence`, `confidence_version`, `computed_at`.
- Confidence is explainable via components (at least support/diversity/prior, and match_score when applicable).
- Query surfaces confidence and uses it in ranking without zeroing results.
- Dedup rules prevent PMID/DOI double counting.

---
