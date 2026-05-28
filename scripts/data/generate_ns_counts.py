from ctypes.wintypes import HKL
import json
from nimare.dataset import Dataset
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
PKL_PATH = os.path.join(
    script_dir, "../data/neurosynth_nimare/neurosynth_dataset_v7.pkl"
)
OUT_PATH = os.path.join(script_dir, "../data/ns_counts.json")


def main():
    print(f"Loading NiMARE dataset from {PKL_PATH} ...")
    dset = Dataset.load(PKL_PATH)
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
    with open(OUT_PATH, "w") as f:
        json.dump(new_term_counts, f, indent=2)
    print("Done.")


if __name__ == "__main__":
    main()
