import csv
import sys
from pathlib import Path

from rapidfuzz.distance import Levenshtein


def exact_fuzzy_match(
    contrasts_csv: str | Path, aliases_tsv: str | Path, out_csv: str | Path
) -> None:
    """Perform exact and fuzzy string matching between contrast names and concept labels.

    Parameters
    ----------
    contrasts_csv : path to contrasts_raw.csv with dataset_id,contrast_name
    aliases_tsv : path to concept_aliases.tsv with columns concept_id,label,alias
    out_csv : output path for matches
    """
    contrasts = []
    with open(contrasts_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            contrasts.append(
                {
                    "dataset_id": row.get("dataset_id", ""),
                    "contrast_name": row.get("contrast_name", ""),
                }
            )

    aliases = []
    with open(aliases_tsv, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            aliases.append(
                {
                    "concept_id": row.get("concept_id", ""),
                    "label": row.get("label", ""),
                    "alias": row.get("alias", ""),
                }
            )

    fields = ["dataset_id", "contrast_name", "concept_id", "method", "confidence"]
    with open(out_csv, "w", newline="") as fo:
        writer = csv.DictWriter(fo, fieldnames=fields)
        writer.writeheader()
        for c in contrasts:
            q = c["contrast_name"].lower()
            for a in aliases:
                label = a["label"].lower()
                alias = a["alias"].lower()
                cid = a["concept_id"]
                if q == label or (alias and q == alias):
                    writer.writerow(
                        {**c, "concept_id": cid, "method": "exact", "confidence": 1.0}
                    )
                else:
                    dist = Levenshtein.distance(q, label)
                    if dist <= 2:
                        writer.writerow(
                            {
                                **c,
                                "concept_id": cid,
                                "method": "fuzzy",
                                "confidence": 0.95,
                            }
                        )


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(
            "Usage: python exact_fuzzy_match.py contrasts.csv concept_aliases.tsv output.csv"
        )
        sys.exit(1)
    exact_fuzzy_match(sys.argv[1], sys.argv[2], sys.argv[3])
