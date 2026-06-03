# BR-KG Ingestion Modes

This document defines the ingestion modes used across the BR-KG pipelines,
what each mode is expected to persist in Neo4j, and how data sources should
declare their behaviour in configuration.

## Overview

Every data source is assigned to one of three modes:

| Mode | Purpose | Persistence strategy |
| ---- | ------- | -------------------- |
| **Full** | Canonical ontology / blueprint data, small and high-value, required for reasoning. | Persist the complete, curated representation (still flattened so Neo4j only stores primitives/arrays). |
| **Spine** | Provide a “search spine” – minimal metadata and key relationships that enable traversal and evidence lookup. Used for large or frequently updated sources. | Store only whitelisted fields and graph edges needed for navigation; omit bulky/free-text payloads. Additional details are fetched on demand. |
| **On-demand** | Extremely large, fast-changing, or licensed data. The graph stores no primary data – instead we register an adapter that fetches the information when asked. | Nothing is written to Neo4j during ingestion. Adapters return results at query time, optionally caching them outside the graph. |

The aim is to keep BR-KG lean, trustworthy, and perfect for assisting search:

- **Full** builds the high-confidence backbone (e.g. Cognitive Atlas tasks/concepts).
- **Spine** provides just enough to join everything else together (e.g. Publication metadata, coordinates, dataset pointers).
- **On-demand** lets downstream consumers enrich the graph at query time without bloating storage.

## Field Whitelist (Spine mode)

To prevent accidental “full ingestion” creep, Spine mode is restricted to a small field set per entity type:

| Entity | Allowed fields |
| ------ | -------------- |
| Task | `id`, `name`, `synonyms[]` |
| Concept | `id`, `label`, `synonyms[]` |
| Publication | `id`, `pmid?`, `doi?`, `title`, `year?`, `journal?` |
| Coordinate | `id`, `space`, `round_mm`, `x`, `y`, `z` |
| Region | `id`, `atlas`, `name`, `aliases[]` |
| Dataset | `id`, `name?`, `license?`, `modalities[]`, `tasks[]?`, `n_subjects?`, `TR?`, `TE?`, `url?` |
| StatisticalMap | `id`, `space`, `modality`, `uri`, `etag?`, `experiment_type?` |
| Phenotype (Neurobagel) | `id`, `name`, `value_type?` |

Only the following relationship types are persisted in Spine mode:
`MEASURES`, `HAS_COORDINATE`, `IN_REGION`, `REPORTS_TASK`, `IMPLEMENTS_TASK`,
`DERIVED_FROM`, `SAME_AS`, `MAPS_TO`, `HAS_PHENOTYPE`.

Any additional information should either be JSON-stringified into a single
auxiliary field (e.g. `evidence_json`) or fetched through an on-demand adapter.

## Data Source Classification

| Source | Mode | Stored content | On-demand lookups |
| ------ | ---- | -------------- | ----------------- |
| Cognitive Atlas | Full | Tasks, concepts, measures, synonyms | — |
| Nilearn Atlases / TemplateFlow metadata | Full | Regions, hierarchies, spatial definitions | Download atlas NIfTI files when needed |
| Neurobagel (phenotype mapping) | Full | Subject ↔ Phenotype mappings, variable aliases | Raw distribution tables |
| NeuroSynth | Spine | Publication spine, coordinates, vocabulary | Abstracts / full text (via PubMed) |
| PubMed | Spine | Minimal metadata (title, journal, year) | Abstracts, MeSH, references (real-time) |
| NeuroVault | Spine | Statistical map pointers, provenance edges | NIfTI files on demand |
| OpenNeuro | Spine | Dataset metadata, licensing, task list | BIDS bundles when selected |
| WikiData | Spine | Cross-identifiers (QIDs, synonyms) | Descriptions / external links |
| NICLIP | Spine | Embedding metadata (id, model, owner) | Vector retrieval via external index |
| Neuromaps / TemplateFlow transforms | Spine | Template and transform catalogue entries | Actual transform files |
| BrainMap (if licensed) | Spine | Coordinates & evidence, provenance | Raw tables per licence |
| Crossref / OpenAlex / ORCID / ROR | On-demand | Cached augmented fields on Publication nodes | Citation graphs, author affiliation (fetched per DOI) |
| NIDM-Results | On-demand | `StatisticalMap` nodes created when archive uploaded | Detailed provenance, cluster tables fetched/parsed on demand |
| Large cohorts (HCP / ABCD / UK Biobank / ADNI / OASIS) | Spine | Dataset metadata, accession info | Subject-level data fetched case-by-case |
| NeuroQuery / NiMARE | On-demand | Evidence components added to score edges | Generated maps / topic scores per query |
| Neuroscout | On-demand | Feature catalogue | Time-aligned features retrieved when needed |
| Allen Human Brain Atlas | Spine (ExpressionProfile) + on-demand | Region-level summaries, Top-K gene pointers, manifest metadata | Full region×gene matrices, donor/sample-level expression |

