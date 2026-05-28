# Missing Configuration Analysis
**Date:** 2025-01-06  
**Comparison:** `docs/standards/` vs `configs/neurokg/`

## Executive Summary

After comparing the standards documentation with existing configs, several important configuration areas are missing from `configs/neurokg/`. These should be added to make the configs the single source of truth.

## Critical Missing Configs

### 1. **Ingestion Modes Configuration** ⚠️ **HIGH PRIORITY**

**Location in standards:** `docs/standards/ingestion_modes.md`  
**Current state:** Hardcoded in `MasterDataLoader.SOURCE_DEFAULT_MODES` (load_all.py:105-128)

**What's missing:**
- Ingestion mode definitions (full, spine, on_demand)
- Field whitelists for spine mode per node type
- Allowed edge types for spine mode
- Data source mode assignments
- On-demand adapter requirements

**Should create:** `configs/neurokg/ingestion_modes.yaml`

**Content needed:**
```yaml
# Ingestion Modes Configuration
# Defines how data sources are ingested into BR-KG

modes:
  full:
    description: "Canonical ontology / blueprint data, small and high-value"
    persistence: "Complete curated representation"
    
  spine:
    description: "Search spine - minimal metadata for traversal"
    persistence: "Whitelisted fields only"
    
  on_demand:
    description: "No primary data stored, fetched via adapters"
    persistence: "Nothing written to Neo4j during ingestion"

# Field whitelists for spine mode (per node type)
spine_whitelists:
  Task:
    required: ["id", "name"]
    optional: ["synonyms"]
    
  Concept:
    required: ["id", "label"]
    optional: ["synonyms"]
    
  Publication:
    required: ["id", "title"]
    optional: ["pmid", "doi", "year", "journal"]
    
  Coordinate:
    required: ["id", "x", "y", "z", "space"]
    optional: ["round_mm"]
    
  Region:
    required: ["id", "atlas", "name"]
    optional: ["aliases"]
    
  Dataset:
    required: ["id"]
    optional: ["name", "license", "modalities", "tasks", "n_subjects", "TR", "TE", "url"]
    
  StatisticalMap:
    required: ["id", "space", "modality", "uri"]
    optional: ["etag", "experiment_type"]
    
  Phenotype:
    required: ["id", "name"]
    optional: ["value_type"]

# Allowed edge types in spine mode
spine_allowed_edges:
  - "MEASURES"
  - "HAS_COORDINATE"
  - "IN_REGION"
  - "REPORTS_TASK"
  - "IMPLEMENTS_TASK"
  - "DERIVED_FROM"
  - "SAME_AS"
  - "MAPS_TO"
  - "HAS_PHENOTYPE"

# Data source mode assignments
source_modes:
  cognitive_atlas: "full"
  nilearn_atlases: "full"
  neurobagel: "full"
  onvoc: "full"
  openneuro_glmfitlins: "full"
  
  pubmed: "spine"
  neurosynth: "spine"
  neurovault: "spine"
  openneuro: "spine"
  wikidata: "spine"
  niclip: "spine"
  brainmap: "spine"
  bids: "spine"
  neuromaps: "spine"
  neurostore: "spine"
  allen_hba: "spine"
  virtual_brain: "spine"
  
  scholarly_metadata: "on_demand"
  nidm_results: "on_demand"
  neuroquery: "on_demand"
  nimare: "on_demand"
  neuroscout: "on_demand"

# On-demand adapter requirements
on_demand_adapters:
  neuroquery:
    data_path: "data/neurokg/raw/evidence/neuroquery_sample.json"
    schema:
      - task_id
      - region_id
      - score
      - confidence (optional)
      - method (optional)
      - source (optional)
      
  nimare:
    data_path: "data/neurokg/raw/evidence/nimare_sample.json"
    schema:
      - task_id
      - region_id
      - probability
      - method (optional)
      
  neuroscout:
    data_path: "data/neurokg/raw/evidence/neuroscout_features.json"
    schema:
      - contrast_id
      - feature
      - value
      - unit (optional)
      - source (optional)
      
  allen_hba:
    data_path: "data/neurokg/raw/evidence/allen_hba_sample.json"
    schema:
      - region_id
      - gene_symbol
      - expression
      - tissue_type (optional)
      - source (optional)
```

