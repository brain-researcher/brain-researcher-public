import argparse
from pathlib import Path

from nimare.dataset import Dataset
from nimare.decode.continuous import CorrelationDecoder

from brain_researcher.core.datasets.neurosynth_source import (
    DEFAULT_DATASET_PICKLE,
    DEFAULT_SOURCE_DIR,
    verify_converted_dataset,
)


def main():
    parser = argparse.ArgumentParser(description="Generate term maps from NiMARE/Neurosynth dataset")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PICKLE,
        help="Path to the converted NiMARE Dataset pickle.",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Directory containing the verified pinned raw source bundle.",
    )
    parser.add_argument("--outdir", default="data/neurosynth/statmaps", help="Output directory for NIfTI maps")
    parser.add_argument("--top", type=int, default=50, help="Top N terms by study_count to generate")
    parser.add_argument("--cores", type=int, default=4, help="Parallel cores for CorrelationDecoder (n_cores)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing maps")
    args = parser.parse_args()

    dset_path = args.dataset.expanduser().resolve()
    verify_converted_dataset(dset_path, args.source_dir)

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