## On-demand Evidence Feed Requirements

The on-demand adapters rely on flat JSON payloads stored under
`data/br-kg/raw/evidence`. Populate each file with the minimal schema below or
wire the adapter to a live API that returns an equivalent structure.

- **NeuroQuery (`neuroquery_sample.json`)**
  - JSON array of records with `task_id`, `region_id`, `score`, optional
    `confidence`, `method`, and `source`.
  - Recommended generation: run the NeuroQuery API or CLI against each canonical
    `task_id`, store the Top-K region scores, then copy the file to
    `data/br-kg/raw/evidence/neuroquery.json`.
- **NiMARE (`nimare_sample.json`)**
  - JSON array with `task_id`, `region_id`, and `probability` (or another scalar
    key passed as `default_score_key`), plus optional `method` metadata.
  - Generate by materialising NiMARE priors (ALE/MKDA/CBMA) for your curated
    corpus and exporting the region-level summary table.
- **Neuroscout (`neuroscout_features.json`)**
  - JSON array with `contrast_id`, `feature`, `value`, optional `unit`, and
    `source`. Keep only the features you plan to expose (e.g., luminance,
    lexical statistics).
  - Populate via the Neuroscout API for the target contrasts, store the
    down-sampled summary (means, prevalence) rather than full time-series.
- **Allen Human Brain Atlas (`allen_hba_sample.json`)**
  - JSON array with `region_id`, `gene_symbol`, `expression`, optional
    `tissue_type`, and `source`.
  - Produce by aggregating the full expression matrix (e.g., in pandas or
    anndata), taking Top-K genes per region, and writing the flattened table.

When the JSON files are present the corresponding entries in
`configs/br-kg/data_config.json` will activate automatically. For real-time
fetching, point `data_path` at a streaming cache directory or omit it and
override the adapter to call the external service directly.

## Configuration Contract

`configs/br-kg/data_config.json` should declare sources using the following structure:

```json
{
  "sources": {
    "cognitive_atlas": { "mode": "full" },
    "neurosynth": {
      "mode": "spine",
      "fields_whitelist": ["id", "pmid", "doi", "title", "year", "journal"]
    },
    "crossref": {
      "mode": "on_demand",
      "cache_ttl_sec": 86400,
      "crossref_mailto": "research@example.org"
    }
  },
  "create_links": true
}
```

Common keys:

- `mode`: `"full"`, `"spine"`, or `"on_demand"`.
- `fields_whitelist` (optional): override the default spine whitelist.
- `cache_ttl_sec` (optional): on-demand cache validity window.
- Source-specific settings (e.g. `niclip_path`, `limit`) remain nested under each source.

## Loader Responsibilities

- Loaders subclass `BaseLoader` and implement `load_full` and/or `load_spine`.
- On-demand sources expose `make_adapter()` returning an object with fetch methods
  (e.g. `fetch_by_doi([...])`). Adapters are registered with the OnDemandRegistry.
- All payloads passed to Neo4j must be flattened (use shared `_flatten_properties` helpers).
- Spine loaders must drop any field not present in the whitelist unless explicitly overridden.

## MasterDataLoader Behaviour

`MasterDataLoader.load_all`:

1. Reads `mode` per source.
2. `full` / `spine`: calls the loader’s `load` method, which internally dispatches to the correct mode.
3. `on_demand`: registers the loader’s adapter with the `OnDemandRegistry`; nothing is persisted now.
4. After ingestion, runs optional on-demand prefetchers (e.g. DOI hydration) only for DOIs not present in the graph.

The loader returns a summary per source, making it easy to assert what was written versus registered.

## Validation & Monitoring

- Integration tests cover:
  - Full mode (Cognitive Atlas) → check counts and critical relationships.
  - Spine mode (NeuroSynth + PubMed) → assert only whitelist fields exist.
  - On-demand sources → ensure no nodes are created but adapters respond and cache results.
- Post-ingestion QA:
  - Golden queries (e.g. task → region evidence) return in <300 ms.
  - Canonical `StatsMap -> IN_REGION -> BrainRegion` coverage is measurable and
    typed-path probes pass on fixed eligible seeds.
  - `BrainRegion -> PART_OF -> BrainRegion` is either live or explicitly marked
    as the only remaining `A2` blocker.
  - `ACTIVATES` coverage is tracked separately as nonblocking semantic
    enrichment.
- On-demand adapters track cache hit rate and last refresh times to decide when to refresh external metadata.

---

By adhering to these modes and contracts we keep BR-KG focused on assisting search:
small, reliable canonical data is always there; the rest is fetched when needed,
ensuring the knowledge graph stays trustworthy, lightweight, and easy to maintain.
