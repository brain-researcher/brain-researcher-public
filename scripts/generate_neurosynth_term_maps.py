import argparse
import os
from pathlib import Path

import numpy as np
import nibabel as nib

from nimare.dataset import Dataset
from nimare.decode.continuous import CorrelationDecoder


def main():
    parser = argparse.ArgumentParser(description="Generate term maps from NiMARE/Neurosynth dataset")
    parser.add_argument(
        "--dataset",
        default=None,
        help="Path to NiMARE Dataset (.pkl or .pkl.gz). If omitted, we auto-pick the first existing among pkl -> pkl.gz in data/neurosynth_nimare/",
    )
    parser.add_argument("--outdir", default="data/neurosynth/statmaps", help="Output directory for NIfTI maps")
    parser.add_argument("--top", type=int, default=50, help="Top N terms by study_count to generate")
    parser.add_argument("--cores", type=int, default=4, help="Parallel cores for CorrelationDecoder (n_cores)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing maps")
    args = parser.parse_args()

    if args.dataset:
        dset_path = Path(args.dataset)
        if not dset_path.exists():
            raise FileNotFoundError(f"Dataset not found: {dset_path}")
    else:
        # Auto-select between pkl and pkl.gz in the standard location
        candidates = [
            Path("data/neurosynth_nimare/neurosynth_dataset_v7.pkl"),
            Path("data/neurosynth_nimare/neurosynth_dataset_v7.pkl.gz"),
        ]
        dset_path = next((p for p in candidates if p.exists()), None)
        if dset_path is None:
            raise FileNotFoundError("No Neurosynth dataset found (pkl or pkl.gz) under data/neurosynth_nimare/. Provide --dataset explicitly.")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"Loading dataset {dset_path} ...")
    dset = Dataset.load(str(dset_path))

    # Get term study counts (columns start with 'terms_' in NiMARE v0.2+)
    ann = dset.annotations
    term_cols = [c for c in ann.columns if c.startswith("terms_")]
    if not term_cols:
        raise RuntimeError("No term columns found (expected columns starting with 'terms_').")

    # Count how many studies mention each term (non-zero entries)
    term_counts = (ann[term_cols] > 0).sum(axis=0)
    sorted_terms = term_counts.sort_values(ascending=False)
    terms = list(sorted_terms.index[: args.top])
    print(f"Selected top {len(terms)} terms")

    # Fit correlation decoder once
    print("Fitting CorrelationDecoder ... (this may take a while)")
    decoder = CorrelationDecoder(features=terms, n_cores=args.cores)
    decoder.fit(dset)

    print("Extracting fitted term maps ...")
    decoded = decoder.results_.maps
    masker = decoder.results_.masker

    for term in terms:
        data = decoded[term]
        img = masker.inverse_transform(data)
        outpath = outdir / f"neurosynth_term_{term}.nii.gz"
        if outpath.exists() and not args.force:
            print(f"[skip] {outpath} exists")
            continue
        img.to_filename(outpath)
        print(f"[saved] {outpath}")


if __name__ == "__main__":
    main()
