# Data sources for the auditable claim record

This worked example runs entirely on **public Neurosynth** coordinate data, so
anyone can reproduce it end to end with no account or data-use agreement. This
file lists where to obtain that data, and — for completeness — the data sources
for the other cases referenced in the manuscript, some of which are
controlled-access and are therefore not redistributed here.

This file belongs to the worked example under `reproducibility/`; it is not a
pack manifest. The formal checksum packs and their data boundaries are
documented alongside it in [`../`](../).

## Working directory

Commands below run from the **repository root**. From anywhere inside the clone:

```bash
cd "$(git rev-parse --show-toplevel)"
```

## Neurosynth — used by *this* example (public, no account required)

The working-memory claim is computed over the Neurosynth v7 coordinate corpus.

- Project site: https://neurosynth.org
- Raw data repository: https://github.com/neurosynth/neurosynth-data
- Pinned source commit:
  `209c33cd009d0b069398a802198b41b9c488b9b7`
- Upstream license: [ODC Open Database License 1.0
  (ODbL-1.0)](https://raw.githubusercontent.com/neurosynth/neurosynth-data/209c33cd009d0b069398a802198b41b9c488b9b7/LICENSE.txt)
- Helper scripts in this repository:
  - `scripts/data/download_neurosynth_data.py` — the only authoritative
    downloader; downloads the Neurosynth version-7 snapshot pinned to the
    commit above into `data/neurosynth_nimare/neurosynth_v7/`
  - `scripts/data/convert_neurosynth.py` — converts it into the term-annotated
    NiMARE dataset `data/neurosynth_nimare/neurosynth_dataset_v7.pkl` and the
    binding sidecar `neurosynth_dataset_v7.pkl.provenance.json`

  Run them from the repository root after installing the light-path environment
  from `README.md`:

  ```bash
  python scripts/data/download_neurosynth_data.py
  python scripts/data/convert_neurosynth.py
  ```
  The downloader verifies the expected byte size and SHA-256 of all four files,
  including files already present locally. A download or checksum failure exits
  nonzero, removes stale provenance, and never publishes a partial file. Only
  after all files verify does it atomically write
  `data/neurosynth_nimare/neurosynth_v7/source_manifest.json`, which records the
  pinned URLs, commit, source snapshot, license, sizes, and hashes. Recheck an existing
  bundle without network access with:

  ```bash
  python scripts/data/download_neurosynth_data.py --check-only
  ```

  `--check-only` is read-only: it requires the exact existing manifest and all
  four verified files. It does not create, delete, or rewrite anything.

  The converter first re-verifies that exact source bundle. It then atomically
  publishes the pickle and a clone-independent provenance sidecar recording the
  pickle filename, size, SHA-256, source-manifest SHA-256, source commit, and
  source snapshot. It exits nonzero and removes both outputs on any failure, so an older
  or tampered pickle cannot be mistaken for a newly converted result.

  | source file | bytes | SHA-256 |
  | --- | ---: | --- |
  | `data-neurosynth_version-7_coordinates.tsv.gz` | 3,587,167 | `17135be3e08a0ab045896c77217e8463086543a0817d52a6a88c8e32c1161616` |
  | `data-neurosynth_version-7_metadata.tsv.gz` | 1,175,486 | `8acde7de2a14ee2a12b406e50a8805e83288b0bc78924ddb36879d496dfb757b` |
  | `data-neurosynth_version-7_vocab-terms_source-abstract_type-tfidf_features.npz` | 9,896,293 | `1b3359eebcbc8557340583788b3855031ea21361e87c265cb8fc540d9b6c4edd` |
  | `data-neurosynth_version-7_vocab-terms_vocabulary.txt` | 33,799 | `71c1858c5eb1bcc79854198bbca234569731efdc382c6205a9e46495379614af` |
- Point the generator at that pickle with
  `--corpus data/neurosynth_nimare/neurosynth_dataset_v7.pkl` (or set
  `$BR_NEUROCLAIM_CORPUS`). With no argument the generator uses that same
  repository-local canonical pickle. A custom corpus must be accompanied by
  its verified raw bundle via `--source-dir` or `$BR_NEUROCLAIM_SOURCE_DIR`;
  the matching provenance sidecar is mandatory.

## HCP Young Adult (WU-Minn) — used by the reproducibility pack (controlled access)

The bounded-autoresearch HCP-YA prediction case uses resting-state functional
connectivity from the WU-Minn Human Connectome Project.

- Study: https://www.humanconnectome.org/study/hcp-young-adult
- Data access (requires a data-use agreement): https://db.humanconnectome.org

HCP-YA is governed data: raw subject rows, subject identifiers, and raw FC files
are **not** redistributed in this repository. Stage them yourself under your own
data-use terms; the reproducibility pack documents the checksum-bound local
input contract that keeps raw rows and identifiers out of the exported bundle.
The HCP export alone does not recreate the A1 deeper rerun: the exact
326-subject FC/behavior intersection and its subject-keyed derived component
table are also governed inputs and are not shipped.

## Liu et al. (2025) functional-connectivity benchmark

The HCP-YA prediction pipelines follow the connectivity-mapping benchmark of
Liu et al., *Benchmarking methods for mapping functional connectivity in the
brain*, Nature Methods (2025).

- DOI: https://doi.org/10.1038/s41592-025-02704-4

## NeuroVault — TRIBE story-versus-math maps (public)

The TRIBE in-silico screen compares against paired HCP language contrast maps
released on NeuroVault.

- Collection 4337: https://neurovault.org/collections/4337/
