# Planner Capability Catalog

## Overview

The Brain Researcher planner uses a **capability catalog** to describe containerized neuroimaging tools and enable catalog-driven planning. This document explains how the catalog works and how to add new tools.

## Architecture

The catalog system consists of four main components:

1. **Capabilities Catalog** (`configs/catalog/capabilities.yaml`) - Defines containerized tools with their capabilities, resources, and container configuration
2. **Legacy Tools Catalog** (`configs/tools_catalog.json`) - Python analysis tools that are still converted into catalog capabilities when legacy-tool merge is enabled
3. **JSON Schema** (`configs/schemas/capabilities.schema.json`) - Validates catalog structure with auto-generated resource types
4. **Catalog Loader** (`src/brain_researcher/services/agent/planner/catalog_loader.py`) - Loads, enriches, and indexes tools

Canonical public tool IDs follow the runtime naming contract in [canonical_runtime_tool_ids.md](<repo>/docs/specs/canonical_runtime_tool_ids.md). Legacy planner/catalog aliases remain ingress-only compatibility inputs.

### Active Runtime Mode

Active planner requests are catalog-only. Keep `BR_PLANNER_SOURCE` unset or set to `catalog`.
The separate `legacy` branch in the loader remains for compatibility/testing only and is
not a supported operational mode for `/agent/plan` or `/api/agent/plan`.

```bash
# Active runtime: catalog-only
export BR_PLANNER_SOURCE=catalog

# Control whether converted legacy Python tools are merged into the catalog index
export BR_PLANNER_INCLUDE_LEGACY=true   # Include Python tools (default)
export BR_PLANNER_INCLUDE_LEGACY=false  # Container tools only
```

**Note**: Python tools from `tools_catalog.json` are still automatically converted to
the unified `ToolCapability` format and merged into the catalog index when
`BR_PLANNER_INCLUDE_LEGACY=true`.

## Catalog-Driven Selection (PR-2)

PR-2 adds **intelligent tool selection** using natural language queries, synonyms, preflight checks, and multi-factor scoring.

### Selection Flow

```
Query → Synonym Matching → Catalog Search → Preflight Checks → Scoring → Ranked Results
```

1. **Synonym Expansion** (`synonyms_loader.py`)
   - Maps natural language to canonical operators (e.g., "skull strip" → `skull_strip`)
   - Supports modality scoping (e.g., `connectome@fmri`)
   - Priority: op_synonyms.yaml > task > concept > roi

2. **Preflight Validation** (`preflight.py`)
   - Container: Image accessibility (CVMFS, local paths)
   - Python: Module importability
   - Returns pass/fail + detail messages

3. **Multi-Factor Scoring** (`selection.py`)
   - Intent match: 40% (synonym confidence + rank)
   - Preflight: 30% (binary pass/fail)
   - Description relevance: 20% (keyword matching)
   - Metadata quality: 10% (docs, runtime preference)

## Performance & Materialization (PR-3)

PR-3 adds **caching, enhanced scoring, and plan materialization** for improved performance and richer candidate information.

### New Features

1. **Preflight Caching** (`cache.py`, `preflight.py`)
   - Redis-backed caching with automatic in-memory fallback
   - TTL-based expiration (default: 15 minutes, configurable via `BR_PREFLIGHT_TTL_SECONDS`)
   - Batch operations with concurrent execution (ThreadPoolExecutor)
   - Automatic cache key generation from tool configuration

   ```python
   from brain_researcher.services.agent.planner.cache import clear_preflight_cache

   # Clear cache when tools change
   clear_preflight_cache()
   ```

2. **Enhanced 5-Factor Scoring** (`selection.py`)
   - **Intent match**: 35% (default, configurable)
   - **Preflight**: 25% (availability/readiness)
   - **Description**: 20% (relevance to query)
   - **Metadata**: 10% (documentation quality)
   - **Resource fit**: 10% (NEW - container/CVMFS/dependencies)

   **Configurable via YAML** (`configs/planner/scoring_weights.yaml`) or environment variables:
   ```bash
   export BR_SCORE_WEIGHT_INTENT_MATCH=0.40
   export BR_SCORE_WEIGHT_PREFLIGHT=0.30
   export BR_SCORE_WEIGHT_RESOURCE_FIT=0.15
   ```

