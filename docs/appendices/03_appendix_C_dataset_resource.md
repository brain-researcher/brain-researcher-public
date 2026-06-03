# Appendix C. Dataset / Resource Card

This appendix has two parts.

- **Part 1 — BR Dataset / Resource System Catalog.** System-level reference for the dataset and resource substrate that Brain Researcher draws on. Covers the resource-type contract, source ingestion modes, the curated public-dataset catalog, the on-disk layout, access classes, license patterns, mount conventions, and the readiness vocabulary used in per-episode cards. Re-issue when `configs/tool_resources.yaml`, `configs/br-kg/ingestion_modes.yaml`, or `configs/datasets/public_datasets_manual_annotation.csv` changes materially.
- **Part 2 — Per-episode dataset/resource card template.** Fillable card recording the resources used or ruled out in one episode.

---

# Part 1 — BR Dataset / Resource System Catalog

## C.S1 Evidence sources

| Source | What it supports |
|--------|--------------------|
| `configs/tool_resources.yaml` | Canonical resource-type vocabulary (volume_3d, surface_mesh, timeseries, connectivity_matrix, stat_map, BIDS roots, etc.) |
| `configs/schemas/resources.schema.json` | JSON schema enforcing the resource-type contract |
| `configs/br-kg/ingestion_modes.yaml` | Source list with ingestion mode (`full` / `spine` / `on_demand`) and spine whitelists |
| `configs/datasets/public_datasets_manual_annotation.csv` | 107-row curated catalog of public neuroimaging datasets (5 categories) |
| `configs/br-kg/config.yml` | Schema definitions referenced by ingestion_modes |
| `data/` | On-disk layout for ingested raw and derivative artifacts |

## C.S2 Resource type contract

The resource-type vocabulary is the language used by `tool_resources`, the registry, recipe generators, and dataset-resolution tools. Episode cards in Part 2 reference these resource types directly.

| Resource type | Description |
|----------------|-------------|
| `volume_3d` | 3D anatomical volume |
| `volume_4d` | 4D time series volume |
| `surface_mesh` | Surface mesh geometry |
| `parcellation_labels` | Atlas/parcellation label map |
| `mask_path` | Binary mask volume |
| `timeseries` | Extracted time series |
| `connectivity_matrix` | Connectivity/correlation matrix |
| `stat_map` | Statistical map |
| `raw_eeg` | Raw EEG recording |
| `clean_eeg` | Cleaned EEG data |
| `epochs` | Epoched EEG/MEG data |
| `power_spectra` | Spectral power features |
| `montage` | Electrode montage |
| `events_tsv` | Events table (BIDS) |
| `features_table` | Tabular features |
| `feature_metadata` | Feature-level metadata table |
| `contacts_mni` | Electrode contacts in MNI space |
| `bids_root` | BIDS root directory |
| `subject_label` | Subject identifier |
| `bvals` / `bvecs` | Diffusion b-values / vectors |
| `coord_table` / `coordinate_table` | Coordinate table |
| `data_file` / `labels_file` / `groups_file` | Numeric matrices for tabular ML |
| `pubmed_query` / `doi_list` | Literature query handles |
| `kg_nodes` | Knowledge graph nodes |

## C.S3 Source ingestion modes

The graph is built from a fixed set of upstream sources, each labelled with one of three persistence modes. This determines what lives in Neo4j vs. what is fetched on demand.

| Mode | Persistence | When to use | Examples |
|------|--------------|-------------|----------|
| `full` | Complete curated representation (flattened for Neo4j) | Small, high-value ontology / blueprint data required for reasoning | cognitive_atlas, nilearn_atlases, neurobagel, onvoc, openneuro_glmfitlins |
| `spine` | Whitelisted fields only; bulky/free-text payloads omitted | Large datasets, frequently updated sources, or data where details are fetched on-demand | neurosynth, pubmed, neurovault, openneuro, wikidata, niclip, brainmap, bids, neuromaps, neurostore, allen_hba, virtual_brain |
| `on_demand` | Nothing written to Neo4j during ingestion; adapters fetch at query time | Extremely large, fast-changing, or licensed data | scholarly_metadata, nidm_results, neuroquery, nimare, neuroscout |

### Full source ↔ mode assignment (from `configs/br-kg/ingestion_modes.yaml`)

