# BR-KG Standards Documentation

## Overview

The BR-KG Standards system ensures consistency, quality, and scientific validity across all data ingestion, processing, and storage operations in the Brain Researcher knowledge graph. This documentation covers the standards framework, validation tools, and integration guidelines.

## Quick Start

### Running Validation

```bash
# Run complete standards validation
python scripts/validation/validate_standards.py

# Use the CLI for specific checks
br standards validate                    # Full validation
br standards check-id Publication '{"pmid": "12345678", "title": "Test"}'
br standards show-config thresholds     # View configuration
br standards export-schema --format cypher > schema.cypher
```

### CI/CD Integration

Use the commands below for local validation before merge.
The active repo CI workflow is `.github/workflows/ci.yml`; a dedicated
`validate-standards.yml` workflow is not checked in today.

## Architecture

### Three-Layer Configuration Model

```
┌─────────────────────────────────────┐
│     Hard Invariants (Immutable)     │  → docs/standards/invariants.md
├─────────────────────────────────────┤
│   Stable Defaults (Rarely Changed)  │  → configs/neurokg/*.yaml
├─────────────────────────────────────┤
│    Tunable Parameters (Flexible)    │  → configs/neurokg/thresholds.yaml
└─────────────────────────────────────┘
```

1. **Hard Invariants**: Rules that MUST NOT change without major version bump
2. **Stable Defaults**: Configuration that changes infrequently
3. **Tunable Parameters**: Values that can be adjusted based on validation

## Neuroimage Asset Backlog

Reusable neuroimaging assets now have a machine-readable backlog at
`configs/neurokg/neuroimage_assets_backlog.yaml` with a human summary in
`docs/standards/neuroimage_assets_backlog.md`.

Validate it with:

```bash
python scripts/validation/check_neuroimage_assets_backlog.py
```

## Neuroimaging Workflow Repo Intake

External neuroimaging repositories that are candidates for Brain Researcher
workflow packaging now have a machine-readable intake registry at
`configs/workflows/neuroimaging_repo_intake.yaml` with a human summary in
`docs/standards/neuroimaging_workflow_repo_intake.md`.

Validate it with:

```bash
python scripts/validation/check_neuroimaging_repo_intake.py
```

## Core Components

### 1. Schema Definitions

Located in `src/brain_researcher/services/neurokg/schemas/`:

- `node_schemas.py`: Pydantic models for all node types
- `edge_schemas.py`: Pydantic models for all relationship types

Example usage:
```python
from brain_researcher.services.neurokg.schemas.node_schemas import Publication, validate_node

# Validate a publication
pub_data = {
    "pmid": "12345678",
    "title": "Neural correlates of working memory",
    "year": 2025,
    "prov": {
        "source": "pubmed",
        "method": "api",
        "loader_version": "v1.0"
    }
}

pub = validate_node("Publication", pub_data)
print(pub.id)  # "pmid:12345678"
```

### 2. Mapping Files

Located in `src/brain_researcher/services/neurokg/mappings/`:

- `task_synonyms.yaml`: Task name mappings across sources
- `concept_synonyms.yaml`: Cognitive concept mappings
- `roi_synonyms.yaml`: Brain region name mappings

Example structure:
```yaml
- canonical: "n-back"
  cognitive_atlas_id: "cogat:TRM_4a3fd79d0a5c8"
  synonyms:
    - "N-back"
    - "working memory n-back"
  source_aliases:
    brainmap:
      - "N-BACK WM"
    neurosynth:
      - "nback"
```

### 3. Configuration Files

Located in `configs/neurokg/`:

#### thresholds.yaml
```yaml
linker:
  string_similarity_min: 0.86
  niclip_cos_min: 0.32
  auto_merge_min_score: 0.92

spatial:
  roi_overlap_min_frac: 0.15
  peak_to_roi_max_mm: 6.0
```

#### edge_scoring.yaml
```yaml
weights:
  literature_count: 0.35
  z_overlap: 0.30
  niclip_cosine: 0.25
  user_feedback: 0.10
```

## ID Generation Rules

### Standard ID Format

All entities use deterministic IDs following these patterns:

| Entity Type | ID Format | Example |
|------------|-----------|---------|
| Publication | `pmid:{id}` or `doi:{id}` | `pmid:12345678` |
| Task | `cogat:{id}` or `task:{name}` | `cogat:TRM_123` |
| Concept | `cogat:{id}` or `concept:{label}` | `concept:working_memory` |
| Region | `{atlas}:{name}` | `schaefer400-7n:L_Cont_7` |
| Coordinate | `coord:{space}:{x}_{y}_{z}` | `coord:MNI152_2009c:10_20_30` |
| Dataset | `{source}:{accession}` | `openneuro:ds000001` |

