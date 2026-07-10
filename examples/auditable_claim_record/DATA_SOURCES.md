# Data sources for the auditable claim record

This worked example runs entirely on **public Neurosynth** coordinate data, so
anyone can reproduce it end to end with no account or data-use agreement. This
file lists where to obtain that data, and — for completeness — the data sources
for the other cases referenced in the manuscript, some of which are
controlled-access and are therefore not redistributed here.

## Neurosynth — used by *this* example (public, no account required)

The working-memory claim is computed over the Neurosynth v7 coordinate corpus.

- Project site: https://neurosynth.org
- Raw data repository: https://github.com/neurosynth/neurosynth-data
- One-call fetch via NiMARE: `nimare.extract.fetch_neurosynth`
  (https://nimare.readthedocs.io/)
- Helper scripts in this repository (run from the repo root):
  - `scripts/data/download_neurosynth_data.py` — downloads the Neurosynth v7
    release into `data/neurosynth_nimare/neurosynth_v7/`
  - `scripts/data/convert_neurosynth.py` — converts it into the term-annotated
    NiMARE dataset `data/neurosynth_nimare/neurosynth_dataset_v7.pkl`
- Point the generator at that pickle with
  `--corpus data/neurosynth_nimare/neurosynth_dataset_v7.pkl` (or set
  `$BR_NEUROCLAIM_CORPUS`). With no argument the generator falls back to
  `~/.nimare/neurosynth/neurosynth_terms_dataset.pkl.gz`.

## HCP Young Adult (WU-Minn) — used by the reproducibility pack (controlled access)

The bounded-autoresearch HCP-YA prediction case uses resting-state functional
connectivity from the WU-Minn Human Connectome Project.

- Study: https://www.humanconnectome.org/study/hcp-young-adult
- Data access (requires a data-use agreement): https://db.humanconnectome.org

HCP-YA is governed data: raw subject rows, subject identifiers, and raw FC files
are **not** redistributed in this repository. Stage them yourself under your own
data-use terms; the reproducibility pack documents the checksum-bound local
input contract that keeps raw rows and identifiers out of the exported bundle.

## Liu et al. (2025) functional-connectivity benchmark

The HCP-YA prediction pipelines follow the connectivity-mapping benchmark of
Liu et al., *Benchmarking methods for mapping functional connectivity in the
brain*, Nature Methods (2025).

- DOI: https://doi.org/10.1038/s41592-025-02704-4

## NeuroVault — TRIBE story-versus-math maps (public)

The TRIBE in-silico screen compares against paired HCP language contrast maps
released on NeuroVault.

- Collection 4337: https://neurovault.org/collections/4337/
