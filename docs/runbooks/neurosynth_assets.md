# Neurosynth & RSFC Asset Downloads

These helper scripts fetch the data products needed to reproduce the richer Neurosynth “Locations” experience locally.

## 1. Neurosynth NiMARE bundle
```
./scripts/tools/ingest/download_neurosynth_dataset.py \
  --output-dir data/neurosynth_nimare \
  --version 7 \
  --source abstract \
  --vocab terms
```
This wraps `nimare.dataset.fetch_neurosynth` and pulls `coordinates.tsv.gz`, `metadata.tsv.gz`, `features.npz`, and `vocabulary.txt` into `data/neurosynth_nimare/`.

## 2. Yeo/Buckner GSP functional-connectivity maps
```
./scripts/tools/ingest/download_yeo_gsp_fc.py \
  --output-dir data/neurokg/raw/nilearn_atlases
```
Downloads and extracts the `Yeo_Buckner_GSP_FC_maps.tgz` bundle. Each `fc_seed_XXX.nii.gz` holds the population-average Fisher-z map for that seed coordinate.

## 3. NeuroVault coactivation parcellations
```
./scripts/tools/ingest/download_neurovault_collection.py \
  --collection-id 2099 \
  --output-dir data/neurovault
```
Fetches and unpacks the specified NeuroVault collection (2099 = Neurosynth coactivation parcellations). Adjust `--collection-id` to grab other collections.

## 4. Neurosynth LDA topic models
```
./scripts/tools/ingest/download_neurosynth_lda.py \
  --output-dir data/neurosynth_nimare/lda \
  --version 7 \
  --variants LDA50 LDA100 LDA200 LDA400
```
Downloads the LDA topic matrices (`features.npz`), vocabularies, metadata, and keyword files for each requested variant. The Graph API defaults to `data/neurosynth_nimare/lda/version_7`; override with `NEUROSYNTH_LDA_DIR=/custom/path` when running the service.

After the assets exist you can request topic summaries from `/api/decode/neurosynth` by including `{"topic_variant": "LDA100", "topic_top_k": 5}` in the POST body.

## 5. NICLIP text & activation embeddings
```
# Abstract/text embeddings + mapping
ls data/niclip/data/text/
  text-normalized_section-abstract_embedding-BrainGPT-7B-v0.2.npy
  text-raw_section-body_embedding-...
  pmid_mapping.txt

# Activation embeddings / summaries
ls data/niclip/data/image/
  coords_method-MKDA_embedding-BrainGPT-7B-v0.2.npy (if downloaded)
  image-normalized_coord-MKDA_embedding-DiFuMo.npy
```
Configure the `niclip` block in `configs/neurokg/data_config.json` to point at these files. Important keys:

- `text_model`, `text_section`, `text_normalization`: select the `text-<norm>_section-<section>_embedding-<model>.npy` you want persisted.
- `coord_method`, `coord_model`, `coord_summary`, `coord_normalization`: pick the activation summary you have on disk (MKDA, ALE, Neurosynth association). If only the DiFuMo fallback exists, leave `coord_model` as shipped and we will ingest from `image-<norm>_coord-<method>_embedding-DiFuMo.npy`.
- `load_text_embeddings` / `load_coordinate_embeddings`: toggle modalities individually.
- `store_vectors`: defaults to `false`. When left off we persist the file path + row index (and vector norm) so you can reload the `.npy` slice on demand. Turn it on only if you need the 4,096-dimension vectors stored inside Neo4j.

Running `python launch_ingestion.py --sources niclip` now creates:

- `(:Publication)-[:HAS_TEXT_EMBEDDING]->(:Embedding {kind:"text", text_section, model, storage_path, storage_index, vector_norm, ...})`
- `(:Publication)-[:HAS_ACTIVATION_EMBEDDING]->(:Embedding {kind:"activation", activation_method, activation_summary, storage_path, storage_index, ...})`

Every embedding aligns with the study order in `pmid_mapping.txt`, so all 14,371 Neurosynth studies inherit both a text vector and an activation summary as soon as the assets are present.

### On-demand API endpoints

- `POST /api/niclip/embedding`
  - Body: `{ "study_id": "9065511", "kind": "text" | "activation", "include_vector": false, ... }`
  - Optional overrides: `text_model`, `text_section`, `coord_method`, `coord_summary`, etc.
- `GET /api/publication/<publication_id>/niclip`
  - Query params mirror the POST payload and you can omit `study_id`. The service resolves the publication’s `pmid`/`neurosynth_id` automatically.

Both endpoints stream vectors directly from the `.npy` files under `data/niclip`; set `include_vector=true` only when you actually need the 4,096-dim payload. Otherwise the response includes metadata + `(storage_path, storage_index, vector_norm)` so you can reload the row lazily.

Run the scripts in any order as assets are needed. Use `--dry-run`, `--keep-archive`, or `--keep-zip` switches when you want to inspect downloads without extraction.