3. **Narrative Explanations** (`selection.py`)
   - Auto-generated brief explanations for each candidate
   - Examples: "Excellent match for query; ready to use; all resources available"
   - Exposed in candidate `explanation` field and `explain_selection()` function

4. **Plan Materializer** (`materializer.py`)
   - Converts `SelectionCandidate` → structured `Plan/PlanDAG`
   - Support for single-step and multi-step plans
   - Includes alternatives and confidence scores
   - Lightweight `create_plan_preview()` for UI display

### Configuration Files

**Preflight Cache** (`configs/planner/preflight.yaml`):
```yaml
cache:
  ttl_seconds: 900        # 15 minutes
  use_redis: true         # Falls back to in-memory

checks:
  container:
    enabled: true
    cvmfs:
      check_mount: true
      trust_mount: true
  python:
    enabled: true
    cache_imports: true
```

**Scoring Weights** (`configs/planner/scoring_weights.yaml`):
```yaml
weights:
  intent_match: 0.35
  preflight: 0.25
  description: 0.20
  metadata: 0.10
  resource_fit: 0.10      # NEW in PR-3
```

### API Usage

**Catalog Mode** (recommended):
```python
# POST /api/agent/plan
{
  "query": "skull strip T1 image",
  "modality": "smri",           # Optional: fmri, smri, dmri, etc.
  "max_results": 10,
  "require_preflight_pass": true,
  "mode": "catalog"
}

# Response
{
  "plan_id": "uuid",
  "candidates": [
    {
      "tool": {"id": "fsl_bet", "name": "BET", ...},
      "final_score": 0.87,
      "intent_match_score": 0.95,
      "preflight_passed": true,
      ...
    }
  ],
  "selected": {...}  // Best candidate
}
```

**Legacy Mode** (template-based):
```python
{
  "intent": "skull strip",
  "mode": "legacy"
}
```

### Synonym Configuration

Edit `configs/legacy/mappings/op_synonyms.yaml`:

```yaml
skull_strip:
  - "skull strip"
  - "brain extraction"
  - "remove skull"
  - "bet"

# Modality-scoped operators
connectome@fmri:
  - "functional connectivity"
  - "resting state connectivity"
```

### Environment Variables

- `BR_PLANNER_SOURCE`: keep unset or `catalog` for active runtime requests
- `BR_PLANNER_INCLUDE_LEGACY`: include converted Python tools in the catalog index
- `BR_PLANNER_MODE`: `advisor`, `autorun`, or `disabled`

## Catalog Structure

### capabilities.yaml

The catalog is a YAML file with the following structure:

```yaml
version: "0.1.0"

tools:
  # Container tool example
  - id: fsl_bet                         # Canonical runtime tool identifier
    name: "FSL BET"                     # Human-readable name
    package: fsl                        # Package name (from niwrap_containers.yaml)
    runtime_kind: container             # Runtime type: container or python
    entrypoint: fsl.6.0.7.bet.run       # Adapter-private NiWrap descriptor
    modality: [smri, fmri]              # Supported imaging modalities
    capabilities: [skull_strip, preprocessing]  # What the tool does
    consumes: [volume_3d, volume_4d]    # Input resource types
    produces: [volume_3d, mask_path]    # Output resource types
    resources:
      cpu_min: 1
      mem_mb_min: 512
      gpu: false
      time_min_default: 2.0
      scaling_hints:                    # Optional: parameter-based scaling
        - param: input_file_size_mb
          mem_mb_per_unit: 2
          time_min_per_unit: 0.01
    container:
      package_ref: fsl                  # Reference to niwrap_containers.yaml
      runtime: apptainer
    metadata:                           # Optional documentation
      description: "Brain extraction tool..."
      literature:
        - "Smith SM. (2002). Fast robust..."

  # Python tool example (usually auto-converted from tools_catalog.json)
  - id: connectivity_matrix
    name: "Nilearn Connectivity Matrix"
    package: python
    runtime_kind: python                # Python runtime
    modality: [fmri]
    capabilities: [connectivity, analysis]
    consumes: [timeseries]
    produces: [connectivity_matrix]
    resources:
      cpu_min: 2
      mem_mb_min: 1024
      gpu: false
      time_min_default: 5.0
    python:
      module: brain_researcher.services.neuroimaging
      function: nilearn_connectivity_matrix
      entry_type: function              # or "class"
```

