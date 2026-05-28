# OpenMed PGC GWAS Metadata Ingest

This document describes the OpenMed/PGC psychiatric genetics integration that was
added to BR-KG. The ingest remains metadata-oriented: it loads study, trait,
publication, normalized population, and top-locus provenance without storing full
GWAS summary-statistics tables in Neo4j.

## Scope

The loader reads OpenMed dataset cards and datasets-server metadata for `OpenMed/pgc-*` repositories and emits typed graph rows for:

- `Study:GWASStudy`
- `DiseaseTrait`
- `Publication`
- `Population`
- `RiskLocus`

The current OpenMed ingest path does not load full variant-level summary statistics
into Neo4j. Top loci are overlaid from GWAS Catalog after filtering to
genome-wide-significant associations.

## Implementation

Core code paths:

- Loader: `src/brain_researcher/services/neurokg/etl/loaders/openmed_pgc_hf_loader.py`
- Top-loci overlay: `src/brain_researcher/services/neurokg/etl/loaders/gwas_catalog_top_loci_loader.py`
- Derived disease-region materializer: `src/brain_researcher/services/neurokg/spatial/disease_trait_region_materializer.py`
- Live ingest script: `scripts/neurokg/run_openmed_pgc_live_ingest.py`

The live ingest script:

1. Loads Neo4j credentials from the repo `.env` or process environment.
2. Connects to the configured live Neo4j database.
3. Deletes legacy fallback `Population` nodes with `population_type='study_cohort'`.
4. Fetches live OpenMed metadata from Hugging Face.
5. Optionally fetches top loci from GWAS Catalog.
6. Upserts the resulting nodes and relationships.
7. Runs scoped `DiseaseTrait -> BrainRegion` derived-edge materialization for the ingested traits only.
8. Prints a JSON summary with before/after counts.

Run it with:

```bash
python scripts/neurokg/run_openmed_pgc_live_ingest.py
```

Optional single-dataset run:

```bash
python scripts/neurokg/run_openmed_pgc_live_ingest.py \
  --dataset-id OpenMed/pgc-bipolar
```

Metadata-only run without GWAS Catalog:

```bash
python scripts/neurokg/run_openmed_pgc_live_ingest.py --skip-top-loci
```

## Graph Model

### Nodes

- `Study:GWASStudy`
  - Example properties: `id`, `name`, `pmid`, `year`, `journal`, `sample_size`, `source`
- `DiseaseTrait`
  - Example properties: `id`, `name`, `trait_slug`, `source`
- `Publication`
  - Example properties: `id`, `pmid`, `journal`, `year`, `url`, `source`
- `Population`
  - Example properties: `id`, `name`, `population_type`, `ancestry_code`, `cohort`, `source`
- `RiskLocus`
  - Example properties: `id`, `name`, `rsid`, `chromosome`, `base_pair_location`, `nearest_gene`, `source`

### Relationships

- `Publication -[:ALIGNS_WITH]-> Study`
- `Study -[:STUDIES]-> DiseaseTrait`
- `Study -[:HAS_POPULATION]-> Population`
- `Study -[:HAS_LEAD_LOCUS]-> RiskLocus`
- `RiskLocus -[:ASSOCIATED_WITH]-> DiseaseTrait`
- Derived `DiseaseTrait -[:ASSOCIATED_WITH]-> BrainRegion`

Top-loci semantics:

- only associations with `p <= 5×10⁻⁸` are kept
- loci are ranked by `p_value` within each disorder before the cap is applied
- duplicate `(rsid, disorder)` pairs keep the strongest association record
- `HAS_LEAD_LOCUS` edges preserve study-level provenance when GWAS Catalog studies can be aligned to OpenMed studies by PMID

## Population Normalization

Population nodes are no longer emitted as study-local fallback placeholders. The loader now normalizes ancestry and cohort signals into shared `Population` nodes derived from:

- phenotype names
- config names
- source file names
- metadata hints found in the dataset card or split/config metadata

