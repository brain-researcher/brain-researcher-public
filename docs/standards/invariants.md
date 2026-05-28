# BR-KG Hard Invariants

This document defines the immutable rules that MUST be enforced across all BR-KG operations. These rules ensure data integrity, consistency, and scientific validity.

## Invariant Rules Table

| Rule | Description | Config Location | Validation | Owner |
|------|-------------|-----------------|------------|--------|
| **ID-01** | Global unique identifiers | `src/brain_researcher/services/neurokg/graph/neo4j_graph_database.py:79-84` | Neo4j NODE KEY constraints + CI validation | Platform |
| **ID-02** | Idempotent operations | All loaders must use upsert | Loader base class enforcement | Data Eng |
| **REL-01** | Relationship whitelist | See allowed relationships below | `create_relationship()` validation | Platform |
| **REL-02** | Domain/range constraints | Node type pairs for edges | Runtime validation in graph DB | Platform |
| **COORD-01** | Default coordinate space | MNI152_2009c, mm units, RAS orientation | `configs/neurokg/coordinate_systems.yaml` | Loader validation | Neuro |
| **COORD-02** | Space field required | All Coordinate/StatisticalMap nodes | Schema validation | Neuro |
| **PROV-01** | Provenance required | All nodes/edges must have source, method, timestamp | NDJSON schema validation | Platform |
| **PROV-02** | Loader versioning | Track loader_version in provenance | Automatic injection | Data Eng |
| **DATA-01** | NDJSON format | Standard data exchange format | JSON Schema validation | Data Eng |
| **DATA-02** | Record types | record_type ∈ {node, edge} | Pre-ingestion validation | Data Eng |
| **TIME-01** | No hard deletes | Use valid_from/valid_to for versioning | Database trigger protection | Platform |
| **TIME-02** | Temporal consistency | valid_from < valid_to always | Constraint check | Platform |
| **MERGE-01** | Reversible merges | SAME_AS edges preserve history | Audit log requirement | Data Eng |
| **MERGE-02** | Canonical stability | canonical_id immutable after merge | Write-once enforcement | Platform |
| **PII-01** | No direct PII | Subject data must be anonymized | Export filter enforcement | Security |
| **PII-02** | Coordinate rounding | Public exports round to 1mm | `security/pii_redaction.yaml` | Security |
| **INDEX-01** | Core indexes | Required indexes for performance | `configs/neurokg/index_plan.yaml` | Migration script | Platform |
| **QUERY-01** | Golden queries | Must pass with latency < threshold | CI performance tests | QA |

## Allowed Relationships

### Core Scientific Relationships
- `Task` → `MEASURES` → `Concept`
- `Task` → `ACTIVATES` → `Region|BrainRegion` (semantic enrichment, not Gate A)
- `Concept` → `ACTIVATES` → `Region|BrainRegion` (semantic enrichment, not Gate A)
- `Publication` → `HAS_COORDINATE` → `Coordinate`
- `StatsMap` → `IN_REGION` → `BrainRegion`
- `StatisticalMap` → `DERIVED_FROM` → `Publication`
- `StatisticalMap` → `DERIVED_FROM` → `Contrast`
- `Dataset` → `IMPLEMENTS_TASK` → `Task`
- `Dataset` → `INCLUDES` → `SubjectGroup`
- `Subject` → `HAS_PHENOTYPE` → `Phenotype`

### Structural Relationships
- `BrainRegion` → `PART_OF` → `BrainRegion`
- `Concept` → `IS_A` → `Concept`
- Any → `SAME_AS` → Any (same type only)
- Any → `MAPS_TO` → Any (cross-source linking)

### Compatibility / Future Enrichment
- `Coordinate` → `IN_REGION` → `Region` remains allowed as a future enrichment lane.
- Existing non-anatomy `PART_OF` uses do not count as anatomy-readiness evidence.

## ID Generation Rules

### Standard ID Computation (from neo4j_graph_database.py)
```python
def _compute_id(self, labels, properties):
    if "id" in properties:
        return str(properties["id"])
    key_props = {k: properties.get(k) for k in
                 ["name", "pmid", "doi", "concept_id", "x", "y", "z"]}
    id_string = f"{'-'.join(labels)}-{str(key_props)}"
    return hashlib.md5(id_string.encode()).hexdigest()
```

### CURIE Namespaces
- `pmid:` - PubMed IDs
- `doi:` - Digital Object Identifiers
- `cogat:` - Cognitive Atlas IDs
- `nv:` - NeuroVault collections/images
- `ns:` - NeuroSynth terms
- `bm:` - BrainMap experiments
- `openneuro:` - OpenNeuro datasets
- `niclip:` - NiCLIP model entities

## Validation Enforcement

### Pre-Ingestion
1. JSON Schema validation on NDJSON records
2. Required field checks
3. Type validation
4. ID format validation

### Runtime
1. Neo4j constraints (NODE KEY, UNIQUE)
2. Relationship type whitelist in `create_relationship()`
3. Provenance field requirements
4. Coordinate space validation

### Post-Ingestion
1. Golden query validation
2. Degree distribution checks
3. Orphan node detection
4. Cross-source link verification

## CI/CD Enforcement

```yaml
# .github/workflows/validate-standards.yml
- name: Validate Standards
  run: |
    python scripts/validation/validate_standards.py
    python -m pytest tests/test_golden_queries.py
    python scripts/check_invariants.py
```

## Audit Trail

All violations are logged to:
- `logs/invariant_violations.log` - Runtime violations
- `data/errors/{source}.errors.ndjson` - Ingestion failures
- Sentry/telemetry for production issues

## Change Process

Modifications to this document require:
1. Architecture review
2. Impact analysis on existing data
3. Migration plan if needed
4. Update to validation scripts
5. Approval from rule owner

Last updated: 2025-01-09
Version: 1.0.0
