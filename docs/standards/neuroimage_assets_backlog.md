# Neuroimage Assets Backlog

This document tracks reusable neuroimaging assets that already exist in the
repo, assets that are present but not yet standardized, and assets that should
be acquired or normalized next.

The machine-readable source of truth lives at
`configs/neurokg/neuroimage_assets_backlog.yaml`.

## Short Answer

### Do we already have standardized templates?

Partially yes.

The repo already contains local standard template assets under:

- `data/neurokg/raw/neuromaps/atlases/MNI152`
- `data/neurokg/raw/neuromaps/atlases/fsaverage`
- `data/neurokg/raw/neuromaps/atlases/fsLR`
- `data/neurokg/raw/neuromaps/atlases/civet`
- `data/neurokg/raw/neuromaps/atlases/regfusion`

There is also an environment-specific TemplateFlow mount in
`configs/datasets/local_mounts.yaml`.

What is still missing is the remaining product layer that turns those files into
a fully canonical runtime abstraction:

- one template registry
- broader alias-normalization policy
- one transform provenance model

`src/brain_researcher/services/tools/resolve_space_tool.py` is now registry
backed, but the canonical registry/provenance layer is still incomplete.

## Asset Families

The backlog is organized into six families:

1. `dataset_metadata_bids`
2. `templates_spaces_transforms`
3. `atlases_parcellations`
4. `reference_maps_annotations`
5. `derivatives_qc_design`
6. `semantic_provenance_glue`

Each family must cover three states:

- `already_usable`
- `present_not_standardized`
- `missing_and_should_acquire`

That rule is enforced by `scripts/validation/check_neuroimage_assets_backlog.py`.

## Priority Order

### P0: Templates, spaces, and transforms

This comes first because every atlas, surface, and reference map depends on a
stable space and density story. The main goal is to convert the existing local
template and transform files into a canonical registry and a real
`resolve_template`-style runtime surface.

### P1: Atlases and parcellations

The repo already ships several common atlas families and now has registry-backed
`fetch_atlas` and `parcellation_fetch` entry points for local Schaefer, AAL,
Harvard-Oxford, Yeo, Destrieux, BASC, and MSDL volume assets plus current
fsaverage surface annotations. What is still missing is a broader
space-aware, version-aware atlas registry with stronger hierarchy and license
metadata.

### P2: Dataset metadata and BIDS

The dataset catalog is already strong and should remain canonical. The backlog
work here is mostly about normalizing file-level assets such as sidecars,
events, confounds, QC summaries, and masks.

### P3: Reference maps and annotations

The repo already has meaningful local corpora for neuromaps, Neurosynth,
NiMARE, and OpenNeuro GLMFitLins outputs, and now also has a
registry-backed `resolve_reference_map` runtime for the current local cache.
These should still be normalized under one fuller cross-source reference-map
inventory once template and atlas resolution is fixed.

### P4: Derivatives, QC, and design assets

Derivative roots and some BIDS design-export capabilities already exist. What is
missing is a canonical inventory for masks, confounds, QC summaries, and other
subject or group derivative bundles.

### P5: Semantic and provenance glue

Cross-family IDs and alias policy come last. The repo already has useful seeds
for this in dataset tags, tasks, annotation provenance, and some space IDs, but
not yet as a complete asset identity layer.

## Representative Assets

### Already usable

- Canonical dataset catalog: `configs/datasets/catalog.v1.jsonl`
- Dataset resource resolvers: `src/brain_researcher/services/tools/dataset_resources_tool.py`
- BIDS path resolution: `src/brain_researcher/services/tools/resolve_bids_tool.py`
- Local MNI and surface templates: `data/neurokg/raw/neuromaps/atlases/*`
- Local nilearn atlas cache: `data/neurokg/raw/nilearn_atlases`
- Registry-backed atlas fetch/parcellation for current common families: `src/brain_researcher/services/tools/fetch_atlas_tool.py`, `src/brain_researcher/services/tools/parcellation_fetch_tool.py`
- Local neuromaps annotations: `data/neurokg/raw/neuromaps/annotations`
- Local Neurosynth and NiMARE cache: `data/neurosynth_nimare`

### Present but not standardized

- Template and coordinate configs: `configs/neurokg/coordinate_systems.yaml`
- Regfusion transform files: `data/neurokg/raw/neuromaps/atlases/regfusion`
- Nilearn atlas ingestion specs: `src/brain_researcher/core/ingestion/loaders/nilearn_atlas_unified.py`
- Partial atlas/reference registry: `src/brain_researcher/services/tools/reference_asset_registry.py`
- Registry-backed reference-map resolver: `src/brain_researcher/services/tools/resolve_reference_map_tool.py`
- Machine-specific mounts and TemplateFlow root: `configs/datasets/local_mounts.yaml`
- `query_neuromaps` runtime helpers in `src/brain_researcher/services/tools/grandmaster/runtime_tools.py`

### Missing and should acquire

- Unified template registry with alias normalization
- Canonical atlas registry covering family, version, space, density, labels, hierarchy, and license metadata
- File-level BIDS sidecar, confounds, QC, and mask inventory
- Full cross-source reference-map registry across neuromaps, Neurosynth, NiMARE, and local stat maps
- Canonical cross-family asset IDs and alias policy

## Validation

Run:

```bash
python scripts/validation/check_neuroimage_assets_backlog.py
```

The validator checks:

- required fields
- allowed enums
- evidence path existence
- per-family state coverage
- the current standardized-template conclusion
