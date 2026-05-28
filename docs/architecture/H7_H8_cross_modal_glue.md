# H7/H8: Cross-Modal Glue + BIDS Resolvers

## Overview

This layer provides standardized tools for cross-modal integration in neuroimaging pipelines. The H7/H8 implementation enables seamless data flow across modalities (fMRI, iEEG, dMRI, sMRI, PET) through coregistration, parcellation management, and BIDS-compliant data resolution.

## Motivation

Multimodal neuroimaging workflows require:
- **Spatial alignment** between modalities (CT→MRI for iEEG, fMRI→T1w for analysis)
- **Standardized atlases** available across pipelines
- **BIDS-compliant data access** without hardcoding paths
- **Flexible plan augmentation** via declarative helpers

Without these tools, each modality pipeline would need to implement its own resolution logic, leading to code duplication and inconsistent behavior.

## Tools

### Coregistration

#### `coreg_register`
**Purpose**: Compute transformation matrix between two images.

**Use Cases**:
- iEEG: Register CT to MRI for electrode localization
- fMRI: Align functional to anatomical images
- PET: Coregister tracer uptake to structural scan

**Args**:
- `moving_image`: Image to be transformed
- `fixed_image`: Reference image defining target space
- `cost_function`: Mutual information (mi), normalized MI (nmi), correlation ratio

**Outputs**:
- `transform_matrix`: Transformation parameters
- `registered_image`: Moving image resampled into fixed space

**Example**:
```python
StepSpec(
    tool="coreg_register",
    consumes={"moving_image": "ct_image", "fixed_image": "mri_image"},
    produces={"transform_matrix": "ct_to_mri_xfm", "registered_image": "ct_in_mri"},
    params={"cost_function": "mi"},
)
```

#### `coreg_apply_xfm`
**Purpose**: Apply pre-computed transformation to a volume.

**Use Cases**:
- Transfer atlas from template space to subject space
- Apply inverse transform to map results back to native space

**Args**:
- `input_volume`: Volume to transform
- `transform_matrix`: Pre-computed transformation
- `reference_image`: Defines output space/resolution
- `interpolation`: trilinear (default), nearest (for labels), spline

**Outputs**:
- `transformed_volume`: Input resampled into reference space

**Example**:
```python
StepSpec(
    tool="coreg_apply_xfm",
    consumes={"input_volume": "atlas", "transform_matrix": "xfm", "reference_image": "dwi"},
    produces={"transformed_volume": "atlas_in_dwi"},
    params={"interpolation": "nearest"},
)
```

### Parcellation Management

#### `parcellation_fetch`
**Purpose**: Retrieve standard brain parcellation from library (stub: returns paths to standard atlases).

**Use Cases**:
- dMRI connectome analysis requires parcellation labels
- ROI-based analysis needs atlas definitions
- Network analysis requires consistent node definitions

**Args**:
- `atlas_name`: Schaefer2018_200, aparc+aseg, DKT, etc.
- `space`: MNI152NLin2009cAsym (default), MNI152NLin6Asym, fsaverage
- `resolution`: 1mm, 2mm (default)

**Outputs**:
- `parcellation_volume`: NIfTI volume with integer labels
- `labels_tsv`: TSV mapping label IDs to region names

**Example**:
```python
StepSpec(
    tool="parcellation_fetch",
    params={"atlas_name": "Schaefer2018_200", "space": "MNI152NLin2009cAsym"},
    produces={"parcellation_volume": "atlas", "labels_tsv": "labels"},
)
```

#### `label_transfer`
**Purpose**: Transfer parcellation labels from one space to another via transformation.

**Use Cases**:
- Apply template-space atlas to subject-native images
- Transfer surface labels to volume space

**Args**:
- `source_labels`: Parcellation in source space
- `transform_matrix`: Transformation to target space
- `reference_image`: Target space definition
- `interpolation`: nearest (preserves integer labels)

**Outputs**:
- `transferred_labels`: Labels resampled into target space

**Example**:
```python
StepSpec(
    tool="label_transfer",
    consumes={"source_labels": "atlas_mni", "transform_matrix": "mni_to_native", "reference_image": "t1w"},
    produces={"transferred_labels": "atlas_native"},
)
```

