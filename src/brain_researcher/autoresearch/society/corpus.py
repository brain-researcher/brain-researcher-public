"""Curated coordinate-corpus loader for the NiMARE evidence backend.

The probabilistic-association layer operates over a curated coordinate corpus
(NeuroQuery / Neurosynth) rather than LLM-extracted facts — the panel's "curated
corpora" choice, which keeps the weakest link (extraction) out of the loop. This
module builds NiMARE ``Dataset`` objects:

* :func:`build_synthetic_corpus` — a tiny in-memory corpus for tests/demos (no
  network), with coordinates clustered at named MNI centroids.
* :func:`load_neurosynth_corpus` — load a cached Neurosynth NiMARE dataset, or (only
  when ``download=True``) fetch + convert it. The fetch is network + hundreds of MB,
  so it is gated off by default; the cache-load path is the normal one.

NiMARE is imported lazily so importing this module is cheap and dependency-free.
"""

from __future__ import annotations

from typing import Any


def _study(coords: list[tuple[float, float, float]], n: int = 25) -> dict[str, Any]:
    xs, ys, zs = zip(*coords)
    return {
        "contrasts": {
            "1": {
                "coords": {"space": "MNI", "x": list(xs), "y": list(ys), "z": list(zs)},
                "metadata": {"sample_sizes": [int(n)]},
            }
        }
    }


def build_synthetic_corpus(
    clusters: dict[str, tuple[float, float, float]],
    *,
    per_cluster: int = 8,
    jitter: int = 6,
    seed: int = 0,
) -> Any:
    """Build a small NiMARE ``Dataset`` with studies clustered at each centroid.

    Args:
        clusters: mapping ``label -> (x, y, z)`` MNI centroid.
        per_cluster: number of synthetic studies per centroid.
        jitter: max +/- mm perturbation applied to each coordinate.
        seed: deterministic RNG seed (``Math.random`` is unavailable anyway).

    Returns a NiMARE ``Dataset``. Used by the tests/demo so a real CBMA can run
    hermetically without the network.
    """
    import random

    from nimare.dataset import Dataset

    rng = random.Random(seed)
    src: dict[str, Any] = {}
    sid = 0
    for label, (cx, cy, cz) in clusters.items():
        for _ in range(per_cluster):
            pt = [
                (
                    cx + rng.randint(-jitter, jitter),
                    cy + rng.randint(-jitter, jitter),
                    cz + rng.randint(-jitter, jitter),
                )
            ]
            src[f"{label}-{sid}"] = _study(pt)
            sid += 1
    return Dataset(src)


def build_synthetic_annotated_corpus(
    clusters_by_term: dict[str, tuple[float, float, float]],
    *,
    per_term: int = 12,
    jitter: int = 6,
    seed: int = 0,
) -> Any:
    """Build a term-annotated NiMARE ``Dataset`` for reverse inference (MKDAChi2).

    ``per_term`` studies are clustered at each term's MNI centroid and tagged ``1.0``
    for their own term and ``0.0`` for the others, so the dataset can be split into
    term-present vs term-absent for a Neurosynth-style P(term | region) test. For
    tests/demos only (no network).
    """
    import random

    from nimare.dataset import Dataset

    rng = random.Random(seed)
    src: dict[str, Any] = {}
    term_of: dict[str, str] = {}
    sid = 0
    for term, (cx, cy, cz) in clusters_by_term.items():
        for _ in range(per_term):
            key = f"{term}-{sid}"
            pt = [
                (
                    cx + rng.randint(-jitter, jitter),
                    cy + rng.randint(-jitter, jitter),
                    cz + rng.randint(-jitter, jitter),
                )
            ]
            src[key] = _study(pt)
            term_of[key] = term
            sid += 1
    dset = Dataset(src)
    ann = dset.annotations.copy()
    for term in clusters_by_term:
        ann[term] = [1.0 if term_of.get(str(s)) == term else 0.0 for s in ann["study_id"]]
    dset.annotations = ann
    return dset


def load_neurosynth_corpus(
    cache_path: str | None = None,
    *,
    download: bool = False,
    data_dir: str | None = None,
    version: str = "7",
    source: str = "abstract",
    vocab: str = "terms",
) -> Any:
    """Load a real Neurosynth NiMARE ``Dataset`` (coordinates + term annotations).

    Resolution order:
      1. if ``cache_path`` points to a saved Dataset (``.pkl.gz``), load it (fast);
      2. else build it from the raw Neurosynth files under ``data_dir`` — NiMARE's
         ``fetch_neurosynth`` cache, default ``~/.nimare`` — and save to ``cache_path``.

    Fetching *missing* raw files needs ``download=True`` (large, network); when the
    cache already holds the raw files (the common case) no network is used. Raises
    ``FileNotFoundError`` if neither a saved Dataset nor raw files exist and
    ``download`` is False, so the caller can fall back to the KG backend rather than
    block on a download. The resulting term labels are ``terms_abstract_tfidf__<term>``
    (selected at the 0.001 TF-IDF convention by :class:`NimareBackend`).
    """
    from pathlib import Path

    from nimare.dataset import Dataset

    if cache_path and Path(cache_path).expanduser().exists():
        return Dataset.load(str(Path(cache_path).expanduser()))

    ddir = Path(data_dir).expanduser() if data_dir else Path("~/.nimare").expanduser()
    raw_coords = ddir / "neurosynth" / f"data-neurosynth_version-{version}_coordinates.tsv.gz"
    if not raw_coords.exists() and not download:
        raise FileNotFoundError(
            f"no saved Dataset at {cache_path!r} and no raw Neurosynth files under "
            f"{ddir}; pass download=True to fetch (large)"
        )

    from nimare.extract import fetch_neurosynth
    from nimare.io import convert_neurosynth_to_dataset

    files = fetch_neurosynth(
        data_dir=str(ddir), version=version, source=source, vocab=vocab, overwrite=False
    )
    ns = files[0] if isinstance(files, (list, tuple)) else files
    dset = convert_neurosynth_to_dataset(
        coordinates_file=ns["coordinates"],
        metadata_file=ns["metadata"],
        annotations_files=ns["features"],
    )
    if cache_path:
        dset.save(str(Path(cache_path).expanduser()))
    return dset