### Synonym Mapping Metadata

The synonym mapping files under `src/brain_researcher/services/neurokg/mappings/`
now carry explicit CURIE-style identifiers alongside the canonical labels:

- `concept_synonyms.yaml` → `concept_id` (e.g., `concept:working_memory`)
- `task_synonyms.yaml` → `task_id` (e.g., `task:n-back`)
- `roi_synonyms.yaml` → `region_id` / `network:` identifiers

These IDs are consumed by ingestion and linking jobs to ensure that downstream
relationships always reference the normalized CURIE form even when the incoming
data uses free-text names.

The auxiliary `scripts/neurostore_task/taxonomy/alias_map.json` has likewise been
simplified to a flat alias → canonical mapping (all lowercase keys), avoiding the
old `comment_*` markers that previously showed up in automated linking.

### ID Generation Implementation

```python
def generate_publication_id(data):
    if data.get('pmid'):
        return f"pmid:{data['pmid']}"
    elif data.get('doi'):
        return f"doi:{data['doi']}"
    else:
        # Fallback to hash
        key = f"{data['title']}-{data.get('year', '')}"
        return hashlib.md5(key.encode()).hexdigest()
```

## Relationship Rules

### Allowed Relationships

Only these relationship types are permitted:

| Relationship | Source → Target | Required Evidence |
|-------------|-----------------|-------------------|
| MEASURES | Task → Concept | Cognitive Atlas or manual curation |
| ACTIVATES | Task/Concept → Region \| BrainRegion | Semantic enrichment; not substrate-gating in the current contract revision |
| HAS_COORDINATE | Publication → Coordinate | Extracted from paper |
| IN_REGION | StatsMap → BrainRegion | Canonical voxel-level spatial substrate |
| PART_OF | BrainRegion → BrainRegion | Canonical anatomy hierarchy target |
| DERIVED_FROM | StatisticalMap → Publication/Contrast | Processing pipeline |
| IMPLEMENTS_TASK | Dataset/Contrast → Task | Task mapping |
| MAPS_TO | Any → Any (same type) | String/embedding similarity |
| SAME_AS | Any → Any (exact type) | High confidence match |

### Spatial Contract

The current canonical spatial contract is:

- `Publication -> HAS_COORDINATE -> Coordinate`
- `StatsMap -> IN_REGION -> BrainRegion`
- `BrainRegion -> PART_OF -> BrainRegion`

The old coordinate-to-region path remains allowed only as future enrichment:

- `Coordinate -> IN_REGION -> Region`

## Data Contracts

### NDJSON Format

All data exchange uses NDJSON with these record types:

#### Node Record
```json
{
  "record_type": "node",
  "entity_type": "Publication",
  "curie": "pmid:12345678",
  "properties": {
    "title": "...",
    "year": 2025
  },
  "prov": {
    "source": "pubmed",
    "loader_version": "v1.0",
    "timestamp": "2025-01-09T10:00:00Z"
  }
}
```

#### Edge Record
```json
{
  "record_type": "edge",
  "edge_type": "MEASURES",
  "source_curie": "task:nback",
  "target_curie": "concept:working_memory",
  "properties": {
    "strength": 0.85,
    "confidence": 0.90
  },
  "prov": {
    "source": "cognitive_atlas",
    "method": "manual",
    "timestamp": "2025-01-09T10:00:00Z"
  }
}
```

## Validation Process

### Automated Checks

1. **ID Generation**: Ensures consistent ID format
2. **Relationship Whitelist**: Validates edge types
3. **Provenance**: Requires complete provenance
4. **Data Contracts**: Validates NDJSON structure
5. **Coordinate Space**: Checks spatial standards
6. **Loader Compliance**: Verifies loader implementation

### Manual Validation

Run validation locally:
```bash
# Full validation
python scripts/validation/validate_standards.py

# Specific checks
python scripts/validation/validate_standards.py --check id-generation
python scripts/validation/validate_standards.py --check relationships
```

### CI/CD Status

There is no dedicated GitHub Actions standards workflow checked in right now.
If you want these checks enforced in automation, wire
`python scripts/validation/validate_standards.py` into `.github/workflows/ci.yml` or
another active workflow.

## Integration Guide

### For Loader Developers