| Source | Mode |
|--------|------|
| cognitive_atlas | full |
| nilearn_atlases | full |
| neurobagel | full |
| onvoc | full |
| openneuro_glmfitlins | full |
| pubmed | spine |
| neurosynth | spine |
| neurovault | spine |
| openneuro | spine |
| wikidata | spine |
| niclip | spine |
| brainmap | spine |
| bids | spine |
| neuromaps | spine |
| neurostore | spine |
| allen_hba | spine |
| virtual_brain | spine |
| scholarly_metadata | on_demand |
| nidm_results | on_demand |
| neuroquery | on_demand |
| nimare | on_demand |
| neuroscout | on_demand |

> Release note: configured presence is not the same as live presence. See Appendix B Part 1 § "Release-ready provenance gap register" for which configured sources are absent from the live source scan (currently brainmap, bids, virtual_brain, wikidata, nidm_results, neuroquery, nimare, neuroscout).

## C.S4 Public datasets catalog

The curated dataset catalog at `configs/datasets/public_datasets_manual_annotation.csv` contains 107 rows organised into five categories. The table below records the categories, sizes, and representative entries. Each row in the source CSV carries: `dataset_id, name, short_name, description, modalities, acquisitions, subjects_count, sessions_count, age_range, species, age_range, disease_flags, center/PI, consortium, source_repo, primary_url, access_type, license, size_human, tags, tasks_paradigms`.

### Category summary

| Category | Approx. count | Typical access | Representative datasets |
|----------|---------------:|-----------------|--------------------------|
| Population & Lifespan Studies (Healthy) | ~26 | public, registration, application | FCP, ABCD, AOMIC, BCP, CamCAN, dHCP, DLBS, GSP, HBN, HCP-YA, HCP-A, HCP-D, IMAGEN, IXI, LEMON, NKI-RS, NSPN, PING, PNC, QTAB, QTIM, SALD, SLIM, TAMI, UKB-Imaging, VETSA |
| Clinical & Disease-Specific Cohorts | ~20 | mostly application / DUA | VITA, 4RTNI, A4, ABIDE, ADHD-200, ADNI, AIBL, ARWIBO, COBRE, EDSD, ENIGMA, NACC, NIFD, OASIS, PPMI, Prevent-AD, REST-meta-MDD, SchizConnect, SCZIowa |
| Deep Phenotyping & Naturalistic Stimuli | ~14 | mostly public | BOLD5000, DeepRecon, VIM, GOD-Kamitani, Raiders, IBC, Narratives, NSD, Sherlock, StudyForrest, THINGS, MSC, MyConnectome |
| Human Atlases & Genomics (Postmortem / In Vitro) + Animal Connectomes | ~30 | mixed (open + dbGaP + Allen license + custom) | Allen-ABA, Allen-MConn, BrainMinds-M, C.elegans Connectome, Hemibrain, IBL-BWM, MICrONS, PRIME-DE, PRIME-RE, Allen BrainSpan, Allen CellTypes, AHBA, BigBrain, BrainMap, CoRR |
| Simulation & Synthetic Data | ~4 | public | (see CSV rows ≥ 103) |

### Representative dataset rows (selected)

| Dataset ID | Short name | Modalities | Subjects | Access type | License |
|------------|------------|------------|---------:|-------------|---------|
| ds:hcp_ya | HCP-YA | MRI; fMRI; DWI; Behavior; MEG (subset) | 1,206 | registration | custom HCP DUA |
| ds:hcp_a | HCP-A | MRI; fMRI; DWI; Behavior | 1,248 | registration | NDA DUA |
| ds:hcp_d | HCP-D | MRI; fMRI; DWI; Behavior | 1,300 | registration | NDA DUA |
| ds:abcd | ABCD | MRI; fMRI; DWI; Behavior; Genomics | 11,000 | registration / application | custom DUA (NDA) |
| ds:ukb_imaging | UKB-Imaging | MRI; fMRI; DWI; SWI; Body MRI; Behavior; Genomics | 60,000 | application | custom UKB DUA |
| ds:camcan | CamCAN | MRI; fMRI; DWI; MEG; Behavior | 700 | registration | custom academic terms |
| ds:dhcp | dHCP | MRI; fMRI; DWI | 1,173 | public | open (project terms) |
| ds:hbn | HBN | MRI; fMRI; EEG; behavior; genomics | 3,600 | application | controls |
| ds:adni | ADNI | MRI; fMRI (subset); PET; CSF; Behavior; Genomics | 1,500 | application | custom DUA |
| ds:ppmi | PPMI | MRI; DaT-SPECT; clinical; CSF; Genomics | 4,000 | registration / application | custom DUA |
| ds:abide | ABIDE | MRI; rs-fMRI | 2,000+ | public | (multiple, see catalog) |
| ds:adhd200 | ADHD-200 | MRI; rs-fMRI | 973 | public | CC-BY-NC-SA |
| ds:nsd | NSD | fMRI | 8 | public | CC-BY 4.0 |
| ds:narratives | Narratives | fMRI | 345 | public | CC0 |
| ds:ibc | IBC | fMRI | 12 | public | CC-BY |
| ds:msc | MSC | fMRI; MRI | 10 | public | CC-BY |
| ds:allen_hba | AHBA | transcriptomics | 6 | Allen data license | — |
| ds:ibl_brainwide | IBL-BWM | electrophysiology (Neuropixels); behavior | 139 mice | CC-BY 4.0 | — |