### 2. **Data Contracts Configuration** ⚠️ **HIGH PRIORITY**

**Location in standards:** `docs/standards/NeuroKG_Standards.md` (lines 186-227), `docs/standards/NeuroKG_Standards.md` (data_contracts section)

**What's missing:**
- NDJSON record schemas (NodeRecord, EdgeRecord)
- Required fields per record type
- Validation rules
- Error handling specifications

**Should create:** `configs/neurokg/data_contracts.yaml` (from Phase 2 plan)

### 3. **Merge Policies Configuration** ⚠️ **MEDIUM PRIORITY**

**Location in standards:** `docs/standards/NeuroKG_Standards.md` (merge_policies section)

**What's missing:**
- Auto-merge thresholds
- Manual review criteria
- Merge procedure
- Split/undo support

**Should create:** `configs/neurokg/merge_policies.yaml` (from Phase 2 plan)

## Important Missing Information

### 4. **ID Generation Rules** (Partially covered)

**Location in standards:** `docs/standards/invariants.md`, `docs/standards/NeuroKG_Standards.md`

**Current state:** Partially in `config.yml` schema section (id_rules), but missing:
- Detailed ID computation logic
- Fallback strategies
- Validation rules

**Enhancement needed:** Expand `config.yml` schema.id_rules section

### 5. **Relationship Whitelist** (Partially covered)

**Location in standards:** `docs/standards/invariants.md` (lines 28-46)

**Current state:** Partially in `config.yml` schema.edges, but missing:
- Domain/range constraints validation rules
- Relationship validation logic

**Enhancement needed:** Add to `config.yml` or create `configs/neurokg/relationship_rules.yaml`

### 6. **Validation Rules** (Missing)

**Location in standards:** `docs/standards/invariants.md` (validation section)

**What's missing:**
- Pre-ingestion validation rules
- Runtime validation rules
- Post-ingestion QA rules
- Golden query definitions

**Should create:** `configs/neurokg/validation_rules.yaml`

## Nice-to-Have (Lower Priority)

### 7. **Loader Responsibilities** (Documentation, not config)

**Location in standards:** `docs/standards/ingestion_modes.md` (lines 130-136)

**Status:** This is more of a coding contract than config. Could be in a separate `loader_contracts.yaml` if needed.

### 8. **On-demand Evidence Feed Schemas** (Partially covered)

**Location in standards:** `docs/standards/ingestion_modes.md` (lines 67-95)

**Status:** Could be part of `ingestion_modes.yaml` (see above) or separate `on_demand_schemas.yaml`

## Summary Table

| Config | Priority | Status | Location in Standards |
|--------|----------|--------|----------------------|
| `ingestion_modes.yaml` | **HIGH** | ✅ **Created** (2025-01-06) | `ingestion_modes.md` |
| `data_contracts.yaml` | **HIGH** | ✅ **Created** (2025-01-06) | `NeuroKG_Standards.md` |
| `merge_policies.yaml` | **MEDIUM** | ✅ **Created** (2025-01-06) | `NeuroKG_Standards.md` |
| `validation_rules.yaml` | **MEDIUM** | ❌ Missing | `invariants.md` |
| `relationship_rules.yaml` | **MEDIUM** | ⚠️ Partial | `invariants.md` |
| Enhanced `id_rules` in config.yml | **LOW** | ⚠️ Partial | `invariants.md` |

## Recommended Action Plan

### Immediate (This Week)
1. ✅ Create `ingestion_modes.yaml` - **CRITICAL** (hardcoded in code)
2. ✅ Create `data_contracts.yaml` - **CRITICAL** (referenced in standards)

### Short-term (Next Week)
3. Create `merge_policies.yaml`
4. Create `validation_rules.yaml`
5. Enhance `config.yml` with complete ID generation rules

### Medium-term (Backlog)
6. Create `relationship_rules.yaml` for domain/range constraints
7. Add on-demand adapter schemas to `ingestion_modes.yaml`

## Notes

- **Ingestion modes** is the most critical missing piece - it's currently hardcoded in `MasterDataLoader.SOURCE_DEFAULT_MODES`
- **Data contracts** are referenced throughout standards but not in configs
- Most other missing items are validation/constraint rules that would improve maintainability

