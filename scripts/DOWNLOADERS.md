# Downloader inventory

This is the authoritative inventory of operator-facing scripts whose primary
purpose is to download, fetch, or stage external data. Run commands from the
repository root unless the `Working directory` column says otherwise.

The machine-readable status names mean:

- `supported-public`: a public, immutable source with integrity checks,
  license/provenance metadata, an output manifest, and non-zero exit on any
  incomplete result.
- `experimental`: useful for exploration, but not a reproducible source
  boundary. Outputs must not be cited as a pinned public dataset without
  additional provenance and integrity work.
- `private-input`: behavior is controlled by a caller-supplied local inventory,
  identifier list, or restricted credential. The repository cannot certify the
  resulting source set.
- `historical`: retained only to explain or inspect an old workflow. Do not use
  it to create a new reproducibility artifact.

## Exact inventory

| Script | Status | Source and version | Integrity | License and provenance | Output and manifest | Failure semantics | Working directory |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `scripts/analysis/cognitive_control/download_dmcc_bold_subset.py` | `experimental` | OpenNeuro `ds003465`, metadata tag `1.0.7`; BOLD/T1w files are copied from the public `s3://openneuro.org/ds003465` namespace. | OpenNeuro metadata uses size checks only (`verify_hash=False`); direct S3 files are checked only for non-zero size. | The dataset license is not copied or recorded by this script. | Defaults under `outputs/patrick_congnitive_control/downloads/dmcc_bold_subset`; `download_manifest.json` records the selection and paths, not hashes or license. | Uncaught API/AWS errors exit non-zero. An empty selected BOLD list can still produce a manifest, so inspect it before use. | Any directory; defaults are repo-derived. |
| `scripts/analysis/cognitive_control/sherlock/download_dmcc_subject_s3.sh` | `experimental` | Current public OpenNeuro S3 namespace for `ds003465`; no OpenNeuro tag is selected. | Requires at least one T1w and eight BOLD files; no size or checksum manifest. | No license or source-version record is emitted. | Caller supplies `target_root`; no output manifest. | `set -euo pipefail`, AWS failure, missing T1w, or fewer than eight BOLD files exits non-zero. | Any directory; both required inputs are explicit. |
| `scripts/atlas/seed_repo_atlas_assets.py` | `experimental` | Installed Nilearn and Neuromaps registries plus caller-supplied local NiCLIP assets; exact upstream versions depend on the active environment. | Library fetchers may use their own checksums; the generated inventory records sizes but no cryptographic digests. | Per-asset license and immutable upstream identifiers are not recorded. | `BR_ATLAS_OUTPUT_ROOT` or `/app/data/atlases`; writes `manifests/atlas_inventory.json`, `.tsv`, and `seed_report.json`. | Uncaught top-level errors exit non-zero, but the reused Neuromaps helper can skip individual annotation failures. | Repository root because default source roots are relative. |
| `scripts/br-kg/download_osf_resources.py` | `private-input` | OSF resource/file IDs supplied by `--metadata`; that local file is the source inventory and version boundary. | Optional metadata checksum is treated as MD5; entries without a checksum are accepted and reused without verification. | License is not inferred or emitted; the caller must preserve it with the metadata. | Defaults to `data/br-kg/raw/neuromaps`; no run manifest. | No matches exits `1`; any failed download exits `2`; a successful set exits `0`. | Repository root for the default output; `--metadata` should be explicit. |
| `scripts/br-kg/fetch_all_neuromaps.py` | `experimental` | Installed `neuromaps` dataset registry and current OSF resources; no immutable package/source inventory is recorded. | Annotation checksums are used when provided by Neuromaps; atlas verification is delegated to the installed library. | Per-resource license and upstream version are not written. | Defaults to `BR_ATLAS_OUTPUT_ROOT/neuromaps`; `--manifest` is optional and records paths only. | Top-level failures exit non-zero, but individual annotation failures are logged and skipped, so exit `0` can be partial. | Repository root is recommended; output can be made explicit. |
| `scripts/data/download_datasets.py` | `historical` | Mixed OpenNeuro, MNE, Kaggle, and PhysioNet paths; some are unversioned and the MNE fallback follows `main`. | No complete checksum contract or authoritative bundle manifest. | Licenses are not consistently captured. | Defaults to `/app/data`; only dataset-specific ad hoc README files are created. | After this governance pass, an unknown dataset or any failed requested dataset exits non-zero. Existing files are still not integrity-verified. | Any directory with explicit `--output`; historical default assumes a container. |
| `scripts/data/download_neurosynth_data.py` | `supported-public` | Neurosynth version-7 snapshot pinned to Git commit `209c33cd009d0b069398a802198b41b9c488b9b7`. | Exact byte size and SHA-256 for all four files; atomic `.part` publication; `--check-only` is read-only and exact. | `ODbL-1.0` and the pinned license URL are recorded in `source_manifest.json`. | Defaults to `data/neurosynth_nimare/neurosynth_v7`; deterministic `source_manifest.json` is mandatory. | Any missing, mismatched, partial, or network-failed file exits non-zero and no success manifest remains. | Any directory after editable/package install; default is repo-derived. |
| `scripts/data/fetch_task_concept_edges.py` | `experimental` | Live Cognitive Atlas `v-alpha` task/search API; there is no immutable API snapshot. | No checksum, response count, or snapshot hash. | No API version/license record is emitted. | `data/graphs/task_concept_edges_v2.json`; the JSON is data, not a provenance manifest. | Initial task-list failure exits non-zero; per-task failures are logged and skipped, so exit `0` can be partial. | Repository root because the output path is relative. |
| `scripts/fetch_pmc_oa_fulltext_pubget.py` | `experimental` | Live PMC Open Access query through the installed `pubget`; query text and tool version are not bound into a repo manifest. | Delegated to `pubget`; the wrapper does not hash the corpus or validate an expected article set. | PMC article licenses vary and are not summarized by the wrapper. | Defaults to `data/pubget/<alias>` with logs under `logs/pubget`; no wrapper manifest. | The wrapper now returns the exact `pubget` exit code. Status `1` is incomplete/failure, not success. | Any directory; query/output/log defaults are repo-derived. |
| `scripts/tools/etl/neurovault_fetch_filtered.py` | `private-input` | Live NeuroVault/Nilearn fetch for IDs supplied by a local text file; `MAX_IDS=100` by default. | Integrity and cache behavior are delegated to the installed Nilearn; no expected hash set. | No license or source snapshot is emitted. | Nilearn cache (normally `~/nilearn_data/neurovault`); no output manifest. | Missing/invalid ID input or library failure exits non-zero; the script does not enforce an expected returned-image count. | Any directory; the default ID path is repo-derived. |
| `scripts/tools/etl/neurovault_fetch_inventory.py` | `experimental` | Live paginated NeuroVault image API. | HTTP failures are retried, but no immutable snapshot ID, checksum, or expected row count is recorded. | No API/data license record is emitted. | Defaults to `data/neurovault/cache/neurovault_images_raw.json`; the snapshot is not accompanied by a provenance manifest. | Exhausted request retries exit non-zero; an empty successful response can still write an empty snapshot and exit `0`. | Repository root because the default destination is relative. |
| `scripts/tools/ingest/download_neurovault_collection.py` | `experimental` | Current ZIP export for a NeuroVault collection ID, default `2099`; collection content is mutable. | HTTP and ZIP parsing are checked; no expected size or checksum. | Collection/license metadata is not captured. | Defaults to `data/neurovault/collection_<id>`; no output manifest. | HTTP, archive, or extraction errors exit non-zero and the temporary ZIP is removed unless `--keep-zip` is set. | Repository root because the default output is relative. |
| `scripts/tools/ingest/download_yeo_gsp_fc.py` | `historical` | Current FreeSurfer-hosted Yeo/Buckner tarball or arbitrary `--url`; the script is marked unused. | No pinned version, expected size, or checksum. | No license/provenance record is emitted. | Defaults to `data/br-kg/raw/nilearn_atlases`; no output manifest. | HTTP/archive failures exit non-zero, but an interrupted extraction can leave partial files. | Repository root because the default output is relative. |

## Governance boundary

The regression test discovers Python and shell entrypoints whose filename starts
with `download` or `fetch`, or contains `_fetch_`. It also explicitly includes
`scripts/atlas/seed_repo_atlas_assets.py` because its default behavior downloads
missing assets. Adding or removing one of these scripts requires updating this
inventory and choosing an honest status.

Analysis, ingestion, smoke, and service scripts that make incidental API calls
are outside this filename-based inventory because downloading is not their
primary operator-facing purpose. They must not be presented as reproducibility
source boundaries merely because a library can populate a cache while they run.
