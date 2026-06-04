# Capability Catalog

This directory contains the **capability catalog** for neuroimaging tools used by the Brain Researcher planner.

## Files

- **capabilities.yaml** - Catalog of containerized tools with their capabilities, resources, and container configuration
- **../tools_catalog.json** - Legacy Python tools that are still converted and merged when `BR_PLANNER_INCLUDE_LEGACY=true`
- Schema: `../schemas/capabilities.schema.json` (validates both runtime types)
- Resource Types: `../schemas/resources.schema.json` (auto-generated from code)

## Quick Start

### View Available Tools

```bash
# Active planner runtime is catalog-only
export BR_PLANNER_SOURCE=${BR_PLANNER_SOURCE:-catalog}
export BR_PLANNER_INCLUDE_LEGACY=${BR_PLANNER_INCLUDE_LEGACY:-true}

# Load and explore in Python
python -c "
from brain_researcher.services.agent.planner.catalog_loader import get_capability_index
index = get_capability_index()
print(f'Available tools: {len(index.by_id)}')
print(f'Packages: {list(index.by_package.keys())}')
print(f'Capabilities: {list(index.by_capability.keys())[:10]}')

# Count by runtime
container_count = sum(1 for t in index.by_id.values() if t.runtime_kind == 'container')
python_count = sum(1 for t in index.by_id.values() if t.runtime_kind == 'python')
print(f'Container tools: {container_count}')
print(f'Python tools: {python_count}')
"
```

### Validate Catalog

```bash
# Run validation
python scripts/maintenance/validate_capabilities.py

# Should output:
# ✓ Schema validation passed
# ✓ Successfully loaded N tools
# ✓ All validations PASSED
```

## Adding a New Tool

1. **Add entry to capabilities.yaml**:

```yaml
  - id: package.tool.run
    name: "Tool Name"
    package: package_name  # Must exist in niwrap_containers.yaml
    entrypoint: package.version.tool.run  # NiWrap tool ID
    modality: [smri]  # fmri, smri, dmri, eeg, meg, ieeg, pet
    capabilities: [preprocessing, skull_strip]
    consumes: [volume_3d]
    produces: [volume_3d, mask_path]
    resources:
      cpu_min: 1
      mem_mb_min: 512
      gpu: false
      time_min_default: 2.0
    container:
      package_ref: package_name
      runtime: apptainer
    metadata:
      description: "Brief description"
```

2. **Validate**:

```bash
python scripts/maintenance/validate_capabilities.py
```

3. **Test**:

```bash
pytest tests/unit/planner/ -v
```

## Current Tools

The catalog currently provides **55 tools total**:
- **14 containerized tools** (defined in `capabilities.yaml`)
- **41 Python tools** (auto-converted from `../tools_catalog.json`)

### Containerized Tools (14)

**FSL (5 tools)**:
- BET (Brain Extraction)
- FLIRT (Linear Registration)
- FNIRT (Non-linear Registration)
- FEAT (fMRI Analysis)
- MELODIC (ICA)

**ANTS (3 tools)**:
- Registration
- Brain Extraction
- N4 Bias Field Correction

**AFNI (4 tools)**:
- 3dvolreg (Motion Correction)
- 3dDeconvolve (GLM)
- 3dSkullStrip
- 3dBlurInMask (Spatial Smoothing)

**Other (2 tools)**:
- FreeSurfer mri_convert
- MRtrix mrconvert

### Python Tools (41)

Python analysis tools are automatically converted from `tools_catalog.json` and include:
- Connectivity analysis (Nilearn)
- Statistical analysis
- Visualization
- Data transformations
- BIDS utilities
- Knowledge graph operations

## Schema

All tools must conform to `configs/schemas/capabilities.schema.json`:

### Required Fields
- `id`, `name`, `package`, `runtime_kind`
- `modality[]`, `capabilities[]`
- `consumes[]`, `produces[]`
- `resources{cpu_min, mem_mb_min, gpu, time_min_default}`

### Runtime-Specific Fields
**Container tools** (`runtime_kind: container`):
- `entrypoint` - NiWrap tool ID
- `container{package_ref, runtime}`

**Python tools** (`runtime_kind: python`):
- `python{module, function, entry_type}`

### Valid Modalities
`fmri`, `smri`, `dmri`, `eeg`, `meg`, `ieeg`, `pet`

### Valid Resource Types (24 types)
Auto-generated from `src/brain_researcher/services/shared/planner/models.py`:

`bids_root`, `bvals`, `bvecs`, `clean_eeg`, `connectivity_matrix`, `contacts_mni`, `coord_table`, `epochs`, `events_tsv`, `features_table`, `kg_edges`, `kg_nodes`, `mask_path`, `montage`, `parcellation_labels`, `power_spectra`, `raw_eeg`, `report_html`, `stat_map`, `subject_label`, `surface_mesh`, `timeseries`, `volume_3d`, `volume_4d`

**Note**: Resource types are validated via `resources.schema.json`, which is auto-generated. Run `scripts/maintenance/generate_resources_schema.py` to regenerate.

### Valid Runtimes
`apptainer`, `singularity`, `docker`

## Documentation

For detailed information, see:
- [Catalog README](catalog_README.md)
- [Catalog Loader API](../src/brain_researcher/services/agent/planner/catalog_loader.py)
- [Unit Tests](../tests/unit/planner/)

## Migration Status

**Current State**: PR-1 (Foundations) - ✓ Complete
- ✓ Schema and catalog structure defined
- ✓ 14 atomic containerized tools cataloged
- ✓ Hybrid runtime support (container + Python)
- ✓ Auto-generated resource types schema
- ✓ Legacy tool conversion (41 Python tools)
- ✓ Loader with enrichment and indexing
- ✓ Maintenance validation with schema generation
- ✓ Comprehensive unit tests (25 tests total)
- ✓ Documentation updated

**Tool Coverage**:
- containerized tools from `capabilities.yaml`
- converted Python analysis tools from `tools_catalog.json` when legacy merge is enabled
- combined into one catalog index for planner lookup

**Next Steps**: PR-2 (Selection & Synonyms)
- Synonym loading (intent → operator mapping)
- Catalog-driven tool selection (`choose_tool`)
- Integration with `/api/agent/plan` endpoint

## Environment Variables

- `BR_PLANNER_SOURCE=catalog` - Active runtime planner mode
- `BR_PLANNER_INCLUDE_LEGACY=true` - Include converted Python tools in the catalog index
- `BR_PREFLIGHT_TTL_SECONDS=900` - (Future: PR-2) Preflight cache TTL
- `BR_PREFLIGHT_MAX_LATENCY_MS=1000` - (Future: PR-2) Max preflight latency

## Support

For issues or questions:
- Check validation output: `python scripts/maintenance/validate_capabilities.py`
- Run tests: `pytest tests/unit/planner/ -v`
- See [Catalog README](catalog_README.md)
