#!/usr/bin/env python3
"""
Fetch NeuroVault images for a prefiltered ID list and pull Neurosynth terms via
nilearn.datasets.fetch_neurovault_ids.

Inputs:
  - data/neurovault/cache/neurovault_image_ids_filtered.txt (one ID per line)

Outputs (cached by nilearn under ~/nilearn_data/neurovault):
  - downloaded NIfTI images
  - images_meta, collections_meta in the returned object
  - optional vocabulary and word_frequencies if vectorize_words=True

This script is intentionally minimal: adjust mode/MAX_IDS as needed.
"""
from __future__ import annotations

from pathlib import Path
from nilearn.datasets import fetch_neurovault_ids

ROOT = Path(__file__).resolve().parents[2]
IDS_TXT = ROOT / "data/neurovault/cache/neurovault_image_ids_filtered.txt"
MAX_IDS = 100  # set to None for full run; keep small for a smoke test


def load_ids(path: Path, limit: int | None = None) -> list[int]:
    ids: list[int] = []
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            ids.append(int(line.strip()))
            if limit is not None and len(ids) >= limit:
                break
    return ids


def main():
    image_ids = load_ids(IDS_TXT, MAX_IDS)
    print(f"Loaded {len(image_ids)} image IDs from {IDS_TXT}")

    nv = fetch_neurovault_ids(
        image_ids=image_ids,
        fetch_neurosynth_words=True,
        mode="download_new",  # change to "offline" to reuse cache only
        resample=False,
        vectorize_words=True,
        verbose=1,
        timeout=30.0,
    )

    vocab = getattr(nv, "vocabulary", None)
    wf = getattr(nv, "word_frequencies", None)
    print(f"Downloaded {len(nv.images)} images")
    print(f"Images meta entries: {len(nv.images_meta)}; Collections meta entries: {len(nv.collections_meta)}")
    if vocab is not None and wf is not None:
        print(f"Neurosynth terms: vocab size {len(vocab)}, word_frequencies shape {wf.shape}")


if __name__ == "__main__":
    main()
