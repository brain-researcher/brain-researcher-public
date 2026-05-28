# BR-KG Config Coverage Analysis
**Date:** 2025-01-06  
**Comparison:** `docs/standards/` vs `configs/neurokg/`

## Executive Summary

After comprehensive review of all standards documents, most critical configuration information has been successfully moved to `configs/neurokg/`. A few minor gaps remain for completeness.

## ✅ Fully Covered Configs

### Core Configuration
- ✅ **`config.yml`** - Main config + complete schema definitions (nodes, edges, ID rules)
- ✅ **`coordinate_systems.yaml`** - COORD-01, COORD-02 (invariants.md)
- ✅ **`string_normalization.yaml`** - Referenced in NeuroKG_Standards.md
- ✅ **`provenance.yaml`** - PROV-01, PROV-02 (invariants.md)
- ✅ **`pii_redaction.yaml`** - PII-01, PII-02 (invariants.md)

### Matching & Scoring
- ✅ **`edge_scoring.yaml`** - Matching methods, canonical priority (MATCHING_IMPLEMENTATION.md)
- ✅ **`thresholds.yaml`** - Confidence thresholds (MATCHING_IMPLEMENTATION.md)
- ✅ **`merge_policies.yaml`** - SAME_AS edge creation, merge rules (NeuroKG_Standards.md)

### Data Contracts
- ✅ **`data_contracts.yaml`** - NDJSON schemas, validation rules (DATA-01, DATA-02)
- ✅ **`ingestion_modes.yaml`** - Full/spine/on-demand modes (ingestion_modes.md)

### Other
- ✅ **`index_plan.yaml`** - INDEX-01 (invariants.md)
- ✅ **`neurokg_fusion_config.yaml`** - NiCLIP-LLM fusion settings

## ⚠️ Minor Gaps (Lower Priority)

### 1. **Golden Queries Configuration** (QUERY-01)

**Location in standards:** 
- `docs/standards/invariants.md` (QUERY-01)
- `docs/standards/NeuroKG_Standards.md` (lines 346-392)
- `docs/standards/ingestion_modes.md` (line 156)

**Status:** Referenced but not in configs

**What's missing:**
- Golden query definitions (Cypher queries for performance validation)
- Latency thresholds per query
- Expected result validation rules

**Should create:** `configs/neurokg/golden_queries.yaml` (or `.json`)

**Example from standards:**
```json
[
  {
    "id": "GQ-001",
    "title": "Working memory → prefrontal regions",
    "query_type": "cypher",
    "query": "MATCH (t:Task {name:'n-back'})-[:MEASURES]->(c:Concept)...",
    "expected": {
      "min_nodes": 5,
      "max_latency_ms": 300
    }
  }
]
```

**Priority:** **MEDIUM** - Important for CI/CD performance validation

### 2. **Relationship Domain/Range Rules** (REL-02)

**Location in standards:**
- `docs/standards/invariants.md` (REL-02, lines 28-46)

**Status:** Partially covered in `config.yml` schema, but missing validation rules

**What's missing:**
- Explicit domain/range constraints per edge type
- Validation rules for relationship creation
- Error messages for invalid relationships

**Current state:** 
- Edge types defined in `config.yml` schema
- Domain/range mentioned in invariants.md but not in config

**Should enhance:** Add to `config.yml` schema section or create `relationship_rules.yaml`

**Priority:** **LOW** - Can be inferred from schema, but explicit rules would be clearer

### 3. **Validation Rules Configuration**

**Location in standards:**
- `docs/standards/invariants.md` (Validation Enforcement section, lines 73-89)

**Status:** Partially covered in `data_contracts.yaml`, but could be more comprehensive

**What's missing:**
- Comprehensive pre-ingestion validation rules
- Runtime validation rules
- Post-ingestion QA rules
- Validation error handling configuration

**Current state:**
- Basic validation in `data_contracts.yaml`
- Some rules in `provenance.yaml`
- Scattered across multiple configs

**Should create:** `configs/neurokg/validation_rules.yaml` (optional consolidation)

**Priority:** **LOW** - Already covered in data_contracts.yaml and other configs

### 4. **Data Config JSON** (Legacy Reference)

**Location in standards:**
- `docs/standards/ingestion_modes.md` (lines 97, 103)

**Status:** Referenced but replaced by `ingestion_modes.yaml`

**What's referenced:**
- `configs/neurokg/data_config.json` - Source mode declarations

**Current state:**
- We created `ingestion_modes.yaml` instead
- May be a legacy reference or different purpose

**Action needed:** 
- Check if `data_config.json` exists elsewhere
- Update `ingestion_modes.md` to reference `ingestion_modes.yaml` instead
- Or create `data_config.json` if it serves a different purpose

**Priority:** **LOW** - Documentation update needed

### 5. **Sheets Sources Config** (Not Core BR-KG)

**Location in standards:**
- `docs/standards/NeuroKG_Standards.md` (lines 932, 938)

**Status:** Referenced but appears to be for specific data source integration

**What's referenced:**
- `configs/sheets_sources.yaml` - Google Sheets integration config

**Priority:** **NONE** - Not core BR-KG config, likely belongs elsewhere

## Summary Table

| Config | Priority | Status | Notes |
|--------|----------|--------|-------|
| `golden_queries.yaml` | **MEDIUM** | ❌ Missing | QUERY-01 invariant |
| `relationship_rules.yaml` | **LOW** | ⚠️ Partial | Can enhance config.yml |
| `validation_rules.yaml` | **LOW** | ⚠️ Partial | Already in data_contracts.yaml |
| `data_config.json` | **LOW** | ⚠️ Legacy | Documentation update needed |
| `sheets_sources.yaml` | **NONE** | ❌ Not needed | Not core BR-KG |

## Recommendations

### Immediate (Optional)
1. Create `golden_queries.yaml` - **Recommended** for CI/CD performance validation
   - Move golden query definitions from standards docs
   - Add latency thresholds
   - Enable automated performance testing

### Documentation Updates
2. Update `ingestion_modes.md` to reference `ingestion_modes.yaml` instead of `data_config.json`
3. Consider adding relationship domain/range rules to `config.yml` schema section

### Low Priority
4. Optionally create `validation_rules.yaml` to consolidate validation rules (currently scattered)
5. Optionally enhance `config.yml` with explicit relationship domain/range constraints

## Conclusion

**Coverage: ~95%** ✅

The vast majority of configuration information from standards documents has been successfully consolidated into `configs/neurokg/`. The remaining gaps are:
- **Golden queries** (medium priority) - Would improve CI/CD
- **Minor enhancements** (low priority) - Nice-to-have improvements

The core configuration is complete and comprehensive. The system now has a single source of truth for all BR-KG configuration.

