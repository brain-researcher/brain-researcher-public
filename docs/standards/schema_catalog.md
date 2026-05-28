# BR-KG Schema Catalog

**Last Updated:** 2025-10-06

This document provides a descriptive catalog of all official node and edge types within the BR-KG. It is intended as a readable guide to the graph's schema. For the strict, immutable rules governing the schema (e.g., ID formats, required fields), please refer to `invariants.md`.

**Current Graph State:**
- **Total Nodes:** 476,889
- **Total Edges:** 51,188
- **Database:** `neurokg_full.db` (424 MB)
- **Detailed Statistics:** See [`neurokg_graph_schema.md`](./neurokg_graph_schema.md)

## Node Types

| Node Type | Description | CURIE / ID Rule | Key Properties | Current Count | Status |
|---|---|---|---|---:|---|
| **Coordinate** | An activation peak in a specific template space. | `coord:<space>:<res>:<x>:<y>:<z>:<study>` | `x`, `y`, `z`, `space`, `resolution` | 318,325 | ✅ Loaded |
| **Publication** | A scientific paper or study. | `pmid:<ID>` or `doi:<DOI>` | `pmid`, `doi`, `title`, `year`, `journal` | 137,535 | ✅ Loaded |
| **Collection** | NeuroVault image collection | `nv:collection:<ID>` | `id`, `name`, `owner`, `doi` | 15,977 | ✅ Loaded |
| **Term** | Cognitive/anatomical term | `term:sha1(<name>)` | `name`, `definition`, `source` | 3,228 | ✅ Loaded |
| **Concept** | A cognitive construct or mental process. | `mesh:<ID>` or `concept:sha1(<name>)` | `id`, `label`, `definition`, `source` | 919 | ✅ Loaded |
| **Task** | An experimental task or paradigm. | `cogat:<ID>` or `task:sha1(<name>)` | `id`, `label`, `description` | 853 | ✅ Loaded |
| **StatisticalMap** | An unthresholded statistical map (e.g., t-map, z-map). Canonical spatial source family; live graph shorthand may appear as `StatsMap`. | `nv:<coll>/<img_id>#<etag>` | `url`, `kind`, `format`, `sha256` | 47 | ⚠️ Partial |
| **Contrast** | An experimental contrast (e.g., A > B). | `contrast:<dataset_id>:<name_hash>` | `name`, `task_id`, `description` | 2 | ⚠️ Minimal |
| **Experiment** | Experimental session | `exp:<ID>` | `id`, `description` | 2 | ⚠️ Minimal |
| **Embedding** | NICLIP text embedding | `emb:<pmid>` | `vector`, `model`, `source` | 1 | ❌ Incomplete |
| **BrainRegion** | Canonical public spatial/anatomy node for substrate readiness. | `<atlas>:<label_index>` or atlas-derived region ID | `id`, `name`, `atlas` | 813 | ✅ Loaded |
| **Region** | Compatibility and future-enrichment atlas region label; no longer the canonical spatial target. | `<atlas>:<name>` (e.g., `schaefer400-7n:L_Cont_7`) | `id`, `label`, `atlas`, `hemisphere` | 86 | ⚠️ Partial |
| **Dataset** | A collection of neuroimaging data. | `openneuro:<ID>` or `doi:<DOI>` | `id`, `doi`, `name`, `source` | 0 | ❌ Not Loaded |
| **Phenotype** | A subject diagnosis, trait, or demographic. | `mesh:<ID>` or `hpo:<ID>` | `label`, `category`, `source` | 0 | ❌ Not Loaded |
| **Subject** | An individual participant in a study. | `sub:<dataset_id>:sha256(<label>)` | `dataset_uid`, `subject_label` | 0 | ❌ Not Loaded |
| **Atlas** | A brain atlas or parcellation scheme. | `atlas:<name>:<version>` | `name`, `version`, `resolution` | 0 | ❌ Not Loaded |
| **Author** | A researcher credited in a publication. | `author:sha256(<name>:<affil_hash>)` | `full_name`, `orcid` | 0 | ❌ Not Loaded |
| **File** | A raw data file (e.g., NIfTI, events.tsv). | `file:<dataset_id>:sha256(<path>)` | `path`, `sha256`, `format`, `size` | 0 | ❌ Not Loaded |

## Edge Types

**Current Edge Count:** 51,188 (very sparse - typically should be 3-10x the node count)

The creation of edges is governed by matching logic and confidence scoring defined as tunable parameters in files under `configs/neurokg/`.

| Edge Type | Path | Description | Matching & Scoring | Status |
|---|---|---|---|---|
| **`HAS_COORDINATE`** | `Publication` → `Coordinate` | The publication reports the activation coordinate. | Direct extraction | ✅ Live literature backbone |
| **`IN_REGION`** | `StatsMap` → `BrainRegion` | Canonical spatial substrate path for voxel-level evidence. | `configs/neurokg/thresholds.yaml` (spatial) | ✅ Live canonical path |
| **`MEASURES`** | `Task` → `Concept` | The task is designed to measure the cognitive concept. | `configs/neurokg/edge_scoring.yaml` | ⚠️ Unknown |
| **`ACTIVATES`** | `Task`/`Concept` → `Region` \| `BrainRegion` | Semantic enrichment edge family; not part of substrate Gate A in the current contract revision. | `configs/neurokg/edge_scoring.yaml` | ⚠️ Partial, nonblocking |
| **`DERIVED_FROM`** | `StatisticalMap` → `Contrast` | The map was generated from the specified contrast. | Direct extraction | ⚠️ Partial |
| **`IMPLEMENTS_TASK`**| `Contrast` → `Task` | The contrast is an implementation of the task. | `configs/neurokg/edge_scoring.yaml` | ⚠️ Minimal |
| **`INCLUDES`** | `Dataset` → `SubjectGroup` | The dataset contains the group of subjects. | Direct extraction | ❌ **Blocked** (no Dataset nodes) |
| **`HAS_PHENOTYPE`** | `Subject` → `Phenotype` | The subject has the specified phenotype. | Direct extraction | ❌ **Blocked** (no Subject nodes) |
| **`PART_OF`** | `BrainRegion` → `BrainRegion` | Canonical anatomy hierarchy target for the current substrate contract. | Atlas-defined | ❌ **Missing on canonical signature** |
| **`CITES`** | `Publication` → `Publication` | Represents the citation network between papers. | Direct extraction | ⚠️ Partial |
| **`SAME_AS`** | `Node` → `Node` | Links two nodes of the same type that represent the same entity. | `configs/neurokg/edge_scoring.yaml` | ⚠️ Unknown |
| **`MAPS_TO`** | `Node` → `Node` | Links two nodes for cross-source or vocabulary mapping. | `configs/neurokg/mappings/` | ⚠️ Unknown |

**Priority Actions:**
1. **Freeze BrainRegion as the canonical public spatial/anatomy node**
2. **Treat `StatsMap -> IN_REGION -> BrainRegion` as the canonical spatial substrate**
3. **Materialize `BrainRegion -> PART_OF -> BrainRegion` as the remaining anatomy blocker**
4. **Keep `Coordinate -> IN_REGION -> Region` only as future enrichment**
