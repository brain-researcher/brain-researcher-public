# OpenMed / PGC GWAS Ingest

This document describes the two-layer psychiatric genetics ingest pipeline that
populates the BR-KG with study metadata (from Hugging Face) and genome-wide
significant loci (from GWAS Catalog).

## Overview

| Layer | Source | What it adds |
|-------|--------|--------------|
| Study metadata | HuggingFace `OpenMed/pgc-*` repos | `GWASStudy`, `DiseaseTrait`, `Population`, `Publication` nodes |
| Top loci | GWAS Catalog REST API | `RiskLocus` nodes + `ASSOCIATED_WITH` + `HAS_LEAD_LOCUS` edges |

### Node types added

| Type | ID format | Example |
|------|-----------|---------|
| `GWASStudy` | `study:openmed_pgc_{disorder}:{config}` | `study:openmed_pgc_schizophrenia:scz2022` |
| `DiseaseTrait` | `disease:{slug}` | `disease:schizophrenia` |
| `Population` | `population:{key}` | `population:european`, `population:decode` |
| `Publication` | `pmid:{id}` | `pmid:39843750` |
| `RiskLocus` | `locus:{rsid}` | `locus:rs1625579` |

### Edge types added

| Type | Direction | Key properties |
|------|-----------|---------------|
| `STUDIES` | `GWASStudy → DiseaseTrait` | source |
| `HAS_POPULATION` | `GWASStudy → Population` | source |
| `ALIGNS_WITH` | `Publication → GWASStudy` | source |
| `ASSOCIATED_WITH` | `RiskLocus → DiseaseTrait` | rank, p_value, p_mantissa, p_exponent, odds_ratio / beta, strongest study provenance |
| `HAS_LEAD_LOCUS` | `GWASStudy → RiskLocus` | study_accession, study_pmid, locus_rank, p_value |

## Running the ingest

```bash
# Full ingest: metadata + top loci (default 500 loci per disorder)
python scripts/neurokg/run_openmed_pgc_live_ingest.py

# Faster metadata-only run (skips GWAS Catalog API)
python scripts/neurokg/run_openmed_pgc_live_ingest.py --skip-top-loci

# Limit loci per disorder
python scripts/neurokg/run_openmed_pgc_live_ingest.py --max-loci-per-disorder 200

# Ingest a specific HF dataset only
python scripts/neurokg/run_openmed_pgc_live_ingest.py --dataset-id OpenMed/pgc-schizophrenia
```

The script is idempotent — re-running upserts without duplicates.

## Data sources

### HuggingFace datasets

OpenMed organises PGC studies as one repo per disorder:

- `OpenMed/pgc-schizophrenia`
- `OpenMed/pgc-adhd`
- `OpenMed/pgc-mdd`
- `OpenMed/pgc-bipolar` *(if published)*
- `OpenMed/pgc-autism`
- `OpenMed/pgc-ptsd`
- `OpenMed/pgc-substance-use`
- … (auto-discovered via `huggingface.co/api/datasets?author=OpenMed`)

Each repo contains one config per study cohort/year. The loader reads only
`datasets-server` metadata endpoints — it does **not** read the parquet
contents (raw summary stats).

### GWAS Catalog

Top loci are fetched via two REST endpoints:

```
GET /studies/search/findByEfoTrait?efoTrait={trait}&page=N&size=50
GET /studies/{GCST_ID}/associations?page=0&size=100
```

The loader keeps only genome-wide significant associations (`p <= 5×10⁻⁸`), ranks loci by
increasing `p_value` within each disorder, and then applies the
`--max-loci-per-disorder` cap after deduplication by `(rsid, disorder)`.

If the same `(rsid, disorder)` pair appears in multiple GWAS Catalog studies, the
stored `ASSOCIATED_WITH` edge keeps the strongest association record (lowest
`p_value`), while `HAS_LEAD_LOCUS` preserves study-level provenance for each aligned
OpenMed study that reported that locus.

Disorders covered and their GWAS Catalog query terms:

| DiseaseTrait node | Query term |
|-------------------|------------|
| `disease:schizophrenia` | `schizophrenia` |
| `disease:bipolar_disorder` | `bipolar disorder` |
| `disease:major_depression` | `major depressive disorder` |
| `disease:adhd` | `attention deficit hyperactivity disorder` |
| `disease:autism_spectrum_disorder` | `autism spectrum disorder` |
| `disease:ptsd` | `post-traumatic stress disorder` |
| `disease:ocd` | `obsessive-compulsive disorder` |
| `disease:anxiety_disorders` | `anxiety disorder` |
| `disease:tourette_syndrome` | `Tourette syndrome` |
| `disease:anorexia_nervosa` | `anorexia nervosa` |
| `disease:alcohol_dependence` | `alcohol use disorder` |
| `disease:opioid_dependence` | `opioid dependence` |

## Cross-modal queries enabled

With both layers ingested, the KG supports chains like:

```cypher
-- Strongest schizophrenia lead loci with study provenance
MATCH (s:Study:GWASStudy)-[hl:HAS_LEAD_LOCUS]->(r:RiskLocus)
MATCH (r)-[aw:ASSOCIATED_WITH]->(d:DiseaseTrait {id: "disease:schizophrenia"})
WHERE hl.source = "gwas_catalog_top_loci_loader"
  AND aw.source = "gwas_catalog_top_loci_loader"
RETURN s.name, r.name, aw.p_value, hl.study_accession
ORDER BY aw.p_value ASC
LIMIT 20
```

```cypher
-- Which OpenNeuro fMRI datasets study disorders sharing top loci with ADHD?
MATCH (r:RiskLocus)-[:ASSOCIATED_WITH]->(d1:DiseaseTrait {id: "disease:adhd"})
MATCH (r)-[:ASSOCIATED_WITH]->(d2:DiseaseTrait)
WHERE d2.id <> "disease:adhd"
MATCH (ds:Dataset)-[:MEASURES]->(d2)
RETURN d2.name, ds.title, count(r) AS shared_loci
ORDER BY shared_loci DESC
```

## Implementation files

| File | Purpose |
|------|---------|
| `src/.../etl/loaders/openmed_pgc_hf_loader.py` | HF metadata → graph inputs |
| `src/.../etl/loaders/gwas_catalog_top_loci_loader.py` | GWAS Catalog → RiskLocus nodes + locus provenance edges |
| `src/.../spatial/disease_trait_region_materializer.py` | Derive DiseaseTrait→BrainRegion edges |
| `scripts/neurokg/run_openmed_pgc_live_ingest.py` | End-to-end ingest + cleanup script |

## Live graph counts (as of 2026-04-08)

These counts reflect the validation run:

```bash
python scripts/neurokg/run_openmed_pgc_live_ingest.py --max-loci-per-disorder 20
```

| Entity | Count |
|--------|-------|
| `GWASStudy` nodes | 53 |
| `DiseaseTrait` nodes | 26 |
| `Population` nodes (normalised) | 16 |
| `Publication` nodes | 46 |
| `RiskLocus` nodes | 164 |
| `ASSOCIATED_WITH` edges | 217 |
| `HAS_LEAD_LOCUS` edges | 61 |

Explicit live DB verification after that run returned:

- `ASSOCIATED_WITH.min_p = 4e-42`
- `ASSOCIATED_WITH.max_p = 5e-8`
- `HAS_LEAD_LOCUS = 61`