### BIDS Resolution

#### `resolve_bids`
**Purpose**: Query BIDS dataset structure to locate files for a given subject/modality.

**Use Cases**:
- Automatic file discovery in derivatives directories
- Consistent path construction across pipelines
- Handle optional session/run/space parameters

**Args**:
- `bids_root`: BIDS dataset root directory
- `subject_id`: Subject identifier (without 'sub-' prefix)
- `datatype`: anat, func, dwi, ieeg, eeg, meg
- `suffix`: T1w, bold, dwi, eeg, etc.
- `space`: (optional) For derivatives with spatial reference
- `desc`: (optional) Description label

**Outputs**:
- `resolved_path`: Full path to matched file
- `metadata`: Extracted BIDS entities (subject, session, space, etc.)

**Example**:
```python
StepSpec(
    tool="resolve_bids",
    consumes={"bids_root": "bids_root", "subject_id": "subject_id"},
    params={"datatype": "anat", "suffix": "T1w"},
    produces={"resolved_path": "t1w_path"},
)
```

#### `resolve_space`
**Purpose**: Fetch standard spatial template (e.g., MNI152) and associated files.

**Use Cases**:
- Normalization workflows need template image
- Statistical analysis requires brain mask in template space
- Group analysis requires common reference

**Args**:
- `space_name`: MNI152NLin2009cAsym, MNI152NLin6Asym, fsaverage, etc.
- `resolution`: 1mm, 2mm (default)

**Outputs**:
- `template_volume`: T1-weighted template image
- `brain_mask`: Binary mask defining brain voxels

**Example**:
```python
StepSpec(
    tool="resolve_space",
    params={"space_name": "MNI152NLin2009cAsym", "resolution": "2mm"},
    produces={"template_volume": "mni_template", "brain_mask": "mni_mask"},
)
```

## Planner Helper Functions

### `_maybe_add_resolvers(steps, artifacts, inputs, requires_bids=False, requires_space=False)`
**Purpose**: Conditionally prepend BIDS or space resolver steps to a plan.

**Usage**:
```python
def _build_my_plan(plan_request):
    steps = []
    artifacts = []
    inputs = plan_request.inputs

    # Add resolvers if needed
    _maybe_add_resolvers(steps, artifacts, inputs, requires_bids=True)

    # Add pipeline-specific steps
    steps.append(StepSpec(tool="my_analysis", ...))
```

### `_ensure_space(steps, artifacts, inputs, target_space, insert_at=0)`
**Purpose**: Ensure a spatial template exists in the plan, inserting resolver step if missing.

**Returns**: Artifact name for the template (e.g., "MNI152NLin2009cAsym_template")

**Usage**:
```python
template_artifact = _ensure_space(steps, artifacts, inputs, "MNI152NLin2009cAsym", insert_at=0)
# Use template_artifact in subsequent steps
```

## Usage Patterns

### Pattern 1: iEEG Electrode Localization with Coregistration

**Problem**: CT and MRI are in different coordinate systems; electrode coordinates must be accurate.

**Solution**: Register CT to MRI before localizing electrodes.

```python
steps = [
    # H7: Coregistration
    StepSpec(
        tool="coreg_register",
        consumes={"moving_image": "ct_image", "fixed_image": "mri_image"},
        produces={"transform_matrix": "ct_to_mri_xfm", "registered_image": "ct_in_mri"},
        params={"cost_function": "mi"},
    ),
    # Original pipeline step, now using registered CT
    StepSpec(
        tool="ieeg_electrode_localize",
        consumes={"ct_image": "ct_in_mri", "mri_image": "mri_image"},
        produces={"contacts_mni": "contacts_mni"},
    ),
]
```

### Pattern 2: dMRI Connectome with Standard Atlas

**Problem**: User provides atlas name but not file path; planner must fetch atlas.

**Solution**: Insert parcellation_fetch step before connectome construction.

