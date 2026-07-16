import json
from pathlib import Path

from nimare.dataset import Dataset

from brain_researcher.core.datasets.neurosynth_source import (
    DEFAULT_DATASET_PICKLE,
    DEFAULT_SOURCE_DIR,
    REPO_ROOT,
    verify_converted_dataset,
)

PKL_PATH = DEFAULT_DATASET_PICKLE
OUT_PATH = REPO_ROOT / "data" / "ns_counts.json"


def main():
    print(f"Loading NiMARE dataset from {PKL_PATH} ...")
    verify_converted_dataset(PKL_PATH, DEFAULT_SOURCE_DIR)
    dset = Dataset.load(str(PKL_PATH))
    print("Counting studies for each term ...")
    term_counts = {
        t.lower(): len(dset.get_studies_by_label(t)) for t in dset.get_labels()
    }
    new_term_counts = {}
    for term, count in term_counts.items():
        if term.startswith("terms_abstract_tfidf__"):
            term = term.replace("terms_abstract_tfidf__", "")
            new_term_counts[term] = count
        else:
            new_term_counts[term] = count

    print(f"Writing term counts to {OUT_PATH} ...")
    with Path(OUT_PATH).open("w", encoding="utf-8") as f:
        json.dump(new_term_counts, f, indent=2)
    print("Done.")


if __name__ == "__main__":
    main()