1. **Import schemas**:
```python
from brain_researcher.services.neurokg.schemas.node_schemas import Task, validate_node
```

2. **Use mappings**:
```python
import yaml

with open('configs/legacy/mappings/task_synonyms.yaml') as f:
    task_mappings = yaml.safe_load(f)

def normalize_task_name(name, source):
    for mapping in task_mappings:
        if source in mapping.get('source_aliases', {}):
            if name in mapping['source_aliases'][source]:
                return mapping['canonical']
    return name
```

3. **Apply thresholds**:
```python
with open('configs/neurokg/thresholds.yaml') as f:
    thresholds = yaml.safe_load(f)

similarity_threshold = thresholds['linker']['string_similarity_min']
```

4. **Generate compliant IDs**:
```python
task = Task(
    name="n-back",
    cognitive_atlas_id="cogat:TRM_123",
    prov={...}
)
task.id = task.generate_id()  # Returns "cogat:TRM_123"
```

### For API Developers

1. **Validate input**:
```python
from brain_researcher.services.neurokg.schemas.node_schemas import validate_node

@app.post("/nodes/create")
def create_node(node_type: str, data: dict):
    try:
        node = validate_node(node_type, data)
        # Proceed with creation
    except ValidationError as e:
        return {"error": str(e)}, 400
```

2. **Check relationships**:
```python
from brain_researcher.services.neurokg.schemas.edge_schemas import validate_edge

def create_relationship(edge_type: str, source_id: str, target_id: str):
    edge_data = {
        "source_id": source_id,
        "target_id": target_id,
        "prov": {...}
    }
    edge = validate_edge(edge_type, edge_data)
```

## Troubleshooting

### Common Validation Errors

| Error | Cause | Solution |
|-------|-------|----------|
| "Node accepted without provenance" | Missing prov field | Add complete provenance info |
| "Unknown edge type" | Invalid relationship | Use only whitelisted types |
| "ID generation failed" | Missing required fields | Ensure pmid/doi/name provided |
| "Space must be one of..." | Invalid coordinate space | Use MNI152_2009c or other allowed |

### Debugging Tips

1. **Check validation report**:
```bash
cat validation_report.json | jq '.failed'
```

2. **Test specific loader**:
```python
from scripts.validation.validate_standards import StandardsValidator

validator = StandardsValidator()
validator.check_loader_compliance()
```

3. **Verify mappings**:
```python
# Check if a task name is mapped
import yaml
with open('configs/legacy/mappings/task_synonyms.yaml') as f:
    mappings = yaml.safe_load(f)

task_name = "N-BACK WM"
for m in mappings:
    if task_name in m.get('source_aliases', {}).get('brainmap', []):
        print(f"Maps to: {m['canonical']}")
```

## Best Practices

### Do's
✅ Always provide complete provenance
✅ Use canonical names from mappings
✅ Validate data before database insertion
✅ Run validation before committing
✅ Keep configurations in sync
✅ Document any deviations

### Don'ts
❌ Skip validation in production
❌ Hard-code thresholds
❌ Create custom ID formats
❌ Add unlisted relationship types
❌ Ignore validation warnings
❌ Bypass provenance requirements

## Maintenance

### Updating Standards

1. **Modify invariants** (requires review):
```bash
vim docs/standards/invariants.md
# Update version number
# Document change rationale
```

2. **Adjust thresholds**:
```bash
vim configs/neurokg/thresholds.yaml
# Test with validation script
python scripts/validation/validate_standards.py
```

3. **Add new mappings**:
```bash
vim configs/legacy/mappings/task_synonyms.yaml
# Add new entries maintaining structure
```

### Monitoring

Check validation status:
```bash
# View recent CI runs
gh run list --limit 5

# Regenerate the validation report
python scripts/validation/validate_standards.py
cat validation_report.json | jq '.summary'
```

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-01-09 | Initial standards implementation |
| 1.0.1 | TBD | Added NiCLIP integration standards |
| 1.1.0 | TBD | Multi-tenant support |

## Support

For questions or issues:
1. Check this documentation
2. Run `br standards validate --verbose`
3. Review `docs/standards/invariants.md`
4. Open an issue with validation report

## References

- [Cognitive Atlas](https://www.cognitiveatlas.org/)
- [NeuroVault](https://neurovault.org/)
- [OpenNeuro](https://openneuro.org/)
- [BrainMap](https://brainmap.org/)
- [Schaefer Atlas](https://github.com/ThomasYeoLab/CBIG/tree/master/stable_projects/brain_parcellation/Schaefer2018_LocalGlobal)
