# Dataset Catalog Schema (v1)

Authoritative specification for the canonical dataset metadata table used to backfill
Neo4j, the orchestrator API, and the Finder UI. The catalog lives under
`configs/datasets/catalog.v1.jsonl` by default and must conform to
`configs/datasets/catalog.schema.json`.

## Field Overview

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `dataset_id` | string | ✅ | Stable identifier, prefixed with namespace (e.g., `ds:openneuro:ds000113`). |
| `name` | string | ✅ | Human-readable dataset title. |
| `short_name` | string |  | Concise label for badges or chips. |
| `alias` | string[] |  | Alternate names / abbreviations. |
| `description` | string |  | Markdown-friendly summary. |
| `modalities` | `DatasetModality[]` | ✅ | Coarse measurement types (MRI, fMRI, EEG, etc.). |
| `acquisitions` | `DatasetAcquisition[]` |  | Fine-grained acquisition tokens (BOLD, T1w, DWI, etc.). |
| `subjects_count` | integer ≥ 0 |  | Approximate number of participants. |
| `sessions_count` | integer ≥ 0 |  | Number of imaging sessions. |
| `species` | string[] | ✅ | Species involved (e.g., `human`, `macaque`). |
| `age_range` | object |  | `{ "min": float, "max": float, "units": "years"|"months" }`. |
| `disease_flags` | string[] |  | Cohort-level diagnoses (ASD, ADHD, AD, etc.). |
| `subject_labels` | string[] |  | Aggregated subject-level labels (e.g., `Diagnosis=ADHD`, `Sex=Female`). |
| `phenotype_summary` | object[] |  | Aggregated phenotype stats per TSV column (counts and optional numeric summary). |
| `annotation_sources` | string[] |  | Provenance for cohort annotations (e.g., `neurobagel_tsv:...`). |
| `annotation_updated_at` | string |  | ISO-8601 timestamp when cohort annotations were refreshed. |
| `center` | string |  | Primary acquisition center / lab. |
| `principal_investigator` | string |  | PI or corresponding author. |
| `consortium` | string |  | Multi-site umbrella program (HCP, ADNI, ENIGMA…). |
| `source_repo` | string | ✅ | Authoritative repository (OpenNeuro, NITRC, OSF, DANDI, LONI, etc.). |
| `source_repo_id` | string |  | Local identifier inside the source repo (e.g., `ds000113`). |
| `primary_url` | URL | ✅ | Landing page for the dataset. |
| `access_type` | `DatasetAccessType` | ✅ | `public`, `registration`, `application`, `restricted`, or `synthetic`. |
| `license` | `DatasetLicense` | ✅ | `CC0`, `CC-BY`, `CC-BY-SA`, `PDDL`, `custom`, or `other`. |
| `approx_size_bytes` | integer ≥ 0 |  | Raw storage footprint in bytes. |
| `size_human` | string |  | Human readable size (e.g., `2.4 TB`). |
| `tags` | string[] |  | Category flags (deep-phenotyping, clinical, population, animal, simulation…). |
| `tasks` | string[] |  | Experimental paradigms / task names (ideally ONVOC-aligned). |
| `modalities_notes` | string |  | Additional notes (e.g., `includes 7T structural scans`). |
| `has_derivatives` | boolean |  | Indicates whether curated derivatives are included. |
| `preview_media` | object[] |  | `{ "kind": "nifti_thumbnail"|"png"|..., "uri": URL, "label": string }`. |
| `created_from` | string |  | Provenance: source spreadsheet or script. |
| `source_version` | string |  | Version stamp for upstream export (e.g., OpenNeuro snapshot). |
| `created_at` | ISO-8601 string |  | Ingestion timestamp. |
| `updated_at` | ISO-8601 string |  | Last refresh timestamp. |

## Enumerations

### DatasetModality
`MRI`, `fMRI`, `DWI`, `T1w`, `T2w`, `ElectronMicroscopy`, `CalciumImaging`, `EEG`, `MEG`, `iEEG`, `ECoG`, `PET`, `MRS`, `Behavior`, `Genomics`, `EHR`, `Simulation`.

### DatasetAcquisition
`BOLD`, `REST`, `T1w`, `T2w`, `FLAIR`, `DWI`, `DTI`, `ASL`, `FieldMap`, `SWI`, `ERP`, `Behavior`.

### DatasetAccessType
`public`, `registration`, `application`, `restricted`, `synthetic`.

### DatasetLicense
`CC0`, `CC-BY`, `CC-BY-SA`, `PDDL`, `custom`, `other`.

### Preview Media Types
Free-form string, but prefer: `nifti_thumbnail`, `png`, `qc_plot`, `connectome`, `timeline`.

## Identity & Constraints

- `dataset_id` is globally unique and MUST remain stable. Format: `<namespace>:<repo>:<local_id>`.
- Add uniqueness constraint in Neo4j: `CREATE CONSTRAINT dataset_id_unique IF NOT EXISTS FOR (d:Dataset) REQUIRE d.dataset_id IS UNIQUE`.
- At least one modality must be present; access_type and license must use the enums above.
- `primary_url` must be HTTPS.

## File Layout

```
configs/datasets/
├── catalog.schema.json        # JSON Schema for validation
├── catalog.v1.jsonl           # Canonical table (newline-delimited JSON)
└── overlays/                  # Storage-specific overrides
```

## Refresh Workflow

1. Aggregate raw sources (xls/csv/JSON dumps) into a staging table.
2. Normalize against the controlled vocabularies listed above.
3. Deduplicate by `dataset_id` (preferred) or `(source_repo, source_repo_id)`.
4. Export to `catalog.v1.jsonl` and run schema validation (`tests/unit/datasets/test_catalog.py`).
5. Run `scripts/tools/etl/load_datasets_to_neo4j.py --from configs/datasets/catalog.v1.jsonl` to upsert nodes.
6. Trigger `/api/datasets/refresh-cache` (or restart orchestrator) so Finder search uses the latest data.

## Future Extensions

- Add ONVOC / CAO identifiers for `tasks` and `constructs`.
- Track `data_access_instructions` for restricted datasets.
- Support per-site contact info for multi-center cohorts.