> For the complete machine-readable catalog use `configs/datasets/public_datasets_manual_annotation.csv` directly. Treat the CSV as source of truth; this table is a navigation aid.

## C.S5 On-disk layout (`data/`)

The `data/` tree mirrors the source-vs-derivative split:

| Directory | Role | Notes |
|-----------|------|-------|
| `data/openneuro/` | OpenNeuro raw datasets (BIDS) | by `ds:openneuro:<id>` |
| `data/openneuro_glmfitlins/` | GLMFitLins statsmodel specs and derived stat-maps | snapshot date in `README.md` |
| `data/neurosynth/` | Neurosynth raw artifacts | |
| `data/neurosynth_maps/` | Neurosynth-derived map files | |
| `data/neurosynth_nimare/` | NiMARE wrapper artifacts over Neurosynth | |
| `data/neurovault/` | NeuroVault collection caches | |
| `data/cognitive_atlas/` | Cognitive Atlas snapshot data | |
| `data/allen_hba/` | Allen HBA local artifacts | |
| `data/atlases/` | Atlas caches (nilearn, neuromaps, niclip) | |
| `data/brainmap/` | BrainMap raw data when licensed | |
| `data/bids/` | Local BIDS datasets | |
| `data/br-kg/`, `data/br-kg_exports/` | BR-KG NDJSON shards and exports | |
| `data/BR-KG/raw/<source>/` | Raw ingestion artifacts (`neurobagel_public`, `gabriel`, `kggen`, `evidence`, etc.) | per-source subfolders with manifests |
| `data/BR-KG/benchmarks/` | Structural-quality benchmark runs | one folder per run |
| `data/runs/mcp_runs/` | MCP run store (default) | per-episode run records |
| `data/agent_outputs/`, `data/autoresearch/`, `data/demo_runs/` | Agent/runtime work products | |

## C.S6 Access classes and license patterns

The catalog spans five access classes that drive readiness gating and release decisions.

| Access class | Typical license shape | Examples | Readiness implication |
|--------------|------------------------|----------|------------------------|
| Public | CC0 / CC-BY / CC-BY-NC-SA / open project terms | NSD, Narratives, IBC, MSC, ABIDE, ADHD-200, AOMIC, GSP, NKI-RS, SALD, SLIM, dHCP | Can be mounted and analysed without per-user gating; cite per license |
| Registration | open after account creation + click-through DUA | CamCAN, HCP-YA (with HCP DUA), COBRE, PPMI | Account registration must be on file before episode opens |
| Application / DUA | named investigator + DUA review (often via NDA, LONI, UKB) | ABCD, HCP-A, HCP-D, ADNI, AIBL, UKB-Imaging, VETSA, NSPN, NIFD, Prevent-AD | DUA approval must be on file; episode card must record approval ID |
| Restricted trial | clinical-trial DUA, often per-cohort | A4 | Episode must verify trial DUA terms before any export |
| Licensed / custom | Allen data license / project DUA / BrainMap | AHBA, Allen-ABA, Allen-MConn, BrainMap | Redistribution restrictions; check before promotion to BR-KG |

## C.S7 Backend reachability and readiness vocabulary

Episode cards report **readiness** for each resource. Readiness uses the following vocabulary; status maps directly into the per-episode card in Part 2.

| Status | Meaning | Action |
|--------|---------|--------|
| `ready` | All required paths exist, BIDS validation passes, derivatives present, phenotype manifest covers required variables. | Proceed to recipe generation. |
| `partial` | Some derivatives or phenotype fields missing but core inputs reachable. | Regenerate missing derivatives or restrict episode scope. |
| `blocked` | Required asset missing, license not satisfied, or backend unreachable. | Stop. Document blocker in Part 2 §C.7; escalate per Appendix I. |
| `not_applicable` | Resource was ruled out before access checks. | Record rationale in Part 2 §C.2. |

### Standard backend probes