### Field Descriptions

#### Required Fields

- **id**: Unique public identifier
  - Canonical runtime tools: `snake_case` (e.g., `fsl_bet`)
  - Adapter-private descriptors may still use NiWrap-style `package.tool.run`
- **name**: Human-readable tool name
- **package**: Parent package
  - Container tools: Must match `niwrap_containers.yaml` entry (e.g., `fsl`, `ants`)
  - Python tools: Use `python`
- **runtime_kind**: Tool runtime type
  - `container`: Containerized tool (NiWrap/Apptainer)
  - `python`: Native Python function
- **modality**: Array of supported modalities (`fmri`, `smri`, `dmri`, `eeg`, `meg`, `ieeg`, `pet`)
- **capabilities**: Array of capability tags describing what the tool does
- **consumes**: Array of input resource types
- **produces**: Array of output resource types
- **resources**: Resource requirements (CPU, memory, GPU, time)

#### Runtime-Specific Fields

**For Container Tools** (`runtime_kind: container`):
- **entrypoint**: NiWrap tool ID used for execution
- **container**: Container configuration with `package_ref` and `runtime`

**For Python Tools** (`runtime_kind: python`):
- **python**: Python execution configuration
  - `module`: Python module path (e.g., `brain_researcher.services.neuroimaging`)
  - `function`: Function or class name
  - `entry_type`: `function` or `class` (default: `function`)

#### Optional Fields

- **metadata**: Documentation (description, authors, literature, URLs)
- **constraints**: Tool-specific constraints

### Resource Types

Valid resource types for `consumes` and `produces` (auto-generated from `src/brain_researcher/services/shared/planner/models.py`):

**Imaging Data**:
- `volume_3d`, `volume_4d` - 3D/4D volumes (NIfTI)
- `surface_mesh` - Surface meshes
- `parcellation_labels` - Parcellation/atlas labels
- `mask_path` - Binary masks

**Derived Data**:
- `timeseries` - Time series data
- `connectivity_matrix` - Connectivity matrices
- `stat_map` - Statistical maps
- `power_spectra` - Frequency spectra
- `features_table` - Feature matrices
- `coord_table` - Coordinate tables

**BIDS & Metadata**:
- `bids_root` - BIDS dataset root
- `subject_label` - Subject identifiers
- `events_tsv` - Task events
- `bvals`, `bvecs` - Diffusion parameters

**Electrophysiology**:
- `raw_eeg`, `clean_eeg` - EEG recordings
- `epochs` - Epoched data
- `montage` - Electrode montages
- `contacts_mni` - Electrode coordinates

**Knowledge Graph**:
- `kg_nodes`, `kg_edges` - Graph data

**Reports**:
- `report_html` - HTML reports

**Note**: Resource types are validated via `configs/schemas/resources.schema.json`, which is auto-generated from the canonical ResourceType enum. Run `scripts/ci/generate_resources_schema.py` to regenerate after adding new types to `models.py`.

### Capability Tags

Capability tags describe what a tool does. Use consistent, descriptive tags:

**Preprocessing**: `skull_strip`, `bias_correction`, `preprocessing`, `format_conversion`

**Registration**: `registration`, `linear_registration`, `nonlinear_registration`, `alignment`, `motion_correction`

**Analysis**: `glm`, `ica`, `decomposition`, `statistical_analysis`, `first_level`

**Spatial Operations**: `smooth`, `spatial_smooth`, `resample`