Currently normalized ancestry descriptors include:

- `EUR`
- `AFR`
- `AAM`
- `EAS`
- `SAS`
- `AMR`
- `MULTI`

Currently normalized cohort descriptors include:

- `iPSYCH`
- `deCODE`
- `CLOZUK`
- `UK Biobank`
- `23andMe`
- `TwinsUK`
- `NTR`
- `SFS`
- `WHI`

Important behavior:

- `study_cohort` fallback `Population` nodes are intentionally removed.
- Broad ancestry labels are suppressed when a more specific normalized label is available.
  - Example: `EAS` wins over a generic `Asian` tag.
- Multi-ancestry studies synthesize a shared `population:multi_ancestry` node when multiple ancestry signals are present.

This is still metadata normalization, not ontology-backed cohort harmonization. The graph now has shared, reusable population entities, but it does not yet map cohorts to an external population ontology.

## Live Neo4j Status

Live validation was rerun against the configured Neo4j database on April 8, 2026
after the GWAS Catalog top-loci fix.

The validation command was:

```bash
python scripts/neurokg/run_openmed_pgc_live_ingest.py --max-loci-per-disorder 20
```

Observed graph counts after that successful ingest:

- `12` OpenMed datasets discovered
- `53` `Study:GWASStudy` nodes
- `26` `DiseaseTrait` nodes
- `46` `Publication` nodes
- `16` normalized `Population` nodes
- `164` `RiskLocus` nodes
- `55` `STUDIES` edges
- `33` `HAS_POPULATION` edges
- `48` `ALIGNS_WITH` edges
- `217` `RiskLocus -[:ASSOCIATED_WITH]-> DiseaseTrait` edges
- `61` `Study -[:HAS_LEAD_LOCUS]-> RiskLocus` edges
- `0` legacy `Population` nodes with `population_type='study_cohort'`

Population breakdown in the live graph:

- `7` ancestry nodes
- `9` cohort nodes

Top-loci validation against the live DB after that run:

- `ASSOCIATED_WITH.min_p = 4e-42`
- `ASSOCIATED_WITH.max_p = 5e-8`
- `HAS_LEAD_LOCUS = 61`

## Current Limitation

The OpenMed ingest currently produces `0` derived `DiseaseTrait -> BrainRegion` edges in the live graph. This is not an ingest failure. It means the current database does not yet contain matching region evidence for the ingested OpenMed studies through either of these paths:

- `Publication -[:MENTIONS_REGION]-> BrainRegion`
- `Study -[:HAS_COORDINATE]-> Coordinate -[:LOCATED_IN]-> BrainRegion`

Once those evidence paths exist for aligned OpenMed studies or publications, rerunning the materializer will create derived trait-region edges.

## Verification

Focused tests covering the loader, schema registration, scoped materialization, and bulk-loader validation:

```bash
pytest -q \
  tests/unit/neurokg/test_bulk_loader_entity_validator.py \
  tests/unit/neurokg/test_db_schema.py \
  tests/unit/neurokg/test_disease_trait_region_materializer.py \
  tests/unit/neurokg/test_gwas_catalog_top_loci_loader.py \
  tests/unit/neurokg/test_gwas_graph_schema.py \
  tests/unit/neurokg/test_openmed_pgc_hf_loader.py \
  tests/unit/neurokg/test_query_service.py \
  tests/services/neurokg/test_bulk_loader.py
```

Latest local result during implementation:

- `101 passed`
- `5 skipped` for Neo4j-only bulk-loader tests that require explicit Neo4j env vars in the test environment

## Follow-Up

High-value next steps:

- scale the live top-loci run to a larger `--max-loci-per-disorder` cap once the desired production envelope is chosen
- connect OpenMed-linked publications to region evidence if the publication ingestion path can recover stable brain-region mentions
- replace heuristic population normalization with ontology-backed cohort normalization if a suitable source is chosen