```python
steps = [
    StepSpec(
        tool="dmri_resolve_dwi_triplet",
        produces={"dwi_image": "dwi", "bvals": "bvals", "bvecs": "bvecs"},
    ),
    StepSpec(
        tool="dmri_fit_model",
        consumes={"dwi_image": "dwi"},
        produces={"fodf": "fodf"},
    ),
    # H7: Fetch standard parcellation
    StepSpec(
        tool="parcellation_fetch",
        params={"atlas_name": "Schaefer2018_200", "space": "MNI152NLin2009cAsym"},
        produces={"parcellation_volume": "atlas", "labels_tsv": "labels"},
    ),
    StepSpec(
        tool="dmri_parcellate_connectome",
        consumes={"fodf": "fodf", "parcellation_labels": "atlas"},
        produces={"connectivity_matrix": "connectome"},
    ),
]
```

### Pattern 3: Cross-Space Label Transfer

**Problem**: Atlas is in MNI space but DWI is in native subject space.

**Solution**: Use label_transfer to warp atlas into DWI space.

```python
steps = [
    # Compute subject→MNI transform
    StepSpec(tool="coreg_register", ...),
    # Fetch MNI atlas
    StepSpec(tool="parcellation_fetch", produces={"parcellation_volume": "atlas_mni"}),
    # Transfer to native space (inverse transform)
    StepSpec(
        tool="label_transfer",
        consumes={"source_labels": "atlas_mni", "transform_matrix": "inv_xfm", "reference_image": "dwi"},
        produces={"transferred_labels": "atlas_native"},
        params={"interpolation": "nearest"},
    ),
]
```

## Implementation Status

**Status**: ✅ **Implemented (stubs + planner integration + tests)**

**Files**:
- Tool stubs: `src/brain_researcher/services/tools/coreg_*.py`, `parcellation_*.py`, `resolve_*.py`
- Registry: `src/brain_researcher/services/tools/auto.py` (6 new entries)
- Catalog: `configs/tools_catalog.json` (6 new tool specs)
- Planner helpers: `src/brain_researcher/services/agent/web_service.py`
- Tests: `tests/unit/agent/test_planner_contract.py`, `test_modality_stub_tools.py`

**Test Coverage**:
- 6 smoke tests verify tool execution
- 3 contract tests verify plan augmentation (iEEG coreg, dMRI atlas fetch, registry)
- All 11 contract tests + 14 smoke tests passing

## Testing

All tools have:
- **Stub implementations** returning mock paths/metadata
- **Contract tests** verifying correct insertion into plans
- **Smoke tests** verifying tool execution succeeds

Run tests:
```bash
pytest tests/unit/agent/test_modality_stub_tools.py -v  # 14 tests
pytest tests/unit/agent/test_planner_contract.py -v     # 11 tests
```

## Design Decisions

### Why Stub-First?
Real implementations require neuroimaging libraries (FSL, ANTs, TemplateFlow). Stubs enable:
- Testing planner logic without dependencies
- Contract verification without heavyweight computation
- Rapid prototyping and iteration

### Why Use `volume_3d` for Transform Matrices?
Avoids adding new ResourceType enum value (`transform_matrix`) which would require schema changes. Using existing type maintains backward compatibility while serving the same purpose (representing file paths).

### Why Helper Functions?
Declarative helpers (`_maybe_add_resolvers`, `_ensure_space`) enable:
- Plan augmentation without modifying every builder
- Consistent behavior across modalities
- Easy addition of new resolvers (e.g., `requires_bem=True` for MEG/EEG)

## Future Enhancements

1. **Real Implementations**: Replace stubs with FSL/ANTs/pybids backends
2. **Caching**: Detect duplicate resolver steps and reuse artifacts
3. **Automatic Insertion**: Analyze tool IO to automatically insert resolvers when needed
4. **Space Compatibility**: Validate space requirements across tool chains
5. **TemplateFlow Integration**: Connect `parcellation_fetch` and `resolve_space` to TemplateFlow API

## References

- H1 (EEG/MEG): `docs/issues/09_move_planning_into_agent.md:154-186`
- H2 (iEEG): `docs/issues/09_move_planning_into_agent.md:188-216`
- H3 (dMRI): `docs/issues/09_move_planning_into_agent.md:218-250`
- Planner architecture: `docs/issues/09_move_planning_into_agent.md:1-128`