**Segmentation**: `segmentation`, `parcellation`

## Adding a New Tool

### Step 1: Check Prerequisites

1. Tool must be available in a NiWrap container
2. Package must be defined in `configs/niwrap_containers.yaml`
3. Tool should have clear inputs/outputs

### Step 2: Add to capabilities.yaml

Add a new entry to `configs/catalog/capabilities.yaml`:

```yaml
  - id: ants_atropos
    name: "ANTS Atropos Segmentation"
    package: ants
    entrypoint: ants.2.6.0.Atropos.run
    modality: [smri]
    capabilities: [segmentation, tissue_classification]
    consumes: [volume_3d]
    produces: [volume_3d, parcellation_labels]
    resources:
      cpu_min: 2
      mem_mb_min: 4096
      gpu: false
      time_min_default: 15.0
    container:
      package_ref: ants
      runtime: apptainer
    metadata:
      description: "Multi-atlas segmentation with prior probability maps"
      literature:
        - "Avants BB, et al. (2011). An open source multivariate framework..."
```

### Step 3: Validate

Run the validation script to ensure your entry is correct:

```bash
python scripts/ci/validate_capabilities.py
```

This will check:
- JSON schema compliance
- Pydantic model validation
- Required fields
- Enum values
- Resource constraints

### Step 4: Test

Add tests for the new tool if it introduces new patterns:

```python
def test_new_tool_loading():
    """Test that new tool loads correctly."""
    with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"}):
        get_capability_index.cache_clear()
        tool = get_tool_by_id("ants_atropos")
        assert tool is not None
        assert "segmentation" in tool.capabilities
```

### Step 5: Document

If the tool introduces new capability tags or patterns, update this guide.

## Container Configuration

### Package References

The `container.package_ref` field references entries in `configs/niwrap_containers.yaml`:

```yaml
# In niwrap_containers.yaml
ants:
  image: "/cvmfs/neurodesk.ardc.edu.au/containers/ants_2.6.0_20250424/ants_2.6.0_20250424.simg"
  image_is_directory: true
  runtime: "apptainer"
  binds:
    - "/data:/data"
    - "/tmp:/tmp"
  env: {}
  network_disabled: true
```

The loader automatically enriches tools with this container configuration.

### License Requirements

Some tools require licenses (e.g., FreeSurfer):

```yaml
container:
  package_ref: freesurfer
  runtime: apptainer
  require_license: true
```

## Catalog Loader API

### Loading and Indexing

```python
from brain_researcher.services.agent.planner.catalog_loader import (
    get_capability_index,
    get_tool_by_id,
    search_by_capability,
    search_by_modality,
    search_by_package,
)

# Get full index (cached)
index = get_capability_index()

# Get specific tool
tool = get_tool_by_id("fsl_bet")

# Search by capability
skull_strip_tools = search_by_capability("skull_strip")

# Search by modality
fmri_tools = search_by_modality("fmri")

# Search by package
fsl_tools = search_by_package("fsl")
```

### Index Structure

The `CapabilityIndex` provides fast lookups:

- `by_id`: Dict mapping tool ID to `ToolCapability`
- `by_capability`: Dict mapping capability tag to list of tool IDs
- `by_modality`: Dict mapping modality to list of tool IDs
- `by_package`: Dict mapping package name to list of tool IDs
- `by_resource_type`: Dict mapping resource type to list of tool IDs

## CI/CD Integration

### Automated Validation

The catalog is validated in CI on every PR. The validation pipeline includes:

1. **Resource Schema Generation**: Auto-generates `resources.schema.json` from canonical source
2. **JSON Schema Validation**: Validates YAML against schema with $ref resolution
3. **Pydantic Model Validation**: Loads tools via catalog_loader to verify model correctness

To run locally:

```bash
# Run full validation pipeline (includes schema generation)
python scripts/ci/validate_capabilities.py

# Generate resource schema only
python scripts/ci/generate_resources_schema.py

# Run unit tests
pytest tests/unit/planner/ -v

# Run specific test suites
pytest tests/unit/planner/test_hybrid_merge.py -v
pytest tests/unit/planner/test_resources_schema_generation.py -v

# Run with coverage
pytest tests/unit/planner/ --cov=brain_researcher.services.agent.planner --cov-report=term-missing
```

### Pre-commit Hooks

Add to `.pre-commit-config.yaml`:

```yaml
  - repo: local
    hooks:
      - id: validate-capabilities
        name: Validate capabilities catalog
        entry: python scripts/ci/validate_capabilities.py
        language: system
        pass_filenames: false
        files: ^configs/catalog/capabilities\.yaml$
```

## Best Practices

### Tool Naming

- Use lowercase package names: `fsl`, `ants`, `afni`
- Public tool IDs follow `snake_case` runtime names such as `fsl_bet`
- Use descriptive, concise names

### Capability Tags

- Use existing tags when possible (check other tools)
- Use underscores: `skull_strip` not `skull-strip`
- Be specific: `linear_registration` vs `registration`

### Resource Estimates

- Start conservative (higher CPU/memory)
- Add scaling hints for parameters that affect resources
- Test with representative data

### Documentation

- Always include `metadata.description`
- Add literature citations for published tools
- Include URLs for tool documentation

## Troubleshooting

### Validation Errors

**Schema validation failed**:
- Check field names match schema exactly
- Ensure required fields are present
- Verify enum values (modality, runtime, resource types)

**Pydantic validation failed**:
- Check resource constraints (CPU 1-32, memory 128-131072 MB)
- Ensure the public tool ID is a lowercase `snake_case` runtime name
- Verify all required fields are present

### Loading Errors

**Tool not found**:
- Ensure active runtime is using catalog mode (`BR_PLANNER_SOURCE` unset or `catalog`)
- Clear LRU cache: `get_capability_index.cache_clear()`
- Check tool ID is spelled correctly

**Container not enriched**:
- Verify `package_ref` exists in `niwrap_containers.yaml`
- Check package name matches exactly (case-sensitive)

## Hybrid Runtime Support

### Automatic Legacy Tool Conversion

The planner supports **hybrid catalog loading** where Python analysis tools from
`tools_catalog.json` are automatically converted to the unified `ToolCapability`
format and merged with containerized tools.

**How it works**:
1. Container tools are loaded from `capabilities.yaml`
2. Python tools are loaded from `tools_catalog.json`
3. Python tools are converted via `legacy_tool_to_capability()`:
   - legacy `domain` + `name` fields are normalized into a canonical runtime tool ID
   - `consumes`/`produces` Dict → converted to List
   - Generates `PythonRunnerSpec` with module/function mapping
   - Applies default resource constraints if not specified
4. Both tool types are merged into a unified index

**Result**: Catalog mode provides containerized tools plus any converted Python tools
enabled by `BR_PLANNER_INCLUDE_LEGACY`.

### Tool ID Patterns

- **Canonical runtime tools**: `snake_case` (e.g., `fsl_bet`)
- **Compatibility aliases**: legacy planner/catalog IDs accepted only at ingress

### Feature Flags

Control which tools are loaded:

```bash
# Default: include both container and Python tools in the catalog index
export BR_PLANNER_SOURCE=catalog
export BR_PLANNER_INCLUDE_LEGACY=true

# Container tools only
export BR_PLANNER_SOURCE=catalog
export BR_PLANNER_INCLUDE_LEGACY=false
```

### Future Migration

Python tools can be manually added to `capabilities.yaml` for better control over resource estimates and metadata. The conversion process provides sensible defaults but manual entries allow for optimization.

## References

- [NiWrap Documentation](https://github.com/childmindresearch/niwrap)
- [Catalog User Guide](../catalog_README.md) - Quick reference and tool listings
- [Capabilities Schema](../../configs/schemas/capabilities.schema.json)
- [Example Tools](../../configs/catalog/capabilities.yaml)
- [Loader Implementation](../../src/brain_researcher/services/agent/planner/catalog_loader.py)