| Backend | Probe | Pass criterion |
|---------|-------|-----------------|
| Local FS | `os.path.exists` on BIDS root and derivatives root | both present, readable |
| Object store | HEAD on the dataset object | 200/204 with expected size |
| Neurodesk image | module load | image present, no missing-tool errors |
| Slurm scratch | `df` / `ls` on scratch mount | free space ≥ recipe budget |
| HTTP API | OPTIONS / GET on health endpoint | 200 within timeout |

### Allowed mount conventions

| Use | Allowed roots (current observed) |
|-----|----------------------------------|
| Run artifacts | `/data/brain_researcher_data/repo_runtime/artifacts` |
| Repo data | `<repo>/data` |
| Repo tmp | `<repo>/tmp` |

These are the defaults enforced by `BR_MCP_ALLOWED_ROOTS`. Any episode writing outside these roots must escalate per Appendix I and update its policy flags in Appendix A.

---

# Part 2 — Per-episode dataset / resource card template

Records the resources used or ruled out in one episode. One card per resource family per episode; use multiple rows in §C.2 when the episode touches several datasets.

## C.1 Card identity

| Field | Value |
|-------|-------|
| Card ID | C-<episode-id>-001 |
| Episode ID | |
| Date | |
| Prepared by | |
| Review status | draft / reviewed / final |

## C.2 Resource ledger

| Resource ID | Name / alias | Type | Access class | Status | Used in episode? |
|-------------|--------------|------|--------------|--------|------------------|
| | | dataset / atlas / derivative / phenotype / external feature | public / registration / application / restricted trial / licensed | ready / partial / blocked / ruled out | yes / no |

## C.3 Dataset identification

| Field | Value |
|-------|-------|
| Dataset identifier | (e.g., `ds:hcp_ya` from `configs/datasets/public_datasets_manual_annotation.csv`) |
| Aliases | |
| Upstream source | OpenNeuro / HCP / NeuroVault / ABCD / Neurobagel / private / other |
| Source URL / DOI | |
| License | (from catalog row) |
| Required citation | |
| Snapshot date | |
| Source version | |
| Ingestion mode (from C.S3) | full / spine / on_demand / not ingested |

## C.4 Paths and roots

| Field | Value |
|-------|-------|
| Local path | |
| BIDS root | |
| Derivative root | |
| Phenotype manifest | |
| Mount point (container / cluster) | |
| Within allowed roots? | yes / no |

## C.5 Modality and content

| Field | Value |
|-------|-------|
| Modalities | T1w / T2w / BOLD / DWI / fMAP / pheno / EEG / MEG / PET / other |
| Tasks | |
| Sessions | |
| Acquisitions | |
| Template space(s) | |
| Has events files? | yes / no |
| Has confounds? | yes / no |

## C.6 Variables of interest

| Variable | Role | Type | Coverage (% subjects) | Missingness handling |
|----------|------|------|----------------------:|----------------------|
| | target / covariate / stratifier / exclusion | continuous / binary / ordinal | | |

## C.7 Missing assets

| Asset | Expected location | Detection method | Impact | Recovery action |
|-------|-------------------|------------------|--------|-----------------|
| missing derivative | | manifest check / file scan | blocking / soft | regenerate / fetch / skip |
| missing phenotype | | | | |

## C.8 Backend reachability

| Backend | Probe | Result | Latency | Notes |
|---------|-------|--------|---------|-------|
| local FS | path exists | pass / fail | | |
| object store | HEAD object | pass / fail | | |
| Neurodesk image | module load | pass / fail | | |
| Slurm scratch | df / ls | pass / fail | | |

## C.9 Readiness verdict

| Field | Value |
|-------|-------|
| Readiness status | ready / partial / blocked |
| Blocking reason | |
| Required fixes | |
| Verified by | preflight tool / human |

## C.10 Subject manifests

| Manifest | Path | Subject count | Covers fold manifest? | Notes |
|----------|------|--------------:|-----------------------|-------|
| primary | | | yes / no | |
| intersection | | | yes / no | |
| selection source | | | yes / no | |

## C.11 Provenance trace

| Field | Value |
|-------|-------|
| Loader / adapter | |
| Loader version | |
| Ingestion run ID | |
| Manifest hash | |
| Linked BR-KG nodes (DataResource / Dataset IDs) | |

## C.12 Caveats and constraints

- Licensing restrictions on redistribution:
- PHI / consent constraints:
- Citation propagation requirement:
- Known biases (site, age, sex, etc.):
- Embargo / publication constraints:
- Resource-type contract (from C.S2) — required types this episode produces or consumes:
