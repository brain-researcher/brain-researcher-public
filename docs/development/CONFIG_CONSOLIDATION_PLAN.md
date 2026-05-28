# BR-KG Config Consolidation Plan

**Date:** 2025-01-06  
**Status:** Planning Phase

## Executive Summary

This plan consolidates configuration from `docs/standards/NeuroKG_Standards.md` into `configs/neurokg/` for better maintainability and programmatic access.

## Current State

### ✅ Already in configs/neurokg/
- `config.yml` - Main config with schema definitions (just added)
- `edge_scoring.yaml` - Edge scoring and matching methods
- `thresholds.yaml` - Matching thresholds per node type
- `index_plan.yaml` - Neo4j indexes and constraints
- `neurokg_fusion_config.yaml` - NiCLIP-LLM fusion settings
- `mappings/` - Directory exists but empty

### ✅ Phase 1 Complete - Critical Configs (Created 2025-01-06)
1. `coordinate_systems.yaml` - COORD-01, COORD-02 ✅
2. `string_normalization.yaml` - Referenced in standards ✅
3. `provenance.yaml` - PROV-01, PROV-02 ✅
4. `pii_redaction.yaml` - PII-01, PII-02 ✅

### ⚠️ Missing Important Configs
5. `merge_policies.yaml` - SAME_AS edge creation
6. `data_contracts.yaml` - NDJSON format specs (DATA-01, DATA-02)
7. Mappings files in `mappings/` directory

## Prioritized Implementation Plan

### Phase 1: Critical Gaps (Week 1) - **DO FIRST**

#### 1.1 `coordinate_systems.yaml` ⚠️ **CRITICAL**
- **Why:** Referenced in invariants.md COORD-01, COORD-02
- **Impact:** Loaders can't validate coordinate spaces
- **Location:** `configs/neurokg/coordinate_systems.yaml`
- **Content:**
  - Default space: MNI152_2009c
  - Registered spaces with voxel size, orientation
  - Transformation chains
  - Validation rules

#### 1.2 `string_normalization.yaml` ⚠️ **CRITICAL**
- **Why:** Required for consistent matching, referenced throughout standards
- **Impact:** Matching inconsistencies, duplicate entities
- **Location:** `configs/neurokg/string_normalization.yaml`
- **Content:**
  - Unicode normalization pipeline
  - Case folding, punctuation mapping
  - Field-specific overrides
  - Test cases

#### 1.3 `provenance.yaml` ⚠️ **CRITICAL**
- **Why:** PROV-01, PROV-02 require provenance on all nodes/edges
- **Impact:** Data lineage tracking incomplete
- **Location:** `configs/neurokg/provenance.yaml`
- **Content:**
  - Provenance schema (source, method, confidence, evidence_components)
  - Required fields per node/edge type
  - Loader version tracking
  - Timestamp formats

#### 1.4 `pii_redaction.yaml` ⚠️ **CRITICAL**
- **Why:** PII-01, PII-02 security requirements
- **Impact:** Security risk, compliance issues
- **Location:** `configs/neurokg/pii_redaction.yaml`
- **Content:**
  - Export profiles (public, collaborator, internal)
  - Field whitelists/blacklists per node type
  - Transform rules (coordinate rounding, ID hashing)
  - Security notes

### Phase 2: Important Additions (Week 2)

#### 2.1 `merge_policies.yaml`
- **Why:** Better duplicate handling, SAME_AS edge creation
- **Location:** `configs/neurokg/merge_policies.yaml`
- **Content:**
  - Auto-merge thresholds
  - Manual review criteria
  - Merge procedure
  - Split/undo support

#### 2.2 `data_contracts.yaml`
- **Why:** DATA-01, DATA-02 require NDJSON format validation
- **Location:** `configs/neurokg/data_contracts.yaml`
- **Content:**
  - NDJSON record schemas (NodeRecord, EdgeRecord)
  - Required fields
  - Validation rules
  - Error handling specs

#### 2.3 Core Mappings (in `mappings/` directory)
- **Priority order:**
  1. `task_synonyms.yaml` - High usage, already referenced in code
  2. `concept_synonyms.yaml` - Important for matching
  3. `roi_synonyms.yaml` - Needed for region matching
  4. `roi_crosswalk.yaml` - Atlas crosswalking
  5. `journal_abbrev.yaml` - Publication metadata normalization

### Phase 3: Nice to Have (Backlog)

#### 3.1 Advanced Mappings
- `paradigm_to_task.yaml`
- `contrast_normalization.yaml`
- `ontology_term_maps.yaml`

#### 3.2 Registries
- `ontology_sources.yaml` - External ontology registry
- `sheets_sources.yaml` - Google Sheets integration (if needed)

#### 3.3 Additional Configs
- Golden queries (can stay in `tests/` or `docs/`)
- SHACL shapes (can stay in `docs/standards/` or separate `shacl/`)

## Implementation Notes

### File Organization
```
configs/neurokg/
├── config.yml                    # ✅ Main config + schema
├── coordinate_systems.yaml       # ❌ Phase 1.1
├── string_normalization.yaml     # ❌ Phase 1.2
├── provenance.yaml               # ❌ Phase 1.3
├── pii_redaction.yaml            # ❌ Phase 1.4
├── merge_policies.yaml           # ❌ Phase 2.1
├── data_contracts.yaml           # ❌ Phase 2.2
├── edge_scoring.yaml             # ✅ Already exists
├── thresholds.yaml                # ✅ Already exists
├── index_plan.yaml                # ✅ Already exists
├── neurokg_fusion_config.yaml    # ✅ Already exists
└── mappings/
    ├── task_synonyms.yaml        # ❌ Phase 2.3
    ├── concept_synonyms.yaml      # ❌ Phase 2.3
    ├── roi_synonyms.yaml          # ❌ Phase 2.3
    ├── roi_crosswalk.yaml         # ❌ Phase 2.3
    └── journal_abbrev.yaml        # ❌ Phase 2.3
```

### Cross-References
- All configs should reference schema in `config.yml`
- Invariants.md should reference config file locations
- Code should load from `configs/neurokg/` not hardcoded defaults

### Migration Strategy
1. Create new config files from standards doc
2. Update code to load from configs (if not already)
3. Add validation scripts
4. Update documentation to point to configs
5. Deprecate hardcoded defaults in code

## Success Criteria

- [x] All Phase 1 configs created and validated ✅ (2025-01-06)
- [ ] Code updated to load from configs
- [ ] Invariants.md references point to config files
- [ ] No hardcoded defaults in loader code
- [ ] CI validates configs on PR

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing code | High | Gradual migration, feature flags |
| Config drift | Medium | Validation scripts, CI checks |
| Performance impact | Low | Lazy loading, caching |
| Maintenance burden | Low | Single source of truth reduces it |

## Next Steps

1. **Immediate:** Create Phase 1 configs (coordinate_systems, string_normalization, provenance, pii_redaction)
2. **This week:** Update code to load from new configs
3. **Next week:** Phase 2 configs and mappings
4. **Ongoing:** Validation, testing, documentation

